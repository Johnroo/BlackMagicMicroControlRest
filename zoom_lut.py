#!/usr/bin/env python3
"""
Look-Up Table (LUT) pour la correspondance entre zoom normalised (0.0-1.0) et distance en mètres.
"""

import json
import os
from typing import Optional, List, Dict
import logging

logger = logging.getLogger(__name__)

# Import pour la conversion croisée avec focuslut
try:
    from focus_lut import FocusLUT
except ImportError:
    FocusLUT = None


class ZoomLUT:
    """Look-Up Table pour la correspondance entre zoom normalised et distance en mètres."""
    
    def __init__(self, lut_file: str = "zoomlut.json", conversion_table_file: str = "zoom_focus_conversion.json"):
        """
        Initialise la LUT et charge le fichier JSON.
        
        Args:
            lut_file: Chemin vers le fichier JSON contenant la LUT
            conversion_table_file: Chemin vers le fichier de table de conversion zoom → focus (optionnel)
        """
        self.lut_file = lut_file
        self.conversion_table_file = conversion_table_file
        self.lut_data: List[Dict] = []
        self.conversion_table: List[Dict] = []
        self.load_lut()
        self.load_conversion_table()
    
    def load_lut(self) -> bool:
        """
        Charge la LUT depuis le fichier JSON.
        
        Returns:
            True si la LUT a été chargée avec succès, False sinon
        """
        if not os.path.exists(self.lut_file):
            logger.warning(f"Fichier LUT zoom non trouvé: {self.lut_file}")
            return False
        
        try:
            with open(self.lut_file, 'r') as f:
                data = json.load(f)
                self.lut_data = data.get('lut', [])
                
                # Trier par zoom_normalised croissant pour faciliter la recherche
                self.lut_data.sort(key=lambda x: x.get('zoom_normalised', 0.0))
                
                logger.info(f"LUT zoom chargée: {len(self.lut_data)} entrées depuis {self.lut_file}")
                return True
        except json.JSONDecodeError as e:
            logger.error(f"Erreur de parsing JSON dans la LUT zoom: {e}")
            return False
        except Exception as e:
            logger.error(f"Erreur lors du chargement de la LUT zoom: {e}")
            return False
    
    def load_conversion_table(self) -> bool:
        """
        Charge la table de conversion zoom → focus depuis le fichier JSON.
        
        Returns:
            True si la table a été chargée avec succès, False sinon
        """
        if not os.path.exists(self.conversion_table_file):
            logger.debug(f"Fichier de table de conversion non trouvé: {self.conversion_table_file}")
            return False
        
        try:
            with open(self.conversion_table_file, 'r') as f:
                data = json.load(f)
                self.conversion_table = data.get('conversion_table', [])
                
                # Trier par zoom_normalised croissant pour faciliter la recherche
                self.conversion_table.sort(key=lambda x: x.get('zoom_normalised', 0.0))
                
                logger.info(f"Table de conversion zoom→focus chargée: {len(self.conversion_table)} entrées depuis {self.conversion_table_file}")
                return True
        except json.JSONDecodeError as e:
            logger.error(f"Erreur de parsing JSON dans la table de conversion: {e}")
            return False
        except Exception as e:
            logger.error(f"Erreur lors du chargement de la table de conversion: {e}")
            return False
    
    def zoom_to_distance(self, zoom_normalised: float) -> Optional[float]:
        """
        Convertit une valeur normalisée de zoom (0.0-1.0) en distance en mètres.
        Utilise une interpolation linéaire entre les points de la LUT.
        
        Args:
            zoom_normalised: Valeur normalisée du zoom (0.0-1.0)
            
        Returns:
            Distance en mètres (float) ou None si la LUT n'est pas disponible
        """
        if not self.lut_data:
            return None
        
        # Clamper la valeur normalisée entre 0.0 et 1.0
        zoom_normalised = max(0.0, min(1.0, zoom_normalised))
        
        # Si la LUT est vide, retourner None
        if len(self.lut_data) == 0:
            return None
        
        # Si un seul point, retourner sa distance
        if len(self.lut_data) == 1:
            distance = self.lut_data[0].get('distance_meters')
            return distance if distance is not None else None
        
        # Vérifier si la valeur est en dehors de la plage de la LUT
        first_zoom = self.lut_data[0].get('zoom_normalised', 0.0)
        last_zoom = self.lut_data[-1].get('zoom_normalised', 1.0)
        
        if zoom_normalised <= first_zoom:
            distance = self.lut_data[0].get('distance_meters')
            return distance if distance is not None else None
        if zoom_normalised >= last_zoom:
            distance = self.lut_data[-1].get('distance_meters')
            return distance if distance is not None else None
        
        # Trouver les deux points encadrants pour l'interpolation linéaire
        for i in range(len(self.lut_data) - 1):
            point1 = self.lut_data[i]
            point2 = self.lut_data[i + 1]
            
            z1 = point1.get('zoom_normalised', 0.0)
            z2 = point2.get('zoom_normalised', 1.0)
            
            if z1 <= zoom_normalised <= z2:
                # Interpolation linéaire
                if z2 == z1:
                    distance = point1.get('distance_meters')
                else:
                    ratio = (zoom_normalised - z1) / (z2 - z1)
                    d1 = point1.get('distance_meters', 0.0)
                    d2 = point2.get('distance_meters', 0.0)
                    distance = d1 + ratio * (d2 - d1)
                
                return distance
        
        # Si on arrive ici, quelque chose ne va pas
        logger.warning(f"Impossible de trouver une correspondance pour zoom_normalised={zoom_normalised}")
        return None
    
    def zoom_to_focus_normalised(self, zoom_normalised: float, focus_lut: Optional['FocusLUT'] = None) -> Optional[float]:
        """
        Convertit une valeur normalisée de zoom (0.0-1.0) en focus normalised (0.0-1.0)
        en utilisant la zoomlut pour obtenir la distance, puis la focuslut pour convertir en focus.
        
        Args:
            zoom_normalised: Valeur normalisée du zoom (0.0-1.0)
            focus_lut: Instance de FocusLUT (si None, essaie de la charger automatiquement)
            
        Returns:
            Focus normalised (0.0-1.0) ou None si la conversion n'est pas possible
        """
        # Obtenir la distance depuis la zoomlut
        distance_meters = self.zoom_to_distance(zoom_normalised)
        if distance_meters is None:
            return None
        
        # Charger la focuslut si nécessaire
        if focus_lut is None:
            if FocusLUT is None:
                logger.error("FocusLUT n'est pas disponible pour la conversion")
                return None
            focus_lut = FocusLUT("focuslut.json")
            if not focus_lut.lut_data:
                logger.error("Impossible de charger la focuslut")
                return None
        
        # Si on a une table de conversion chargée, l'utiliser en priorité (plus rapide)
        if self.conversion_table:
            # Recherche dans la table de conversion
            zoom_normalised = max(0.0, min(1.0, zoom_normalised))
            
            # Si un seul point, retourner sa valeur
            if len(self.conversion_table) == 1:
                return self.conversion_table[0].get('focus_normalised')
            
            # Vérifier si la valeur est en dehors de la plage
            first_zoom = self.conversion_table[0].get('zoom_normalised', 0.0)
            last_zoom = self.conversion_table[-1].get('zoom_normalised', 1.0)
            
            if zoom_normalised <= first_zoom:
                return self.conversion_table[0].get('focus_normalised')
            if zoom_normalised >= last_zoom:
                return self.conversion_table[-1].get('focus_normalised')
            
            # Trouver les deux points encadrants pour l'interpolation linéaire
            for i in range(len(self.conversion_table) - 1):
                point1 = self.conversion_table[i]
                point2 = self.conversion_table[i + 1]
                
                z1 = point1.get('zoom_normalised', 0.0)
                z2 = point2.get('zoom_normalised', 1.0)
                
                if z1 <= zoom_normalised <= z2:
                    # Interpolation linéaire
                    if z2 == z1:
                        return point1.get('focus_normalised')
                    else:
                        ratio = (zoom_normalised - z1) / (z2 - z1)
                        f1 = point1.get('focus_normalised', 0.0)
                        f2 = point2.get('focus_normalised', 1.0)
                        focus_normalised = f1 + ratio * (f2 - f1)
                        return max(0.0, min(1.0, focus_normalised))
        
        # Sinon, utiliser la méthode avec focuslut (plus lente mais toujours disponible)
        # Convertir la distance en focus normalised en utilisant la focuslut
        # On doit faire une recherche inverse : distance → focus_normalised
        # Note: la distance de zoomlut n'a pas la correction -1m, donc on l'ajoute pour correspondre à focuslut
        distance_corrected = distance_meters - 1.0
        return focus_lut.distance_to_normalised(max(0.0, distance_corrected))

