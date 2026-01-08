#!/usr/bin/env python3
"""
Script pour corriger la LUT 3D : diviser toutes les distances par 2
car l'échelle était en demi-centimètres.
"""

import json
import sys

def fix_lut3d_scale(input_file="focus_zoom_lut_3d.json", output_file=None):
    """Corrige la LUT 3D en divisant toutes les distances par 2."""
    if output_file is None:
        output_file = input_file
    
    print(f"Chargement de {input_file}...")
    with open(input_file, 'r') as f:
        data = json.load(f)
    
    lut_3d = data.get("lut_3d", [])
    print(f"Nombre d'entrées: {len(lut_3d)}")
    
    # Corriger toutes les distances
    corrected = 0
    for entry in lut_3d:
        if "distance_cm" in entry:
            old_distance = entry["distance_cm"]
            entry["distance_cm"] = old_distance / 2.0
            corrected += 1
    
    print(f"Distances corrigées: {corrected}")
    print(f"Exemple: {lut_3d[0].get('distance_cm') if lut_3d else 'N/A'}cm (était {lut_3d[0].get('distance_cm') * 2 if lut_3d else 'N/A'}cm)")
    
    # Sauvegarder
    data["lut_3d"] = lut_3d
    data["scale_corrected"] = True
    data["correction_note"] = "Distances divisées par 2 (échelle était en demi-centimètres)"
    
    print(f"Sauvegarde dans {output_file}...")
    with open(output_file, 'w') as f:
        json.dump(data, f, indent=2)
    
    print("✓ Correction terminée!")

if __name__ == "__main__":
    input_file = sys.argv[1] if len(sys.argv) > 1 else "focus_zoom_lut_3d.json"
    output_file = sys.argv[2] if len(sys.argv) > 2 else None
    fix_lut3d_scale(input_file, output_file)



