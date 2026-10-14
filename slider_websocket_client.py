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
import urllib.request

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
        self.max_reconnect_delay = 30  # Plafond backoff
        self.reconnect_attempts = 0
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.thread: Optional[threading.Thread] = None
        self._stopped = False  # empêche les callbacks après stop()
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
        
        self._stopped = False
        self.running = True
        self.thread = threading.Thread(target=self._run_event_loop, daemon=True)
        self.thread.start()
    
    def stop(self):
        """Arrête le client WebSocket (non-bloquant pour le thread UI)."""
        self._stopped = True
        self.running = False
        self.auto_reconnect_enabled = False
        self.connected = False
        # Couper les callbacks pour éviter d'écraser un nouveau client
        self.on_connection_status_callback = None
        self.on_position_update_callback = None
        loop = self.loop
        thread = self.thread
        self.thread = None
        if loop and loop.is_running():
            try:
                asyncio.run_coroutine_threadsafe(self._close_websocket(), loop)
                # Stopper la boucle rapidement (évite join 10s sur connect() bloqué)
                loop.call_soon_threadsafe(loop.stop)
            except Exception:
                pass
        # Ne jamais joindre longtemps depuis le thread UI — laisse le daemon mourir
        if thread and thread.is_alive() and threading.current_thread() is not thread:
            thread.join(timeout=0.2)
    
    def is_connected(self) -> bool:
        """Vérifie si le WebSocket est connecté (WS ou HTTP fallback)."""
        return bool(self.connected)
    
    def _notify_status(self, connected: bool, message: str):
        """Notifie le statut uniquement si ce client est encore actif."""
        if self._stopped:
            return
        cb = self.on_connection_status_callback
        if not cb:
            return
        try:
            cb(connected, message)
        except Exception as e:
            self.logger.error(f"Erreur dans on_connection_status_callback: {e}")
    
    async def _interruptible_sleep(self, delay: float):
        """Sleep découpé pour pouvoir s'arrêter rapidement sur stop()."""
        end = asyncio.get_event_loop().time() + max(0.0, delay)
        while self.running and self.auto_reconnect_enabled:
            remaining = end - asyncio.get_event_loop().time()
            if remaining <= 0:
                return
            await asyncio.sleep(min(0.25, remaining))
    
    def _run_event_loop(self):
        """Exécute la boucle d'événements asyncio dans un thread séparé."""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.create_task(self._connect_and_listen())
            self.loop.run_forever()
        except Exception:
            pass
        finally:
            try:
                pending = asyncio.all_tasks(self.loop)
                for t in pending:
                    t.cancel()
                if pending:
                    self.loop.run_until_complete(
                        asyncio.gather(*pending, return_exceptions=True)
                    )
            except Exception:
                pass
            try:
                self.loop.close()
            except Exception:
                pass
            self.loop = None
    
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
        
        while self.running and self.auto_reconnect_enabled and not self._stopped:
            try:
                self.logger.info(f"Tentative de connexion WebSocket slider à {self.ws_url}")
                
                # WiFi ESP souvent lent (RTT 100–400ms) : ping tolérant, connect court
                websocket = await asyncio.wait_for(
                    websockets.connect(
                        self.ws_url,
                        ping_interval=45,
                        ping_timeout=25,
                        close_timeout=2,
                        open_timeout=4,
                    ),
                    timeout=5.0
                )
                
                async with websocket:
                    self.websocket = websocket
                    self.connected = True
                    self.reconnect_attempts = 0
                    self.logger.info(f"✓ WebSocket slider connecté avec succès à {self.ws_url}")
                    
                    self._notify_status(True, "WebSocket slider connecté")
                    
                    # Écouter les messages
                    self.logger.info("En attente de messages WebSocket slider...")
                    
                    try:
                        async for message in websocket:
                            if not self.running or self._stopped:
                                break
                            await self._handle_message(message)
                    except websockets.exceptions.ConnectionClosed:
                        raise

            except (websockets.exceptions.InvalidStatus, websockets.exceptions.InvalidStatusCode) as e:
                # Souvent HTTP 200 = le firmware sert une page au lieu d'upgrader le WS.
                if self.running and self.auto_reconnect_enabled and not self._stopped:
                    self.websocket = None
                    self.logger.warning(
                        f"WebSocket slider rejeté par {self.ws_url}: {e} — "
                        f"bascule en polling HTTP"
                    )
                    await self._http_poll_loop()
                else:
                    break
                        
            except websockets.exceptions.InvalidURI as e:
                if self.running and self.auto_reconnect_enabled and not self._stopped:
                    self.logger.error(f"URL WebSocket invalide: {e}")
                    self.logger.error(f"URL utilisée: {self.ws_url}")
                    self._notify_status(False, f"URL WebSocket invalide: {e}")
                    await self._interruptible_sleep(self.reconnect_delay)
                else:
                    break
            except (asyncio.TimeoutError, websockets.exceptions.ConnectionClosed, OSError, Exception) as e:
                if not (self.running and self.auto_reconnect_enabled and not self._stopped):
                    break
                self.reconnect_attempts += 1
                self.websocket = None
                self.connected = False
                err_s = str(e)
                is_timeout = isinstance(e, asyncio.TimeoutError)
                # Après 2 échecs (ping keepalive, HTTP invalide, timeout…) → HTTP fallback
                # évite de saturer l'ESP / le thread UI en boucle WS.
                if self.reconnect_attempts >= 2:
                    self.logger.warning(
                        f"WebSocket slider {self.ws_url} instable ({e}) — "
                        f"bascule en polling HTTP"
                    )
                    self._notify_status(False, f"WS instable, fallback HTTP")
                    await self._http_poll_loop()
                    self.reconnect_attempts = 0
                    continue
                delay = min(
                    self.reconnect_delay * (2 ** min(self.reconnect_attempts - 1, 3)),
                    self.max_reconnect_delay,
                )
                if is_timeout:
                    self.logger.warning(
                        f"Timeout connexion WebSocket {self.ws_url}, retry dans {delay}s"
                    )
                    self._notify_status(False, "Timeout de connexion")
                else:
                    self.logger.warning(f"WebSocket slider erreur: {err_s}")
                    self._notify_status(False, f"Erreur: {e}")
                await self._interruptible_sleep(delay)
    
    async def _http_poll_loop(self):
        """Fallback positions via HTTP quand le WebSocket est indisponible."""
        poll_interval = 0.5  # 2 Hz
        ws_retry_every = 20.0  # retenter le WS périodiquement
        last_ws_try = 0.0
        announced = False

        while self.running and self.auto_reconnect_enabled and not self._stopped:
            loop_time = asyncio.get_event_loop().time()
            # Retenter le WebSocket de temps en temps
            if loop_time - last_ws_try >= ws_retry_every:
                last_ws_try = loop_time
                try:
                    websocket = await asyncio.wait_for(
                        websockets.connect(
                            self.ws_url,
                            ping_interval=30,
                            ping_timeout=10,
                        ),
                        timeout=5.0,
                    )
                    # WS OK → sortir du fallback pour reprendre la boucle principale
                    await websocket.close()
                    self.logger.info(
                        f"WebSocket slider à nouveau disponible sur {self.ws_url}, "
                        f"sortie du polling HTTP"
                    )
                    self.connected = False
                    return
                except Exception:
                    pass

            ok = await asyncio.get_event_loop().run_in_executor(
                None, self._poll_http_status_once
            )
            if self._stopped or not self.running:
                break
            if ok:
                if not self.connected or not announced:
                    self.connected = True
                    announced = True
                    self.logger.info(
                        f"✓ Slider {self.slider_ip} joignable via HTTP "
                        f"(fallback, WS indisponible)"
                    )
                    self._notify_status(True, "Slider connecté (HTTP fallback)")
            else:
                if self.connected:
                    self.connected = False
                    announced = False
                    self._notify_status(False, "Slider HTTP offline")
            await self._interruptible_sleep(poll_interval)

    def _poll_http_status_once(self) -> bool:
        """Lit /api/v1/status ou /api/status et pousse un update positions. Retourne True si OK."""
        if not self.slider_ip or self._stopped:
            return False
        for path in ("/api/v1/status", "/api/status"):
            try:
                url = f"http://{self.slider_ip}{path}"
                req = urllib.request.Request(url, headers={"Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=1.5) as resp:
                    if resp.status != 200:
                        continue
                    payload = json.loads(resp.read().decode("utf-8", "replace"))
                if not isinstance(payload, dict):
                    continue
                motors_percent = payload.get("motors_percent") or {}
                motors = payload.get("motors") or {}
                if not motors_percent and not motors:
                    continue

                def norm(axis: str) -> float:
                    if axis in motors_percent and motors_percent[axis] is not None:
                        return max(0.0, min(1.0, float(motors_percent[axis]) / 100.0))
                    return 0.0

                data = {
                    "pan": {"steps": motors.get("pan", 0), "normalized": norm("pan")},
                    "tilt": {"steps": motors.get("tilt", 0), "normalized": norm("tilt")},
                    "zoom": {"steps": motors.get("zoom", 0), "normalized": norm("zoom")},
                    "slide": {"steps": motors.get("slide", 0), "normalized": norm("slide")},
                }
                if self._stopped:
                    return False
                if self.on_position_update_callback:
                    try:
                        self.on_position_update_callback(data)
                    except Exception as e:
                        self.logger.error(f"Erreur callback positions HTTP: {e}")
                return True
            except Exception:
                continue
        return False

    async def _handle_message(self, message: str):
        """Traite un message reçu du WebSocket."""
        if self._stopped:
            return
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
