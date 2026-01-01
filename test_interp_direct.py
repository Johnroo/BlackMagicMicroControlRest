#!/usr/bin/env python3
"""
Script de test pour l'endpoint /api/v1/interp/setpoints/direct
Génère et teste des séquences aléatoires d'interpolation sur 30 secondes.
"""

import requests
import json
import random
import time
import sys

def generate_random_sequence(num_points=None, duration=30.0):
    """
    Génère une séquence aléatoire d'interpolation.
    
    Args:
        num_points: Nombre de points (3-6). Si None, choisi aléatoirement entre 3 et 6.
        duration: Durée totale en secondes (défaut: 30.0)
    
    Returns:
        dict: Séquence au format attendu par l'API
    """
    if num_points is None:
        num_points = random.randint(3, 6)
    else:
        num_points = max(3, min(6, num_points))
    
    points = []
    axes = ['pan', 'tilt', 'zoom', 'slide']
    
    # Générer les fractions (triées)
    fractions = sorted([random.random() for _ in range(num_points)])
    # S'assurer que le premier est 0.0 et le dernier 1.0
    fractions[0] = 0.0
    fractions[-1] = 1.0
    
    for i, fraction in enumerate(fractions):
        point = {"fraction": round(fraction, 3)}
        
        # Pour chaque point, décider aléatoirement quels axes inclure
        # Le premier et dernier point incluent toujours tous les axes
        if i == 0 or i == len(fractions) - 1:
            # Premier et dernier point : tous les axes
            for axis in axes:
                point[axis] = round(random.random(), 3)
        else:
            # Points intermédiaires : 1 à 4 axes aléatoires
            num_axes = random.randint(1, len(axes))
            selected_axes = random.sample(axes, num_axes)
            for axis in selected_axes:
                point[axis] = round(random.random(), 3)
        
        points.append(point)
    
    return {
        "points": points,
        "duration": duration
    }

def send_sequence(slider_url, sequence, use_direct=True):
    """
    Envoie une séquence au slider.
    
    Args:
        slider_url: URL de base du slider (ex: "http://slider1.local")
        sequence: Séquence au format dict
        use_direct: Si True, utilise /api/v1/interp/setpoints/direct, sinon utilise l'ancien format
    
    Returns:
        tuple: (success: bool, response: dict or None, error: str or None)
    """
    try:
        if use_direct:
            url = f"{slider_url}/api/v1/interp/setpoints/direct"
        else:
            # Ancien format avec presets (nécessite de créer des presets d'abord)
            url = f"{slider_url}/api/v1/interp/setpoints"
            # Convertir le format direct en format avec presets
            # Pour l'instant, on retourne une erreur car il faudrait créer les presets
            return False, None, "Format avec presets non implémenté dans ce script"
        
        response = requests.post(
            url,
            json=sequence,
            headers={'Content-Type': 'application/json'},
            timeout=5.0
        )
        
        if response.status_code == 200:
            return True, response.json(), None
        else:
            error_msg = f"HTTP {response.status_code}: {response.text}"
            # Si l'endpoint direct n'existe pas, essayer l'ancien format
            if use_direct and response.status_code == 404:
                return False, None, f"Endpoint /api/v1/interp/setpoints/direct non disponible. Le slider doit être mis à jour avec le nouveau firmware."
            return False, None, error_msg
    except requests.exceptions.ConnectionError as e:
        return False, None, f"Connexion impossible: {e}"
    except requests.exceptions.Timeout:
        return False, None, "Timeout"
    except Exception as e:
        return False, None, f"Erreur: {e}"

def start_auto_interpolation(slider_url, duration=None):
    """
    Démarre l'interpolation automatique.
    
    Args:
        slider_url: URL de base du slider
        duration: Durée optionnelle (utilise celle de setpoints/direct si None)
    
    Returns:
        tuple: (success: bool, response: dict or None, error: str or None)
    """
    try:
        url = f"{slider_url}/api/v1/interp/auto"
        payload = {"enable": True}
        if duration is not None:
            payload["duration"] = duration
        
        response = requests.post(
            url,
            json=payload,
            headers={'Content-Type': 'application/json'},
            timeout=5.0
        )
        
        if response.status_code == 200:
            return True, response.json(), None
        else:
            error_msg = f"HTTP {response.status_code}: {response.text}"
            return False, None, error_msg
    except Exception as e:
        return False, None, f"Erreur: {e}"

