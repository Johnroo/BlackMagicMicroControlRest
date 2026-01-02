#!/usr/bin/env python3
"""
Look-Up Table (LUT) pour la correspondance entre focus normalised (0.0-1.0) et distance en mètres.
"""

import json
import os
from typing import Optional, List, Dict
import logging

logger = logging.getLogger(__name__)


class FocusLUT:
    """Look-Up Table pour la correspondance entre focus normalised et distance en mètres."""
    
    def __init__(self, lut_file: str = "focuslut.json"):
        """
        Initialise la LUT et charge le fichier JSON.
        
        Args:
            lut_file: Chemin vers le fichier JSON contenant la LUT
        """
        self.lut_file = lut_file
        self.lut_data: List[Dict] = []
        self.load_lut()
    
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
        
        La focuslut est correcte uniquement pour zoom_normalised = 0.13 (ratio 1:1).
        Pour les autres valeurs de zoom, on applique le ratio mesuré via la zoomlut.
        
        Args:
            normalised: Valeur normalisée du focus (0.0-1.0)
            zoom_normalised: Valeur normalisée du zoom (0.0-1.0), optionnel
            
        Returns:
            Distance en mètres (float) ou None si la conversion n'est pas possible
        """
        # Obtenir la distance depuis la focuslut (basée sur zoom 0.13)
        distance_base = self.normalised_to_distance(normalised)
        if distance_base is None:
            return None
        
        # Si pas de zoom ou zoom = 0.13, retourner directement la valeur de la focuslut avec correction -1m
        if zoom_normalised is None or abs(zoom_normalised - 0.13) < 0.001:
            # Retirer 1 mètre au résultat (correction)
            return max(0.0, distance_base - 1.0)
        
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
        # La zoomlut donne la distance mesurée pour chaque zoom (avec autofocus)
        # La focuslut est correcte pour zoom 0.13, donc on utilise ce zoom comme référence
        # Pour les autres zooms, on applique le ratio inversé mesuré
        if distance_zoom_actual == 0.0:
            logger.warning("Distance zoom actuel est nulle, utilisation de la valeur de base")
            return distance_base
        
        # Ratio inversé : distance_zoom_0.13 / distance_zoom_actuel
        # Plus le zoom est grand, plus la distance mesurée est grande, donc on divise par le ratio
        ratio = distance_zoom_ref / distance_zoom_actual
        
        # Appliquer le ratio à la distance de base (focuslut)
        adjusted_distance = distance_base * ratio
        
        # Retirer 1 mètre au résultat (correction)
        adjusted_distance = max(0.0, adjusted_distance - 1.0)
        
        return adjusted_distance


