#!/usr/bin/env python3
"""
Script pour visualiser les données de la LUT 3D.
"""

import json
import sys
from collections import defaultdict

def view_lut3d(filename="focus_zoom_lut_3d.json"):
    """Affiche les statistiques et un échantillon de la LUT 3D."""
    try:
        with open(filename, 'r') as f:
            data = json.load(f)
        
        lut_3d = data.get('lut_3d', [])
        generated_at = data.get('generated_at', 'N/A')
        
        print("=" * 80)
        print(f"LUT 3D: {filename}")
        print("=" * 80)
        print(f"Généré le: {generated_at}")
        print(f"Total d'entrées: {len(lut_3d)}")
        print()
        
        if not lut_3d:
            print("La LUT est vide.")
            return
        
        # Statistiques par zoom
        zoom_stats = defaultdict(list)
        for entry in lut_3d:
            zoom = entry.get('zoom_normalised')
            if zoom is not None:
                zoom_stats[zoom].append(entry)
        
        print(f"Zooms uniques: {len(zoom_stats)}")
        print()
        
        # Afficher les statistiques pour chaque zoom
        for zoom in sorted(zoom_stats.keys()):
            entries = zoom_stats[zoom]
            distances = [e.get('distance_cm') for e in entries if e.get('distance_cm') is not None]
            focuses = [e.get('focus_normalised') for e in entries if e.get('focus_normalised') is not None]
            
            print(f"Zoom {zoom:.4f}:")
            print(f"  - Nombre d'entrées: {len(entries)}")
            if distances:
                print(f"  - Distance min: {min(distances)}cm, max: {max(distances)}cm")
            if focuses:
                print(f"  - Focus min: {min(focuses):.4f}, max: {max(focuses):.4f}")
            print()
        
        # Afficher un échantillon (premières et dernières entrées)
        print("=" * 80)
        print("Échantillon (10 premières entrées):")
        print("=" * 80)
        for i, entry in enumerate(lut_3d[:10], 1):
            print(f"{i:3d}. Zoom={entry.get('zoom_normalised', 'N/A'):.4f}, "
                  f"Focus={entry.get('focus_normalised', 'N/A'):.4f}, "
                  f"Distance={entry.get('distance_cm', 'N/A')}cm")
        
        if len(lut_3d) > 10:
            print()
            print("=" * 80)
            print("Échantillon (10 dernières entrées):")
            print("=" * 80)
            for i, entry in enumerate(lut_3d[-10:], len(lut_3d) - 9):
                print(f"{i:3d}. Zoom={entry.get('zoom_normalised', 'N/A'):.4f}, "
                      f"Focus={entry.get('focus_normalised', 'N/A'):.4f}, "
                      f"Distance={entry.get('distance_cm', 'N/A')}cm")
        
        print()
        print("=" * 80)
        print("Pour voir les valeurs en temps réel pendant la génération:")
        print("  tail -f lut_generation.log")
        print("=" * 80)
        
    except FileNotFoundError:
        print(f"Erreur: Le fichier {filename} n'existe pas encore.")
        print("La génération est peut-être en cours. Consultez lut_generation.log pour voir la progression.")
    except json.JSONDecodeError as e:
        print(f"Erreur: Le fichier JSON est invalide: {e}")
    except Exception as e:
        print(f"Erreur: {e}")


if __name__ == "__main__":
    filename = sys.argv[1] if len(sys.argv) > 1 else "focus_zoom_lut_3d.json"
    view_lut3d(filename)


