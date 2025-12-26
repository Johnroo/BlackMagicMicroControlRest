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
        
        try:
            url = f"{self.base_url}{self.endpoint}"
            response = self.session.post(
                url,
                json=payload,
                timeout=self.timeout,
                headers={'Content-Type': 'application/json'}
            )
            
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