def stop_auto_interpolation(slider_url):
    """
    Arrête l'interpolation automatique.
    
    Args:
        slider_url: URL de base du slider
    """
    try:
        url = f"{slider_url}/api/v1/interp/auto"
        response = requests.post(
            url,
            json={"enable": False},
            headers={'Content-Type': 'application/json'},
            timeout=5.0
        )
        return response.status_code == 200
    except:
        return False

def main():
    """Fonction principale de test."""
    # Configuration
    if len(sys.argv) > 1:
        slider_url = sys.argv[1]
    else:
        slider_url = "http://slider1.local"
    
    if len(sys.argv) > 2:
        num_sequences = int(sys.argv[2])
    else:
        num_sequences = 5
    
    duration = 30.0  # 30 secondes par séquence
    
    print(f"🧪 Test de séquences d'interpolation aléatoires")
    print(f"📍 Slider: {slider_url}")
    print(f"⏱️  Durée par séquence: {duration} secondes")
    print(f"🔄 Nombre de séquences: {num_sequences}")
    print("-" * 60)
    
    for seq_num in range(1, num_sequences + 1):
        print(f"\n📋 Séquence {seq_num}/{num_sequences}")
        
        # Générer une séquence aléatoire
        sequence = generate_random_sequence(duration=duration)
        num_points = len(sequence["points"])
        
        print(f"   Points: {num_points}")
        print(f"   Durée: {sequence['duration']}s")
        print(f"   Fractions: {[p['fraction'] for p in sequence['points']]}")
        
        # Afficher les axes pour chaque point
        for i, point in enumerate(sequence['points']):
            axes_str = ", ".join([f"{k}={v:.3f}" for k, v in point.items() if k != 'fraction'])
            print(f"   Point {i+1}: {axes_str}")
        
        # Envoyer la séquence
        print(f"\n   📤 Envoi de la séquence...")
        success, response, error = send_sequence(slider_url, sequence, use_direct=True)
        
        if not success:
            print(f"   ❌ Erreur: {error}")
            if "non disponible" in error.lower() or "preset" in error.lower():
                print(f"\n   ⚠️  Le slider semble utiliser l'ancien format.")
                print(f"   💡 Vérifiez que le firmware du slider a été mis à jour avec le nouvel endpoint.")
                print(f"   💡 L'endpoint attendu est: POST /api/v1/interp/setpoints/direct")
            continue
        
        print(f"   ✅ Séquence acceptée")
        if response:
            print(f"   📊 Réponse: {json.dumps(response, indent=2)}")
        
        # Démarrer l'interpolation automatique
        print(f"\n   ▶️  Démarrage de l'interpolation automatique...")
        success, response, error = start_auto_interpolation(slider_url)
        
        if not success:
            print(f"   ❌ Erreur: {error}")
            continue
        
        print(f"   ✅ Interpolation démarrée")
        if response:
            print(f"   📊 Réponse: {json.dumps(response, indent=2)}")
        
        # Attendre la durée de la séquence + un peu de marge
        wait_time = duration + 2.0
        print(f"\n   ⏳ Attente de {wait_time:.1f} secondes...")
        time.sleep(wait_time)
        
        # Arrêter l'interpolation
        print(f"   ⏹️  Arrêt de l'interpolation...")
        stop_auto_interpolation(slider_url)
        print(f"   ✅ Interpolation arrêtée")
        
        # Pause entre les séquences
        if seq_num < num_sequences:
            pause = 2.0
            print(f"\n   ⏸️  Pause de {pause} secondes avant la prochaine séquence...")
            time.sleep(pause)
    
    # Arrêt final de l'interpolation pour s'assurer qu'elle est désactivée
    print("\n" + "=" * 60)
    print("🛑 Arrêt final de l'interpolation...")
    stop_auto_interpolation(slider_url)
    print("✅ Interpolation désactivée")
    print("✅ Tests terminés")

if __name__ == "__main__":
    main()

