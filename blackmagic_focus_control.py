#!/usr/bin/env python3
"""
Script pour contrôler le focus d'une caméra Blackmagic via l'API REST.
Permet de faire du polling pour lire la valeur actuelle et de mettre à jour la valeur désirée.
"""

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import time
import json
import threading
from typing import Optional, Callable, Dict, Any
import argparse
import os
import ssl
import asyncio
import websockets
from websockets.client import WebSocketClientProtocol
from base64 import b64encode
import logging
import os

# Configuration par défaut
DEFAULT_POLLING_FREQUENCY = 4  # fois par seconde
DEFAULT_TARGET_VALUE = None  # Aucune valeur cible par défaut
CONFIG_FILE = "focus_config.json"


class BlackmagicWebSocketClient:
    """Client WebSocket pour s'abonner aux changements de paramètres de la caméra Blackmagic."""
    
    def __init__(self, base_url: str, username: str = "roo", password: str = "koko", on_change_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None, on_connection_status_callback: Optional[Callable[[bool, str], None]] = None):
        """
        Initialise le client WebSocket.
        
        Args:
            base_url: URL de base de la caméra (ex: http://Micro-Studio-Camera-4K-G2.local)
            username: Nom d'utilisateur pour l'authentification basique
            password: Mot de passe pour l'authentification basique
            on_change_callback: Fonction appelée quand un paramètre change (param_name, data)
            on_connection_status_callback: Fonction appelée quand l'état de connexion change (connected: bool, message: str)
        """
        self.base_url = base_url.rstrip('/')
        # Convertir http:// en ws:// ou https:// en wss://
        ws_base = base_url.replace('http://', 'ws://').replace('https://', 'wss://')
        # Endpoint WebSocket selon la documentation Blackmagic Design
        # Format: /control/api/v1/event/websocket
        self.ws_url = f"{ws_base}/control/api/v1/event/websocket"
        self.username = username
        self.password = password
        self.on_change_callback = on_change_callback
        self.on_connection_status_callback = on_connection_status_callback
        self.websocket: Optional[WebSocketClientProtocol] = None
        self.running = False
        self.reconnect_delay = 5  # Secondes avant reconnexion
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.thread: Optional[threading.Thread] = None
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)
        
        # Créer les headers d'authentification basique
        credentials = b64encode(f"{username}:{password}".encode()).decode('ascii')
        self.auth_headers = {
            'Authorization': f'Basic {credentials}'
        }
        
        self.logger.info(f"Initialisation WebSocket client - URL: {self.ws_url}")
    
    def start(self):
        """Démarre le client WebSocket dans un thread séparé."""
        if self.running:
            return
        
        self.running = True
        self.thread = threading.Thread(target=self._run_event_loop, daemon=True)
        self.thread.start()
    
    def stop(self):
        """Arrête le client WebSocket."""
        self.running = False
        if self.loop and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(self._close_websocket(), self.loop)
        if self.thread:
            self.thread.join(timeout=2)
    
    def _run_event_loop(self):
        """Exécute la boucle d'événements asyncio dans un thread séparé."""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        
        self.loop.run_until_complete(self._connect_and_listen())
    
    async def _close_websocket(self):
        """Ferme la connexion WebSocket."""
        if self.websocket:
            try:
                await self.websocket.close()
            except Exception:
                pass
            self.websocket = None
    
    async def _connect_and_listen(self):
        """Se connecte et écoute les messages WebSocket avec reconnexion automatique."""
        # Notifier qu'on essaie de se connecter
        if self.on_connection_status_callback:
            try:
                self.on_connection_status_callback(False, "Tentative de connexion...")
            except Exception:
                pass
        
        while self.running:
            try:
                self.logger.info(f"Tentative de connexion WebSocket à {self.ws_url}")
                
                # Connexion WebSocket avec authentification
                # Note: websockets.connect peut nécessiter des paramètres supplémentaires
                # selon l'implémentation de l'API Blackmagic
                # Ajout d'un timeout pour éviter les blocages
                try:
                    # websockets 15.0.1 utilise additional_headers (liste de tuples) au lieu de extra_headers
                    # Convertir le dict en liste de tuples pour additional_headers
                    additional_headers = list(self.auth_headers.items())
                    
                    websocket = await asyncio.wait_for(
                        websockets.connect(
                            self.ws_url,
                            additional_headers=additional_headers,
                            ssl=None if 'ws://' in self.ws_url else ssl.create_default_context(),
                            ping_interval=None,
                            ping_timeout=None
                        ),
                        timeout=10.0
                    )
                    
                except asyncio.TimeoutError:
                    raise
                
                async with websocket:
                    self.websocket = websocket
                    self.logger.info(f"✓ WebSocket connecté avec succès à {self.ws_url}")
                    
                    # Notifier la connexion réussie
                    if self.on_connection_status_callback:
                        try:
                            self.on_connection_status_callback(True, "WebSocket caméra connecté")
                        except Exception as e:
                            self.logger.error(f"Erreur dans on_connection_status_callback: {e}")
                    
                    # S'abonner aux changements de tous les paramètres
                    await self._subscribe_to_all()
                    
                    # Écouter les messages
                    self.logger.info("En attente de messages WebSocket...")
                    
                    try:
                        async for message in websocket:
                            if not self.running:
                                break
                            await self._handle_message(message)
                    except websockets.exceptions.ConnectionClosed as e:
                        raise
                        
            except websockets.exceptions.InvalidURI as e:
                if self.running:
                    self.logger.error(f"URL WebSocket invalide: {e}")
                    self.logger.error(f"URL utilisée: {self.ws_url}")
                    self.logger.error("Vérifiez que l'endpoint WebSocket est correct selon la documentation (page 71)")
                    if self.on_connection_status_callback:
                        try:
                            self.on_connection_status_callback(False, f"URL WebSocket invalide: {e}")
                        except Exception:
                            pass
                    await asyncio.sleep(self.reconnect_delay)
            except websockets.exceptions.InvalidHandshake as e:
                if self.running:
                    self.logger.error(f"Échec du handshake WebSocket: {e}")
                    self.logger.error("Vérifiez l'authentification et l'endpoint WebSocket")
                    if self.on_connection_status_callback:
                        try:
                            self.on_connection_status_callback(False, f"Échec authentification: {e}")
                        except Exception:
                            pass
                    await asyncio.sleep(self.reconnect_delay)
            except websockets.exceptions.ConnectionClosed as e:
                if self.running:
                    self.logger.warning(f"Connexion WebSocket fermée (code: {e.code}, raison: {e.reason}), reconnexion dans {self.reconnect_delay}s...")
                    if self.on_connection_status_callback:
                        try:
                            self.on_connection_status_callback(False, f"Connexion fermée (code: {e.code})")
                        except Exception:
                            pass
                    await asyncio.sleep(self.reconnect_delay)
            except OSError as e:
                if self.running:
                    self.logger.error(f"Erreur réseau WebSocket: {e}")
                    self.logger.error(f"Vérifiez que la caméra est accessible à {self.base_url}")
                    if self.on_connection_status_callback:
                        try:
                            self.on_connection_status_callback(False, f"Erreur réseau: {e}")
                        except Exception:
                            pass
                    await asyncio.sleep(self.reconnect_delay)
            except Exception as e:
                if self.running:
                    self.logger.error(f"Erreur WebSocket inattendue: {type(e).__name__}: {e}")
                    import traceback
                    self.logger.error(traceback.format_exc())
                    if self.on_connection_status_callback:
                        try:
                            self.on_connection_status_callback(False, f"Erreur: {type(e).__name__}")
                        except Exception:
                            pass
                    await asyncio.sleep(self.reconnect_delay)
            finally:
                was_connected = self.websocket is not None
                self.websocket = None
                # Notifier la déconnexion si on était connecté
                if was_connected and self.on_connection_status_callback:
                    try:
                        self.on_connection_status_callback(False, "Déconnecté")
                    except Exception:
                        pass
    
    async def _subscribe_to_all(self):
        """S'abonne aux changements de tous les paramètres."""
        if not self.websocket:
            return
        
        try:
            # Format d'abonnement selon la documentation Blackmagic Design
            # Format: {"type": "request", "data": {"action": "subscribe", "properties": ["*"]}}
            # Pour s'abonner à toutes les propriétés, ou spécifier les chemins exacts
            subscribe_msg = {
                "type": "request",
                "data": {
                    "action": "subscribe",
                    "properties": [
                        "/lens/focus",
                        "/lens/iris",
                        "/lens/zoom",
                        "/video/gain",
                        "/video/shutter",
                        "/monitoring/HDMI/zebra",
                        "/monitoring/HDMI/focusAssist",
                        "/monitoring/HDMI/falseColor"
                    ]
                }
            }
            
            await self.websocket.send(json.dumps(subscribe_msg))
            self.logger.info("Abonnement envoyé pour tous les paramètres")
        except Exception as e:
            self.logger.error(f"Erreur lors de l'abonnement: {e}")
    
    async def _handle_message(self, message: str):
        """Traite un message reçu du WebSocket."""
        try:
            data = json.loads(message)
            
            self.logger.debug(f"Message WebSocket reçu: {data}")
            
            # Format selon la documentation Blackmagic Design
            # Les messages peuvent être de type "event" ou "response"
            msg_type = data.get('type', '')
            
            if msg_type == 'event':
                # Message d'événement - format réel: {"data": {"action": "propertyValueChanged", "property": "/lens/focus", "value": {...}}, "type": "event"}
                event_data = data.get('data', {})
                action = event_data.get('action', '')
                
                if action == 'propertyValueChanged':
                    # Format réel: property est une string, value est un dict
                    prop_path = event_data.get('property', '')
                    prop_value = event_data.get('value', {})
                    
                    param_type = None
                    
                    # Déterminer le type de paramètre selon le chemin
                    if '/lens/focus' in prop_path:
                        param_type = 'focus'
                        # Format: {"normalised": 0.5}
                        param_data = prop_value if isinstance(prop_value, dict) else {'normalised': prop_value}
                    elif '/lens/iris' in prop_path:
                        param_type = 'iris'
                        param_data = prop_value if isinstance(prop_value, dict) else {'normalised': prop_value}
                    elif '/lens/zoom' in prop_path:
                        param_type = 'zoom'
                        param_data = prop_value if isinstance(prop_value, dict) else prop_value
                    elif '/video/gain' in prop_path:
                        param_type = 'gain'
                        param_data = prop_value if isinstance(prop_value, dict) else {'gain': prop_value}
                    elif '/video/shutter' in prop_path:
                        param_type = 'shutter'
                        param_data = prop_value if isinstance(prop_value, dict) else prop_value
                    elif '/monitoring/HDMI/zebra' in prop_path or '/video/zebra' in prop_path:
                        param_type = 'zebra'
                        param_data = prop_value if isinstance(prop_value, dict) else {'enabled': prop_value}
                    elif '/monitoring/HDMI/focusAssist' in prop_path or '/video/focusAssist' in prop_path:
                        param_type = 'focusAssist'
                        param_data = prop_value if isinstance(prop_value, dict) else {'enabled': prop_value}
                    elif '/monitoring/HDMI/falseColor' in prop_path or '/video/falseColor' in prop_path:
                        param_type = 'falseColor'
                        param_data = prop_value if isinstance(prop_value, dict) else {'enabled': prop_value}
                    elif '/monitoring/HDMI/cleanfeed' in prop_path or '/video/cleanfeed' in prop_path:
                        param_type = 'cleanfeed'
                        param_data = prop_value if isinstance(prop_value, dict) else {'enabled': prop_value}
                    
                    if param_type and self.on_change_callback:
                        self.logger.debug(f"Événement {param_type} reçu: {param_data}")
                        self.on_change_callback(param_type, param_data)
                elif action == 'websocketOpened':
                    # Message de confirmation d'ouverture - on l'ignore
                    self.logger.debug("WebSocket ouvert confirmé")
                else:
                    self.logger.debug(f"Action d'événement non gérée: {action}")
            
            elif msg_type == 'response':
                # Message de réponse - peut contenir des données initiales
                response_data = data.get('data', {})
                self.logger.debug(f"Réponse WebSocket reçue: {response_data}")
                # Les réponses peuvent contenir des données initiales, mais on les ignore
                # car on récupère les valeurs initiales via HTTP
            
            else:
                # Format inattendu, essayer de parser quand même
                self.logger.warning(f"Format de message inattendu: {msg_type}, données: {data}")
                
        except json.JSONDecodeError as e:
            self.logger.warning(f"Message WebSocket non-JSON reçu: {message}")
        except Exception as e:
            self.logger.error(f"Erreur lors du traitement du message WebSocket: {e}")
            import traceback
            self.logger.error(traceback.format_exc())


