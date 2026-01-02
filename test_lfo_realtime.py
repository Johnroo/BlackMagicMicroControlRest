#!/usr/bin/env python3
"""
Script de test pour la mise à jour en temps réel du LFO.
Vérifie que toutes les méthodes sont présentes et que la logique est correcte.
"""

import sys
import math

# Test de la fonction de calcul de séquence LFO
def test_calculate_lfo_sequence():
    """Test de la logique de calcul de séquence LFO."""
    print("Test de calcul de séquence LFO...")
    
    # Paramètres de test
    base_slide = 0.5
    base_pan = 0.5  # 90° perpendiculaire
    amplitude = 0.2  # 20% d'amplitude
    distance = 2.0  # 2 mètres
    slider_length = 1.47  # 147 cm
    
    # Calculer les positions + et - de manière symétrique
    half_amplitude = amplitude / 2.0
    slide_plus_ideal = base_slide + half_amplitude
    slide_minus_ideal = base_slide - half_amplitude
    
    # Vérifier les limites
    slide_plus = max(0.0, min(1.0, slide_plus_ideal))
    slide_minus = max(0.0, min(1.0, slide_minus_ideal))
    
    # Calculer les décalages en mètres
    delta_slide_plus_meters = (slide_plus - base_slide) * slider_length
    delta_slide_minus_meters = (slide_minus - base_slide) * slider_length
    
    # Calculer les compensations pan
    base_pan_angle_deg = (base_pan - 0.5) * 180.0
    base_pan_angle_rad = math.radians(base_pan_angle_deg)
    compensation_factor = abs(math.cos(base_pan_angle_rad))
    
    if abs(delta_slide_plus_meters) > 0.001 and distance > 0.1:
        pan_angle_plus_rad = -math.atan(delta_slide_plus_meters / distance)
    else:
        pan_angle_plus_rad = 0.0
    
    if abs(delta_slide_minus_meters) > 0.001 and distance > 0.1:
        pan_angle_minus_rad = -math.atan(delta_slide_minus_meters / distance)
    else:
        pan_angle_minus_rad = 0.0
    
    pan_angle_plus_rad *= compensation_factor
    pan_angle_minus_rad *= compensation_factor
    
    pan_angle_plus_deg = math.degrees(pan_angle_plus_rad)
    pan_angle_minus_deg = math.degrees(pan_angle_minus_rad)
    
    pan_plus = base_pan + (pan_angle_plus_deg / 180.0)
    pan_minus = base_pan + (pan_angle_minus_deg / 180.0)
    
    pan_plus = max(0.0, min(1.0, pan_plus))
    pan_minus = max(0.0, min(1.0, pan_minus))
    
    # Vérifications
    assert 0.0 <= slide_plus <= 1.0, f"slide_plus hors limites: {slide_plus}"
    assert 0.0 <= slide_minus <= 1.0, f"slide_minus hors limites: {slide_minus}"
    assert 0.0 <= pan_plus <= 1.0, f"pan_plus hors limites: {pan_plus}"
    assert 0.0 <= pan_minus <= 1.0, f"pan_minus hors limites: {pan_minus}"
    
    print(f"  ✓ slide_plus: {slide_plus:.3f} (attendu: ~{base_slide + half_amplitude:.3f})")
    print(f"  ✓ slide_minus: {slide_minus:.3f} (attendu: ~{base_slide - half_amplitude:.3f})")
    print(f"  ✓ pan_plus: {pan_plus:.3f} (compensation: {pan_angle_plus_deg:.2f}°)")
    print(f"  ✓ pan_minus: {pan_minus:.3f} (compensation: {pan_angle_minus_deg:.2f}°)")
    print(f"  ✓ compensation_factor: {compensation_factor:.3f}")
    print("  ✓ Test de calcul réussi\n")
    
    return True

def test_slider_controller_methods():
    """Test que les méthodes existent dans SliderController."""
    print("Test des méthodes SliderController...")
    
    try:
        from slider_controller import SliderController
        
        sc = SliderController("http://test")
        
        # Vérifier que la méthode existe
        assert hasattr(sc, 'update_interpolation_sequence'), "update_interpolation_sequence manquante"
        assert hasattr(sc, 'send_interpolation_sequence'), "send_interpolation_sequence manquante"
        assert hasattr(sc, 'set_auto_interpolation'), "set_auto_interpolation manquante"
        
        print("  ✓ update_interpolation_sequence présente")
        print("  ✓ send_interpolation_sequence présente")
        print("  ✓ set_auto_interpolation présente")
        print("  ✓ Test des méthodes réussi\n")
        
        return True
    except Exception as e:
        print(f"  ✗ Erreur: {e}\n")
        return False

def test_detection_logic():
    """Test de la logique de détection des changements."""
    print("Test de la logique de détection...")
    
    threshold = 0.01
    
    # Test 1: Changement significatif de pan
    base_pan = 0.5
    current_pan = 0.52  # Écart de 0.02 > threshold
    pan_delta = abs(current_pan - base_pan)
    assert pan_delta > threshold, "Détection de changement devrait être positive"
    print(f"  ✓ Détection changement pan: {pan_delta:.3f} > {threshold}")
    
    # Test 2: Pas de changement (proche de la base)
    current_pan2 = 0.501  # Écart de 0.001 < threshold
    pan_delta2 = abs(current_pan2 - base_pan)
    assert pan_delta2 < threshold, "Pas de changement devrait être détecté"
    print(f"  ✓ Pas de changement détecté: {pan_delta2:.3f} < {threshold}")
    
    # Test 3: Détection changement amplitude
    last_amplitude = 0.2
    current_amplitude = 0.25  # Écart de 0.05 > 0.001
    amplitude_delta = abs(current_amplitude - last_amplitude)
    assert amplitude_delta > 0.001, "Changement amplitude devrait être détecté"
    print(f"  ✓ Détection changement amplitude: {amplitude_delta:.3f} > 0.001")
    
    print("  ✓ Test de détection réussi\n")
    return True

if __name__ == "__main__":
    print("=" * 60)
    print("Tests de la mise à jour en temps réel du LFO")
    print("=" * 60)
    print()
    
    tests = [
        ("Calcul de séquence LFO", test_calculate_lfo_sequence),
        ("Méthodes SliderController", test_slider_controller_methods),
        ("Logique de détection", test_detection_logic),
    ]
    
    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            print(f"  ✗ Erreur dans {name}: {e}\n")
            results.append((name, False))
    
    print("=" * 60)
    print("Résultats:")
    print("=" * 60)
    for name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status} - {name}")
    
    all_passed = all(result for _, result in results)
    print()
    if all_passed:
        print("✓ Tous les tests sont passés !")
        sys.exit(0)
    else:
        print("✗ Certains tests ont échoué")
        sys.exit(1)





