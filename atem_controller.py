#!/usr/bin/env python3
"""
atem_controller.py - Contrôleur ATEM pour FocusBMrestAPI1

Ce module gère la connexion avec le switcher ATEM pour commuter
la sortie HDMI 2 (AUX 2) vers une caméra sélectionnée.

Fonctionnalités :
- Commutation de l'AUX 2 (HDMI 2) vers une caméra sélectionnée
- Gestion de la connexion avec retry automatique
"""

try:
    from PyATEMMax.ATEMMax import ATEMMax
except ImportError:
    # Fallback si PyATEMMax n'est pas installé
    ATEMMax = None

import threading
import time
import logging

logger = logging.getLogger(__name__)


class AtemController:
    """
    Contrôleur pour gérer les interactions avec un switcher ATEM.
    """
    
    def __init__(
        self,
        ip,
        aux_output=2,
        auto_retry=True,
        retry_delay=10,
        max_retry_delay=60,
        max_retry_attempts=5,
        status_callback=None,
    ):
        """
        Initialise le contrôleur ATEM.
        
        Args:
            ip (str): Adresse IP du switcher ATEM
            aux_output (int): Numéro de sortie AUX (1=AUX1, 2=AUX2, etc.) - défaut: 2 pour HDMI 2
            auto_retry (bool): Si True, retente automatiquement la connexion en cas d'échec
            retry_delay (int): Délai initial entre les tentatives (secondes)
            max_retry_delay (int): Délai maximum entre les tentatives (secondes)
            max_retry_attempts (int): Nombre maximum de tentatives (-1 = illimité)
            status_callback (callable): Fonction appelée quand l'état de connexion change (connected: bool, ip: str)
        """
        self.ip = ip
        self.aux_output = aux_output
        self.atem = None
        self.connected = False
        self.auto_retry = bool(auto_retry)
        self.base_retry_delay = max(1, int(retry_delay))
        self.max_retry_delay = max(self.base_retry_delay, int(max_retry_delay))
        if max_retry_attempts is None or int(max_retry_attempts) < 0:
            self.max_retry_attempts = -1
        else:
            self.max_retry_attempts = int(max_retry_attempts)
        self.status_callback = status_callback
        self.lock = threading.Lock()
        self.running = False
        self.last_camera_id = None  # Dernière caméra sélectionnée
        
        logger.info(f"ATEM Controller initialisé pour {ip} (AUX {aux_output})")
    
    def _emit_status(self, connected):
        """Notifie le changement d'état de connexion via le callback."""
        if self.status_callback:
            try:
                self.status_callback(connected, self.ip)
            except Exception as e:
                logger.error(f"Erreur dans status_callback: {e}")

    def _cleanup_connection(self):
        """Nettoie la connexion ATEM."""
        with self.lock:
            if self.atem:
                try:
                    self.atem.disconnect()
                except Exception:
                    pass
            self.atem = None
            self.connected = False

    def connect(self):
        """
        Établit la connexion avec l'ATEM.
        Retente automatiquement en cas d'échec si auto_retry est True.
        """
        if ATEMMax is None:
            logger.error("PyATEMMax n'est pas installé. Installez-le avec: pip install PyATEMMax")
            self._emit_status(False)
            return
        
        attempt = 0
        delay = self.base_retry_delay
        self.running = True

        while self.running and not self.connected:
            try:
                logger.info(f"Tentative de connexion à l'ATEM {self.ip}...")
                self._cleanup_connection()
                self.atem = ATEMMax()
                self.atem.connect(self.ip)
                logger.info(f"Attente de la connexion ATEM (timeout 10s)...")
                
                # Attendre la connexion avec un timeout
                timeout = 10
                start_time = time.time()
                while self.atem and not self.atem.connected and (time.time() - start_time) < timeout:
                    time.sleep(0.1)
                
                if self.atem and self.atem.connected:
                    self.connected = True
                    logger.info(f"Connecté à l'ATEM {self.ip}")
                    self._emit_status(True)
                    break
                else:
                    logger.warning(f"Timeout de connexion ATEM après {timeout}s")
                    self._emit_status(False)
                    attempt += 1
                    self._cleanup_connection()
                    if not self.auto_retry or (self.max_retry_attempts > 0 and attempt >= self.max_retry_attempts):
                        logger.warning("Arrêt des tentatives automatiques")
                        break
                    wait = min(delay, self.max_retry_delay)
                    logger.info(f"Nouvelle tentative dans {wait} seconde(s)...")
                    time.sleep(wait)
                    delay = min(delay * 2, self.max_retry_delay)
                
            except Exception as e:
                logger.error(f"Erreur de connexion ATEM : {e}")
                import traceback
                logger.debug(traceback.format_exc())
                self._emit_status(False)
                attempt += 1
                self._cleanup_connection()
                if not self.auto_retry or (self.max_retry_attempts > 0 and attempt >= self.max_retry_attempts):
                    logger.warning("Arrêt des tentatives automatiques")
                    break
                wait = min(delay, self.max_retry_delay)
                logger.info(f"Nouvelle tentative dans {wait} seconde(s)...")
                time.sleep(wait)
                delay = min(delay * 2, self.max_retry_delay)
        
        if not self.connected:
            self._cleanup_connection()
            self.running = False
    
    def switch_to_camera(self, camera_id):
        """
        Commute la sortie HDMI 2 (AUX 2) vers la caméra spécifiée.
        
        Args:
            camera_id (int): ID de la caméra (correspond à l'input ATEM, mapping 1:1)
        
        Returns:
            bool: True si succès, False sinon
        """
        if not self.connected or not self.atem:
            logger.warning(f"ATEM non connecté - impossible de commuter vers caméra {camera_id}")
            return False
        
        try:
            # PyATEMMax: setAuxSourceInput(output, source)
            # output = aux_output - 1 (car indexé à partir de 0)
            # AUX 1 = index 0, AUX 2 = index 1, etc.
            aux_index = self.aux_output - 1
            
            # Conversion de camera_id (1, 2, 3...) vers l'index PyATEMMax pour les inputs
            # Correction du décalage: camera_id 2 doit sélectionner l'input 2
            # Si PyATEMMax utilise des constantes 1-based, utiliser les constantes directement
            # Sinon, utiliser camera_id directement (1-based)
            try:
                from PyATEMMax import ATEMVideoSources
                # PyATEMMax a des constantes comme input1, input2, etc. (1-based)
                source_attr = f"input{camera_id}"
                if hasattr(ATEMVideoSources, source_attr):
                    # Utiliser la constante PyATEMMax (qui a la bonne valeur 1-based)
                    source_index = getattr(ATEMVideoSources, source_attr)
                else:
                    # Fallback: utiliser directement camera_id (1-based)
                    source_index = camera_id
            except (ImportError, AttributeError):
                # Fallback: utiliser directement camera_id (1-based)
                source_index = camera_id
            
            with self.lock:
                self.atem.setAuxSourceInput(aux_index, source_index)
            self.last_camera_id = camera_id
            logger.info(f"HDMI 2 (AUX {self.aux_output}) → Caméra {camera_id} (source: {source_index})")
            return True
            
        except Exception as e:
            logger.error(f"Erreur lors de la commutation vers caméra {camera_id} : {e}")
            return False

    def safe_call(self, func, *args, **kwargs):
        """
        Appel thread-safe vers l'instance ATEM. Retourne False si non connecté.
        """
        cleanup_needed = False
        with self.lock:
            if not self.connected or not self.atem:
                logger.warning("ATEM non connecté - appel ignoré")
                return False
            try:
                func(*args, **kwargs)
                return True
            except Exception as e:
                logger.error(f"Erreur ATEM : {e}")
                cleanup_needed = True

        if cleanup_needed:
            self.connected = False
            self._emit_status(False)
            self._cleanup_connection()
            logger.warning("Connexion ATEM interrompue")
        return False

    def perform_cut(self):
        """Effectue un CUT (PVW → PGM) sur le Mix Effect 0."""
        result = self.safe_call(lambda: self.atem.execCutME(0))
        if result:
            logger.info("CUT exécuté (PVW → PGM)")
        return result

    def set_preview_source(self, camera_id):
        """Place une caméra en preview sur le Mix Effect 0."""
        result = self.safe_call(lambda: self.atem.setPreviewInputVideoSource(0, camera_id))
        if result:
            logger.info(f"Cam{camera_id} → Preview")
        return result

    def route_hdmi_output(self, mode, hdmi_out_index=None):
        """
        Route la sortie HDMI (AUX) vers Program, Preview ou Multiview.
        Ne modifie pas les bus PGM/PVW, uniquement l'AUX demandé.

        Args:
            mode (str): 'program', 'preview' ou 'multiview'
            hdmi_out_index (int, optional): index de la sortie AUX (défaut : self.aux_output - 1)

        Returns:
            bool: True si succès, False sinon
        """
        if not self.connected or not self.atem:
            logger.warning("ATEM non connecté - impossible de router HDMI OUTPUT")
            return False

        if hdmi_out_index is None:
            hdmi_out_index = self.aux_output - 1

        try:
            try:
                from PyATEMMax import ATEMVideoSources
                sources = {
                    'program': ATEMVideoSources.mE1Prog,
                    'preview': ATEMVideoSources.mE1Prev,
                    'multiview': getattr(ATEMVideoSources, 'multiview1', 9001),
                }
            except ImportError:
                # Fallback : lire les entrées actuelles
                sources = {
                    'program': str(self.atem.programInput[0].videoSource),
                    'preview': str(self.atem.previewInput[0].videoSource),
                    'multiview': 9001,
                }

            if mode not in sources:
                logger.error(f"Mode HDMI OUTPUT inconnu: {mode}")
                return False

            source = sources[mode]
            # Convertir les strings "inputX" en index numérique si nécessaire
            if isinstance(source, str) and source.startswith('input'):
                try:
                    source = int(source.replace('input', ''))
                except ValueError:
                    pass

            if not self.safe_call(self.atem.setAuxSourceInput, hdmi_out_index, source):
                return False
            logger.info(f"HDMI OUT (AUX {hdmi_out_index + 1}) → {mode.upper()}")
            return True
        except Exception as e:
            logger.error(f"Erreur lors du routage HDMI OUTPUT ({mode}) : {e}")
            return False

    def switch_to_program(self):
        """
        Route l'AUX configuré vers la source actuellement en Program.
        """
        return self.route_hdmi_output('program')

    def switch_to_preview(self):
        """
        Route l'AUX configuré vers la source actuellement en Preview.
        """
        return self.route_hdmi_output('preview')

    def switch_to_multiview(self):
        """
        Route l'AUX configuré vers le Multiview.
        """
        return self.route_hdmi_output('multiview')
    
    def disconnect(self):
        """
        Ferme proprement la connexion ATEM.
        """
        self.running = False
        self.connected = False
        try:
            self._cleanup_connection()
            logger.info("Déconnecté de l'ATEM")
            self._emit_status(False)
        except Exception as e:
            logger.error(f"Erreur lors de la déconnexion : {e}")
    
    def is_connected(self):
        """Retourne True si connecté à l'ATEM."""
        return self.connected
    
    def get_last_camera_id(self):
        """Retourne l'ID de la dernière caméra sélectionnée."""
        return self.last_camera_id
    
    def __del__(self):
        """
        Destructeur - ferme la connexion si l'objet est détruit.
        """
        self.disconnect()
