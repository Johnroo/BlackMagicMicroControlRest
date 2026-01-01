#!/usr/bin/env python3
"""
CompanionWsServer: Serveur WebSocket pour Bitfocus Companion.
Gère les connexions, envoie des snapshots et des patchs, reçoit des commandes.
"""

import json
import logging
from typing import List, Optional
from PySide6.QtCore import QObject, Signal
from PySide6.QtWebSockets import QWebSocketServer, QWebSocket
from PySide6.QtNetwork import QHostAddress

from state_store import StateStore

logger = logging.getLogger(__name__)


class CompanionWsServer(QObject):
    """Serveur WebSocket pour Companion."""
    
    # Signal émis quand une commande est reçue
    command_received = Signal(QWebSocket, dict)  # client, cmd
    
    def __init__(self, state_store: StateStore):
        super().__init__()
        self.state_store = state_store
        self.server: Optional[QWebSocketServer] = None
        self.clients: List[QWebSocket] = []
        self.port = 8765
        
        # Connecter le signal state_changed du StateStore pour broadcast les patchs
        self.state_store.state_changed.connect(self.broadcast_patch)
    
    def start(self, port: int = 8765):
        """
        Démarre le serveur WebSocket.
        
        Args:
            port: Port d'écoute (défaut: 8765)
        """
        if self.server and self.server.isListening():
            logger.warning("Le serveur WebSocket est déjà en cours d'exécution")
            return
        
        self.port = port
        self.server = QWebSocketServer(
            "CompanionWsServer",
            QWebSocketServer.SslMode.NonSecureMode,
            self
        )
        
        if not self.server.listen(QHostAddress.Any, port):
            logger.error(f"Impossible de démarrer le serveur WebSocket sur le port {port}: {self.server.errorString()}")
            return
        
        self.server.newConnection.connect(self._on_new_connection)
        logger.info(f"Serveur WebSocket Companion démarré sur le port {port}")
    
    def stop(self):
        """Arrête le serveur WebSocket."""
        if self.server:
            # Fermer toutes les connexions
            for client in self.clients[:]:
                client.close()
            self.clients.clear()
            
            self.server.close()
            self.server = None
            logger.info("Serveur WebSocket Companion arrêté")
    
    def _on_new_connection(self):
        """Gère une nouvelle connexion client."""
        if not self.server:
            return
        
        socket = self.server.nextPendingConnection()
        if not socket:
            return
        
        logger.info(f"Nouvelle connexion WebSocket: {socket.peerAddress().toString()}")
        
        # Connecter les signaux
        socket.textMessageReceived.connect(lambda msg: self._on_message_received(socket, msg))
        socket.disconnected.connect(lambda: self._on_client_disconnected(socket))
        
        # Ajouter à la liste des clients
        self.clients.append(socket)
        
        # Envoyer un snapshot initial
        self.broadcast_snapshot(socket)
    
    def _on_message_received(self, client: QWebSocket, message: str):
        """
        Gère un message reçu d'un client.
        
        Args:
            client: Socket WebSocket du client
            message: Message JSON reçu
        """
        try:
            data = json.loads(message)
            msg_type = data.get("type")
            
            if msg_type == "hello":
                # Identification du client
                client_name = data.get("client", "unknown")
                version = data.get("version", 0)
                logger.info(f"Client identifié: {client_name} (version {version})")
                
                # Envoyer un ack
                self.send_ack(client, True)
                
            elif msg_type == "cmd":
                # Commande à traiter
                cmd = data.get("cmd")
                if cmd:
                    logger.debug(f"Commande reçue: {cmd}")
                    # Émettre le signal pour que MainWindow traite la commande
                    self.command_received.emit(client, data)
                else:
                    logger.warning("Commande reçue sans champ 'cmd'")
                    self.send_ack(client, False, "Commande invalide: champ 'cmd' manquant")
            else:
                logger.warning(f"Type de message inconnu: {msg_type}")
                self.send_ack(client, False, f"Type de message inconnu: {msg_type}")
                
        except json.JSONDecodeError as e:
            logger.error(f"Erreur de parsing JSON: {e}")
            self.send_ack(client, False, f"Erreur de parsing JSON: {str(e)}")
        except Exception as e:
            logger.error(f"Erreur lors du traitement du message: {e}")
            self.send_ack(client, False, f"Erreur: {str(e)}")
    
    def _on_client_disconnected(self, client: QWebSocket):
        """Gère la déconnexion d'un client."""
        if client in self.clients:
            self.clients.remove(client)
            logger.info(f"Client déconnecté: {client.peerAddress().toString()}")
        client.deleteLater()
    
    def broadcast_snapshot(self, client: Optional[QWebSocket] = None):
        """
        Envoie un snapshot complet à un client ou à tous les clients.
        
        Args:
            client: Client spécifique (None = tous les clients)
        """
        snapshot = self.state_store.snapshot()
        message = {
            "type": "snapshot",
            "state": snapshot
        }
        
        message_json = json.dumps(message)
        
        if client:
            # Envoyer à un client spécifique
            if client in self.clients:
                client.sendTextMessage(message_json)
                logger.debug(f"Snapshot envoyé à {client.peerAddress().toString()}")
        else:
            # Broadcast à tous les clients
            for c in self.clients:
                c.sendTextMessage(message_json)
            if self.clients:
                logger.debug(f"Snapshot broadcast à {len(self.clients)} client(s)")
    
    def broadcast_patch(self, patch: dict):
        """
        Broadcast un patch incrémental à tous les clients.
        
        Args:
            patch: Dictionnaire contenant les changements incrémentaux
        """
        if not self.clients:
            return
        
        message = {
            "type": "patch",
            "patch": patch
        }
        
        message_json = json.dumps(message)
        
        # Broadcast à tous les clients
        for client in self.clients:
            client.sendTextMessage(message_json)
        
        logger.debug(f"Patch broadcast à {len(self.clients)} client(s): {patch}")
    
    def send_ack(self, client: QWebSocket, ok: bool, error: Optional[str] = None):
        """
        Envoie un accusé de réception à un client.
        
        Args:
            client: Socket WebSocket du client
            ok: True si succès, False si erreur
            error: Message d'erreur (optionnel)
        """
        message = {
            "type": "ack",
            "ok": ok
        }
        
        if error:
            message["error"] = error
        
        message_json = json.dumps(message)
        client.sendTextMessage(message_json)
        
        logger.debug(f"Ack envoyé à {client.peerAddress().toString()}: ok={ok}, error={error}")