class BlackmagicFocusController:
    """Contrôleur pour l'API REST Blackmagic Focus."""
    
    def __init__(self, base_url: str, username: str = "roo", password: str = "koko"):
        """
        Initialise le contrôleur.
        
        Args:
            base_url: URL de base de la caméra (ex: https://Micro-Studio-Camera-4K-G2.local)
            username: Nom d'utilisateur pour l'authentification basique
            password: Mot de passe pour l'authentification basique
        """
        self.base_url = base_url.rstrip('/')
        self.focus_endpoint = f"{self.base_url}/control/api/v1/lens/focus"
        self.iris_endpoint = f"{self.base_url}/control/api/v1/lens/iris"
        self.zoom_endpoint = f"{self.base_url}/control/api/v1/lens/zoom"
        self.gain_endpoint = f"{self.base_url}/control/api/v1/video/gain"
        self.supported_gains_endpoint = f"{self.base_url}/control/api/v1/video/supportedGains"
        self.shutter_endpoint = f"{self.base_url}/control/api/v1/video/shutter"
        self.shutter_measurement_endpoint = f"{self.base_url}/control/api/v1/video/shutter/measurement"
        self.supported_shutters_endpoint = f"{self.base_url}/control/api/v1/video/supportedShutters"
        self.display_name = "HDMI"  # Display name fixe selon la documentation
        self.zebra_endpoint = f"{self.base_url}/control/api/v1/monitoring/{self.display_name}/zebra"
        self.focus_assist_endpoint = f"{self.base_url}/control/api/v1/monitoring/{self.display_name}/focusAssist"
        self.false_color_endpoint = f"{self.base_url}/control/api/v1/monitoring/{self.display_name}/falseColor"
        self.cleanfeed_endpoint = f"{self.base_url}/control/api/v1/monitoring/{self.display_name}/cleanFeed"
        self.autofocus_endpoint = f"{self.base_url}/control/api/v1/lens/focus/doAutoFocus"
        self.auth = (username, password)
        self.current_value: Optional[float] = None
        self.target_value: Optional[float] = None
        self.polling_active = False
        self.polling_thread: Optional[threading.Thread] = None
        self.polling_frequency = DEFAULT_POLLING_FREQUENCY
        self.config_watch_active = False
        self.config_watch_thread: Optional[threading.Thread] = None
        self.last_config_mtime = 0
        self.interactive_mode = False
        self.debug = False
        
        # Créer une session avec configuration SSL permissive
        self.session = requests.Session()
        self.session.auth = self.auth
        self.session.verify = False
        
        # Désactiver les avertissements SSL
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        
        # Configuration pour gérer les certificats auto-signés
        retry_strategy = Retry(
            total=3,
            backoff_factor=0.3,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        
    def get_focus(self) -> Optional[float]:
        """
        Récupère la valeur actuelle du focus.
        
        Returns:
            La valeur normalisée du focus (0.0 à 1.0) ou None en cas d'erreur
        """
        try:
            if self.debug:
                print(f"[DEBUG] GET {self.focus_endpoint}")
                print(f"[DEBUG] Auth: {self.auth[0]}:{self.auth[1]}")
            
            response = self.session.get(
                self.focus_endpoint,
                timeout=10,
                headers={'Accept': 'application/json', 'Content-Type': 'application/json'}
            )
            
            if self.debug:
                print(f"[DEBUG] Status: {response.status_code}")
                print(f"[DEBUG] Response: {response.text}")
            
            response.raise_for_status()
            data = response.json()
            self.current_value = data.get("normalised")
            return self.current_value
        except requests.exceptions.SSLError as e:
            print(f"Erreur SSL lors de la récupération du focus: {e}")
            return None
        except requests.exceptions.ConnectionError as e:
            print(f"Erreur de connexion lors de la récupération du focus: {e}")
            print(f"Vérifiez que la caméra est accessible à: {self.focus_endpoint}")
            return None
        except requests.exceptions.RequestException as e:
            print(f"Erreur lors de la récupération du focus: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"Status code: {e.response.status_code}")
                print(f"Response: {e.response.text}")
            return None

    def get_zoom(self) -> Optional[dict]:
        """
        Récupère les valeurs actuelles du zoom (focale et valeur normalisée).
        
        Returns:
            Dictionnaire avec focalLength et normalised, ou None en cas d'erreur
        """
        try:
            if self.debug:
                print(f"[DEBUG] GET {self.zoom_endpoint}")
                print(f"[DEBUG] Auth: {self.auth[0]}:{self.auth[1]}")
            
            response = self.session.get(
                self.zoom_endpoint,
                timeout=10,
                headers={'Accept': 'application/json', 'Content-Type': 'application/json'}
            )
            
            if self.debug:
                print(f"[DEBUG] Status: {response.status_code}")
                print(f"[DEBUG] Response: {response.text}")
            
            response.raise_for_status()
            data = response.json()
            return {
                'focalLength': data.get('focalLength'),
                'normalised': data.get('normalised')
            }
        except requests.exceptions.SSLError as e:
            print(f"Erreur SSL lors de la récupération du zoom: {e}")
            return None
        except requests.exceptions.ConnectionError as e:
            print(f"Erreur de connexion lors de la récupération du zoom: {e}")
            print(f"Vérifiez que la caméra est accessible à: {self.zoom_endpoint}")
            return None
        except requests.exceptions.RequestException as e:
            print(f"Erreur lors de la récupération du zoom: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"Status code: {e.response.status_code}")
                print(f"Response: {e.response.text}")
            return None
    
    def set_focus(self, value: float, silent: bool = False) -> bool:
        """
        Définit la valeur du focus.
        
        Args:
            value: Valeur normalisée du focus (0.0 à 1.0)
            silent: Si True, n'affiche pas de message de confirmation
            
        Returns:
            True si la mise à jour a réussi, False sinon
        """
        if not 0.0 <= value <= 1.0:
            print(f"Erreur: La valeur doit être entre 0.0 et 1.0, reçu: {value}")
            return False
            
        try:
            payload = {"normalised": value}
            
            if self.debug:
                print(f"[DEBUG] PUT {self.focus_endpoint}")
                print(f"[DEBUG] Payload: {payload}")
                print(f"[DEBUG] Auth: {self.auth[0]}:{self.auth[1]}")
            
            response = self.session.put(
                self.focus_endpoint,
                json=payload,
                timeout=10,
                headers={'Accept': 'application/json', 'Content-Type': 'application/json'}
            )
            
            if self.debug:
                print(f"[DEBUG] Status: {response.status_code}")
                print(f"[DEBUG] Response: {response.text}")
            
            response.raise_for_status()
            self.target_value = value
            if not silent:
                print(f"Focus mis à jour avec succès: {value}")
            return True
        except requests.exceptions.SSLError as e:
            print(f"Erreur SSL lors de la mise à jour du focus: {e}")
            return False
        except requests.exceptions.ConnectionError as e:
            print(f"Erreur de connexion lors de la mise à jour du focus: {e}")
            print(f"Vérifiez que la caméra est accessible à: {self.focus_endpoint}")
            return False
        except requests.exceptions.RequestException as e:
            print(f"Erreur lors de la mise à jour du focus: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"Status code: {e.response.status_code}")
                print(f"Response: {e.response.text}")
            return False
    
    def get_iris(self) -> Optional[dict]:
        """
        Récupère les valeurs actuelles de l'iris.
        
        Returns:
            Dictionnaire avec normalised, apertureStop, apertureNumber, continuousApertureAutoExposure
            ou None en cas d'erreur
        """
        try:
            if self.debug:
                print(f"[DEBUG] GET {self.iris_endpoint}")
                print(f"[DEBUG] Auth: {self.auth[0]}:{self.auth[1]}")
            
            response = self.session.get(
                self.iris_endpoint,
                timeout=10,
                headers={'Accept': 'application/json', 'Content-Type': 'application/json'}
            )
            
            if self.debug:
                print(f"[DEBUG] Status: {response.status_code}")
                print(f"[DEBUG] Response: {response.text}")
            
            response.raise_for_status()
            data = response.json()
            return {
                'normalised': data.get('normalised'),
                'apertureStop': data.get('apertureStop'),
                'apertureNumber': data.get('apertureNumber'),
                'continuousApertureAutoExposure': data.get('continuousApertureAutoExposure', False)
            }
        except requests.exceptions.SSLError as e:
            print(f"Erreur SSL lors de la récupération de l'iris: {e}")
            return None
        except requests.exceptions.ConnectionError as e:
            print(f"Erreur de connexion lors de la récupération de l'iris: {e}")
            print(f"Vérifiez que la caméra est accessible à: {self.iris_endpoint}")
            return None
        except requests.exceptions.RequestException as e:
            print(f"Erreur lors de la récupération de l'iris: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"Status code: {e.response.status_code}")
                print(f"Response: {e.response.text}")
            return None
    
    def set_iris(self, value: float, silent: bool = False) -> bool:
        """
        Définit la valeur de l'iris.
        
        Args:
            value: Valeur normalisée de l'iris (0.0 à 1.0)
            silent: Si True, n'affiche pas de message de confirmation
            
        Returns:
            True si la mise à jour a réussi, False sinon
        """
        if not 0.0 <= value <= 1.0:
            if not silent:
                print(f"Erreur: La valeur doit être entre 0.0 et 1.0, reçu: {value}")
            return False
            
        try:
            payload = {"normalised": value}
            
            if self.debug:
                print(f"[DEBUG] PUT {self.iris_endpoint}")
                print(f"[DEBUG] Payload: {payload}")
                print(f"[DEBUG] Auth: {self.auth[0]}:{self.auth[1]}")
            
            response = self.session.put(
                self.iris_endpoint,
                json=payload,
                timeout=10,
                headers={'Accept': 'application/json', 'Content-Type': 'application/json'}
            )
            
            if self.debug:
                print(f"[DEBUG] Status: {response.status_code}")
                print(f"[DEBUG] Response: {response.text}")
            
            response.raise_for_status()
            if not silent:
                print(f"Iris mis à jour avec succès: {value}")
            return True
        except requests.exceptions.SSLError as e:
            if not silent:
                print(f"Erreur SSL lors de la mise à jour de l'iris: {e}")
            return False
        except requests.exceptions.ConnectionError as e:
            if not silent:
                print(f"Erreur de connexion lors de la mise à jour de l'iris: {e}")
                print(f"Vérifiez que la caméra est accessible à: {self.iris_endpoint}")
            return False
        except requests.exceptions.RequestException as e:
            if not silent:
                print(f"Erreur lors de la mise à jour de l'iris: {e}")
                if hasattr(e, 'response') and e.response is not None:
                    print(f"Status code: {e.response.status_code}")
                    print(f"Response: {e.response.text}")
            return False
    
    def get_supported_gains(self) -> Optional[list]:
        """
        Récupère la liste des gains supportés en décibels.
        
        Returns:
            Liste d'entiers représentant les gains supportés en dB, ou None en cas d'erreur
        """
        try:
            if self.debug:
                print(f"[DEBUG] GET {self.supported_gains_endpoint}")
                print(f"[DEBUG] Auth: {self.auth[0]}:{self.auth[1]}")
            
            response = self.session.get(
                self.supported_gains_endpoint,
                timeout=10,
                headers={'Accept': 'application/json', 'Content-Type': 'application/json'}
            )
            
            if self.debug:
                print(f"[DEBUG] Status: {response.status_code}")
                print(f"[DEBUG] Response: {response.text}")
            
            response.raise_for_status()
            data = response.json()
            return data.get('supportedGains', [])
        except requests.exceptions.SSLError as e:
            print(f"Erreur SSL lors de la récupération des gains supportés: {e}")
            return None
        except requests.exceptions.ConnectionError as e:
            print(f"Erreur de connexion lors de la récupération des gains supportés: {e}")
            print(f"Vérifiez que la caméra est accessible à: {self.supported_gains_endpoint}")
            return None
        except requests.exceptions.RequestException as e:
            print(f"Erreur lors de la récupération des gains supportés: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"Status code: {e.response.status_code}")
                print(f"Response: {e.response.text}")
            return None
    
    def get_gain(self) -> Optional[int]:
        """
        Récupère la valeur actuelle du gain en décibels.
        
        Returns:
            La valeur du gain en dB (integer) ou None en cas d'erreur
        """
        try:
            if self.debug:
                print(f"[DEBUG] GET {self.gain_endpoint}")
                print(f"[DEBUG] Auth: {self.auth[0]}:{self.auth[1]}")
            
            response = self.session.get(
                self.gain_endpoint,
                timeout=10,
                headers={'Accept': 'application/json', 'Content-Type': 'application/json'}
            )
            
            if self.debug:
                print(f"[DEBUG] Status: {response.status_code}")
                print(f"[DEBUG] Response: {response.text}")
            
            response.raise_for_status()
            data = response.json()
            return data.get('gain')
        except requests.exceptions.SSLError as e:
            print(f"Erreur SSL lors de la récupération du gain: {e}")
            return None
        except requests.exceptions.ConnectionError as e:
            print(f"Erreur de connexion lors de la récupération du gain: {e}")
            print(f"Vérifiez que la caméra est accessible à: {self.gain_endpoint}")
            return None
        except requests.exceptions.RequestException as e:
            print(f"Erreur lors de la récupération du gain: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"Status code: {e.response.status_code}")
                print(f"Response: {e.response.text}")
            return None
    
    def set_gain(self, value: int, silent: bool = False) -> bool:
        """
        Définit la valeur du gain en décibels.
        
        Args:
            value: Valeur du gain en dB (integer)
            silent: Si True, n'affiche pas de message de confirmation
            
        Returns:
            True si la mise à jour a réussi, False sinon
        """
        try:
            payload = {"gain": value}
            
            if self.debug:
                print(f"[DEBUG] PUT {self.gain_endpoint}")
                print(f"[DEBUG] Payload: {payload}")
                print(f"[DEBUG] Auth: {self.auth[0]}:{self.auth[1]}")
            
            response = self.session.put(
                self.gain_endpoint,
                json=payload,
                timeout=10,
                headers={'Accept': 'application/json', 'Content-Type': 'application/json'}
            )
            
            if self.debug:
                print(f"[DEBUG] Status: {response.status_code}")
                print(f"[DEBUG] Response: {response.text}")
            
            response.raise_for_status()
            if not silent:
                print(f"Gain mis à jour avec succès: {value} dB")
            return True
        except requests.exceptions.SSLError as e:
            if not silent:
                print(f"Erreur SSL lors de la mise à jour du gain: {e}")
            return False
        except requests.exceptions.ConnectionError as e:
            if not silent:
                print(f"Erreur de connexion lors de la mise à jour du gain: {e}")
                print(f"Vérifiez que la caméra est accessible à: {self.gain_endpoint}")
            return False
        except requests.exceptions.RequestException as e:
            if not silent:
                print(f"Erreur lors de la mise à jour du gain: {e}")
                if hasattr(e, 'response') and e.response is not None:
                    status_code = e.response.status_code
                    print(f"Status code: {status_code}")
                    if status_code == 403:
                        print("Le gain ne peut pas être modifié dans l'état actuel de la caméra")
                    print(f"Response: {e.response.text}")
            return False
    
    def get_shutter_measurement(self) -> Optional[str]:
        """
        Récupère le mode de mesure du shutter actuel.
        
        Returns:
            "ShutterAngle" ou "ShutterSpeed", ou None en cas d'erreur
        """
        try:
            if self.debug:
                print(f"[DEBUG] GET {self.shutter_measurement_endpoint}")
            
            response = self.session.get(
                self.shutter_measurement_endpoint,
                timeout=10,
                headers={'Accept': 'application/json', 'Content-Type': 'application/json'}
            )
            
            if self.debug:
                print(f"[DEBUG] Status: {response.status_code}")
                print(f"[DEBUG] Response: {response.text}")
            
            response.raise_for_status()
            data = response.json()
            return data.get('measurement')
        except requests.exceptions.RequestException as e:
            print(f"Erreur lors de la récupération du mode shutter: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"Status code: {e.response.status_code}")
            return None
    
    def set_shutter_measurement(self, mode: str, silent: bool = False) -> bool:
        """
        Définit le mode de mesure du shutter.
        
        Args:
            mode: "ShutterAngle" ou "ShutterSpeed"
            silent: Si True, n'affiche pas de message de confirmation
            
        Returns:
            True si la mise à jour a réussi, False sinon
        """
        if mode not in ['ShutterAngle', 'ShutterSpeed']:
            if not silent:
                print(f"Erreur: Le mode doit être 'ShutterAngle' ou 'ShutterSpeed', reçu: {mode}")
            return False
        
        try:
            payload = {"measurement": mode}
            
            if self.debug:
                print(f"[DEBUG] PUT {self.shutter_measurement_endpoint}")
                print(f"[DEBUG] Payload: {payload}")
            
            response = self.session.put(
                self.shutter_measurement_endpoint,
                json=payload,
                timeout=10,
                headers={'Accept': 'application/json', 'Content-Type': 'application/json'}
            )
            
            if self.debug:
                print(f"[DEBUG] Status: {response.status_code}")
            
            response.raise_for_status()
            if not silent:
                print(f"Mode shutter mis à jour: {mode}")
            return True
        except requests.exceptions.RequestException as e:
            if not silent:
                print(f"Erreur lors de la mise à jour du mode shutter: {e}")
                if hasattr(e, 'response') and e.response is not None:
                    print(f"Status code: {e.response.status_code}")
            return False
    
    def get_supported_shutters(self) -> Optional[dict]:
        """
        Récupère les valeurs de shutter supportées.
        
        Returns:
            Dictionnaire avec shutterAngles (array) et shutterSpeeds (array), ou None en cas d'erreur
        """
        try:
            if self.debug:
                print(f"[DEBUG] GET {self.supported_shutters_endpoint}")
            
            response = self.session.get(
                self.supported_shutters_endpoint,
                timeout=10,
                headers={'Accept': 'application/json', 'Content-Type': 'application/json'}
            )
            
            if self.debug:
                print(f"[DEBUG] Status: {response.status_code}")
                print(f"[DEBUG] Response: {response.text}")
            
            response.raise_for_status()
            data = response.json()
            return {
                'shutterAngles': data.get('shutterAngles', []),
                'shutterSpeeds': data.get('shutterSpeeds', [])
            }
        except requests.exceptions.RequestException as e:
            print(f"Erreur lors de la récupération des shutters supportés: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"Status code: {e.response.status_code}")
            return None
    
    def get_shutter(self) -> Optional[dict]:
        """
        Récupère les valeurs actuelles du shutter.
        
        Returns:
            Dictionnaire avec shutterSpeed, shutterAngle, continuousShutterAutoExposure
            ou None en cas d'erreur
        """
        try:
            if self.debug:
                print(f"[DEBUG] GET {self.shutter_endpoint}")
            
            response = self.session.get(
                self.shutter_endpoint,
                timeout=10,
                headers={'Accept': 'application/json', 'Content-Type': 'application/json'}
            )
            
            if self.debug:
                print(f"[DEBUG] Status: {response.status_code}")
                print(f"[DEBUG] Response: {response.text}")
            
            response.raise_for_status()
            data = response.json()
            return {
                'shutterSpeed': data.get('shutterSpeed'),
                'shutterAngle': data.get('shutterAngle'),
                'continuousShutterAutoExposure': data.get('continuousShutterAutoExposure', False)
            }
        except requests.exceptions.RequestException as e:
            print(f"Erreur lors de la récupération du shutter: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"Status code: {e.response.status_code}")
            return None
    
    def set_shutter(self, shutter_speed: Optional[int] = None, shutter_angle: Optional[float] = None, silent: bool = False) -> bool:
        """
        Définit la valeur du shutter.
        
        Args:
            shutter_speed: Valeur en fractions de seconde (integer) pour le mode ShutterSpeed
            shutter_angle: Valeur en degrés (float) pour le mode ShutterAngle
            silent: Si True, n'affiche pas de message de confirmation
            
        Returns:
            True si la mise à jour a réussi, False sinon
        """
        if shutter_speed is None and shutter_angle is None:
            if not silent:
                print("Erreur: Il faut fournir soit shutter_speed soit shutter_angle")
            return False
        
        try:
            payload = {}
            if shutter_speed is not None:
                payload['shutterSpeed'] = shutter_speed
            if shutter_angle is not None:
                payload['shutterAngle'] = shutter_angle
            
            if self.debug:
                print(f"[DEBUG] PUT {self.shutter_endpoint}")
                print(f"[DEBUG] Payload: {payload}")
            
            response = self.session.put(
                self.shutter_endpoint,
                json=payload,
                timeout=10,
                headers={'Accept': 'application/json', 'Content-Type': 'application/json'}
            )
            
            if self.debug:
                print(f"[DEBUG] Status: {response.status_code}")
            
            response.raise_for_status()
            if not silent:
                if shutter_speed is not None:
                    print(f"Shutter mis à jour: {shutter_speed} (1/{shutter_speed}s)")
                if shutter_angle is not None:
                    print(f"Shutter mis à jour: {shutter_angle}°")
            return True
        except requests.exceptions.RequestException as e:
            if not silent:
                print(f"Erreur lors de la mise à jour du shutter: {e}")
                if hasattr(e, 'response') and e.response is not None:
                    status_code = e.response.status_code
                    print(f"Status code: {status_code}")
                    if status_code == 403:
                        print("Le shutter ne peut pas être modifié dans l'état actuel de la caméra")
                    print(f"Response: {e.response.text}")
            return False
    
    def get_zebra(self) -> Optional[bool]:
        """
        Récupère l'état actuel du Zebra.
        
        Returns:
            True si activé, False si désactivé, ou None en cas d'erreur
        """
        try:
            response = self.session.get(
                self.zebra_endpoint,
                timeout=10,
                headers={'Accept': 'application/json', 'Content-Type': 'application/json'}
            )
            response.raise_for_status()
            data = response.json()
            result = data.get('enabled', False)
            return result
        except requests.exceptions.RequestException as e:
            if self.debug:
                print(f"Erreur lors de la récupération du Zebra: {e}")
            return None
    
    def set_zebra(self, enabled: bool, silent: bool = False) -> bool:
        """
        Active ou désactive le Zebra.
        
        Args:
            enabled: True pour activer, False pour désactiver
            silent: Si True, n'affiche pas de message de confirmation
            
        Returns:
            True si la mise à jour a réussi, False sinon
        """
        try:
            payload = {"enabled": enabled}
            response = self.session.put(
                self.zebra_endpoint,
                json=payload,
                timeout=10,
                headers={'Accept': 'application/json', 'Content-Type': 'application/json'}
            )
            # Le code 204 (No Content) indique le succès selon la documentation
            if response.status_code == 204:
                if not silent:
                    print(f"Zebra {'activé' if enabled else 'désactivé'}")
                return True
            else:
                # Pour les autres codes de succès (200, etc.)
                response.raise_for_status()
                if not silent:
                    print(f"Zebra {'activé' if enabled else 'désactivé'}")
                return True
        except requests.exceptions.RequestException as e:
            if not silent:
                if hasattr(e, 'response') and e.response is not None:
                    status_code = e.response.status_code
                    if status_code == 400:
                        print("Erreur: Entrée invalide (400)")
                    elif status_code == 422:
                        print("Erreur: Impossible de traiter les instructions (422)")
                    else:
                        print(f"Erreur lors de la mise à jour du Zebra: {e}")
                else:
                    print(f"Erreur lors de la mise à jour du Zebra: {e}")
            return False
    
    def get_focus_assist(self) -> Optional[bool]:
        """
        Récupère l'état actuel du Focus Assist.
        
        Returns:
            True si activé, False si désactivé, ou None en cas d'erreur
        """
        try:
            response = self.session.get(
                self.focus_assist_endpoint,
                timeout=10,
                headers={'Accept': 'application/json', 'Content-Type': 'application/json'}
            )
            response.raise_for_status()
            data = response.json()
            result = data.get('enabled', False)
            return result
        except requests.exceptions.RequestException as e:
            if self.debug:
                print(f"Erreur lors de la récupération du Focus Assist: {e}")
            return None
    
    def set_focus_assist(self, enabled: bool, silent: bool = False) -> bool:
        """
        Active ou désactive le Focus Assist.
        
        Args:
            enabled: True pour activer, False pour désactiver
            silent: Si True, n'affiche pas de message de confirmation
            
        Returns:
            True si la mise à jour a réussi, False sinon
        """
        try:
            payload = {"enabled": enabled}
            response = self.session.put(
                self.focus_assist_endpoint,
                json=payload,
                timeout=10,
                headers={'Accept': 'application/json', 'Content-Type': 'application/json'}
            )
            # Le code 204 (No Content) indique le succès selon la documentation
            if response.status_code == 204:
                if not silent:
                    print(f"Focus Assist {'activé' if enabled else 'désactivé'}")
                return True
            else:
                # Pour les autres codes de succès (200, etc.)
                response.raise_for_status()
                if not silent:
                    print(f"Focus Assist {'activé' if enabled else 'désactivé'}")
                return True
        except requests.exceptions.RequestException as e:
            if not silent:
                if hasattr(e, 'response') and e.response is not None:
                    status_code = e.response.status_code
                    if status_code == 400:
                        print("Erreur: Entrée invalide ou configuration invalide (400)")
                    elif status_code == 422:
                        print("Erreur: Impossible de traiter les instructions (422)")
                    else:
                        print(f"Erreur lors de la mise à jour du Focus Assist: {e}")
                else:
                    print(f"Erreur lors de la mise à jour du Focus Assist: {e}")
            return False
    
    def get_false_color(self) -> Optional[bool]:
        """
        Récupère l'état actuel du False Color.
        
        Returns:
            True si activé, False si désactivé, ou None en cas d'erreur
        """
        try:
            response = self.session.get(
                self.false_color_endpoint,
                timeout=10,
                headers={'Accept': 'application/json', 'Content-Type': 'application/json'}
            )
            response.raise_for_status()
            data = response.json()
            return data.get('enabled', False)
        except requests.exceptions.RequestException as e:
            if self.debug:
                print(f"Erreur lors de la récupération du False Color: {e}")
            return None
    
    def set_false_color(self, enabled: bool, silent: bool = False) -> bool:
        """
        Active ou désactive le False Color.
        
        Args:
            enabled: True pour activer, False pour désactiver
            silent: Si True, n'affiche pas de message de confirmation
            
        Returns:
            True si la mise à jour a réussi, False sinon
        """
        try:
            payload = {"enabled": enabled}
            response = self.session.put(
                self.false_color_endpoint,
                json=payload,
                timeout=10,
                headers={'Accept': 'application/json', 'Content-Type': 'application/json'}
            )
            response.raise_for_status()
            if not silent:
                print(f"False Color {'activé' if enabled else 'désactivé'}")
            return True
        except requests.exceptions.RequestException as e:
            if not silent:
                print(f"Erreur lors de la mise à jour du False Color: {e}")
            return False
    
    def get_cleanfeed(self) -> Optional[bool]:
        """
        Récupère l'état actuel du Cleanfeed.
        
        Returns:
            True si activé, False si désactivé, ou None en cas d'erreur
        """
        try:
            response = self.session.get(
                self.cleanfeed_endpoint,
                timeout=10,
                headers={'Accept': 'application/json', 'Content-Type': 'application/json'}
            )
            response.raise_for_status()
            data = response.json()
            return data.get('enabled', False)
        except requests.exceptions.RequestException as e:
            if self.debug:
                print(f"Erreur lors de la récupération du Cleanfeed: {e}")
            return None
    
    def set_cleanfeed(self, enabled: bool, silent: bool = False) -> bool:
        """
        Active ou désactive le Cleanfeed.
        
        Args:
            enabled: True pour activer, False pour désactiver
            silent: Si True, n'affiche pas de message de confirmation
            
        Returns:
            True si la mise à jour a réussi, False sinon
        """
        try:
            payload = {"enabled": enabled}
            response = self.session.put(
                self.cleanfeed_endpoint,
                json=payload,
                timeout=10,
                headers={'Accept': 'application/json', 'Content-Type': 'application/json'}
            )
            response.raise_for_status()
            if not silent:
                print(f"Cleanfeed {'activé' if enabled else 'désactivé'}")
            return True
        except requests.exceptions.RequestException as e:
            if not silent:
                print(f"Erreur lors de la mise à jour du Cleanfeed: {e}")
            return False
    
    def do_autofocus(self, x: float = 0.5, y: float = 0.5, silent: bool = False) -> bool:
        """
        Déclenche l'autofocus à une position donnée.
        
        Args:
            x: Position X normalisée (0.0 à 1.0) pour le point de focus
            y: Position Y normalisée (0.0 à 1.0) pour le point de focus
            silent: Si True, n'affiche pas de message de confirmation
            
        Returns:
            True si l'autofocus a été déclenché avec succès, False sinon
        """
        if not (0.0 <= x <= 1.0) or not (0.0 <= y <= 1.0):
            error_msg = f"Erreur: Les positions doivent être entre 0.0 et 1.0, reçu: x={x}, y={y}"
            if not silent:
                print(error_msg)
            logging.error(error_msg)
            return False
        
        try:
            # Format selon la documentation: {"position": {"x": x, "y": y}}
            payload = {"position": {"x": x, "y": y}}
            
            if self.debug or not silent:
                print(f"[DEBUG] PUT {self.autofocus_endpoint}")
                print(f"[DEBUG] Payload: {payload}")
            
            # Utiliser PUT au lieu de POST selon la documentation
            response = self.session.put(
                self.autofocus_endpoint,
                json=payload,
                timeout=10,
                headers={'Accept': 'application/json', 'Content-Type': 'application/json'}
            )
            
            if self.debug or not silent:
                print(f"[DEBUG] Status: {response.status_code}")
                print(f"[DEBUG] Response: {response.text}")
            
            # L'API peut retourner 204 (No Content) ou 200 pour indiquer le succès
            if response.status_code in [200, 204]:
                if not silent:
                    print(f"Autofocus déclenché à la position ({x:.2f}, {y:.2f})")
                return True
            else:
                # Log l'erreur même en mode silent pour le débogage
                error_msg = f"Status code inattendu: {response.status_code}, Response: {response.text}"
                logging.error(f"Autofocus error: {error_msg}")
                if not silent:
                    print(f"Erreur: {error_msg}")
                response.raise_for_status()
                return True
        except requests.exceptions.SSLError as e:
            error_msg = f"Erreur SSL lors du déclenchement de l'autofocus: {e}"
            logging.error(error_msg)
            if not silent:
                print(error_msg)
            return False
        except requests.exceptions.ConnectionError as e:
            error_msg = f"Erreur de connexion lors du déclenchement de l'autofocus: {e}"
            logging.error(f"{error_msg}, Endpoint: {self.autofocus_endpoint}")
            if not silent:
                print(error_msg)
                print(f"Vérifiez que la caméra est accessible à: {self.autofocus_endpoint}")
            return False
        except requests.exceptions.RequestException as e:
            error_msg = f"Erreur lors du déclenchement de l'autofocus: {e}"
            logging.error(error_msg)
            if hasattr(e, 'response') and e.response is not None:
                status_code = e.response.status_code
                response_text = e.response.text
                logging.error(f"Status code: {status_code}, Response: {response_text}")
                if not silent:
                    print(error_msg)
                    print(f"Status code: {status_code}")
                    if status_code == 403:
                        print("L'autofocus ne peut pas être déclenché dans l'état actuel de la caméra")
                    elif status_code == 400:
                        print("Erreur: Position invalide ou paramètres incorrects")
                    elif status_code == 404:
                        print(f"Erreur: Endpoint non trouvé. Vérifiez que l'endpoint {self.autofocus_endpoint} est correct.")
                    print(f"Response: {response_text}")
            else:
                if not silent:
                    print(error_msg)
            return False
    
    def _polling_loop(self):
        """Boucle de polling qui s'exécute dans un thread séparé."""
        while self.polling_active:
            value = self.get_focus()
            if value is not None:
                # Afficher sur une seule ligne avec retour chariot pour éviter le spam
                if self.target_value is not None:
                    print(f"\r[Polling] Focus actuel: {value:.6f} | Cible: {self.target_value:.6f}", end='', flush=True)
                else:
                    print(f"\r[Polling] Focus actuel: {value:.6f}", end='', flush=True)
            else:
                print("\r[Polling] Erreur lors de la récupération", end='', flush=True)
            
            time.sleep(1.0 / self.polling_frequency)
    
    def start_polling(self, frequency: float = DEFAULT_POLLING_FREQUENCY):
        """
        Démarre le polling en arrière-plan.
        
        Args:
            frequency: Fréquence de polling (nombre de fois par seconde)
        """
        if self.polling_active:
            print("Le polling est déjà actif")
            return
        
        self.polling_frequency = frequency
        self.polling_active = True
        self.polling_thread = threading.Thread(target=self._polling_loop, daemon=True)
        self.polling_thread.start()
        print(f"Polling démarré à {frequency} Hz")
    
    def stop_polling(self):
        """Arrête le polling."""
        if not self.polling_active:
            print("Le polling n'est pas actif")
            return
        
        self.polling_active = False
        if self.polling_thread:
            self.polling_thread.join(timeout=2)
        print("Polling arrêté")
    
    def load_target_from_config(self) -> Optional[float]:
        """
        Charge la valeur cible depuis le fichier de configuration.
        
        Returns:
            La valeur cible ou None si le fichier n'existe pas ou est invalide
        """
        if not os.path.exists(CONFIG_FILE):
            return None
        
        try:
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
                target = config.get("target_focus")
                if target is not None:
                    self.target_value = float(target)
                    return self.target_value
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            print(f"Erreur lors du chargement de la configuration: {e}")
        
        return None
    
    def save_target_to_config(self, value: float):
        """
        Sauvegarde la valeur cible dans le fichier de configuration.
        
        Args:
            value: Valeur à sauvegarder
        """
        config = {"target_focus": value}
        try:
            with open(CONFIG_FILE, 'w') as f:
                json.dump(config, f, indent=2)
            # Mettre à jour le timestamp pour éviter de recharger immédiatement
            self.last_config_mtime = os.path.getmtime(CONFIG_FILE)
            print(f"\nValeur cible sauvegardée dans {CONFIG_FILE}: {value}")
        except Exception as e:
            print(f"\nErreur lors de la sauvegarde de la configuration: {e}")
    
    def sweep_focus(self, start: float = 0.0, end: float = 1.0, steps: int = 100, delay: float = None, infinite: bool = False, duration: float = None):
        """
        Fait varier le focus progressivement de start à end.
        
        Args:
            start: Valeur de départ (défaut: 0.0)
            end: Valeur de fin (défaut: 1.0)
            steps: Nombre d'étapes (défaut: 100)
            delay: Délai entre chaque étape en secondes (défaut: 0.1, ignoré si duration est fourni)
            infinite: Si True, fait des allers-retours à l'infini (défaut: False)
            duration: Durée totale en secondes (calcule automatiquement le délai, prioritaire sur delay)
        """
        # Si duration est fourni, calculer le délai automatiquement
        if duration is not None and duration > 0:
            delay = duration / steps
        elif delay is None:
            delay = 0.1  # Valeur par défaut
        if not 0.0 <= start <= 1.0 or not 0.0 <= end <= 1.0:
            print("Erreur: Les valeurs doivent être entre 0.0 et 1.0")
            return False
        
        # Calculer la fréquence d'affichage (afficher toutes les N étapes pour ne pas saturer)
        display_interval = max(1, steps // 50)  # Afficher environ 50 fois par cycle
        
        if infinite:
            print(f"\n[Sweep] Démarrage du balayage infini (allers-retours) de {start:.3f} à {end:.3f}")
            if duration is not None:
                print(f"[Sweep] {steps} étapes par direction, durée: {duration:.2f}s ({delay*1000:.2f}ms par étape)")
            else:
                print(f"[Sweep] {steps} étapes par direction, délai: {delay:.3f}s")
            print(f"[Sweep] Le polling continue en arrière-plan. Appuyez sur Ctrl+C pour arrêter\n")
        else:
            print(f"\n[Sweep] Démarrage du balayage de {start:.3f} à {end:.3f} en {steps} étapes")
            if duration is not None:
                print(f"[Sweep] Durée totale: {duration:.2f}s ({delay*1000:.2f}ms par étape)")
            else:
                print(f"[Sweep] Délai entre chaque étape: {delay:.3f}s")
                print(f"[Sweep] Durée totale estimée: {steps * delay:.1f}s")
            print()
        
        try:
            cycle = 0
            forward = True
            
            while True:
                if infinite:
                    direction = "→" if forward else "←"
                    print(f"[Sweep] Cycle {cycle + 1} - Direction: {direction}")
                
                for i in range(steps + 1):
                    # Calculer la valeur actuelle (interpolation linéaire)
                    progress = i / steps
                    
                    if forward:
                        current_value = start + (end - start) * progress
                    else:
                        current_value = end - (end - start) * progress
                    
                    # Appliquer la valeur (mode silencieux pour laisser le polling s'afficher)
                    if not self.set_focus(current_value, silent=True):
                        print(f"\n[Sweep] Erreur à l'étape {i}/{steps}")
                        return False
                    
                    # Afficher périodiquement (pas à chaque étape pour ne pas saturer)
                    if i % display_interval == 0 or i == steps:
                        if infinite:
                            print(f"[Sweep] Cycle {cycle + 1} {direction} - Étape {i}/{steps} ({progress*100:.1f}%)")
                        else:
                            print(f"[Sweep] Étape {i}/{steps} ({progress*100:.1f}%)")
                    
                    # Attendre avant la prochaine étape (sauf pour la dernière)
                    if i < steps:
                        time.sleep(delay)
                
                if not infinite:
                    break
                
                # Inverser la direction pour le prochain cycle
                forward = not forward
                cycle += 1
            
            if not infinite:
                print(f"\n[Sweep] Balayage terminé avec succès!")
            return True
            
        except KeyboardInterrupt:
            if infinite:
                print(f"\n\n[Sweep] Balayage infini interrompu par l'utilisateur après {cycle + 1} cycle(s)")
            else:
                print(f"\n[Sweep] Balayage interrompu par l'utilisateur")
            return False
        except Exception as e:
            print(f"\n[Sweep] Erreur lors du balayage: {e}")
            return False
    
    def _config_watch_loop(self):
        """Surveille le fichier de configuration et applique les changements automatiquement."""
        while self.config_watch_active:
            try:
                if os.path.exists(CONFIG_FILE):
                    current_mtime = os.path.getmtime(CONFIG_FILE)
                    if current_mtime != self.last_config_mtime:
                        self.last_config_mtime = current_mtime
                        target = self.load_target_from_config()
                        if target is not None:
                            print(f"\n[Config] Nouvelle valeur détectée: {target}")
                            self.set_focus(target)
                time.sleep(0.5)  # Vérifier toutes les 0.5 secondes
            except Exception as e:
                print(f"\n[Config] Erreur lors de la surveillance: {e}")
                time.sleep(1)
    
    def start_config_watch(self):
        """Démarre la surveillance du fichier de configuration."""
        if self.config_watch_active:
            return
        
        self.config_watch_active = True
        if os.path.exists(CONFIG_FILE):
            self.last_config_mtime = os.path.getmtime(CONFIG_FILE)
        self.config_watch_thread = threading.Thread(target=self._config_watch_loop, daemon=True)
        self.config_watch_thread.start()
        print("Surveillance du fichier de configuration activée")
    
    def stop_config_watch(self):
        """Arrête la surveillance du fichier de configuration."""
        self.config_watch_active = False
        if self.config_watch_thread:
            self.config_watch_thread.join(timeout=1)
    
    def interactive_mode_loop(self):
        """Boucle interactive permettant de changer le focus en temps réel."""
        print("\n" + "="*60)
        print("Mode interactif activé")
        print("="*60)
        print("Commandes disponibles:")
        print("  <valeur>          - Définir le focus (ex: 0.5)")
        print("  get               - Lire la valeur actuelle")
        print("  save <valeur>     - Définir et sauvegarder dans la config")
        print("  sweep             - Balayer le focus de 0 à 1 progressivement")
        print("  sweep <start> <end> <steps> <delay> - Balayer de start à end")
        print("  sweep infinite    - Balayer en allers-retours à l'infini")
        print("  sweep <start> <end> <steps> <delay> infinite - Balayer infini personnalisé")
        print("  watch             - Activer la surveillance du fichier config")
        print("  unwatch           - Désactiver la surveillance du fichier config")
        print("  help              - Afficher cette aide")
        print("  quit / exit       - Quitter")
        print("="*60 + "\n")
        
        while True:
            try:
                # Afficher un prompt propre
                print("\r> ", end='', flush=True)
                user_input = input().strip()
                
                if not user_input:
                    continue
                
                # Quitter
                if user_input.lower() in ['quit', 'exit', 'q']:
                    print("\nArrêt du mode interactif...")
                    break
                
                # Aide
                if user_input.lower() == 'help':
                    print("\nCommandes:")
                    print("  <valeur>          - Définir le focus (ex: 0.5)")
                    print("  get               - Lire la valeur actuelle")
                    print("  save <valeur>     - Définir et sauvegarder dans la config")
                    print("  sweep             - Balayer le focus de 0 à 1 progressivement")
                    print("  sweep <start> <end> <steps> <delay> - Balayer de start à end")
                    print("  sweep infinite    - Balayer en allers-retours à l'infini")
                    print("  watch             - Activer la surveillance du fichier config")
                    print("  unwatch           - Désactiver la surveillance du fichier config")
                    print("  help              - Afficher cette aide")
                    print("  quit / exit       - Quitter")
                    continue
                
                # Lire la valeur actuelle
                if user_input.lower() == 'get':
                    value = self.get_focus()
                    if value is not None:
                        print(f"\nValeur actuelle du focus: {value:.6f}")
                    continue
                
                # Surveiller le fichier config
                if user_input.lower() == 'watch':
                    self.start_config_watch()
                    continue
                
                if user_input.lower() == 'unwatch':
                    self.stop_config_watch()
                    print("\nSurveillance du fichier config désactivée")
                    continue
                
                # Sauvegarder dans la config
                if user_input.lower().startswith('save '):
                    try:
                        value = float(user_input.split()[1])
                        self.set_focus(value)
                        self.save_target_to_config(value)
                    except (IndexError, ValueError):
                        print("\nErreur: Format invalide. Utilisez: save <valeur>")
                    continue
                
                # Balayer le focus
                if user_input.lower().startswith('sweep'):
                    parts = user_input.split()
                    try:
                        # Vérifier si mode infini
                        infinite = 'infinite' in user_input.lower() or 'inf' in user_input.lower()
                        
                        if len(parts) == 1:
                            # Sweep par défaut: 0 à 1, 100 étapes, 0.1s de délai
                            self.sweep_focus(0.0, 1.0, 100, 0.1, infinite=False)
                        elif len(parts) == 2 and infinite:
                            # sweep infinite - par défaut en mode infini
                            self.sweep_focus(0.0, 1.0, 100, 0.1, infinite=True)
                        elif len(parts) == 5:
                            # sweep <start> <end> <steps> <delay>
                            start = float(parts[1])
                            end = float(parts[2])
                            steps = int(parts[3])
                            delay = float(parts[4])
                            self.sweep_focus(start, end, steps, delay, infinite=False)
                        elif len(parts) == 6 and infinite:
                            # sweep <start> <end> <steps> <delay> infinite
                            start = float(parts[1])
                            end = float(parts[2])
                            steps = int(parts[3])
                            delay = float(parts[4])
                            self.sweep_focus(start, end, steps, delay, infinite=True)
                        else:
                            print("\nErreur: Format invalide.")
                            print("Utilisez: sweep [start] [end] [steps] [delay] [infinite]")
                            print("Exemple: sweep 0 1 100 0.1")
                            print("Exemple: sweep infinite")
                            print("Exemple: sweep 0 1 50 0.2 infinite")
                    except (IndexError, ValueError) as e:
                        print(f"\nErreur: Format invalide. {e}")
                        print("Utilisez: sweep [start] [end] [steps] [delay] [infinite]")
                    continue
                
                # Essayer de parser comme une valeur numérique
                try:
                    value = float(user_input)
                    self.set_focus(value)
                except ValueError:
                    print(f"\nCommande inconnue: {user_input}. Tapez 'help' pour l'aide.")
                    
            except (EOFError, KeyboardInterrupt):
                print("\n\nArrêt du mode interactif...")
                break
            except Exception as e:
                print(f"\nErreur: {e}")


def main():
    """Fonction principale."""
    parser = argparse.ArgumentParser(
        description="Contrôleur de focus pour caméra Blackmagic",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemples:
  # Mode interactif (recommandé) - polling + commandes en temps réel
  python blackmagic_focus_control.py --interactive
  
  # Démarrer le polling uniquement
  python blackmagic_focus_control.py --polling
  
  # Définir une valeur cible et démarrer le polling
  python blackmagic_focus_control.py --set 0.5 --polling
  
  # Définir une valeur cible sans polling
  python blackmagic_focus_control.py --set 0.5
  
  # Lire la valeur actuelle une fois
  python blackmagic_focus_control.py --get
  
  # Balayer le focus de 0 à 1 (par défaut: 100 étapes, 0.1s de délai)
  python blackmagic_focus_control.py --sweep
  
  # Balayer le focus avec paramètres personnalisés
  python blackmagic_focus_control.py --sweep 0,1,50,0.2
  
  # Balayer en allers-retours à l'infini
  python blackmagic_focus_control.py --sweep --infinite
  
  # Balayer infini avec paramètres personnalisés
  python blackmagic_focus_control.py --sweep 0,1,50,0.2 --infinite
  
  # Surveiller le fichier de configuration
  python blackmagic_focus_control.py --polling --watch-config
        """
    )
    
    parser.add_argument(
        "--url",
        default="http://Micro-Studio-Camera-4K-G2.local",
        help="URL de base de la caméra (défaut: http://Micro-Studio-Camera-4K-G2.local, peut utiliser https:// si configuré)"
    )
    parser.add_argument(
        "--user",
        default="roo",
        help="Nom d'utilisateur pour l'authentification (défaut: roo)"
    )
    parser.add_argument(
        "--pass",
        dest="password",
        default="koko",
        help="Mot de passe pour l'authentification (défaut: koko)"
    )
    parser.add_argument(
        "--set",
        type=float,
        metavar="VALUE",
        help="Définir la valeur du focus (0.0 à 1.0)"
    )
    parser.add_argument(
        "--get",
        action="store_true",
        help="Lire la valeur actuelle du focus"
    )
    parser.add_argument(
        "--sweep",
        nargs='?',
        const='default',
        metavar="CONFIG",
        help="Balayer le focus de 0 à 1. Format: start,end,steps,delay (ex: 0,1,100,0.1) ou start,end,steps,duration (ex: 0,1,512,5.0)"
    )
    parser.add_argument(
        "--infinite",
        action="store_true",
        help="Mode infini: fait des allers-retours à l'infini (à utiliser avec --sweep)"
    )
    parser.add_argument(
        "--duration",
        type=float,
        metavar="SECONDS",
        help="Durée totale en secondes pour le balayage (calcule automatiquement le délai, prioritaire sur delay dans --sweep)"
    )
    parser.add_argument(
        "--polling",
        action="store_true",
        help="Démarrer le polling continu"
    )
    parser.add_argument(
        "--frequency",
        type=float,
        default=DEFAULT_POLLING_FREQUENCY,
        help=f"Fréquence de polling en Hz (défaut: {DEFAULT_POLLING_FREQUENCY})"
    )
    parser.add_argument(
        "--load-config",
        action="store_true",
        help="Charger la valeur cible depuis le fichier de configuration"
    )
    parser.add_argument(
        "--save-config",
        action="store_true",
        help="Sauvegarder la valeur cible dans le fichier de configuration"
    )
    parser.add_argument(
        "--interactive",
        "-i",
        action="store_true",
        help="Mode interactif: permet de changer le focus en temps réel"
    )
    parser.add_argument(
        "--watch-config",
        action="store_true",
        help="Surveiller le fichier de configuration et appliquer les changements automatiquement"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Mode debug: affiche les détails des requêtes HTTP"
    )
    
    args = parser.parse_args()
    
    # Désactiver les avertissements SSL pour les certificats auto-signés
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    
    # Créer le contrôleur
    controller = BlackmagicFocusController(args.url, args.user, args.password)
    controller.debug = args.debug
    
    # Charger la configuration si demandé
    if args.load_config:
        target = controller.load_target_from_config()
        if target is not None:
            print(f"Valeur cible chargée depuis la configuration: {target}")
            controller.set_focus(target)
    
    # Définir la valeur si demandé
    if args.set is not None:
        controller.set_focus(args.set)
        if args.save_config:
            controller.save_target_to_config(args.set)
    
    # Lire la valeur actuelle si demandé
    if args.get:
        value = controller.get_focus()
        if value is not None:
            print(f"Valeur actuelle du focus: {value:.6f}")
    
    # Balayer le focus si demandé
    if args.sweep is not None:
        # Démarrer le polling automatiquement pour voir la valeur en temps réel pendant le sweep
        if not args.polling and not args.interactive:
            controller.start_polling(args.frequency)
            polling_started_for_sweep = True
        else:
            polling_started_for_sweep = False
        if args.sweep == 'default':
            # Sweep par défaut: 0 à 1, 100 étapes
            if args.duration:
                controller.sweep_focus(0.0, 1.0, 100, duration=args.duration, infinite=args.infinite)
            else:
                controller.sweep_focus(0.0, 1.0, 100, 0.1, infinite=args.infinite)
        else:
            # Parser la configuration: start,end,steps,delay ou start,end,steps (avec --duration)
            try:
                parts = args.sweep.split(',')
                if args.duration:
                    # Si --duration est spécifié, on peut avoir 3 ou 4 paramètres
                    if len(parts) == 3:
                        start = float(parts[0])
                        end = float(parts[1])
                        steps = int(parts[2])
                        controller.sweep_focus(start, end, steps, duration=args.duration, infinite=args.infinite)
                    elif len(parts) == 4:
                        # On ignore le 4ème paramètre si --duration est spécifié
                        start = float(parts[0])
                        end = float(parts[1])
                        steps = int(parts[2])
                        controller.sweep_focus(start, end, steps, duration=args.duration, infinite=args.infinite)
                    else:
                        print("Erreur: Format invalide. Utilisez: --sweep start,end,steps --duration SECONDS")
                        print("Exemple: --sweep 0,1,512 --duration 5.0")
                elif len(parts) == 4:
                    # Format classique: start,end,steps,delay
                    start = float(parts[0])
                    end = float(parts[1])
                    steps = int(parts[2])
                    delay = float(parts[3])
                    controller.sweep_focus(start, end, steps, delay=delay, infinite=args.infinite)
                else:
                    print("Erreur: Format invalide. Utilisez: --sweep start,end,steps,delay")
                    print("Exemple: --sweep 0,1,100,0.1")
                    print("Ou utilisez --duration pour spécifier la durée totale: --sweep 0,1,512 --duration 5.0")
                    print("Ajoutez --infinite pour les allers-retours à l'infini")
            except (ValueError, IndexError) as e:
                print(f"Erreur lors du parsing de la configuration sweep: {e}")
                print("Format attendu: start,end,steps,delay ou start,end,steps avec --duration")
        
        # Gérer le polling après le sweep
        if polling_started_for_sweep:
            if args.infinite:
                # Pour le mode infini, maintenir le script en vie jusqu'à Ctrl+C
                try:
                    while controller.polling_active:
                        time.sleep(1)
                except KeyboardInterrupt:
                    pass
                finally:
                    controller.stop_polling()
            else:
                # Pour le mode non-infini, arrêter le polling après le sweep
                controller.stop_polling()
    
    # Démarrer la surveillance du fichier config si demandé
    if args.watch_config or args.interactive:
        controller.start_config_watch()
    
    # Démarrer le polling si demandé (mais pas si on l'a déjà démarré pour le sweep)
    if (args.polling or args.interactive) and not polling_started_for_sweep:
        controller.start_polling(args.frequency)
    
    # Mode interactif
    if args.interactive:
        try:
            controller.interactive_mode_loop()
        except KeyboardInterrupt:
            print("\nArrêt du script...")
        finally:
            controller.stop_polling()
            controller.stop_config_watch()
    elif args.polling:
        try:
            # Maintenir le script en vie pour le polling
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nArrêt du script...")
            controller.stop_polling()
            controller.stop_config_watch()
    elif not args.get and args.set is None and not args.load_config and args.sweep is None:
        # Si aucune action n'est spécifiée, afficher l'aide
        parser.print_help()


if __name__ == "__main__":
    main()

