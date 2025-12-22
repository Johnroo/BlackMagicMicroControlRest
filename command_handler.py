#!/usr/bin/env python3
"""
CommandHandler: Route les commandes Companion vers les méthodes MainWindow.
"""

import logging
from typing import Tuple, Optional

logger = logging.getLogger(__name__)


class CommandHandler:
    """Gère les commandes reçues de Companion."""
    
    def handle(self, main_window, cmd: dict) -> Tuple[bool, Optional[str]]:
        """
        Traite une commande et appelle la méthode appropriée de MainWindow.
        
        Args:
            main_window: Instance de MainWindow
            cmd: Dictionnaire contenant la commande (type "cmd", champ "cmd", etc.)
        
        Returns:
            Tuple (ok: bool, error: str | None)
        """
        cmd_type = cmd.get("cmd")
        if not cmd_type:
            return False, "Champ 'cmd' manquant"
        
        try:
            if cmd_type == "set_active_cam":
                return self._handle_set_active_cam(main_window, cmd)
            elif cmd_type == "set_param":
                return self._handle_set_param(main_window, cmd)
            elif cmd_type == "nudge":
                return self._handle_nudge(main_window, cmd)
            elif cmd_type == "recall_preset":
                return self._handle_recall_preset(main_window, cmd)
            elif cmd_type == "store_preset":
                return self._handle_store_preset(main_window, cmd)
            elif cmd_type == "do_autofocus":
                return self._handle_do_autofocus(main_window, cmd)
            elif cmd_type == "do_autowhitebalance":
                return self._handle_do_autowhitebalance(main_window, cmd)
            else:
                return False, f"Commande inconnue: {cmd_type}"
        except Exception as e:
            logger.error(f"Erreur lors du traitement de la commande {cmd_type}: {e}")
            return False, str(e)
    
    def _handle_set_active_cam(self, main_window, cmd: dict) -> Tuple[bool, Optional[str]]:
        """Gère la commande set_active_cam."""
        cam = cmd.get("cam")
        if cam is None:
            return False, "Champ 'cam' manquant"
        
        if not isinstance(cam, int) or cam < 1 or cam > 8:
            return False, f"Numéro de caméra invalide: {cam} (doit être entre 1 et 8)"
        
        try:
            main_window.switch_active_camera(cam)
            return True, None
        except Exception as e:
            return False, f"Erreur lors du changement de caméra active: {str(e)}"
    
    def _handle_set_param(self, main_window, cmd: dict) -> Tuple[bool, Optional[str]]:
        """Gère la commande set_param."""
        cam = cmd.get("cam")
        param = cmd.get("param")
        value = cmd.get("value")
        
        if cam is None:
            return False, "Champ 'cam' manquant"
        if param is None:
            return False, "Champ 'param' manquant"
        if value is None:
            return False, "Champ 'value' manquant"
        
        if not isinstance(cam, int) or cam < 1 or cam > 8:
            return False, f"Numéro de caméra invalide: {cam}"
        
        # Vérifier que la caméra est connectée
        if cam not in main_window.cameras:
            return False, f"Caméra {cam} non configurée"
        
        cam_data = main_window.cameras[cam]
        if not cam_data.connected or not cam_data.controller:
            return False, f"Caméra {cam} non connectée"
        
        try:
            if param == "focus":
                # Pour focus, il faut changer temporairement la caméra active et contourner la vérification focus_slider_user_touching
                original_active_cam = main_window.active_camera_id
                if main_window.active_camera_id != cam:
                    main_window.switch_active_camera(cam)
                
                original_touching = main_window.focus_slider_user_touching
                main_window.focus_slider_user_touching = True
                
                try:
                    # Appeler _send_focus_value_now
                    main_window._send_focus_value_now(float(value))
                finally:
                    # Remettre l'état original
                    main_window.focus_slider_user_touching = original_touching
                    # Restaurer la caméra active si nécessaire
                    if original_active_cam != cam:
                        main_window.switch_active_camera(original_active_cam)
                
            elif param == "iris":
                main_window.send_iris_value(float(value), camera_id=cam)
            elif param == "gain":
                main_window.send_gain_value(int(value), camera_id=cam)
            elif param == "shutter":
                main_window.send_shutter_value(int(value), camera_id=cam)
            elif param == "whiteBalance":
                main_window.send_whitebalance_value(int(value), camera_id=cam)
            else:
                return False, f"Paramètre inconnu: {param}"
            
            return True, None
            
        except Exception as e:
            return False, f"Erreur lors de la mise à jour du paramètre {param}: {str(e)}"
    
    def _handle_nudge(self, main_window, cmd: dict) -> Tuple[bool, Optional[str]]:
        """Gère la commande nudge."""
        cam = cmd.get("cam")
        param = cmd.get("param")
        delta = cmd.get("delta")
        
        if cam is None:
            return False, "Champ 'cam' manquant"
        if param is None:
            return False, "Champ 'param' manquant"
        if delta is None:
            return False, "Champ 'delta' manquant"
        
        if not isinstance(cam, int) or cam < 1 or cam > 8:
            return False, f"Numéro de caméra invalide: {cam}"
        
        # Vérifier que la caméra est connectée
        if cam not in main_window.cameras:
            return False, f"Caméra {cam} non configurée"
        
        cam_data = main_window.cameras[cam]
        if not cam_data.connected:
            return False, f"Caméra {cam} non connectée"
        
        try:
            # Calculer la nouvelle valeur
            if param == "focus":
                current_value = cam_data.focus_actual_value
                new_value = current_value + float(delta)
                # Clamper entre 0.0 et 1.0
                new_value = max(0.0, min(1.0, new_value))
                # Appeler set_param avec la nouvelle valeur
                return self._handle_set_param(main_window, {
                    "cmd": "set_param",
                    "cam": cam,
                    "param": "focus",
                    "value": new_value
                })
            elif param == "iris":
                current_value = cam_data.iris_actual_value
                new_value = current_value + float(delta)
                # Clamper entre 0.0 et 1.0
                new_value = max(0.0, min(1.0, new_value))
                return self._handle_set_param(main_window, {
                    "cmd": "set_param",
                    "cam": cam,
                    "param": "iris",
                    "value": new_value
                })
            elif param == "gain":
                # Pour gain, on doit utiliser les valeurs supportées
                if not cam_data.supported_gains:
                    return False, "Gains supportés non chargés pour cette caméra"
                current_value = cam_data.gain_actual_value
                new_value = current_value + int(delta)
                # Trouver la valeur supportée la plus proche
                closest = min(cam_data.supported_gains, key=lambda x: abs(x - new_value))
                return self._handle_set_param(main_window, {
                    "cmd": "set_param",
                    "cam": cam,
                    "param": "gain",
                    "value": closest
                })
            elif param == "shutter":
                # Pour shutter, on doit utiliser les valeurs supportées
                if not cam_data.supported_shutter_speeds:
                    return False, "Shutter speeds supportés non chargés pour cette caméra"
                current_value = cam_data.shutter_actual_value
                new_value = current_value + int(delta)
                # Trouver la valeur supportée la plus proche
                closest = min(cam_data.supported_shutter_speeds, key=lambda x: abs(x - new_value))
                return self._handle_set_param(main_window, {
                    "cmd": "set_param",
                    "cam": cam,
                    "param": "shutter",
                    "value": closest
                })
            elif param == "whiteBalance":
                # Pour whiteBalance, on doit utiliser les limites min/max
                if cam_data.whitebalance_min == 0 and cam_data.whitebalance_max == 0:
                    return False, "Plage white balance non chargée pour cette caméra"
                current_value = cam_data.whitebalance_actual_value if cam_data.whitebalance_actual_value > 0 else cam_data.whitebalance_sent_value
                if current_value == 0:
                    current_value = 3200  # Valeur par défaut
                new_value = current_value + int(delta)
                # Clamper entre min et max
                new_value = max(cam_data.whitebalance_min, min(cam_data.whitebalance_max, new_value))
                return self._handle_set_param(main_window, {
                    "cmd": "set_param",
                    "cam": cam,
                    "param": "whiteBalance",
                    "value": new_value
                })
            else:
                return False, f"Paramètre inconnu pour nudge: {param}"
        except Exception as e:
            return False, f"Erreur lors du nudge: {str(e)}"
    
    def _handle_recall_preset(self, main_window, cmd: dict) -> Tuple[bool, Optional[str]]:
        """Gère la commande recall_preset."""
        cam = cmd.get("cam")
        preset_number = cmd.get("preset_number")
        
        if cam is None:
            return False, "Champ 'cam' manquant"
        if preset_number is None:
            return False, "Champ 'preset_number' manquant"
        
        if not isinstance(cam, int) or cam < 1 or cam > 8:
            return False, f"Numéro de caméra invalide: {cam}"
        
        if not isinstance(preset_number, int) or preset_number < 1 or preset_number > 10:
            return False, f"Numéro de preset invalide: {preset_number} (doit être entre 1 et 10)"
        
        # Vérifier que la caméra est connectée
        if cam not in main_window.cameras:
            return False, f"Caméra {cam} non configurée"
        
        cam_data = main_window.cameras[cam]
        if not cam_data.connected or not cam_data.controller:
            return False, f"Caméra {cam} non connectée"
        
        try:
            # Changer temporairement la caméra active si nécessaire
            original_active_cam = main_window.active_camera_id
            if main_window.active_camera_id != cam:
                main_window.switch_active_camera(cam)
            
            # Appeler recall_preset
            main_window.recall_preset(preset_number)
            
            # Restaurer la caméra active si nécessaire
            if original_active_cam != cam:
                main_window.switch_active_camera(original_active_cam)
            
            return True, None
        except Exception as e:
            # Restaurer la caméra active en cas d'erreur
            if original_active_cam != cam:
                try:
                    main_window.switch_active_camera(original_active_cam)
                except:
                    pass
            return False, f"Erreur lors du rappel du preset: {str(e)}"
    
    def _handle_store_preset(self, main_window, cmd: dict) -> Tuple[bool, Optional[str]]:
        """Gère la commande store_preset."""
        cam = cmd.get("cam")
        preset_number = cmd.get("preset_number")
        
        if cam is None:
            return False, "Champ 'cam' manquant"
        if preset_number is None:
            return False, "Champ 'preset_number' manquant"
        
        if not isinstance(cam, int) or cam < 1 or cam > 8:
            return False, f"Numéro de caméra invalide: {cam}"
        
        if not isinstance(preset_number, int) or preset_number < 1 or preset_number > 10:
            return False, f"Numéro de preset invalide: {preset_number} (doit être entre 1 et 10)"
        
        # Vérifier que la caméra est connectée
        if cam not in main_window.cameras:
            return False, f"Caméra {cam} non configurée"
        
        cam_data = main_window.cameras[cam]
        if not cam_data.connected or not cam_data.controller:
            return False, f"Caméra {cam} non connectée"
        
        try:
            # Changer temporairement la caméra active si nécessaire
            original_active_cam = main_window.active_camera_id
            if main_window.active_camera_id != cam:
                main_window.switch_active_camera(cam)
            
            # Appeler save_preset
            main_window.save_preset(preset_number)
            
            # Restaurer la caméra active si nécessaire
            if original_active_cam != cam:
                main_window.switch_active_camera(original_active_cam)
            
            return True, None
        except Exception as e:
            # Restaurer la caméra active en cas d'erreur
            if original_active_cam != cam:
                try:
                    main_window.switch_active_camera(original_active_cam)
                except:
                    pass
            return False, f"Erreur lors de la sauvegarde du preset: {str(e)}"
    
    def _handle_do_autofocus(self, main_window, cmd: dict) -> Tuple[bool, Optional[str]]:
        """Gère la commande do_autofocus."""
        cam = cmd.get("cam")
        
        if cam is None:
            return False, "Champ 'cam' manquant"
        
        if not isinstance(cam, int) or cam < 1 or cam > 8:
            return False, f"Numéro de caméra invalide: {cam}"
        
        # Vérifier que la caméra est connectée
        if cam not in main_window.cameras:
            return False, f"Caméra {cam} non configurée"
        
        cam_data = main_window.cameras[cam]
        if not cam_data.connected or not cam_data.controller:
            return False, f"Caméra {cam} non connectée"
        
        try:
            # Appeler do_autofocus avec le camera_id spécifié
            main_window.do_autofocus(camera_id=cam)
            return True, None
        except Exception as e:
            return False, f"Erreur lors de l'autofocus: {str(e)}"
    
    def _handle_do_autowhitebalance(self, main_window, cmd: dict) -> Tuple[bool, Optional[str]]:
        """Gère la commande do_autowhitebalance."""
        cam = cmd.get("cam")
        
        if cam is None:
            return False, "Champ 'cam' manquant"
        
        if not isinstance(cam, int) or cam < 1 or cam > 8:
            return False, f"Numéro de caméra invalide: {cam}"
        
        # Vérifier que la caméra est connectée
        if cam not in main_window.cameras:
            return False, f"Caméra {cam} non configurée"
        
        cam_data = main_window.cameras[cam]
        if not cam_data.connected or not cam_data.controller:
            return False, f"Caméra {cam} non connectée"
        
        try:
            # Appeler do_auto_whitebalance avec le camera_id spécifié
            main_window.do_auto_whitebalance(camera_id=cam)
            return True, None
        except Exception as e:
            return False, f"Erreur lors de l'auto white balance: {str(e)}"

