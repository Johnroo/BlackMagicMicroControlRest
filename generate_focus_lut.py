#!/usr/bin/env python3
"""
Script pour générer automatiquement la LUT focus (normalised → distance_meters).
Teste différentes valeurs de focusDistance et enregistre les correspondances.
"""

import argparse
import json
import time
import sys
from blackmagic_focus_control import BlackmagicFocusController


def generate_focus_lut(
    camera_url: str,
    username: str = "roo",
    password: str = "koko",
    output_file: str = "focuslut.json",
    min_cm: int = 10,
    max_cm: int = 2000,
    step_cm: int = 10,
    delay: float = 0.5
):
    """
    Génère une LUT en testant différentes valeurs de focusDistance (en cm).
    Envoie PUT avec focusDistance et récupère les valeurs normalised correspondantes.
    
    Args:
        camera_url: URL de la caméra (ex: http://camera.local)
        username: Nom d'utilisateur
        password: Mot de passe
        output_file: Fichier de sortie pour la LUT
        min_cm: Distance minimale en centimètres (défaut: 10)
        max_cm: Distance maximale en centimètres (défaut: 2000)
        step_cm: Pas entre les valeurs en centimètres (défaut: 10)
        delay: Délai d'attente après chaque positionnement (secondes)
    """
    print(f"Connexion à la caméra: {camera_url}")
    controller = BlackmagicFocusController(camera_url, username, password)
    
    # Vérifier la connexion
    focus_data = controller.get_focus()
    if focus_data is None:
        print("ERREUR: Impossible de se connecter à la caméra")
        sys.exit(1)
    
    print(f"Connexion réussie!")
    print(f"Génération de la LUT: {min_cm}cm à {max_cm}cm par pas de {step_cm}cm")
    print(f"Fichier de sortie: {output_file}")
    print()
    
    # Charger la LUT existante si elle existe
    lut = []
    try:
        with open(output_file, 'r') as f:
            existing_data = json.load(f)
            if 'lut' in existing_data:
                lut = existing_data['lut']
                print(f"LUT existante chargée: {len(lut)} entrées")
                if len(lut) > 0:
                    print(f"Dernière entrée: normalised={lut[-1]['normalised']:.4f}, distance={lut[-1]['distance_meters']:.2f}m")
    except FileNotFoundError:
        print("Aucune LUT existante, génération complète")
    except Exception as e:
        print(f"Erreur lors du chargement de la LUT existante: {e}, génération complète")
    
    # Pour les 5 premiers mètres (10-500 cm), utiliser un pas de 1 cm pour plus de précision
    # De 500 cm à 2000 cm (20 m), utiliser un pas de 10 cm
    # Au-delà de 2000 cm, utiliser un pas de 20 cm jusqu'à normalised >= 0.98
    # Si plus de 200 mesures avec pas de 20 cm sans atteindre 0.98, passer à pas de 50 cm
    fine_range_end = 500  # 5 mètres en cm
    medium_range_end = 2000  # 20 mètres en cm
    target_normalised = 0.98
    
    # Vérifier si on doit générer les points initiaux ou continuer
    should_generate_initial = len(lut) == 0
    
    if len(lut) > 0:
        last_normalised = lut[-1]['normalised']
        last_distance_cm = int(lut[-1]['distance_meters'] * 100)
        
        if last_normalised >= target_normalised:
            print(f"La LUT existante atteint déjà normalised >= {target_normalised} ({last_normalised:.4f})")
            should_generate_initial = False
        elif last_distance_cm >= medium_range_end - 10:  # Si on est proche de 20m (à 10cm près), continuer directement
            print(f"La LUT existante va jusqu'à {last_distance_cm}cm (normalised={last_normalised:.4f}), continuation au-delà de {medium_range_end}cm")
            should_generate_initial = False
        else:
            print(f"La LUT existante va jusqu'à {last_distance_cm}cm, complétion jusqu'à {medium_range_end}cm d'abord")
            should_generate_initial = True
    
    # Générer la liste des distances à tester (seulement si nécessaire)
    focus_distances = []
    
    if should_generate_initial:
        # De 10 cm à 500 cm par pas de 1 cm
        if min_cm <= fine_range_end:
            fine_start = max(min_cm, 10)
            focus_distances.extend(range(fine_start, min(fine_range_end + 1, max_cm + 1), 1))
        
        # De 500 cm à 2000 cm par pas de 10 cm
        if max_cm > fine_range_end:
            medium_start = max(fine_range_end + 1, min_cm)
            medium_end = min(medium_range_end, max_cm)
            if medium_end >= medium_start:
                focus_distances.extend(range(medium_start, medium_end + 1, 10))
        
        # Supprimer les doublons et trier
        focus_distances = sorted(list(set(focus_distances)))
        total_initial = len(focus_distances)
        
        print(f"Points initiaux: {total_initial} (précision 1cm de {min_cm}cm à {fine_range_end}cm, puis 10cm jusqu'à {medium_range_end}cm)")
        print()
        
        # Mesurer les points initiaux
        for i, focus_distance_cm in enumerate(focus_distances, 1):
            print(f"[{i}/{total_initial}] Test focusDistance={focus_distance_cm}cm...", end=" ", flush=True)
            
            try:
                # Envoyer PUT /lens/focus avec focusDistance (en cm)
                payload = {"focusDistance": focus_distance_cm}
                response = controller.session.put(
                    controller.focus_endpoint,
                    json=payload,
                    timeout=10,
                    headers={'Accept': 'application/json', 'Content-Type': 'application/json'}
                )
                
                if response.status_code != 204:
                    print(f"ERREUR: Status {response.status_code}")
                    continue
                
                # Attendre que la caméra se positionne
                time.sleep(delay)
                
                # Récupérer la valeur normalised correspondante
                focus_data = controller.get_focus()
                if focus_data is None or 'normalised' not in focus_data:
                    print("ERREUR: Impossible de récupérer normalised")
                    continue
                
                normalised = focus_data.get('normalised')
                if normalised is None:
                    print("ERREUR: normalised est None")
                    continue
                
                # Calculer distance_meters = focusDistance / 100.0 (conversion cm → m)
                distance_meters = focus_distance_cm / 100.0
                
                # Stocker le couple (normalised, distance_meters)
                lut.append({
                    "normalised": float(normalised),
                    "distance_meters": distance_meters
                })
                
                print(f"OK: normalised={normalised:.4f}, distance={distance_meters:.2f}m")
                
                # Vérifier si on a atteint la cible
                if normalised >= target_normalised:
                    target_reached = True
                    print(f"\nCible atteinte: normalised >= {target_normalised} à {focus_distance_cm}cm ({distance_meters:.2f}m)")
                    break
                
            except Exception as e:
                print(f"ERREUR: {e}")
                continue
    
    # Continuer au-delà de 2000 cm si la cible n'est pas atteinte
    target_reached = False
    if len(lut) > 0:
        last_normalised = lut[-1]['normalised']
        if last_normalised >= target_normalised:
            target_reached = True
    
    # Déterminer le point de départ pour la continuation
    if len(lut) > 0:
        last_distance_cm = int(lut[-1]['distance_meters'] * 100)
        if last_distance_cm >= medium_range_end - 10:  # Si on est proche de 20m, continuer directement
            current_cm = last_distance_cm + 20  # Commencer 20 cm après la dernière valeur
        else:
            current_cm = medium_range_end + 1
    else:
        current_cm = medium_range_end + 1
    
    step_20cm_count = 0
    max_step_20cm_measures = 200
    
    if not target_reached and current_cm > medium_range_end:
        print(f"\nContinuation au-delà de {medium_range_end}cm à partir de {current_cm}cm...")
        print(f"\nContinuation au-delà de {medium_range_end}cm...")
        step_cm = 20  # Commencer avec pas de 20 cm
        
        while not target_reached:
            print(f"[{len(lut)+1}] Test focusDistance={current_cm}cm (pas {step_cm}cm)...", end=" ", flush=True)
            
            try:
                # Envoyer PUT /lens/focus avec focusDistance (en cm)
                payload = {"focusDistance": current_cm}
                response = controller.session.put(
                    controller.focus_endpoint,
                    json=payload,
                    timeout=10,
                    headers={'Accept': 'application/json', 'Content-Type': 'application/json'}
                )
                
                if response.status_code != 204:
                    print(f"ERREUR: Status {response.status_code}")
                    current_cm += step_cm
                    continue
                
                # Attendre que la caméra se positionne
                time.sleep(delay)
                
                # Récupérer la valeur normalised correspondante
                focus_data = controller.get_focus()
                if focus_data is None or 'normalised' not in focus_data:
                    print("ERREUR: Impossible de récupérer normalised")
                    current_cm += step_cm
                    continue
                
                normalised = focus_data.get('normalised')
                if normalised is None:
                    print("ERREUR: normalised est None")
                    current_cm += step_cm
                    continue
                
                # Calculer distance_meters = focusDistance / 100.0 (conversion cm → m)
                distance_meters = current_cm / 100.0
                
                # Stocker le couple (normalised, distance_meters)
                lut.append({
                    "normalised": float(normalised),
                    "distance_meters": distance_meters
                })
                
                print(f"OK: normalised={normalised:.4f}, distance={distance_meters:.2f}m")
                
                # Vérifier si on a atteint la cible
                if normalised >= target_normalised:
                    target_reached = True
                    print(f"\nCible atteinte: normalised >= {target_normalised} à {current_cm}cm ({distance_meters:.2f}m)")
                    break
                
                # Si on a fait plus de 200 mesures avec pas de 20 cm, passer à pas de 50 cm
                if step_cm == 20:
                    step_20cm_count += 1
                    if step_20cm_count > max_step_20cm_measures:
                        print(f"\nPlus de {max_step_20cm_measures} mesures avec pas de 20cm, passage à pas de 50cm")
                        step_cm = 50
                
                current_cm += step_cm
                
            except Exception as e:
                print(f"ERREUR: {e}")
                current_cm += step_cm
                continue
    
    # Trier la LUT par normalised croissant
    lut.sort(key=lambda x: x.get('normalised', 0.0))
    
    # Sauvegarder dans focuslut.json
    output = {
        "lut": lut,
        "version": "1.0",
        "camera_model": "Micro-Studio-Camera-4K-G2"
    }
    
    with open(output_file, 'w') as f:
        json.dump(output, f, indent=2)
    
    print()
    print(f"LUT générée avec succès: {len(lut)} entrées dans {output_file}")
    print(f"Plage normalised: {lut[0]['normalised']:.3f} à {lut[-1]['normalised']:.3f}")
    print(f"Plage distance: {lut[0]['distance_meters']:.2f}m à {lut[-1]['distance_meters']:.2f}m")


