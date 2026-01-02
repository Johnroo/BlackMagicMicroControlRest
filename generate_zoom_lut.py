#!/usr/bin/env python3
"""
Script pour générer automatiquement la LUT zoom (zoom_normalised → distance_meters).
Teste 15 valeurs de zoom et utilise la LUT focus pour convertir le focus en distance.
"""

import argparse
import json
import time
import sys
from blackmagic_focus_control import BlackmagicFocusController
from focus_lut import FocusLUT
from slider_controller import SliderController


def generate_zoom_lut(
    camera_url: str,
    username: str = "roo",
    password: str = "koko",
    slider_ip: str = None,
    output_file: str = "zoomlut.json",
    num_points: int = 15,
    delay: float = 0.5,
    use_autofocus: bool = False
):
    """
    Génère une LUT en testant différentes valeurs de zoom normalised (0.0-1.0).
    Le zoom est contrôlé via le slider, puis on lit la valeur réelle depuis la caméra.
    Pour chaque zoom, lit le focus et utilise la LUT focus pour convertir en distance.
    
    Args:
        camera_url: URL de la caméra (ex: http://camera.local)
        username: Nom d'utilisateur
        password: Mot de passe
        slider_ip: IP du slider (ex: 192.168.1.37)
        output_file: Fichier de sortie pour la LUT
        num_points: Nombre de points à mesurer (défaut: 15)
        delay: Délai d'attente après chaque positionnement (secondes)
        use_autofocus: Si True, fait un autofocus avant de lire le focus pour chaque zoom
    """
    print(f"Connexion à la caméra: {camera_url}")
    controller = BlackmagicFocusController(camera_url, username, password)
    
    # Connexion au slider pour contrôler le zoom
    if slider_ip:
        print(f"Connexion au slider: {slider_ip}")
        slider_controller = SliderController(slider_ip)
        if not slider_controller.is_configured():
            print("ERREUR: Impossible de se connecter au slider")
            sys.exit(1)
        print("Slider connecté!")
    else:
        print("ERREUR: L'IP du slider est requise pour contrôler le zoom")
        sys.exit(1)
    
    # Charger la LUT focus pour convertir focus → distance
    focus_lut = FocusLUT("focuslut.json")
    if not focus_lut.lut_data:
        print("ERREUR: La LUT focus (focuslut.json) est requise pour générer la LUT zoom")
        print("Veuillez d'abord générer la LUT focus avec generate_focus_lut.py")
        sys.exit(1)
    
    # Vérifier la connexion
    zoom_data = controller.get_zoom()
    if zoom_data is None:
        print("ERREUR: Impossible de se connecter à la caméra")
        sys.exit(1)
    
    print(f"Connexion réussie!")
    print(f"LUT focus chargée: {len(focus_lut.lut_data)} entrées")
    print(f"Génération de la LUT zoom: {num_points} mesures entre zoom normalised 0.0 et 1.0")
    print(f"Fichier de sortie: {output_file}")
    print()
    print("Le zoom sera contrôlé via le slider, puis la valeur réelle sera lue depuis la caméra.")
    if use_autofocus:
        print("Mode: Autofocus activé pour chaque mesure")
    else:
        print("Mode: Lecture du focus actuel (pas d'autofocus)")
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
                    print(f"Dernière entrée: zoom_normalised={lut[-1]['zoom_normalised']:.4f}, distance={lut[-1]['distance_meters']:.2f}m")
    except FileNotFoundError:
        print("Aucune LUT existante, génération complète")
    except Exception as e:
        print(f"Erreur lors du chargement de la LUT existante: {e}, génération complète")
    
    # Générer num_points valeurs de zoom entre 0.0 et 1.0
    zoom_values = []
    for i in range(num_points):
        zoom_normalised = i / (num_points - 1) if num_points > 1 else 0.0
        zoom_values.append(zoom_normalised)
    
    # Filtrer les valeurs déjà mesurées
    existing_zooms = {point.get('zoom_normalised') for point in lut}
    zoom_values_to_test = [z for z in zoom_values if z not in existing_zooms]
    
    if not zoom_values_to_test:
        print("Toutes les valeurs de zoom ont déjà été mesurées!")
        return
    
    print(f"Points à mesurer: {len(zoom_values_to_test)}/{num_points}")
    print()
    
    for i, target_zoom in enumerate(zoom_values_to_test, 1):
        print(f"[{i}/{len(zoom_values_to_test)}] Test zoom_normalised={target_zoom:.4f}...", end=" ", flush=True)
        
        try:
            # Contrôler le zoom via le slider (zoom_motor)
            success = slider_controller.move_axes(zoom=target_zoom, duration=1.0, silent=True)
            if not success:
                print(f"ERREUR: Impossible de positionner le zoom via le slider")
                continue
            
            # Attendre que le zoom se positionne (attendre la durée du mouvement + un peu plus)
            time.sleep(1.0 + delay)  # 1.0s pour le mouvement + delay pour stabilisation
            
            # Lire la valeur de zoom réelle depuis la caméra (plusieurs tentatives)
            # On utilise la focale (focalLength) de l'API pour déterminer le zoom normalised
            actual_zoom = None
            focal_length = None
            
            # Attendre un peu plus pour que le zoom se stabilise
            time.sleep(0.5)
            
            # Plage de focales observées (sera ajustée dynamiquement si nécessaire)
            # Valeurs typiques observées : 14mm (min) à 34mm (max)
            focal_min = 14.0
            focal_max = 34.0
            
            for attempt in range(10):  # Jusqu'à 10 tentatives
                zoom_data = controller.get_zoom()
                if zoom_data is not None:
                    # Utiliser focalLength pour déterminer le zoom normalised
                    if 'focalLength' in zoom_data:
                        focal_length = zoom_data.get('focalLength')
                        if focal_length is not None:
                            focal_length = float(focal_length)
                            # Mettre à jour les limites si nécessaire
                            if focal_length < focal_min:
                                focal_min = focal_length
                            if focal_length > focal_max:
                                focal_max = focal_length
                            
                            # Calculer zoom_normalised à partir de la focale
                            if focal_max > focal_min:
                                actual_zoom = (focal_length - focal_min) / (focal_max - focal_min)
                                actual_zoom = max(0.0, min(1.0, actual_zoom))  # Clamper entre 0.0 et 1.0
                            else:
                                actual_zoom = 0.0
                            
                            # Si on a aussi normalised de l'API, l'utiliser en priorité
                            if 'normalised' in zoom_data:
                                read_zoom = zoom_data.get('normalised')
                                if read_zoom is not None and read_zoom > 0.0:
                                    actual_zoom = float(read_zoom)
                            
                            break
                time.sleep(0.3)  # Attendre un peu avant de réessayer
            
            # Si on n'a toujours pas de zoom, utiliser la valeur du slider
            if actual_zoom is None:
                slider_status = slider_controller.get_status(silent=True)
                if slider_status and 'zoom' in slider_status:
                    actual_zoom = float(slider_status.get('zoom', 0.0))
                else:
                    actual_zoom = target_zoom
            
            # Afficher la focale et le zoom calculé
            if focal_length:
                print(f"(focale: {focal_length:.1f}mm, zoom_calc: {actual_zoom:.4f})", end=" ", flush=True)
            
            # Optionnel: faire un autofocus
            # IMPORTANT: L'autofocus doit être fait APRÈS que le zoom soit positionné
            # et on doit attendre suffisamment longtemps pour que le focus se stabilise
            if use_autofocus:
                print("(autofocus...)", end=" ", flush=True)
                controller.do_autofocus(0.5, 0.5, silent=True)
                # Attendre plus longtemps après autofocus pour que le focus se stabilise
                time.sleep(3.0)  # 3 secondes pour laisser le temps à l'autofocus de se stabiliser
                
                # Vérifier que le focus a changé en relisant
                focus_after_af = controller.get_focus()
                if focus_after_af and 'normalised' in focus_after_af:
                    focus_after_af_value = focus_after_af.get('normalised')
                    if focus_after_af_value:
                        print(f"(focus après AF: {focus_after_af_value:.4f})", end=" ", flush=True)
            
            # Récupérer la valeur focus normalised correspondante
            focus_data = controller.get_focus()
            if focus_data is None or 'normalised' not in focus_data:
                print("ERREUR: Impossible de récupérer focus")
                continue
            
            focus_normalised = focus_data.get('normalised')
            if focus_normalised is None:
                print("ERREUR: focus normalised est None")
                continue
            
            # Utiliser la LUT focus pour convertir focus → distance
            distance_meters = focus_lut.normalised_to_distance(focus_normalised)
            if distance_meters is None:
                print("ERREUR: Impossible de convertir focus en distance via LUT focus")
                continue
            
            # Stocker le couple (zoom_normalised, distance_meters) avec la valeur réelle lue
            lut.append({
                "zoom_normalised": actual_zoom,
                "distance_meters": distance_meters
            })
            
            print(f"OK: zoom={actual_zoom:.4f}, focus={focus_normalised:.4f}, distance={distance_meters:.2f}m")
            
        except Exception as e:
            print(f"ERREUR: {e}")
            continue
    
    # Trier la LUT par zoom_normalised croissant
    lut.sort(key=lambda x: x.get('zoom_normalised', 0.0))
    
    # Sauvegarder dans zoomlut.json
    output = {
        "lut": lut,
        "version": "1.0",
        "camera_model": "Micro-Studio-Camera-4K-G2"
    }
    
    with open(output_file, 'w') as f:
        json.dump(output, f, indent=2)
    
    print()
    print(f"LUT zoom générée avec succès: {len(lut)} entrées dans {output_file}")
    if len(lut) > 0:
        print(f"Plage zoom_normalised: {lut[0]['zoom_normalised']:.4f} à {lut[-1]['zoom_normalised']:.4f}")
        print(f"Plage distance: {lut[0]['distance_meters']:.2f}m à {lut[-1]['distance_meters']:.2f}m")


def main():
    parser = argparse.ArgumentParser(
        description="Génère une LUT zoom (zoom_normalised → distance_meters)"
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
        '--slider-ip',
        dest='slider_ip',
        required=True,
        help='IP du slider (ex: 192.168.1.37)'
    )
    parser.add_argument(
        '--output',
        default='zoomlut.json',
        help='Fichier de sortie (défaut: zoomlut.json)'
    )
    parser.add_argument(
        '--points',
        type=int,
        default=15,
        help='Nombre de points à mesurer (défaut: 15)'
    )
    parser.add_argument(
        '--delay',
        type=float,
        default=0.5,
        help='Délai d\'attente après chaque positionnement en secondes (défaut: 0.5)'
    )
    parser.add_argument(
        '--autofocus',
        action='store_true',
        help='Faire un autofocus avant de lire le focus pour chaque zoom'
    )
    
    args = parser.parse_args()
    
    generate_zoom_lut(
        camera_url=args.url,
        username=args.user,
        password=args.password,
        slider_ip=args.slider_ip,
        output_file=args.output,
        num_points=args.points,
        delay=args.delay,
        use_autofocus=args.autofocus
    )


if __name__ == "__main__":
    main()

