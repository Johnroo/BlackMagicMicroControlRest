#!/usr/bin/env python3
"""
preset_description_manager.py - Gestionnaire de preset_description.json

Ce module gère les descriptions des presets avec assignation des musiciens et plans.
Remplace cameras_config.json d'AUTOREAL pour éviter les conflits avec cameras_config.json existant.
"""

from pathlib import Path
from typing import Optional, Dict, Any, List
import json
import logging

logger = logging.getLogger(__name__)

# Chemin vers le fichier de description des presets
PRESET_DESC_PATH = Path(__file__).parent / "preset_description.json"


def load_preset_descriptions() -> Dict[str, Any]:
    """
    Charge les descriptions des presets depuis le fichier JSON.
    
    Returns:
        dict: Les données avec structure :
        {
            "musicians": ["chanteur", "batteur", ...],
            "cameras": [
                {
                    "id": 1,
                    "presets": [
                        {
                            "id": 1,
                            "musicians": {
                                "chanteur": "mcu",
                                "batteur": "ws"
                            }
                        }
                    ]
                }
            ]
        }
    """
    try:
        if not PRESET_DESC_PATH.exists():
            # Créer un fichier vide avec structure par défaut
            default_data = {
                "musicians": [],
                "cameras": []
            }
            save_preset_descriptions(default_data)
            logger.info(f"Fichier {PRESET_DESC_PATH} créé avec structure par défaut")
            return default_data
        
        with open(PRESET_DESC_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data
    except json.JSONDecodeError as e:
        logger.error(f"Erreur de décodage JSON dans {PRESET_DESC_PATH}: {e}")
        return {"musicians": [], "cameras": []}
    except Exception as e:
        logger.error(f"Erreur lors du chargement de {PRESET_DESC_PATH}: {e}")
        return {"musicians": [], "cameras": []}


def save_preset_descriptions(data: Dict[str, Any]) -> bool:
    """
    Sauvegarde les descriptions des presets dans le fichier JSON.
    
    Args:
        data: Les données à sauvegarder
    
    Returns:
        bool: True si succès, False sinon
    """
    try:
        with open(PRESET_DESC_PATH, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logger.error(f"Erreur lors de la sauvegarde de {PRESET_DESC_PATH}: {e}")
        return False


def get_musicians() -> List[str]:
    """
    Récupère la liste des musiciens.
    
    Returns:
        list: Liste des noms de musiciens
    """
    data = load_preset_descriptions()
    return data.get("musicians", [])


def add_musician(name: str) -> bool:
    """
    Ajoute un musicien à la liste.
    
    Args:
        name: Nom du musicien
    
    Returns:
        bool: True si succès, False sinon
    """
    data = load_preset_descriptions()
    musicians = data.get("musicians", [])
    
    if name not in musicians:
        musicians.append(name)
        data["musicians"] = musicians
        return save_preset_descriptions(data)
    return False


def remove_musician(name: str) -> bool:
    """
    Supprime un musicien de la liste et de tous les presets.
    
    Args:
        name: Nom du musicien
    
    Returns:
        bool: True si succès, False sinon
    """
    data = load_preset_descriptions()
    musicians = data.get("musicians", [])
    
    if name in musicians:
        musicians.remove(name)
        data["musicians"] = musicians
        
        # Supprimer le musicien de tous les presets
        for camera in data.get("cameras", []):
            for preset in camera.get("presets", []):
                musicians_dict = preset.get("musicians", {})
                if name in musicians_dict:
                    del musicians_dict[name]
        
        return save_preset_descriptions(data)
    return False


def get_camera_presets(camera_id: int) -> List[Dict[str, Any]]:
    """
    Récupère les presets d'une caméra.
    
    Args:
        camera_id: ID de la caméra
    
    Returns:
        list: Liste des presets avec leurs descriptions
    """
    data = load_preset_descriptions()
    for camera in data.get("cameras", []):
        if camera.get("id") == camera_id:
            return camera.get("presets", [])
    
    # Si la caméra n'existe pas, créer une entrée vide
    ensure_camera_exists(camera_id)
    return []


def ensure_camera_exists(camera_id: int) -> bool:
    """
    S'assure qu'une caméra existe dans la structure.
    
    Args:
        camera_id: ID de la caméra
    
    Returns:
        bool: True si succès
    """
    data = load_preset_descriptions()
    cameras = data.get("cameras", [])
    
    # Vérifier si la caméra existe
    for camera in cameras:
        if camera.get("id") == camera_id:
            return True
    
    # Créer la caméra avec 10 presets vides
    new_camera = {
        "id": camera_id,
        "presets": [
            {
                "id": i,
                "musicians": {}
            }
            for i in range(1, 11)
        ]
    }
    cameras.append(new_camera)
    data["cameras"] = cameras
    return save_preset_descriptions(data)


def set_preset_musician_plan(camera_id: int, preset_id: int, musician: str, plan: str) -> bool:
    """
    Assigne un plan à un musicien pour un preset.
    
    Args:
        camera_id: ID de la caméra
        preset_id: ID du preset
        musician: Nom du musicien
        plan: Plan à assigner (absent, ecu, cu, mcu, ms, ws)
    
    Returns:
        bool: True si succès, False sinon
    """
    data = load_preset_descriptions()
    
    # S'assurer que la caméra existe
    ensure_camera_exists(camera_id)
    
    # Trouver la caméra
    for camera in data.get("cameras", []):
        if camera.get("id") == camera_id:
            # Trouver le preset
            for preset in camera.get("presets", []):
                if preset.get("id") == preset_id:
                    if "musicians" not in preset:
                        preset["musicians"] = {}
                    
                    if plan == "absent":
                        # Supprimer le musicien si plan = absent
                        preset["musicians"].pop(musician, None)
                    else:
                        preset["musicians"][musician] = plan
                    
                    return save_preset_descriptions(data)
    
    return False


def get_preset_musician_plan(camera_id: int, preset_id: int, musician: str) -> str:
    """
    Récupère le plan assigné à un musicien pour un preset.
    
    Args:
        camera_id: ID de la caméra
        preset_id: ID du preset
        musician: Nom du musicien
    
    Returns:
        str: Plan assigné ou "absent" par défaut
    """
    data = load_preset_descriptions()
    
    for camera in data.get("cameras", []):
        if camera.get("id") == camera_id:
            for preset in camera.get("presets", []):
                if preset.get("id") == preset_id:
                    musicians_dict = preset.get("musicians", {})
                    return musicians_dict.get(musician, "absent")
    
    return "absent"