def main():
    parser = argparse.ArgumentParser(
        description="Génère une LUT focus (normalised → distance_meters)"
    )
    parser.add_argument(
        '--url',
        required=True,
        help='URL de la caméra (ex: http://camera.local)'
    )
    parser.add_argument(
        '--user',
        default='roo',
        help='Nom d\'utilisateur (défaut: roo)'
    )
    parser.add_argument(
        '--pass',
        dest='password',
        default='koko',
        help='Mot de passe (défaut: koko)'
    )
    parser.add_argument(
        '--output',
        default='focuslut.json',
        help='Fichier de sortie (défaut: focuslut.json)'
    )
    parser.add_argument(
        '--min',
        type=int,
        default=10,
        help='Distance minimale en centimètres (défaut: 10)'
    )
    parser.add_argument(
        '--max',
        type=int,
        default=2000,
        help='Distance maximale en centimètres (défaut: 2000)'
    )
    parser.add_argument(
        '--step',
        type=int,
        default=10,
        help='Pas entre les valeurs en centimètres (défaut: 10)'
    )
    parser.add_argument(
        '--delay',
        type=float,
        default=0.5,
        help='Délai d\'attente après chaque positionnement en secondes (défaut: 0.5)'
    )
    
    args = parser.parse_args()
    
    generate_focus_lut(
        camera_url=args.url,
        username=args.user,
        password=args.password,
        output_file=args.output,
        min_cm=args.min,
        max_cm=args.max,
        step_cm=args.step,
        delay=args.delay
    )


if __name__ == "__main__":
    main()

