#!/usr/bin/env python3
"""
Client WebSocket pour recevoir les positions du slider en temps réel.
"""

import asyncio
import websockets
from websockets.client import WebSocketClientProtocol
import json
import logging
import threading
from typing import Optional, Callable, Dict, Any

logger = logging.getLogger(__name__)


class SliderWebSocketClient:
    """Client WebSocket pour recevoir les positions du slider en temps réel."""
    
    def __init__(self, slider_ip: str, on_position_update_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
                 on_connection_status_callback: Optional[Callable[[bool, str], None]] = None, auto_reconnect_enabled: bool = True):
        """
        Initialise le client WebSocket pour le slider.
        
        Args:
            slider_ip: Adresse IP ou hostname du slider (ex: "192.168.1.37" ou "slider1.local")
            on_position_update_callback: Fonction appelée quand les positions changent (data dict)
            on_connection_status_callback: Fonction appelée quand l'état de connexion change (connected: bool, message: str)
            auto_reconnect_enabled: Si False, n'essaie pas de se reconnecter automatiquement
        """
        self.slider_ip = slider_ip.strip() if slider_ip else ""
        # Construire l'URL WebSocket
        if not self.slider_ip:
            self.ws_url = None
        else:
            # Support IP directe et hostname mDNS
            if '.' in self.slider_ip and not self.slider_ip.endswith('.local'):
                # IP directe
                self.ws_url = f"ws://{self.slider_ip}/ws/positions"
            else:
                # Hostname mDNS
                self.ws_url = f"ws://{self.slider_ip}/ws/positions"
        
        self.on_position_update_callback = on_position_update_callback
        self.on_connection_status_callback = on_connection_status_callback
        self.auto_reconnect_enabled = bool(auto_reconnect_enabled)  # Flag pour activer/désactiver la reconnexion automatique
        self.websocket: Optional[WebSocketClientProtocol] = None
        self.connected = False  # Flag pour suivre l'état de connexion
        self.running = False
        self.reconnect_delay = 2  # Secondes avant reconnexion
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.thread: Optional[threading.Thread] = None
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)
        
        if self.ws_url:
            self.logger.info(f"Initialisation WebSocket slider client - URL: {self.ws_url} (auto_reconnect: {self.auto_reconnect_enabled})")
        else:
            self.logger.warning("Slider IP non configuré, WebSocket non disponible")
    
    def is_configured(self) -> bool:
        """Vérifie si le slider est configuré (IP non vide)."""
        return bool(self.slider_ip and self.slider_ip.strip() and self.ws_url)
    
    def start(self):
        """Démarre le client WebSocket dans un thread séparé."""
        if not self.is_configured():
            self.logger.warning("Impossible de démarrer le WebSocket : slider non configuré")
            return
        
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
    
    def is_connected(self) -> bool:
        """Vérifie si le WebSocket est connecté."""
        return self.websocket is not None
    
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
            self.connected = False
    
    async def _connect_and_listen(self):
        """Se connecte et écoute les messages WebSocket avec reconnexion automatique."""
        if not self.is_configured():
            return
        
        # Notifier qu'on essaie de se connecter
        if self.on_connection_status_callback:
            try:
                self.on_connection_status_callback(False, "Tentative de connexion au slider...")
            except Exception:
                pass
        
        while self.running and self.auto_reconnect_enabled:
            try:
                self.logger.info(f"Tentative de connexion WebSocket slider à {self.ws_url}")
                
                # Connexion WebSocket (pas d'authentification nécessaire pour le slider)
                websocket = await asyncio.wait_for(
                    websockets.connect(
                        self.ws_url,
                        ping_interval=30,  # Ping toutes les 30 secondes
                        ping_timeout=10   # Timeout de 10 secondes
                    ),
                    timeout=10.0
                )
                
                async with websocket:
                    self.websocket = websocket
                    self.connected = True
                    self.logger.info(f"✓ WebSocket slider connecté avec succès à {self.ws_url}")
                    
                    # Notifier la connexion réussie
                    if self.on_connection_status_callback:
                        try:
                            self.on_connection_status_callback(True, "WebSocket slider connecté")
                        except Exception as e:
                            self.logger.error(f"Erreur dans on_connection_status_callback: {e}")
                    
                    # Écouter les messages
                    self.logger.info("En attente de messages WebSocket slider...")
                    
                    try:
                        async for message in websocket:
                            if not self.running:
                                break
                            await self._handle_message(message)
                    except websockets.exceptions.ConnectionClosed as e:
                        raise
                        
            except websockets.exceptions.InvalidURI as e:
                if self.running and self.auto_reconnect_enabled:
                    self.logger.error(f"URL WebSocket invalide: {e}")
                    self.logger.error(f"URL utilisée: {self.ws_url}")
                    if self.on_connection_status_callback:
                        try:
                            self.on_connection_status_callback(False, f"URL WebSocket invalide: {e}")
                        except Exception:
                            pass
                    await asyncio.sleep(self.reconnect_delay)
                else:
                    if not self.auto_reconnect_enabled:
                        self.logger.info("Reconnexion automatique désactivée, arrêt des tentatives")
                        break
            except asyncio.TimeoutError:
                if self.running and self.auto_reconnect_enabled:
                    self.logger.warning(f"Timeout lors de la connexion WebSocket à {self.ws_url}")
                    if self.on_connection_status_callback:
                        try:
                            self.on_connection_status_callback(False, "Timeout de connexion")
                        except Exception:
                            pass
                    await asyncio.sleep(self.reconnect_delay)
                else:
                    if not self.auto_reconnect_enabled:
                        self.logger.info("Reconnexion automatique désactivée, arrêt des tentatives")
                        break
            except websockets.exceptions.ConnectionClosed as e:
                if self.running and self.auto_reconnect_enabled:
                    self.logger.warning(f"WebSocket slider fermé: {e}")
                    self.websocket = None
                    self.connected = False
                    if self.on_connection_status_callback:
                        try:
                            self.on_connection_status_callback(False, f"Connexion fermée: {e}")
                        except Exception:
                            pass
                    await asyncio.sleep(self.reconnect_delay)
                else:
                    if not self.auto_reconnect_enabled:
                        self.logger.info("Reconnexion automatique désactivée, arrêt des tentatives")
                        break
            except Exception as e:
                if self.running and self.auto_reconnect_enabled:
                    self.logger.error(f"Erreur WebSocket slider: {e}")
                    self.websocket = None
                    self.connected = False
                    if self.on_connection_status_callback:
                        try:
                            self.on_connection_status_callback(False, f"Erreur: {e}")
                        except Exception:
                            pass
                    await asyncio.sleep(self.reconnect_delay)
                else:
                    if not self.auto_reconnect_enabled:
                        self.logger.info("Reconnexion automatique désactivée, arrêt des tentatives")
                        break
    
    async def _handle_message(self, message: str):
        """Traite un message reçu du WebSocket."""
        try:
            data = json.loads(message)
            
            # Format attendu :
            # {
            #   "pan": {"steps": 12345, "normalized": 0.5},
            #   "tilt": {"steps": 6789, "normalized": 0.75},
            #   "zoom": {"steps": 1000, "normalized": 0.3},
            #   "slide": {"steps": 5000, "normalized": 0.6},
            #   "timestamp": 1234567890
            # }
            
            if self.on_position_update_callback:
                try:
                    self.on_position_update_callback(data)
                except Exception as e:
                    self.logger.error(f"Erreur dans on_position_update_callback: {e}")
        except json.JSONDecodeError as e:
            self.logger.warning(f"Message JSON invalide reçu: {e}")
        except Exception as e:
            self.logger.error(f"Erreur lors du traitement du message WebSocket: {e}")








