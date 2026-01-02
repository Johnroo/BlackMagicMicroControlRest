#!/usr/bin/env python3
"""
Script pour générer une table de conversion zoom_normalised → focus_normalised
en croisant zoomlut et focuslut.
"""

import json
import argparse
from zoom_lut import ZoomLUT
from focus_lut import FocusLUT


def generate_zoom_focus_conversion_table(
    zoom_lut_file: str = "zoomlut.json",
    focus_lut_file: str = "focuslut.json",
    output_file: str = "zoom_focus_conversion.json",
    num_points: int = 100
):
    """
    Génère une table de conversion zoom_normalised → focus_normalised
    en utilisant les deux LUTs.
    
    Args:
        zoom_lut_file: Fichier de la LUT zoom
        focus_lut_file: Fichier de la LUT focus
        output_file: Fichier de sortie pour la table de conversion
        num_points: Nombre de points à générer (défaut: 100)
    """
    print(f"Chargement de la LUT zoom: {zoom_lut_file}")
    zoom_lut = ZoomLUT(zoom_lut_file)
    if not zoom_lut.lut_data:
        print("ERREUR: Impossible de charger la LUT zoom")
        return
    
    print(f"Chargement de la LUT focus: {focus_lut_file}")
    focus_lut = FocusLUT(focus_lut_file)
    if not focus_lut.lut_data:
        print("ERREUR: Impossible de charger la LUT focus")
        return
    
    print(f"Génération de la table de conversion: {num_points} points")
    print()
    
    conversion_table = []
    
    # Générer num_points valeurs de zoom entre 0.0 et 1.0
    for i in range(num_points):
        zoom_normalised = i / (num_points - 1) if num_points > 1 else 0.0
        
        # Obtenir la distance depuis la zoomlut
        distance_meters = zoom_lut.zoom_to_distance(zoom_normalised)
        if distance_meters is None:
            print(f"ERREUR: Impossible de convertir zoom {zoom_normalised:.4f} en distance")
            continue
        
        # Convertir la distance en focus normalised
        focus_normalised = zoom_lut.zoom_to_focus_normalised(zoom_normalised, focus_lut)
        if focus_normalised is None:
            print(f"ERREUR: Impossible de convertir distance {distance_meters:.2f}m en focus pour zoom {zoom_normalised:.4f}")
            continue
        
        conversion_table.append({
            "zoom_normalised": zoom_normalised,
            "focus_normalised": focus_normalised,
            "distance_meters": distance_meters
        })
        
        if (i + 1) % 10 == 0 or i == 0 or i == num_points - 1:
            print(f"  [{i+1}/{num_points}] zoom={zoom_normalised:.4f} → focus={focus_normalised:.4f} (distance={distance_meters:.2f}m)")
    
    # Sauvegarder la table de conversion
    output = {
        "conversion_table": conversion_table,
        "version": "1.0",
        "description": "Table de conversion zoom_normalised → focus_normalised générée en croisant zoomlut et focuslut",
        "num_points": num_points
    }
    
    with open(output_file, 'w') as f:
        json.dump(output, f, indent=2)
    
    print()
    print(f"Table de conversion générée avec succès: {len(conversion_table)} entrées dans {output_file}")
    if len(conversion_table) > 0:
        print(f"Plage zoom_normalised: {conversion_table[0]['zoom_normalised']:.4f} à {conversion_table[-1]['zoom_normalised']:.4f}")
        print(f"Plage focus_normalised: {conversion_table[0]['focus_normalised']:.4f} à {conversion_table[-1]['focus_normalised']:.4f}")
        print(f"Plage distance: {conversion_table[0]['distance_meters']:.2f}m à {conversion_table[-1]['distance_meters']:.2f}m")


def main():
    parser = argparse.ArgumentParser(
        description="Génère une table de conversion zoom_normalised → focus_normalised"
    )
    parser.add_argument(
        '--zoom-lut',
        default='zoomlut.json',
        help='Fichier de la LUT zoom (défaut: zoomlut.json)'
    )
    parser.add_argument(
        '--focus-lut',
        default='focuslut.json',
        help='Fichier de la LUT focus (défaut: focuslut.json)'
    )
    parser.add_argument(
        '--output',
        default='zoom_focus_conversion.json',
        help='Fichier de sortie (défaut: zoom_focus_conversion.json)'
    )
    parser.add_argument(
        '--points',
        type=int,
        default=100,
        help='Nombre de points à générer (défaut: 100)'
    )
    
    args = parser.parse_args()
    
    generate_zoom_focus_conversion_table(
        zoom_lut_file=args.zoom_lut,
        focus_lut_file=args.focus_lut,
        output_file=args.output,
        num_points=args.points
    )


if __name__ == "__main__":
    main()

