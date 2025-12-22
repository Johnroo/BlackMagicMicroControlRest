#!/usr/bin/env python3
"""
StateStore: Store canonique de l'état de l'application pour Companion.
Émet des patchs incrémentaux quand des valeurs changent.
"""

from typing import Dict, Any, Optional
from PySide6.QtCore import QObject, Signal

import logging
logger = logging.getLogger(__name__)


class StateStore(QObject):
    """Store canonique de l'état de l'application."""
    
    # Signal émis quand l'état change (patch incrémental)
    state_changed = Signal(dict)  # patch: dict
    
    def __init__(self):
        super().__init__()
        
        # État initial
        self._state = {
            "active_cam": 1,
            "cams": {},
            "presets": {},
            "meta": {
                "app": "koko-focus",
                "version": "0.1"
            }
        }
        
        # Initialiser les 8 caméras avec des valeurs par défaut
        for i in range(1, 9):
            self._state["cams"][str(i)] = {
                "connected": False,
                "focus": None,
                "iris": None,
                "gain": None,
                "shutter": None,
                "whiteBalance": None,
                "zoom": None
            }
            self._state["presets"][str(i)] = {}
    
    def snapshot(self) -> dict:
        """
        Retourne un snapshot complet de l'état.
        
        Returns:
            Dictionnaire contenant l'état complet (active_cam, cams, meta)
            Note: Les presets ne sont pas inclus car Companion n'en a pas besoin
        """
        # Retourner une copie profonde pour éviter les modifications externes
        import copy
        snapshot = copy.deepcopy(self._state)
        # Retirer les presets du snapshot (Companion n'en a pas besoin)
        snapshot.pop("presets", None)
        return snapshot
    
    def update_cam(self, cam: int, **kwargs):
        """
        Met à jour les valeurs d'une caméra.
        
        Args:
            cam: Numéro de la caméra (1-8)
            **kwargs: Valeurs à mettre à jour (connected, focus, iris, gain, shutter, whiteBalance, zoom)
        """
        cam_key = str(cam)
        if cam_key not in self._state["cams"]:
            logger.warning(f"Caméra {cam} n'existe pas dans le state")
            return
        
        # Construire le patch
        patch = {
            "cams": {
                cam_key: {}
            }
        }
        
        # Mettre à jour les valeurs dans l'état
        cam_state = self._state["cams"][cam_key]
        for key, value in kwargs.items():
            if key in ["connected", "focus", "iris", "gain", "shutter", "whiteBalance", "zoom"]:
                # Vérifier si la valeur a changé
                if cam_state.get(key) != value:
                    cam_state[key] = value
                    patch["cams"][cam_key][key] = value
        
        # Émettre le signal seulement si le patch contient des changements
        if patch["cams"][cam_key]:
            self.state_changed.emit(patch)
            logger.debug(f"StateStore: Patch émis pour cam {cam}: {patch}")
    
    def set_active_cam(self, cam: int):
        """
        Change la caméra active (UI uniquement).
        
        Args:
            cam: Numéro de la caméra (1-8)
        """
        if cam < 1 or cam > 8:
            logger.warning(f"Numéro de caméra invalide: {cam}")
            return
        
        if self._state["active_cam"] != cam:
            self._state["active_cam"] = cam
            
            # Émettre un patch pour le changement de caméra active
            patch = {
                "active_cam": cam
            }
            self.state_changed.emit(patch)
            logger.debug(f"StateStore: Caméra active changée vers {cam}")
    
    def set_preset(self, cam: int, name: str, data: dict):
        """
        Met à jour un preset pour une caméra (interne uniquement).
        
        Args:
            cam: Numéro de la caméra (1-8)
            name: Nom du preset (ex: "preset_1")
            data: Données du preset (focus, iris, gain, shutter, zoom)
        
        Note: Les presets ne sont pas envoyés à Companion via patchs car Companion
        n'a pas besoin de connaître le contenu des presets, seulement de pouvoir les
        rappeler et sauvegarder.
        """
        cam_key = str(cam)
        if cam_key not in self._state["presets"]:
            self._state["presets"][cam_key] = {}
        
        # Mettre à jour le preset (interne uniquement)
        self._state["presets"][cam_key][name] = data.copy()
        
        # Ne PAS émettre de patch - Companion n'a pas besoin de connaître le contenu
        logger.debug(f"StateStore: Preset {name} mis à jour pour cam {cam} (interne uniquement)")
    
    def get_preset(self, cam: int, name: str) -> Optional[dict]:
        """
        Récupère un preset pour une caméra.
        
        Args:
            cam: Numéro de la caméra (1-8)
            name: Nom du preset (ex: "preset_1")
        
        Returns:
            Dictionnaire contenant les données du preset, ou None si introuvable
        """
        cam_key = str(cam)
        if cam_key not in self._state["presets"]:
            return None
        
        return self._state["presets"][cam_key].get(name)

