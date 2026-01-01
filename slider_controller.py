#!/usr/bin/env python3
"""
Contrôleur pour slider motorisé (pan, tilt, slide, zoom motor).
Communique avec le slider via HTTP POST /api/v1/axes/move_multiple
"""

import requests
import logging
from typing import Optional, Dict
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)


class SliderController:
    """Contrôleur pour slider motorisé via API HTTP."""
    
    def __init__(self, slider_ip: str, port: int = 80):
        """
        Initialise le contrôleur du slider.
        
        Args:
            slider_ip: Adresse IP du slider (ex: "192.168.1.100") ou hostname mDNS (ex: "slider1.local")
            port: Port HTTP du slider (défaut: 80)
        """
        self.slider_ip = slider_ip.strip() if slider_ip else ""
        self.port = port
        self.base_url = f"http://{self.slider_ip}:{port}" if self.slider_ip else None
        self.endpoint = "/api/v1/axes/move_multiple"
        
        # Créer une session HTTP avec retry (mais pas pour ConnectionError)
        self.session = requests.Session()
        # Ne pas retry sur ConnectionError (Host is down) - échec immédiat
        retry_strategy = Retry(
            total=0,  # Pas de retry pour éviter les warnings répétés
            backoff_factor=0.1,
            status_forcelist=[429, 500, 502, 503, 504],
            connect=0,  # Pas de retry sur les erreurs de connexion
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        
        # Timeout pour la réactivité (augmenté pour permettre la résolution mDNS)
        self.timeout = 1.0  # 1 seconde (permet la résolution mDNS si nécessaire)
    
    def is_configured(self) -> bool:
        """Vérifie si le slider est configuré (IP non vide)."""
        return bool(self.slider_ip and self.slider_ip.strip())
    
    def get_status(self, silent: bool = False) -> Optional[Dict[str, float]]:
        """
        Récupère le statut actuel du slider, notamment les positions des axes.
        
        Args:
            silent: Si True, n'affiche pas de message d'erreur
            
        Returns:
            Dictionnaire avec les valeurs normalisées (0.0-1.0) pour pan, tilt, zoom, slide
            ou None en cas d'erreur
        """
        if not self.is_configured():
            if not silent:
                logger.debug("Slider non configuré (IP vide)")
            return None
        
        try:
            url = f"{self.base_url}/api/v1/status"
            response = self.session.get(
                url,
                timeout=self.timeout,
                headers={'Accept': 'application/json'}
            )
            
            if response.status_code == 200:
                data = response.json()
                motors_percent = data.get('motors_percent', {})
                
                # Extraire les valeurs normalisées (elles sont déjà en pourcentage 0-100, convertir en 0.0-1.0)
                result = {
                    'pan': motors_percent.get('pan', 0.0) / 100.0 if motors_percent.get('pan') is not None else 0.0,
                    'tilt': motors_percent.get('tilt', 0.0) / 100.0 if motors_percent.get('tilt') is not None else 0.0,
                    'zoom': motors_percent.get('zoom', 0.0) / 100.0 if motors_percent.get('zoom') is not None else 0.0,
                    'slide': motors_percent.get('slide', 0.0) / 100.0 if motors_percent.get('slide') is not None else 0.0
                }
                
                # S'assurer que les valeurs sont dans la plage 0.0-1.0
                for key in result:
                    result[key] = max(0.0, min(1.0, result[key]))
                
                return result
            else:
                if not silent:
                    logger.warning(f"Slider erreur HTTP {response.status_code}: {response.text}")
                return None
                
        except requests.exceptions.ConnectionError:
            if not silent:
                logger.debug(f"Slider non accessible à {self.base_url}")
            return None
        except requests.exceptions.Timeout:
            if not silent:
                logger.debug(f"Slider timeout à {self.base_url}")
            return None
        except Exception as e:
            if not silent:
                logger.error(f"Erreur lors de la récupération du statut du slider: {e}")
            return None
    
    def move_axes(self, pan: Optional[float] = None, tilt: Optional[float] = None, 
                  slide: Optional[float] = None, zoom: Optional[float] = None,
                  duration: Optional[float] = None, silent: bool = False) -> bool:
        """
        Déplace plusieurs axes simultanément.
        
        Args:
            pan: Valeur pan (0.0-1.0), optionnel
            tilt: Valeur tilt (0.0-1.0), optionnel
            slide: Valeur slide (0.0-1.0), optionnel
            zoom: Valeur zoom motor (0.0-1.0), optionnel
            duration: Durée en secondes pour synchronisation, optionnel
            silent: Si True, n'affiche pas de message d'erreur
            
        Returns:
            True si la requête a réussi, False sinon
        """
        if not self.is_configured():
            if not silent:
                logger.debug("Slider non configuré (IP vide)")
            return False
        
        # Construire le payload avec seulement les axes spécifiés
        payload = {}
        if pan is not None:
            payload["pan"] = max(0.0, min(1.0, pan))  # Clamper entre 0.0 et 1.0
        if tilt is not None:
            payload["tilt"] = max(0.0, min(1.0, tilt))
        if slide is not None:
            payload["slide"] = max(0.0, min(1.0, slide))
        if zoom is not None:
            payload["zoom"] = max(0.0, min(1.0, zoom))
        if duration is not None:
            payload["duration"] = duration
        
        # Si aucun axe n'est spécifié, ne rien faire
        if not payload:
            return False
        
        # #region agent log
        try:
            import json, time
            with open('/Users/laurenteyen/Documents/cursor/FocusBMrestAPI1/.cursor/debug.log', 'a') as f:
                f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"K,N","location":"slider_controller.py:150","message":"move_axes: avant envoi","data":{"payload":payload,"url":f"{self.base_url}{self.endpoint}"},"timestamp":int(time.time()*1000)})+'\n')
        except: pass
        # #endregion
        
        try:
            url = f"{self.base_url}{self.endpoint}"
            send_time = time.time() * 1000
            response = self.session.post(
                url,
                json=payload,
                timeout=self.timeout,
                headers={'Content-Type': 'application/json'}
            )
            
            receive_time = time.time() * 1000
            # #region agent log
            try:
                import json, time
                response_data = None
                if response.text:
                    try:
                        response_data = json.loads(response.text)
                    except:
                        response_data = response.text[:200]
                with open('/Users/laurenteyen/Documents/cursor/FocusBMrestAPI1/.cursor/debug.log', 'a') as f:
                    f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"K,N","location":"slider_controller.py:160","message":"move_axes: réponse reçue","data":{"status_code":response.status_code,"response_data":response_data,"latency_ms":receive_time - send_time,"payload":payload},"timestamp":int(receive_time)})+'\n')
            except: pass
            # #endregion
            
            if response.status_code in [200, 204]:
                return True
            else:
                if not silent:
                    logger.warning(f"Slider erreur HTTP {response.status_code}: {response.text}")
                return False
                
        except requests.exceptions.ConnectionError as e:
            # Le slider n'est pas accessible (éteint, réseau différent, mDNS non résolu, etc.)
            # En mode silent, on retourne False sans message pour éviter le spam
            return False
        except requests.exceptions.Timeout:
            if not silent:
                logger.debug(f"Slider timeout à {self.base_url}")
            return False
        except Exception as e:
            if not silent:
                logger.error(f"Erreur slider: {e}")
            return False
    
    def move_pan(self, value: float, silent: bool = False) -> bool:
        """Déplace uniquement l'axe pan."""
        return self.move_axes(pan=value, silent=silent)
    
    def move_tilt(self, value: float, silent: bool = False) -> bool:
        """Déplace uniquement l'axe tilt."""
        return self.move_axes(tilt=value, silent=silent)
    
    def move_slide(self, value: float, silent: bool = False) -> bool:
        """Déplace uniquement l'axe slide."""
        return self.move_axes(slide=value, silent=silent)
    
    def move_zoom(self, value: float, silent: bool = False) -> bool:
        """Déplace uniquement l'axe zoom motor."""
        return self.move_axes(zoom=value, silent=silent)
    
    def send_joy_command(self, pan: Optional[float] = None, tilt: Optional[float] = None, 
                         slide: Optional[float] = None, zoom: Optional[float] = None,
                         silent: bool = False) -> bool:
        """
        Envoie une commande joystick au slider.
        
        Args:
            pan: Valeur pan (-1.0 à +1.0), optionnel
            tilt: Valeur tilt (-1.0 à +1.0), optionnel
            slide: Valeur slide (-1.0 à +1.0), optionnel
            zoom: Valeur zoom (-1.0 à +1.0), optionnel
            silent: Si True, n'affiche pas de message d'erreur
            
        Returns:
            True si la requête a réussi, False sinon
        """
        if not self.is_configured():
            if not silent:
                logger.debug("Slider non configuré (IP vide)")
            return False
        
        # Construire le payload avec seulement les axes spécifiés
        payload = {}
        if pan is not None:
            payload["pan"] = max(-1.0, min(1.0, pan))  # Clamper entre -1.0 et +1.0
        if tilt is not None:
            payload["tilt"] = max(-1.0, min(1.0, tilt))
        if slide is not None:
            payload["slide"] = max(-1.0, min(1.0, slide))
        if zoom is not None:
            payload["zoom"] = max(-1.0, min(1.0, zoom))
        
        # Si aucun axe n'est spécifié, ne rien faire
        if not payload:
            return False
        
        # #region agent log
        try:
            import json, time
            with open('/Users/laurenteyen/Documents/cursor/FocusBMrestAPI1/.cursor/debug.log', 'a') as f:
                f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"O","location":"slider_controller.py:232","message":"send_joy_command: avant envoi","data":{"payload":payload,"url":f"{self.base_url}/api/v1/joy"},"timestamp":int(time.time()*1000)})+'\n')
        except: pass
        # #endregion
        
        try:
            url = f"{self.base_url}/api/v1/joy"
            send_time = time.time() * 1000
            response = self.session.post(
                url,
                json=payload,
                timeout=self.timeout,
                headers={'Content-Type': 'application/json'}
            )
            
            # #region agent log
            try:
                import json, time
                receive_time = time.time() * 1000
                with open('/Users/laurenteyen/Documents/cursor/FocusBMrestAPI1/.cursor/debug.log', 'a') as f:
                    f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"O","location":"slider_controller.py:245","message":"send_joy_command: réponse reçue","data":{"status_code":response.status_code,"latency_ms":receive_time - send_time,"payload":payload},"timestamp":int(receive_time)})+'\n')
            except: pass
            # #endregion
            
            if response.status_code in [200, 204]:
                return True
            else:
                if not silent:
                    logger.warning(f"Slider erreur HTTP {response.status_code}: {response.text}")
                return False
                
        except requests.exceptions.ConnectionError as e:
            # Le slider n'est pas accessible (éteint, réseau différent, mDNS non résolu, etc.)
            # En mode silent, on retourne False sans message pour éviter le spam
            return False
        except requests.exceptions.Timeout:
            if not silent:
                logger.debug(f"Slider timeout à {self.base_url}")
            return False
        except Exception as e:
            if not silent:
                logger.error(f"Erreur slider: {e}")
            return False
    
    def send_interpolation_sequence(self, points: list, duration: float, silent: bool = False) -> bool:
        """
        Envoie une séquence d'interpolation directe au slider.
        
        Args:
            points: Liste de dictionnaires avec les points de la séquence.
                   Chaque point doit contenir 'fraction' (0.0-1.0) et optionnellement
                   'pan', 'tilt', 'zoom', 'slide' (0.0-1.0)
            duration: Durée totale en secondes pour parcourir toute la séquence
            silent: Si True, n'affiche pas de message d'erreur
            
        Returns:
            True si la requête a réussi, False sinon
        """
        if not self.is_configured():
            if not silent:
                logger.debug("Slider non configuré (IP vide)")
            return False
        
        # Construire le payload
        payload = {
            "points": points,
            "duration": duration
        }
        
        # #region agent log
        try:
            import json, time
            with open('/Users/laurenteyen/Documents/cursor/FocusBMrestAPI1/.cursor/debug.log', 'a') as f:
                f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"N","location":"slider_controller.py:280","message":"send_interpolation_sequence: payload construit","data":{"points":points,"duration":duration,"payload_keys":list(payload.keys())},"timestamp":int(time.time()*1000)})+'\n')
        except: pass
        # #endregion
        
        try:
            url = f"{self.base_url}/api/v1/interp/setpoints/direct"
            response = self.session.post(
                url,
                json=payload,
                timeout=self.timeout,
                headers={'Content-Type': 'application/json'}
            )
            
            # #region agent log
            try:
                import json, time
                response_data = None
                response_text_full = response.text
                if response.text:
                    try:
                        response_data = json.loads(response.text)
                    except:
                        response_data = response.text[:500]
                # Extraire les valeurs de tilt de tous les points pour vérifier
                tilt_values_in_points = [p.get("tilt") for p in points if "tilt" in p]
                tilt_all_same = len(set(tilt_values_in_points)) <= 1 if tilt_values_in_points else False
                with open('/Users/laurenteyen/Documents/cursor/FocusBMrestAPI1/.cursor/debug.log', 'a') as f:
                    f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"V,W,X,Y","location":"slider_controller.py:295","message":"send_interpolation_sequence: réponse reçue","data":{"status_code":response.status_code,"response_data":response_data,"response_text_full":response_text_full[:1000],"payload_sent":payload,"tilt_values_in_points":tilt_values_in_points,"tilt_all_same":tilt_all_same,"tilt_count":len(tilt_values_in_points)},"timestamp":int(time.time()*1000)})+'\n')
            except: pass
            # #endregion
            
            if response.status_code == 200:
                return True
            else:
                if not silent:
                    logger.warning(f"Slider erreur HTTP {response.status_code}: {response.text}")
                return False
                
        except requests.exceptions.ConnectionError:
            if not silent:
                logger.debug(f"Slider non accessible à {self.base_url}")
            return False
        except requests.exceptions.Timeout:
            if not silent:
                logger.debug(f"Slider timeout à {self.base_url}")
            return False
        except Exception as e:
            if not silent:
                logger.error(f"Erreur slider: {e}")
            return False
    
    def set_auto_interpolation(self, enable: bool, duration: Optional[float] = None, silent: bool = False) -> bool:
        """
        Active ou désactive l'interpolation automatique du slider.
        
        Args:
            enable: True pour activer, False pour désactiver
            duration: Durée optionnelle en secondes (utilise celle de setpoints/direct si None)
            silent: If True, n'affiche pas de message d'erreur
            
        Returns:
            True si la requête a réussi, False sinon
        """
        if not self.is_configured():
            if not silent:
                logger.debug("Slider non configuré (IP vide)")
            return False
        
        # Construire le payload
        payload = {"enable": enable}
        if duration is not None:
            payload["duration"] = duration
        
        # #region agent log
        try:
            import json, time
            status_before = self.get_status(silent=True)
            with open('/Users/laurenteyen/Documents/cursor/FocusBMrestAPI1/.cursor/debug.log', 'a') as f:
                f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"L,M","location":"slider_controller.py:354","message":"set_auto_interpolation: avant envoi","data":{"enable":enable,"duration":duration,"payload":payload,"status_before":status_before},"timestamp":int(time.time()*1000)})+'\n')
        except: pass
        # #endregion
        
        try:
            url = f"{self.base_url}/api/v1/interp/auto"
            send_time = time.time() * 1000
            response = self.session.post(
                url,
                json=payload,
                timeout=self.timeout,
                headers={'Content-Type': 'application/json'}
            )
            
            receive_time = time.time() * 1000
            # #region agent log
            try:
                import json, time
                response_data = None
                response_text_full = response.text
                if response.text:
                    try:
                        response_data = json.loads(response.text)
                    except:
                        response_data = response.text[:200]
                status_after = self.get_status(silent=True)
                position_changes = {
                    "pan": status_after.get("pan", 0) - status_before.get("pan", 0) if (status_after and status_before and "pan" in status_after and "pan" in status_before) else None,
                    "tilt": status_after.get("tilt", 0) - status_before.get("tilt", 0) if (status_after and status_before and "tilt" in status_after and "tilt" in status_before) else None,
                    "zoom": status_after.get("zoom", 0) - status_before.get("zoom", 0) if (status_after and status_before and "zoom" in status_after and "zoom" in status_before) else None,
                    "slide": status_after.get("slide", 0) - status_before.get("slide", 0) if (status_after and status_before and "slide" in status_after and "slide" in status_before) else None
                }
                with open('/Users/laurenteyen/Documents/cursor/FocusBMrestAPI1/.cursor/debug.log', 'a') as f:
                    f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"Z,AA,AB,AC","location":"slider_controller.py:377","message":"set_auto_interpolation: réponse reçue","data":{"status_code":response.status_code,"response_data":response_data,"response_text_full":response_text_full[:1000],"latency_ms":receive_time - send_time,"status_before":status_before,"status_after":status_after,"position_changes":position_changes,"enable":enable,"duration":duration},"timestamp":int(receive_time)})+'\n')
            except: pass
            # #endregion
            
            if response.status_code == 200:
                return True
            else:
                if not silent:
                    logger.warning(f"Slider erreur HTTP {response.status_code}: {response.text}")
                return False
                
        except requests.exceptions.ConnectionError:
            if not silent:
                logger.debug(f"Slider non accessible à {self.base_url}")
            return False
        except requests.exceptions.Timeout:
            if not silent:
                logger.debug(f"Slider timeout à {self.base_url}")
            return False
        except Exception as e:
            if not silent:
                logger.error(f"Erreur slider: {e}")
            return False
    
    def goto_interpolation_fraction(self, fraction: float, silent: bool = False) -> bool:
        """
        Va à une position interpolée immédiatement.
        
        Args:
            fraction: Fraction de l'interpolation (0.0-1.0)
            silent: Si True, n'affiche pas de message d'erreur
            
        Returns:
            True si la requête a réussi, False sinon
        """
        if not self.is_configured():
            if not silent:
                logger.debug("Slider non configuré (IP vide)")
            return False
        
        if not 0.0 <= fraction <= 1.0:
            if not silent:
                logger.warning(f"Fraction doit être entre 0.0 et 1.0, reçu: {fraction}")
            return False
        
        payload = {"fraction": fraction}
        
        try:
            url = f"{self.base_url}/api/v1/interp/goto"
            response = self.session.post(
                url,
                json=payload,
                timeout=self.timeout,
                headers={'Content-Type': 'application/json'}
            )
            
            if response.status_code == 200:
                return True
            else:
                if not silent:
                    logger.warning(f"Slider erreur HTTP {response.status_code}: {response.text}")
                return False
                
        except requests.exceptions.ConnectionError:
            if not silent:
                logger.debug(f"Slider non accessible à {self.base_url}")
            return False
        except requests.exceptions.Timeout:
            if not silent:
                logger.debug(f"Slider timeout à {self.base_url}")
            return False
        except Exception as e:
            if not silent:
                logger.error(f"Erreur slider: {e}")
            return False
    
    def update_interpolation_sequence(self, points: list, recalculate_duration: bool = False, 
                                     duration: Optional[float] = None, silent: bool = False) -> bool:
        """
        Met à jour une séquence d'interpolation en temps réel sans interrompre le mouvement.
        
        Args:
            points: Liste de dictionnaires avec les points de la séquence à mettre à jour.
                   Chaque point doit contenir 'fraction' (0.0-1.0) et optionnellement
                   'pan', 'tilt', 'zoom', 'slide' (0.0-1.0)
            recalculate_duration: Si True, recalcule la durée (nécessite duration)
            duration: Durée optionnelle en secondes (si recalculate_duration=True)
            silent: Si True, n'affiche pas de message d'erreur
            
        Returns:
            True si la requête a réussi, False sinon
        """
        if not self.is_configured():
            if not silent:
                logger.debug("Slider non configuré (IP vide)")
            return False
        
        # Construire le payload
        payload = {"points": points}
        if recalculate_duration:
            payload["recalculate_duration"] = True
            if duration is not None:
                payload["duration"] = duration
        
        try:
            url = f"{self.base_url}/api/v1/interp/setpoints/direct/update"
            response = self.session.patch(
                url,
                json=payload,
                timeout=self.timeout,
                headers={'Content-Type': 'application/json'}
            )
            
            if response.status_code == 200:
                return True
            else:
                if not silent:
                    logger.warning(f"Slider erreur HTTP {response.status_code}: {response.text}")
                return False
                
        except requests.exceptions.ConnectionError:
            if not silent:
                logger.debug(f"Slider non accessible à {self.base_url}")
            return False
        except requests.exceptions.Timeout:
            if not silent:
                logger.debug(f"Slider timeout à {self.base_url}")
            return False
        except Exception as e:
            if not silent:
                logger.error(f"Erreur slider: {e}")
            return False
    
    def bake_offsets(self, silent: bool = False) -> bool:
        """
        Intègre les offsets actuels dans le mouvement en cours et les réinitialise.
        Cela "bake" (intègre) les offsets joystick dans la position de base actuelle.
        
        Args:
            silent: Si True, n'affiche pas de message d'erreur
            
        Returns:
            True si la requête a réussi, False sinon
        """
        if not self.is_configured():
            if not silent:
                logger.debug("Slider non configuré (IP vide)")
            return False
        
        try:
            url = f"{self.base_url}/api/v1/offsets/bake"
            response = self.session.post(
                url,
                json={},  # Body vide selon la doc
                timeout=self.timeout,
                headers={'Content-Type': 'application/json'}
            )
            
            if response.status_code == 200:
                if not silent:
                    logger.debug("Offsets 'bakeés' avec succès")
                return True
            else:
                if not silent:
                    logger.warning(f"Slider erreur HTTP {response.status_code} lors du bake: {response.text}")
                return False
                
        except requests.exceptions.ConnectionError:
            if not silent:
                logger.debug(f"Slider non accessible à {self.base_url}")
            return False
        except requests.exceptions.Timeout:
            if not silent:
                logger.debug(f"Slider timeout à {self.base_url}")
            return False
        except Exception as e:
            if not silent:
                logger.error(f"Erreur slider lors du bake: {e}")
            return False

