#!/usr/bin/env python3
"""
Génère une table 3D (zoom × focus → distance) pour le focus.
Mesure tous les 5 cm de 50cm à 15m (300 mesures) pour 10 valeurs de zoom.
Total: 3000 mesures (au lieu de 46500).
"""

import json
import time
import argparse
import logging
import os
from typing import Dict, List, Optional, Tuple
from blackmagic_focus_control import BlackmagicFocusController
from slider_controller import SliderController

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def save_lut_3d(output_file: str, lut_3d: List[Dict]):
    """Sauvegarde la LUT 3D dans un fichier JSON."""
    data = {
        "lut_3d": lut_3d,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S")
    }
    with open(output_file, 'w') as f:
        json.dump(data, f, indent=2)
    logger.info(f"LUT 3D sauvegardée: {len(lut_3d)} entrées dans {output_file}")


def generate_focus_zoom_lut_3d(
    camera_url: str,
    camera_user: str,
    camera_pass: str,
    slider_ip: str,
    output_file: str = "focus_zoom_lut_3d.json"
):
    """
    Génère la table 3D focus-zoom-distance.
    
    Structure de données :
    {
        "lut_3d": [
            {
                "zoom_normalised": 0.0,
                "focus_normalised": 0.1,
                "distance_cm": 50
            },
            ...
        ]
    }
    """
    # Initialiser les contrôleurs
    camera_controller = BlackmagicFocusController(camera_url, camera_user, camera_pass)
    slider_controller = SliderController(slider_ip)
    
    if not slider_controller.is_configured():
        logger.error(f"Slider non configuré à {slider_ip}")
        return
    
    # 10 valeurs de zoom de 0.0 à 1.0
    zoom_values = [i / 9.0 for i in range(10)]  # 0.0, 0.111, 0.222, ..., 1.0
    
    # Distances de 50cm à 15m (tous les 5 cm)
    # 50, 55, 60, ..., 1500 (300 mesures au lieu de 1550)
    distances_cm = list(range(50, 1501, 5))  # Pas de 5 cm
    
    lut_3d = []
    total_measurements = len(zoom_values) * len(distances_cm)
    current_measurement = 0
    measurements_done = 0  # Compteur des mesures réellement effectuées (hors existantes)
    start_time = time.time()
    last_measurement_time = start_time
    
    # Charger la LUT existante si elle existe et déterminer où reprendre
    existing_lut: Dict[Tuple[float, float], int] = {}
    resume_zoom_idx = 0
    resume_distance_idx = 0
    
    if os.path.exists(output_file):
        try:
            with open(output_file, 'r') as f:
                data = json.load(f)
                existing_entries = data.get("lut_3d", [])
                # Créer un dictionnaire pour recherche rapide
                for entry in existing_entries:
                    zoom_norm = entry.get("zoom_normalised")
                    focus_norm = entry.get("focus_normalised")
                    distance_cm = entry.get("distance_cm")
                    if zoom_norm is not None and focus_norm is not None and distance_cm is not None:
                        key = (round(zoom_norm, 6), round(focus_norm, 6))
                        existing_lut[key] = distance_cm
                
                # Déterminer où reprendre : trouver le dernier zoom et la dernière distance mesurée
                if existing_entries:
                    # Trier par zoom puis par distance pour trouver le dernier point
                    sorted_entries = sorted(existing_entries, key=lambda e: (e.get("zoom_normalised", 0), e.get("distance_cm", 0)))
                    last_entry = sorted_entries[-1]
                    last_zoom = last_entry.get("zoom_normalised")
                    last_distance = last_entry.get("distance_cm")
                    
                    # Trouver l'index du zoom dans zoom_values
                    for idx, z in enumerate(zoom_values):
                        if abs(z - last_zoom) < 0.01:  # Tolérance pour les arrondis
                            resume_zoom_idx = idx
                            # Trouver l'index de la distance dans distances_cm
                            if last_distance in distances_cm:
                                resume_distance_idx = distances_cm.index(last_distance) + 1  # +1 pour reprendre après
                            break
                    
                    logger.info(f"LUT existante chargée: {len(existing_lut)} entrées")
                    logger.info(f"Reprise à partir de: Zoom {resume_zoom_idx + 1}/10 ({zoom_values[resume_zoom_idx]:.4f}), "
                              f"Distance {resume_distance_idx}/{len(distances_cm)} ({distances_cm[resume_distance_idx] if resume_distance_idx < len(distances_cm) else 'FIN'}cm)")
        except Exception as e:
            logger.warning(f"Impossible de charger la LUT existante: {e}")
    
    try:
        for zoom_idx, target_zoom in enumerate(zoom_values):
            # Passer les zooms déjà complétés
            if zoom_idx < resume_zoom_idx:
                logger.info(f"=== Zoom {zoom_idx + 1}/10: {target_zoom:.4f} === (DÉJÀ COMPLÉTÉ, passage...)")
                # Compter les mesures déjà faites pour ce zoom
                zoom_entries = [e for e in existing_lut.keys() if abs(e[0] - target_zoom) < 0.01]
                current_measurement += len(distances_cm)  # Toutes les distances pour ce zoom
                continue
            
            logger.info(f"=== Zoom {zoom_idx + 1}/10: {target_zoom:.4f} ===")
            
            # Contrôler le zoom via le slider
            logger.info(f"Positionnement du zoom à {target_zoom:.4f} ({target_zoom*100:.1f}%) via le slider...")
            
            # Lire la focale avant le changement pour comparaison
            zoom_data_before = camera_controller.get_zoom()
            focal_before = zoom_data_before.get("focalLength") if zoom_data_before else None
            if focal_before:
                logger.info(f"  Focale avant changement: {focal_before}mm")
            
            if not slider_controller.move_axes(zoom=target_zoom, duration=3.0, silent=True):
                logger.error(f"Échec du positionnement du zoom à {target_zoom:.4f}")
                continue
            
            logger.info(f"  Commande envoyée au slider, attente de stabilisation...")
            
            # Attendre que le zoom se stabilise et vérifier que la focale change
            # NOTE: L'API caméra retourne toujours normalised=0.0, mais la focale change bien
            # On utilise donc la valeur envoyée au slider (target_zoom) comme zoom_normalised dans la LUT
            max_attempts = 5
            focal_length = None
            previous_focal = None
            
            for attempt in range(max_attempts):
                # Attendre un peu plus longtemps au début
                wait_time = 3.0 if attempt == 0 else 1.5
                time.sleep(wait_time)
                
                # Vérifier la focale depuis l'API caméra (GET /lens/zoom)
                zoom_data = camera_controller.get_zoom()
                if not zoom_data:
                    logger.warning(f"Tentative {attempt + 1}/{max_attempts}: Impossible de lire le zoom")
                    continue
                
                focal_length = zoom_data.get("focalLength")
                if focal_length is None:
                    logger.warning(f"Tentative {attempt + 1}/{max_attempts}: Focale non disponible")
                    continue
                
                # Vérifier si la focale a changé (signe que le zoom se stabilise)
                if previous_focal is not None:
                    focal_diff = abs(focal_length - previous_focal)
                    if focal_diff < 1.0:
                        # La focale est stable (variation < 1mm)
                        logger.info(f"✓ Zoom stabilisé: focale={focal_length}mm (variation: {focal_diff:.1f}mm, tentative {attempt + 1}/{max_attempts})")
                        break
                    else:
                        logger.info(f"Tentative {attempt + 1}/{max_attempts}: Focale={focal_length}mm (variation: {focal_diff:.1f}mm, en stabilisation...)")
                else:
                    logger.info(f"Tentative {attempt + 1}/{max_attempts}: Focale={focal_length}mm (première lecture)")
                
                previous_focal = focal_length
            
            if focal_length is None:
                logger.error(f"Impossible de lire la focale depuis l'API caméra après {max_attempts} tentatives")
                continue
            
            # IMPORTANT: On utilise target_zoom (valeur envoyée au slider) comme zoom_normalised dans la LUT
            # car l'API caméra ne retourne pas correctement la valeur normalisée
            # La valeur normalisée du slider (0.0-1.0) correspond au zoom réel
            actual_zoom = target_zoom
            
            # Comparer avec la focale avant pour confirmer le changement
            if focal_before:
                focal_change = abs(focal_length - focal_before)
                logger.info(f"Zoom utilisé dans la LUT: {actual_zoom:.4f} ({actual_zoom*100:.1f}%)")
                logger.info(f"  Focale: {focal_before}mm → {focal_length}mm (changement: {focal_change:.1f}mm)")
                if focal_change < 2.0:
                    logger.warning(f"  ⚠ Changement de focale faible ({focal_change:.1f}mm), le zoom a peut-être peu changé")
            else:
                logger.info(f"Zoom utilisé dans la LUT: {actual_zoom:.4f} ({actual_zoom*100:.1f}%) - Focale: {focal_length}mm")
            
            # Réinitialiser l'index de distance pour les zooms suivants
            if zoom_idx > resume_zoom_idx:
                resume_distance_idx = 0
            
            # Pour chaque distance
            start_distance_idx = resume_distance_idx if zoom_idx == resume_zoom_idx else 0
            
            if start_distance_idx > 0:
                logger.info(f"  Reprise à partir de la distance {distances_cm[start_distance_idx]}cm ({start_distance_idx}/{len(distances_cm)})")
            
            for dist_idx, distance_cm in enumerate(distances_cm):
                # Passer les distances déjà mesurées pour ce zoom
                if zoom_idx == resume_zoom_idx and dist_idx < start_distance_idx:
                    current_measurement += 1
                    continue
                
                current_measurement += 1
                measurement_start_time = time.time()
                
                # Régler le focus avec la distance en cm
                if not camera_controller.set_focus_distance(distance_cm, silent=True):
                    logger.warning(f"  Échec du réglage du focus à {distance_cm}cm")
                    continue
                
                # Attendre que le focus se stabilise
                time.sleep(0.5)
                
                # Lire la valeur normalisée du focus
                focus_data = camera_controller.get_focus()
                if not focus_data or focus_data.get("normalised") is None:
                    logger.warning(f"  Impossible de lire le focus pour {distance_cm}cm")
                    continue
                
                focus_normalised = focus_data.get("normalised")
                
                # Vérifier si cette entrée existe déjà (avec tolérance)
                rounded_zoom = round(actual_zoom, 6)
                rounded_focus = round(focus_normalised, 6)
                existing_key = (rounded_zoom, rounded_focus)
                
                if existing_key in existing_lut:
                    # Entrée déjà existante, passer silencieusement (sauf toutes les 50 pour montrer la progression)
                    if current_measurement % 50 == 0:
                        elapsed_time = time.time() - start_time
                        progress_pct = (current_measurement / total_measurements) * 100
                        logger.info(f"  [{current_measurement}/{total_measurements} ({progress_pct:.1f}%)] "
                                  f"Zoom={actual_zoom:.4f} Distance={distance_cm}cm [EXISTANT - passage...]")
                    continue
                
                # Ajouter l'entrée
                # NOTE: zoom_normalised est la valeur normalisée lue depuis l'API caméra (GET /lens/zoom)
                # et non la valeur du moteur slider
                entry = {
                    "zoom_normalised": actual_zoom,  # Valeur normalisée depuis l'API caméra
                    "focus_normalised": focus_normalised,  # Valeur normalisée depuis l'API caméra
                    "distance_cm": distance_cm
                }
                lut_3d.append(entry)
                existing_lut[existing_key] = distance_cm
                measurements_done += 1
                
                # Calculer les statistiques de temps
                elapsed_time = time.time() - start_time
                progress_pct = (current_measurement / total_measurements) * 100
                
                # Calculer le temps moyen par mesure et estimation du temps restant
                if measurements_done > 0:
                    avg_time_per_measurement = elapsed_time / measurements_done
                    remaining_measurements = total_measurements - current_measurement
                    estimated_time_remaining = avg_time_per_measurement * remaining_measurements
                    
                    # Formater le temps restant
                    hours_remaining = int(estimated_time_remaining // 3600)
                    minutes_remaining = int((estimated_time_remaining % 3600) // 60)
                    seconds_remaining = int(estimated_time_remaining % 60)
                    
                    if hours_remaining > 0:
                        time_remaining_str = f"{hours_remaining}h {minutes_remaining}m {seconds_remaining}s"
                    elif minutes_remaining > 0:
                        time_remaining_str = f"{minutes_remaining}m {seconds_remaining}s"
                    else:
                        time_remaining_str = f"{seconds_remaining}s"
                    
                    # Vitesse de mesure
                    measurements_per_sec = 1.0 / avg_time_per_measurement if avg_time_per_measurement > 0 else 0
                else:
                    time_remaining_str = "calcul..."
                    measurements_per_sec = 0
                
                # Afficher les informations en temps réel
                elapsed_min = elapsed_time / 60
                logger.info(f"  [{current_measurement}/{total_measurements} ({progress_pct:.1f}%)] "
                          f"Zoom={actual_zoom:.4f} Focus={focus_normalised:.4f} Distance={distance_cm}cm "
                          f"| Temps: {elapsed_min:.1f}min | Restant: {time_remaining_str} | "
                          f"Vitesse: {measurements_per_sec:.2f} mesures/s | Total: {len(lut_3d)} entrées")
                
                # Sauvegarder périodiquement (toutes les 100 mesures)
                if len(lut_3d) % 100 == 0:
                    save_lut_3d(output_file, lut_3d)
                    logger.info(f"  ✓ Sauvegarde intermédiaire: {len(lut_3d)} entrées")
                
                # Petit délai pour éviter de surcharger l'API
                time.sleep(0.1)
        
        # Sauvegarde finale
        total_time = time.time() - start_time
        total_hours = int(total_time // 3600)
        total_minutes = int((total_time % 3600) // 60)
        total_seconds = int(total_time % 60)
        
        save_lut_3d(output_file, lut_3d)
        logger.info("=" * 80)
        logger.info(f"✓ Génération terminée!")
        logger.info(f"  Total d'entrées: {len(lut_3d)}")
        logger.info(f"  Mesures effectuées: {measurements_done}")
        logger.info(f"  Temps total: {total_hours}h {total_minutes}m {total_seconds}s")
        if measurements_done > 0:
            avg_time = total_time / measurements_done
            logger.info(f"  Temps moyen par mesure: {avg_time:.2f}s")
        logger.info(f"  Fichier: {output_file}")
        logger.info("=" * 80)
        
    except KeyboardInterrupt:
        total_time = time.time() - start_time
        total_hours = int(total_time // 3600)
        total_minutes = int((total_time % 3600) // 60)
        total_seconds = int(total_time % 60)
        
        logger.info("Génération interrompue par l'utilisateur")
        save_lut_3d(output_file, lut_3d)
        logger.info(f"Données sauvegardées: {len(lut_3d)} entrées")
        logger.info(f"Temps écoulé: {total_hours}h {total_minutes}m {total_seconds}s")
    except Exception as e:
        total_time = time.time() - start_time
        total_hours = int(total_time // 3600)
        total_minutes = int((total_time % 3600) // 60)
        total_seconds = int(total_time % 60)
        
        logger.error(f"Erreur lors de la génération: {e}", exc_info=True)
        save_lut_3d(output_file, lut_3d)
        logger.info(f"Données sauvegardées: {len(lut_3d)} entrées")
        logger.info(f"Temps écoulé: {total_hours}h {total_minutes}m {total_seconds}s")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Génère une table 3D focus-zoom-distance")
    parser.add_argument("--camera-url", required=True, help="URL de la caméra (ex: http://Micro-Studio-Camera-4K-G2.local)")
    parser.add_argument("--camera-user", default="roo", help="Utilisateur caméra")
    parser.add_argument("--camera-pass", default="koko", help="Mot de passe caméra")
    parser.add_argument("--slider-ip", required=True, help="IP du slider (ex: 192.168.1.37)")
    parser.add_argument("--output", default="focus_zoom_lut_3d.json", help="Fichier de sortie")
    
    args = parser.parse_args()
    
    generate_focus_zoom_lut_3d(
        args.camera_url,
        args.camera_user,
        args.camera_pass,
        args.slider_ip,
        args.output
    )

