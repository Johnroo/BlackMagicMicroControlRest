#!/usr/bin/env python3
"""
Look-Up Table (LUT) pour la correspondance entre focus normalised (0.0-1.0) et distance en mètres.
"""

import json
import os
from typing import Optional, List, Dict, Tuple
import logging

logger = logging.getLogger(__name__)


class FocusLUT:
    """Look-Up Table pour la correspondance entre focus normalised et distance en mètres."""
    
    def __init__(self, lut_file: str = "focuslut.json", lut_3d_file: Optional[str] = "focus_zoom_lut_3d.json"):
        """
        Initialise la LUT et charge le fichier JSON.
        
        Args:
            lut_file: Chemin vers le fichier JSON contenant la LUT 2D (legacy)
            lut_3d_file: Chemin vers le fichier JSON contenant la LUT 3D (zoom × focus → distance)
        """
        self.lut_file = lut_file
        self.lut_3d_file = lut_3d_file
        self.lut_data: List[Dict] = []
        self.lut_3d_data: List[Dict] = []
        self.lut_3d_index: Dict[Tuple[float, float], float] = {}  # Index: (zoom_normalised, focus_normalised) -> distance_cm
        self.load_lut()
        self.load_lut_3d()
    
    def load_lut(self) -> bool:
        """
        Charge la LUT depuis le fichier JSON.
        
        Returns:
            True si la LUT a été chargée avec succès, False sinon
        """
        if not os.path.exists(self.lut_file):
            logger.warning(f"Fichier LUT non trouvé: {self.lut_file}")
            return False
        
        try:
            with open(self.lut_file, 'r') as f:
                data = json.load(f)
                self.lut_data = data.get('lut', [])
                
                # Trier par normalised croissant pour faciliter la recherche
                self.lut_data.sort(key=lambda x: x.get('normalised', 0.0))
                
                logger.info(f"LUT chargée: {len(self.lut_data)} entrées depuis {self.lut_file}")
                return True
        except json.JSONDecodeError as e:
            logger.error(f"Erreur de parsing JSON dans la LUT: {e}")
            return False
        except Exception as e:
            logger.error(f"Erreur lors du chargement de la LUT: {e}")
            return False
    
    def load_lut_3d(self) -> bool:
        """
        Charge la LUT 3D depuis le fichier JSON.
        
        Returns:
            True si la LUT 3D a été chargée avec succès, False sinon
        """
        if not self.lut_3d_file or not os.path.exists(self.lut_3d_file):
            logger.debug(f"Fichier LUT 3D non trouvé: {self.lut_3d_file}")
            return False
        
        try:
            with open(self.lut_3d_file, 'r') as f:
                data = json.load(f)
                self.lut_3d_data = data.get('lut_3d', [])
                
                # Créer un index pour recherche rapide
                self.lut_3d_index = {}
                for entry in self.lut_3d_data:
                    zoom_norm = entry.get('zoom_normalised')
                    focus_norm = entry.get('focus_normalised')
                    distance_cm = entry.get('distance_cm')
                    if zoom_norm is not None and focus_norm is not None and distance_cm is not None:
                        # Utiliser des clés arrondies pour éviter les problèmes de précision flottante
                        key = (round(zoom_norm, 6), round(focus_norm, 6))
                        self.lut_3d_index[key] = distance_cm
                
                logger.info(f"LUT 3D chargée: {len(self.lut_3d_data)} entrées depuis {self.lut_3d_file}")
                return True
        except json.JSONDecodeError as e:
            logger.error(f"Erreur de parsing JSON dans la LUT 3D: {e}")
            return False
        except Exception as e:
            logger.error(f"Erreur lors du chargement de la LUT 3D: {e}")
            return False
    
    def normalised_to_distance(self, normalised: float) -> Optional[float]:
        """
        Convertit une valeur normalisée (0.0-1.0) en distance en mètres.
        Utilise une interpolation linéaire entre les points de la LUT.
        
        Args:
            normalised: Valeur normalisée du focus (0.0-1.0)
            
        Returns:
            Distance en mètres (float) ou None si la LUT n'est pas disponible
        """
        if not self.lut_data:
            return None
        
        # Clamper la valeur normalisée entre 0.0 et 1.0
        normalised = max(0.0, min(1.0, normalised))
        
        # Si la LUT est vide, retourner None
        if len(self.lut_data) == 0:
            return None
        
        # Si un seul point, retourner sa distance
        if len(self.lut_data) == 1:
            distance = self.lut_data[0].get('distance_meters')
            return distance if distance is not None else None
        
        # Vérifier si la valeur est en dehors de la plage de la LUT
        first_normalised = self.lut_data[0].get('normalised', 0.0)
        last_normalised = self.lut_data[-1].get('normalised', 1.0)
        
        if normalised <= first_normalised:
            distance = self.lut_data[0].get('distance_meters')
            return distance if distance is not None else None
        if normalised >= last_normalised:
            distance = self.lut_data[-1].get('distance_meters')
            return distance if distance is not None else None
        
        # Trouver les deux points encadrants pour l'interpolation linéaire
        for i in range(len(self.lut_data) - 1):
            point1 = self.lut_data[i]
            point2 = self.lut_data[i + 1]
            
            n1 = point1.get('normalised', 0.0)
            n2 = point2.get('normalised', 1.0)
            
            if n1 <= normalised <= n2:
                # Interpolation linéaire
                if n2 == n1:
                    distance = point1.get('distance_meters')
                else:
                    ratio = (normalised - n1) / (n2 - n1)
                    d1 = point1.get('distance_meters', 0.0)
                    d2 = point2.get('distance_meters', 0.0)
                    distance = d1 + ratio * (d2 - d1)
                
                return distance
        
        # Si on arrive ici, quelque chose ne va pas
        logger.warning(f"Impossible de trouver une correspondance pour normalised={normalised}")
        return None
    
    def distance_to_normalised(self, distance_meters: float) -> Optional[float]:
        """
        Convertit une distance en mètres en valeur normalisée de focus (0.0-1.0).
        Conversion inverse de normalised_to_distance.
        Utilise une interpolation linéaire entre les points de la LUT.
        
        Args:
            distance_meters: Distance en mètres
            
        Returns:
            Focus normalised (0.0-1.0) ou None si la conversion n'est pas possible
        """
        if not self.lut_data:
            return None
        
        # Si la LUT est vide, retourner None
        if len(self.lut_data) == 0:
            return None
        
        # Si un seul point, retourner sa valeur normalisée
        if len(self.lut_data) == 1:
            return self.lut_data[0].get('normalised')
        
        # Trouver les deux points encadrants pour l'interpolation linéaire
        # On cherche les points où la distance est la plus proche
        for i in range(len(self.lut_data) - 1):
            point1 = self.lut_data[i]
            point2 = self.lut_data[i + 1]
            
            d1 = point1.get('distance_meters', 0.0)
            d2 = point2.get('distance_meters', 0.0)
            
            # Vérifier si la distance est entre ces deux points
            if d1 <= distance_meters <= d2 or d2 <= distance_meters <= d1:
                # Interpolation linéaire
                if d2 == d1:
                    normalised = point1.get('normalised', 0.0)
                else:
                    # Normaliser d1 et d2 pour l'interpolation
                    if d1 > d2:
                        d1, d2 = d2, d1
                        point1, point2 = point2, point1
                    
                    ratio = (distance_meters - d1) / (d2 - d1)
                    n1 = point1.get('normalised', 0.0)
                    n2 = point2.get('normalised', 1.0)
                    normalised = n1 + ratio * (n2 - n1)
                
                return max(0.0, min(1.0, normalised))
        
        # Si la distance est en dehors de la plage, retourner la valeur la plus proche
        first_distance = self.lut_data[0].get('distance_meters', 0.0)
        last_distance = self.lut_data[-1].get('distance_meters', 0.0)
        
        if distance_meters <= first_distance:
            return self.lut_data[0].get('normalised', 0.0)
        if distance_meters >= last_distance:
            return self.lut_data[-1].get('normalised', 1.0)
        
        # Si on arrive ici, quelque chose ne va pas
        logger.warning(f"Impossible de trouver une correspondance pour distance={distance_meters}")
        return None
    
    def normalised_to_distance_with_zoom(self, normalised: float, zoom_normalised: Optional[float] = None) -> Optional[float]:
        """
        Convertit une valeur normalisée de focus (0.0-1.0) en distance en mètres,
        en tenant compte du zoom si fourni.
        
        Utilise la table 3D si disponible, sinon utilise l'ancienne méthode avec zoomlut.
        
        IMPORTANT: zoom_normalised doit être la valeur normalisée du SLIDER (0.0-1.0),
        et non la valeur de l'API caméra. La table 3D utilise les valeurs du slider.
        
        Args:
            normalised: Valeur normalisée du focus (0.0-1.0) depuis l'API caméra
            zoom_normalised: Valeur normalisée du zoom (0.0-1.0) depuis l'API caméra (GET /lens/zoom), optionnel
            
        Returns:
            Distance en mètres (float) ou None si la conversion n'est pas possible
        """
        # Si on a une LUT 3D et un zoom, utiliser la méthode 3D
        if zoom_normalised is not None and self.lut_3d_data:
            result = self.normalised_to_distance_with_zoom_3d(normalised, zoom_normalised)
            if result is not None:
                return result
            # Si la méthode 3D échoue, fallback sur l'ancienne méthode
            logger.debug("LUT 3D n'a pas trouvé de correspondance, utilisation de la méthode legacy")
        
        # Méthode legacy (ancienne logique)
        # Obtenir la distance depuis la focuslut (basée sur zoom 0.13)
        distance_base = self.normalised_to_distance(normalised)
        if distance_base is None:
            return None
        
        # Si pas de zoom ou zoom = 0.13, retourner directement la valeur de la focuslut
        if zoom_normalised is None or abs(zoom_normalised - 0.13) < 0.001:
            return distance_base
        
        # Import pour la conversion croisée avec zoomlut
        try:
            from zoom_lut import ZoomLUT
        except ImportError:
            logger.warning("ZoomLUT non disponible, utilisation de la valeur de base (zoom 0.13)")
            return distance_base
        
        # Charger la zoomlut
        zoom_lut = ZoomLUT("zoomlut.json")
        if not zoom_lut.lut_data:
            logger.warning("ZoomLUT non disponible, utilisation de la valeur de base (zoom 0.13)")
            return distance_base
        
        # Obtenir la distance pour zoom 0.13 (référence)
        distance_zoom_ref = zoom_lut.zoom_to_distance(0.13)
        if distance_zoom_ref is None:
            logger.warning("Impossible d'obtenir la distance pour zoom 0.13, utilisation de la valeur de base")
            return distance_base
        
        # Obtenir la distance pour le zoom actuel
        distance_zoom_actual = zoom_lut.zoom_to_distance(zoom_normalised)
        if distance_zoom_actual is None:
            logger.warning(f"Impossible d'obtenir la distance pour zoom {zoom_normalised}, utilisation de la valeur de base")
            return distance_base
        
        # Calculer le ratio : distance_zoom_0.13 / distance_zoom_actuel (inversé)
        if distance_zoom_actual == 0.0:
            logger.warning("Distance zoom actuel est nulle, utilisation de la valeur de base")
            return distance_base
        
        # Ratio inversé : distance_zoom_0.13 / distance_zoom_actuel
        ratio = distance_zoom_ref / distance_zoom_actual
        
        # Appliquer le ratio à la distance de base (focuslut)
        adjusted_distance = distance_base * ratio
        
        return max(0.0, adjusted_distance)
    
    def normalised_to_distance_with_zoom_3d(self, normalised: float, zoom_normalised: float) -> Optional[float]:
        """
        Convertit focus normalised + zoom normalised → distance en mètres en utilisant la table 3D.
        Utilise une interpolation bilinéaire si nécessaire.
        
        IMPORTANT: zoom_normalised doit être la valeur normalisée du SLIDER (0.0-1.0), 
        et non la valeur de l'API caméra. La table 3D a été générée avec les valeurs 
        normalisées du slider (position du moteur zoom du slider).
        
        Args:
            normalised: Valeur normalisée du focus (0.0-1.0) depuis l'API caméra
            zoom_normalised: Valeur normalisée du zoom du SLIDER (0.0-1.0), position du moteur zoom
            
        Returns:
            Distance en mètres (float) ou None si la conversion n'est pas possible
        """
        if not self.lut_3d_data:
            return None
        
        # Clamper les valeurs
        normalised = max(0.0, min(1.0, normalised))
        zoom_normalised = max(0.0, min(1.0, zoom_normalised))
        
        # Recherche exacte d'abord (avec tolérance)
        rounded_zoom = round(zoom_normalised, 6)
        rounded_focus = round(normalised, 6)
        exact_key = (rounded_zoom, rounded_focus)
        
        if exact_key in self.lut_3d_index:
            distance_cm = self.lut_3d_index[exact_key]
            return distance_cm / 200.0  # Convertir demi-cm en mètres (demi-cm / 2 = cm, puis / 100 = m)
        
        # Interpolation bilinéaire : trouver les 4 points les plus proches
        # (zoom1, focus1), (zoom1, focus2), (zoom2, focus1), (zoom2, focus2)
        
        # Trouver les zooms encadrants
        zoom_points = sorted(set(entry['zoom_normalised'] for entry in self.lut_3d_data))
        if not zoom_points:
            return None
        
        zoom1, zoom2 = None, None
        for i in range(len(zoom_points) - 1):
            if zoom_points[i] <= zoom_normalised <= zoom_points[i + 1]:
                zoom1, zoom2 = zoom_points[i], zoom_points[i + 1]
                break
        
        if zoom1 is None:
            # Zoom hors limites, utiliser le plus proche
            if zoom_normalised < zoom_points[0]:
                zoom1 = zoom2 = zoom_points[0]
            else:
                zoom1 = zoom2 = zoom_points[-1]
        
        # Pour chaque zoom, trouver les focus encadrants et leurs distances
        def find_focus_points(zoom_val):
            """Trouve les points focus encadrants pour un zoom donné."""
            entries = [e for e in self.lut_3d_data if abs(e['zoom_normalised'] - zoom_val) < 0.0001]
            if not entries:
                return None, None, None, None
            
            focus_values = sorted(set(e['focus_normalised'] for e in entries))
            if not focus_values:
                return None, None, None, None
            
            focus1, focus2 = None, None
            for i in range(len(focus_values) - 1):
                if focus_values[i] <= normalised <= focus_values[i + 1]:
                    focus1, focus2 = focus_values[i], focus_values[i + 1]
                    break
            
            if focus1 is None:
                if normalised < focus_values[0]:
                    focus1 = focus2 = focus_values[0]
                else:
                    focus1 = focus2 = focus_values[-1]
            
            # Trouver les distances correspondantes
            dist1 = next((e['distance_cm'] for e in entries if abs(e['focus_normalised'] - focus1) < 0.0001), None)
            dist2 = next((e['distance_cm'] for e in entries if abs(e['focus_normalised'] - focus2) < 0.0001), None)
            
            return focus1, focus2, dist1, dist2
        
        # Obtenir les points pour zoom1 et zoom2
        f1_z1, f2_z1, d1_z1, d2_z1 = find_focus_points(zoom1)
        f1_z2, f2_z2, d1_z2, d2_z2 = find_focus_points(zoom2)
        
        if None in (f1_z1, f2_z1, d1_z1, d2_z1, f1_z2, f2_z2, d1_z2, d2_z2):
            logger.debug(f"Impossible de trouver les points pour interpolation (zoom={zoom_normalised:.4f}, focus={normalised:.4f})")
            return None
        
        # Interpolation bilinéaire
        # 1. Interpolation sur focus pour zoom1
        if abs(f2_z1 - f1_z1) < 0.0001:
            dist_z1 = d1_z1
        else:
            ratio_f = (normalised - f1_z1) / (f2_z1 - f1_z1)
            dist_z1 = d1_z1 + ratio_f * (d2_z1 - d1_z1)
        
        # 2. Interpolation sur focus pour zoom2
        if abs(f2_z2 - f1_z2) < 0.0001:
            dist_z2 = d1_z2
        else:
            ratio_f = (normalised - f1_z2) / (f2_z2 - f1_z2)
            dist_z2 = d1_z2 + ratio_f * (d2_z2 - d1_z2)
        
        # 3. Interpolation sur zoom
        if abs(zoom2 - zoom1) < 0.0001:
            distance_cm = dist_z1
        else:
            ratio_z = (zoom_normalised - zoom1) / (zoom2 - zoom1)
            distance_cm = dist_z1 + ratio_z * (dist_z2 - dist_z1)
        
        return distance_cm / 200.0  # Convertir demi-cm en mètres (demi-cm / 2 = cm, puis / 100 = m)


