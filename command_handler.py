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
            elif cmd_type == "adjust_param":
                return self._handle_adjust_param(main_window, cmd)
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
                
            elif param == "gain":
                main_window.send_gain_value(int(value), camera_id=cam)
            elif param == "shutter":
                main_window.send_shutter_value(int(value), camera_id=cam)
            elif param == "whiteBalance":
                main_window.send_whitebalance_value(int(value), camera_id=cam)
            elif param in ["slider_pan", "slider_tilt", "zoom_motor", "slider_slide"]:
                # ⚠️ IMPORTANT: Commandes joystick relatives (-1.0 à +1.0), PAS des positions absolues
                # Ces commandes fonctionnent exactement comme le joystick du workspace 2:
                # - Valeurs positives (0.0 à +1.0) = mouvement dans un sens
                # - Valeurs négatives (-1.0 à 0.0) = mouvement dans l'autre sens
                # - 0.0 = arrêt du mouvement (retour au centre)
                # Les commandes sont envoyées via POST /api/v1/joy (protocole joystick)
                # NE PAS mettre à jour les valeurs dans CameraData car ce sont des commandes de mouvement, pas des positions
                
                joy_value = float(value)
                if joy_value < -1.0 or joy_value > 1.0:
                    return False, f"Valeur joystick invalide: {joy_value} (doit être entre -1.0 et +1.0)"
                
                # Vérifier que le slider est configuré pour cette caméra
                slider_controller = main_window.slider_controllers.get(cam)
                if not slider_controller or not slider_controller.is_configured():
                    return False, f"Slider non configuré pour la caméra {cam}"
                
                # Envoyer UNIQUEMENT la commande joystick (mouvement relatif)
                # Ne PAS mettre à jour CameraData.slider_*_value car ce sont des positions absolues (0.0-1.0)
                # Ne PAS mettre à jour le StateStore car les positions sont mises à jour via WebSocket
                if param == "slider_pan":
                    slider_controller.send_joy_command(pan=joy_value, silent=True)
                elif param == "slider_tilt":
                    slider_controller.send_joy_command(tilt=joy_value, silent=True)
                elif param == "zoom_motor":
                    slider_controller.send_joy_command(zoom=joy_value, silent=True)
                elif param == "slider_slide":
                    slider_controller.send_joy_command(slide=joy_value, silent=True)
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
            else:
                return False, f"Paramètre non supporté pour nudge: {param} (supportés: focus uniquement). Utilisez 'adjust_param' pour iris, gain, shutter et whiteBalance."
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
    
    def _handle_adjust_param(self, main_window, cmd: dict) -> Tuple[bool, Optional[str]]:
        """Gère la commande adjust_param pour les paramètres discrets (gain, shutter, whiteBalance)."""
        cam = cmd.get("cam")
        param = cmd.get("param")
        direction = cmd.get("direction")
        
        if cam is None:
            return False, "Champ 'cam' manquant"
        if param is None:
            return False, "Champ 'param' manquant"
        if direction is None:
            return False, "Champ 'direction' manquant"
        
        if not isinstance(cam, int) or cam < 1 or cam > 8:
            return False, f"Numéro de caméra invalide: {cam}"
        
        if direction not in ["up", "down"]:
            return False, f"Direction invalide: {direction} (doit être 'up' ou 'down')"
        
        # Vérifier que la caméra est connectée
        if cam not in main_window.cameras:
            return False, f"Caméra {cam} non configurée"
        
        cam_data = main_window.cameras[cam]
        if not cam_data.connected or not cam_data.controller:
            return False, f"Caméra {cam} non connectée"
        
        try:
            if param == "gain":
                if direction == "up":
                    main_window.increment_gain(camera_id=cam)
                else:
                    main_window.decrement_gain(camera_id=cam)
            elif param == "shutter":
                if direction == "up":
                    main_window.increment_shutter(camera_id=cam)
                else:
                    main_window.decrement_shutter(camera_id=cam)
            elif param == "whiteBalance":
                if direction == "up":
                    main_window.increment_whitebalance(camera_id=cam)
                else:
                    main_window.decrement_whitebalance(camera_id=cam)
            elif param == "iris":
                if direction == "up":
                    main_window.increment_iris(camera_id=cam)
                else:
                    main_window.decrement_iris(camera_id=cam)
            elif param in ["slider_pan", "slider_tilt", "zoom_motor", "slider_slide"]:
                # ⚠️ IMPORTANT: Commandes joystick relatives (-1.0 à +1.0), PAS des positions absolues
                # Fonctionne exactement comme le joystick du workspace 2
                # "up" = mouvement positif, "down" = mouvement négatif
                slider_controller = main_window.slider_controllers.get(cam)
                if not slider_controller or not slider_controller.is_configured():
                    return False, f"Slider non configuré pour la caméra {cam}"
                
                # Valeur relative pour le joystick (impulsion de mouvement)
                joy_value = 0.1 if direction == "up" else -0.1
                
                # Envoyer UNIQUEMENT la commande joystick (mouvement relatif)
                # Ne PAS mettre à jour CameraData ou StateStore car ce sont des positions absolues
                if param == "slider_pan":
                    slider_controller.send_joy_command(pan=joy_value, silent=True)
                elif param == "slider_tilt":
                    slider_controller.send_joy_command(tilt=joy_value, silent=True)
                elif param == "zoom_motor":
                    slider_controller.send_joy_command(zoom=joy_value, silent=True)
                elif param == "slider_slide":
                    slider_controller.send_joy_command(slide=joy_value, silent=True)
            else:
                return False, f"Paramètre non supporté pour adjust_param: {param} (supportés: iris, gain, shutter, whiteBalance, slider_pan, slider_tilt, zoom_motor, slider_slide)"
            
            return True, None
        except Exception as e:
            return False, f"Erreur lors de l'ajustement du paramètre {param}: {str(e)}"

