#!/usr/bin/env python3
"""
companion_controller.py - Contrôleur Bitfocus Companion

Ce module gère la communication TCP avec Bitfocus Companion pour synchroniser
les pages du Stream Deck avec les caméras sélectionnées.

Fonctionnalités :
- Envoi de commandes TCP à Companion
- Changement automatique de page selon la caméra sélectionnée
- Support de multiples surfaces (Stream Decks)
"""

import socket
import logging

logger = logging.getLogger(__name__)


class CompanionController:
    """
    Contrôleur pour gérer les interactions avec Bitfocus Companion.
    """
    
    def __init__(self, host="127.0.0.1", port=16759, surface_ids=None):
        """
        Initialise le contrôleur Companion.
        
        Args:
            host (str): Adresse IP de Companion (défaut: 127.0.0.1)
            port (int): Port TCP de Companion (défaut: 16759)
            surface_ids (list): Liste des IDs de surfaces à contrôler (défaut: ["0"])
                               Peut être une liste ["0", "1", "2"] ou "all" pour toutes
        """
        self.host = host
        self.port = port
        
        # Gérer surface_ids
        if surface_ids is None:
            self.surface_ids = ["0"]
        elif surface_ids == "all":
            # Pour "all", on va envoyer à un range de surfaces (0-9)
            self.surface_ids = [str(i) for i in range(10)]
        elif isinstance(surface_ids, str):
            # Si c'est une string, la convertir en liste
            self.surface_ids = [surface_ids]
        elif isinstance(surface_ids, list):
            # Garder les IDs tels quels (peuvent être des strings complexes comme "emulator:...")
            self.surface_ids = [sid if isinstance(sid, str) else str(sid) for sid in surface_ids]
        else:
            self.surface_ids = ["0"]
        
        self.connected = False
        self.socket = None  # Connexion TCP persistante
        
        if len(self.surface_ids) == 1:
            logger.info(f"Companion Controller initialisé pour {host}:{port} (Surface: {self.surface_ids[0]})")
        else:
            logger.info(f"Companion Controller initialisé pour {host}:{port} (Surfaces: {', '.join(self.surface_ids)})")
    
    
    def _ensure_connection(self):
        """
        S'assure qu'une connexion TCP persistante existe.
        Crée une nouvelle connexion si nécessaire.
        
        Returns:
            bool: True si connecté, False sinon
        """
        # Si on a déjà une connexion, vérifier qu'elle est toujours valide
        if self.socket:
            try:
                # Test rapide de la connexion
                self.socket.getpeername()
                return True
            except:
                # La connexion est morte, la fermer
                try:
                    self.socket.close()
                except:
                    pass
                self.socket = None
                self.connected = False
        
        # Créer une nouvelle connexion
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(2)
            self.socket.connect((self.host, self.port))
            self.connected = True
            return True
        except Exception as e:
            self.socket = None
            self.connected = False
            logger.debug(f"Impossible de se connecter à Companion: {e}")
            return False
    
    
    def send_command(self, command):
        """
        Envoie une commande TCP à Companion via une connexion persistante.
        
        Args:
            command (str): Commande à envoyer
            
        Returns:
            bool: True si succès, False sinon
        """
        try:
            # S'assurer d'avoir une connexion
            if not self._ensure_connection():
                logger.debug(f"Impossible de se connecter à Companion ({self.host}:{self.port})")
                return False
            
            # Envoyer la commande (avec retour à la ligne)
            self.socket.sendall(f"{command}\n".encode('utf-8'))
            
            return True
            
        except socket.timeout:
            logger.debug(f"Timeout lors de l'envoi à Companion ({self.host}:{self.port})")
            self.socket = None
            self.connected = False
            return False
        except ConnectionRefusedError:
            logger.debug(f"Connexion refusée par Companion ({self.host}:{self.port})")
            self.socket = None
            self.connected = False
            return False
        except BrokenPipeError:
            # Connexion perdue, réessayer une fois
            logger.debug(f"Connexion perdue, reconnexion...")
            self.socket = None
            self.connected = False
            if self._ensure_connection():
                try:
                    self.socket.sendall(f"{command}\n".encode('utf-8'))
                    return True
                except:
                    return False
            return False
        except Exception as e:
            logger.debug(f"Erreur lors de l'envoi de commande à Companion: {e}")
            self.socket = None
            self.connected = False
            return False
    
    
    def set_page(self, page_number):
        """
        Change la page de toutes les surfaces Companion configurées.
        
        Args:
            page_number (int): Numéro de page (1-99)
            
        Returns:
            bool: True si au moins une commande a réussi, False sinon
        """
        if page_number < 1 or page_number > 99:
            logger.warning(f"Numéro de page invalide : {page_number} (doit être entre 1 et 99)")
            return False
        
        # Envoyer la commande à toutes les surfaces
        success_count = 0
        
        for surface_id in self.surface_ids:
            # Construire la commande pour cette surface selon la syntaxe Companion
            # Format: SURFACE {surface_id} PAGE-SET {page_number}
            command = f"SURFACE {surface_id} PAGE-SET {page_number}"
            
            logger.debug(f"Envoi commande Companion : {command}")
            
            # Envoyer la commande
            if self.send_command(command):
                success_count += 1
        
        if success_count > 0:
            if len(self.surface_ids) == 1:
                logger.info(f"Companion → Page {page_number} (Surface {self.surface_ids[0]})")
            else:
                logger.info(f"Companion → Page {page_number} ({success_count}/{len(self.surface_ids)} surfaces)")
            return True
        else:
            logger.warning(f"Échec du changement de page Companion vers {page_number}")
            return False
    
    
    def switch_camera_page(self, camera_id, companion_page=None):
        """
        Change la page Companion selon l'ID de la caméra.
        Si companion_page est fourni, l'utilise, sinon utilise camera_id comme page.
        
        Args:
            camera_id (int): ID de la caméra
            companion_page (int, optional): Numéro de page Companion spécifique
            
        Returns:
            bool: True si succès, False sinon
        """
        # Utiliser companion_page si fourni, sinon mapper directement l'ID de caméra
        if companion_page is not None:
            page_number = companion_page
        else:
            page_number = camera_id
        
        return self.set_page(page_number)
    
    
    def test_connection(self):
        """
        Teste la connexion avec Companion.
        
        Returns:
            bool: True si Companion est accessible, False sinon
        """
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            sock.connect((self.host, self.port))
            sock.close()
            logger.info(f"Companion accessible sur {self.host}:{self.port}")
            return True
        except Exception as e:
            logger.debug(f"Companion non accessible sur {self.host}:{self.port} : {e}")
            return False
    
    
    def disconnect(self):
        """
        Ferme proprement la connexion TCP persistante.
        """
        if self.socket:
            try:
                self.socket.close()
                logger.debug("Déconnecté de Companion")
            except Exception as e:
                logger.debug(f"Erreur lors de la déconnexion : {e}")
            finally:
                self.socket = None
                self.connected = False
    
    
    def __del__(self):
        """
        Destructeur - ferme la connexion si l'objet est détruit.
        """
        self.disconnect()
