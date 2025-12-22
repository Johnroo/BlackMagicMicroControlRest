#!/usr/bin/env python3
"""
Interface PySide6 pour contrôler le focus de la caméra Blackmagic.
Application standalone qui communique directement avec la caméra.
"""

import sys
import argparse
import logging
import time
import json
import os
from typing import Optional, Dict, Any
from dataclasses import dataclass, field
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QSlider, QPushButton, QLineEdit, QDialog, QGridLayout,
    QDialogButtonBox, QSizePolicy, QDoubleSpinBox
)
from PySide6.QtCore import Qt, Signal, QObject, QTimer, QEvent
from PySide6.QtGui import QResizeEvent, QKeyEvent

from blackmagic_focus_control import BlackmagicFocusController, BlackmagicWebSocketClient
from state_store import StateStore
from ws_server import CompanionWsServer
from command_handler import CommandHandler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class CameraData:
    """Données pour une caméra."""
    # Configuration
    url: str = ""
    username: str = ""
    password: str = ""
    
    # Connexions
    controller: Optional[Any] = None  # BlackmagicFocusController
    websocket_client: Optional[Any] = None  # BlackmagicWebSocketClient
    connected: bool = False
    
    # Valeurs
    focus_sent_value: float = 0.0
    focus_actual_value: float = 0.0
    iris_sent_value: float = 0.0
    iris_actual_value: float = 0.0
    gain_sent_value: int = 0
    gain_actual_value: int = 0
    shutter_sent_value: int = 0
    shutter_actual_value: int = 0
    zoom_sent_value: float = 0.0
    zoom_actual_value: float = 0.0
    
    # États des contrôles (zebra, focus assist, etc.)
    zebra_enabled: bool = False
    focusAssist_enabled: bool = False
    falseColor_enabled: bool = False
    cleanfeed_enabled: bool = False
    
    # État
    supported_gains: list = field(default_factory=list)
    supported_shutter_speeds: list = field(default_factory=list)
    initial_values_received: bool = False  # True si les valeurs initiales ont été reçues du WebSocket
    
    # Presets
    presets: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    active_preset: Optional[int] = None  # Numéro du preset actuellement actif (1-10)
    
    # Recall Scope - paramètres à exclure lors du recall (True = exclu, False = inclus)
    recall_scope: Dict[str, bool] = field(default_factory=lambda: {
        'focus': False,
        'iris': False,
        'gain': False,
        'shutter': False
    })
    
    # Crossfade duration - durée du crossfade entre presets en secondes
    crossfade_duration: float = 2.0  # Durée du crossfade en secondes (défaut: 2.0)
    
    # Throttling pour les autres paramètres
    last_iris_send_time: int = 0
    last_gain_send_time: int = 0
    last_shutter_send_time: int = 0


class CameraSignals(QObject):
    """Signaux Qt pour mettre à jour l'UI depuis les threads."""
    focus_changed = Signal(float)
    iris_changed = Signal(dict)
    gain_changed = Signal(int)
    shutter_changed = Signal(dict)
    zoom_changed = Signal(dict)
    zebra_changed = Signal(bool)
    focusAssist_changed = Signal(bool)
    falseColor_changed = Signal(bool)
    cleanfeed_changed = Signal(bool)
    websocket_status = Signal(bool, str)


class ConnectionDialog(QDialog):
    """Dialog pour la connexion à la caméra."""
    
    def __init__(self, parent=None, camera_id: int = 1, camera_url: str = "", username: str = "", password: str = "", connected: bool = False):
        super().__init__(parent)
        self.setWindowTitle(f"Paramètres de connexion - Caméra {camera_id}")
        self.setMinimumWidth(400)
        self.setModal(True)
        
        # Variables
        self.camera_id = camera_id
        self.connected = connected
        
        # Layout principal
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Titre
        title = QLabel("Connexion à la caméra")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #fff;")
        layout.addWidget(title)
        
        # Champ URL
        url_label = QLabel("URL de la caméra:")
        url_label.setStyleSheet("font-size: 12px; color: #aaa;")
        layout.addWidget(url_label)
        self.url_input = QLineEdit()
        self.url_input.setText(camera_url)
        self.url_input.setPlaceholderText("http://Micro-Studio-Camera-4K-G2.local")
        self.url_input.setStyleSheet("""
            QLineEdit {
                padding: 8px;
                background-color: #333;
                border: 1px solid #555;
                border-radius: 4px;
                color: #fff;
            }
        """)
        layout.addWidget(self.url_input)
        
        # Champ Username
        user_label = QLabel("Nom d'utilisateur:")
        user_label.setStyleSheet("font-size: 12px; color: #aaa;")
        layout.addWidget(user_label)
        self.username_input = QLineEdit()
        self.username_input.setText(username)
        self.username_input.setPlaceholderText("roo")
        self.username_input.setStyleSheet("""
            QLineEdit {
                padding: 8px;
                background-color: #333;
                border: 1px solid #555;
                border-radius: 4px;
                color: #fff;
            }
        """)
        layout.addWidget(self.username_input)
        
        # Champ Password
        pass_label = QLabel("Mot de passe:")
        pass_label.setStyleSheet("font-size: 12px; color: #aaa;")
        layout.addWidget(pass_label)
        self.password_input = QLineEdit()
        self.password_input.setText(password)
        self.password_input.setEchoMode(QLineEdit.Password)
        self.password_input.setPlaceholderText("koko")
        self.password_input.setStyleSheet("""
            QLineEdit {
                padding: 8px;
                background-color: #333;
                border: 1px solid #555;
                border-radius: 4px;
                color: #fff;
            }
        """)
        layout.addWidget(self.password_input)
        
        # Voyant de statut
        status_layout = QHBoxLayout()
        status_label = QLabel("Statut:")
        status_label.setStyleSheet("font-size: 12px; color: #aaa;")
        status_layout.addWidget(status_label)
        self.status_indicator = QLabel("●")
        self.status_indicator.setStyleSheet("font-size: 20px; color: #f00;")
        self.status_text = QLabel("Déconnecté")
        self.status_text.setStyleSheet("font-size: 12px; color: #aaa;")
        status_layout.addWidget(self.status_indicator)
        status_layout.addWidget(self.status_text)
        status_layout.addStretch()
        layout.addLayout(status_layout)
        
        # Bouton Connect/Disconnect
        self.connect_btn = QPushButton("Connecter")
        self.connect_btn.setStyleSheet("""
            QPushButton {
                padding: 10px;
                font-size: 14px;
                font-weight: bold;
                background-color: #0a5;
                color: #fff;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #0c7;
            }
        """)
        self.connect_btn.clicked.connect(self.toggle_connection)
        layout.addWidget(self.connect_btn)
        
        # Boutons de dialog
        button_box = QDialogButtonBox(QDialogButtonBox.Close)
        button_box.rejected.connect(self.accept)
        layout.addWidget(button_box)
        
        # Mettre à jour l'affichage initial
        self.update_status_display()
    
    def toggle_connection(self):
        """Émet un signal pour connecter/déconnecter."""
        if self.connected:
            # Déconnecter
            self.connected = False
            if self.parent():
                self.parent().disconnect_from_camera()
        else:
            # Connecter
            if self.parent():
                self.parent().connect_to_camera(
                    self.url_input.text().strip(),
                    self.username_input.text().strip(),
                    self.password_input.text().strip()
                )
        self.update_status_display()
    
    def update_status_display(self):
        """Met à jour l'affichage du statut."""
        if self.connected:
            self.status_indicator.setStyleSheet("font-size: 20px; color: #0f0;")
            self.status_text.setText("Connecté")
            self.connect_btn.setText("Déconnecter")
            self.connect_btn.setStyleSheet("""
                QPushButton {
                    padding: 10px;
                    font-size: 14px;
                    font-weight: bold;
                    background-color: #a50;
                    color: #fff;
                    border: none;
                    border-radius: 4px;
                }
                QPushButton:hover {
                    background-color: #c70;
                }
            """)
        else:
            self.status_indicator.setStyleSheet("font-size: 20px; color: #f00;")
            self.status_text.setText("Déconnecté")
            self.connect_btn.setText("Connecter")
            self.connect_btn.setStyleSheet("""
                QPushButton {
                    padding: 10px;
                    font-size: 14px;
                    font-weight: bold;
                    background-color: #0a5;
                    color: #fff;
                    border: none;
                    border-radius: 4px;
                }
                QPushButton:hover {
                    background-color: #0c7;
                }
            """)
    
    def set_connected(self, connected: bool):
        """Met à jour l'état de connexion."""
        self.connected = connected
        self.update_status_display()


class MainWindow(QMainWindow):
    """Fenêtre principale de l'application PySide6."""
    
    def __init__(self):
        super().__init__()
        self.signals = CameraSignals()
        
        # StateStore pour Companion
        self.state_store = StateStore()
        
        # Companion WebSocket Server
        self.companion_server = CompanionWsServer(self.state_store)
        self.companion_server.command_received.connect(self._handle_companion_command)
        self.companion_server.start(8765)
        
        # CommandHandler pour traiter les commandes Companion
        self.command_handler = CommandHandler()
        
        # Variables de connexion (remplacées par cameras dict)
        self.cameras: Dict[int, CameraData] = {}
        self.active_camera_id: int = 1
        
        # Variables pour le throttling (les timestamps sont maintenant dans CameraData)
        self.OTHER_MIN_INTERVAL = 500  # ms
        
        # Variables pour le slider focus
        self.focus_slider_user_touching = False  # True seulement quand l'utilisateur touche physiquement le slider
        self.focus_send_sequence = 0  # Compteur pour annuler les envois différés
        self.focus_sending = False  # True pendant qu'une requête PUT est en cours ou en attente de délai
        self.focus_keyboard_adjusting = False  # True quand on ajuste avec les flèches clavier
        
        # Variables pour le slider iris
        self.iris_slider_user_touching = False  # True seulement quand l'utilisateur touche physiquement le slider
        self.iris_sending = False  # True pendant qu'une requête PUT est en cours ou en attente de délai
        
        # Variables pour la répétition des touches flèches
        self.key_repeat_timer = None
        self.key_repeat_direction = None  # 'up' ou 'down'
        
        # File d'attente pour les valeurs clavier (pour ne pas perdre de valeurs)
        self.keyboard_focus_queue = []
        self.keyboard_focus_processing = False
        
        # Transition progressive entre presets
        self.smooth_preset_transition = False
        self.preset_transition_timer = None
        self.preset_transition_start_time = None
        self.preset_transition_start_values = {}
        self.preset_transition_target_values = {}
        
        # Recall scope checkboxes (initialisé dans create_presets_panel)
        self.recall_scope_checkboxes = {}
        
        # Charger la configuration des caméras
        self.load_cameras_config()
        
        # Initialiser l'UI
        self.init_ui()
        
        # Connecter les signaux
        self.connect_signals()
        
        # Charger les valeurs de la caméra active dans l'UI
        self._update_ui_from_camera_data(self.get_active_camera_data())
        
        # Mettre à jour l'UI du recall scope
        self.update_recall_scope_ui()
        
        # Mettre à jour l'UI du crossfade duration
        self.update_crossfade_duration_ui()
        
        # Initialiser le StateStore avec les presets existants
        for camera_id, cam_data in self.cameras.items():
            for preset_name, preset_data in cam_data.presets.items():
                self.state_store.set_preset(camera_id, preset_name, preset_data)
        
        # Initialiser active_cam dans le StateStore
        self.state_store.set_active_cam(self.active_camera_id)
        
        # Connexion automatique si la caméra active a des paramètres configurés
        cam_data = self.get_active_camera_data()
        if cam_data.url and cam_data.username and cam_data.password:
            self.connect_to_camera(self.active_camera_id, cam_data.url, cam_data.username, cam_data.password)
        
        # Détection du réveil de l'ordinateur pour reconnecter les WebSockets
        app = QApplication.instance()
        if app:
            app.applicationStateChanged.connect(self._on_application_state_changed)
        
        # Timer périodique pour vérifier l'état des WebSockets (toutes les 10 secondes)
        self.websocket_check_timer = QTimer()
        self.websocket_check_timer.timeout.connect(self._check_websockets_health)
        self.websocket_check_timer.start(10000)  # 10 secondes
    
    def load_cameras_config(self):
        """Charge la configuration des caméras depuis cameras_config.json."""
        config_file = "cameras_config.json"
        
        try:
            if os.path.exists(config_file):
                with open(config_file, 'r') as f:
                    config = json.load(f)
            else:
                # Créer une configuration par défaut
                config = {
                    "camera_1": {
                        "url": "http://Micro-Studio-Camera-4K-G2.local",
                        "username": "roo",
                        "password": "koko",
                        "presets": {}
                    }
                }
                for i in range(2, 9):
                    config[f"camera_{i}"] = {
                        "url": "",
                        "username": "",
                        "password": "",
                        "presets": {}
                    }
                config["active_camera"] = 1
            
            # Initialiser les 8 caméras
            for i in range(1, 9):
                cam_key = f"camera_{i}"
                if cam_key in config:
                    cam_config = config[cam_key]
                    # Initialiser les presets vides si absents
                    if "presets" not in cam_config:
                        cam_config["presets"] = {}
                    
                    # Charger recall_scope avec valeurs par défaut si absent
                    default_recall_scope = {
                        'focus': False,
                        'iris': False,
                        'gain': False,
                        'shutter': False
                    }
                    recall_scope = cam_config.get("recall_scope", default_recall_scope)
                    # S'assurer que tous les paramètres sont présents
                    for param in ['focus', 'iris', 'gain', 'shutter']:
                        if param not in recall_scope:
                            recall_scope[param] = False
                    
                    # Charger crossfade_duration avec valeur par défaut si absent
                    crossfade_duration = cam_config.get("crossfade_duration", 2.0)
                    
                    self.cameras[i] = CameraData(
                        url=cam_config.get("url", "").rstrip('/'),
                        username=cam_config.get("username", ""),
                        password=cam_config.get("password", ""),
                        presets=cam_config.get("presets", {}),
                        recall_scope=recall_scope,
                        crossfade_duration=float(crossfade_duration)
                    )
                else:
                    # Créer une caméra vide
                    self.cameras[i] = CameraData()
            
            # Définir la caméra active
            self.active_camera_id = config.get("active_camera", 1)
            
        except Exception as e:
            logger.error(f"Erreur lors du chargement de la configuration: {e}")
            # Initialiser avec des valeurs par défaut
            for i in range(1, 9):
                self.cameras[i] = CameraData()
            self.active_camera_id = 1
    
    def save_cameras_config(self):
        """Sauvegarde la configuration des caméras dans cameras_config.json."""
        config_file = "cameras_config.json"
        
        try:
            config = {
                "active_camera": self.active_camera_id
            }
            
            for i in range(1, 9):
                cam_data = self.cameras[i]
                config[f"camera_{i}"] = {
                    "url": cam_data.url,
                    "username": cam_data.username,
                    "password": cam_data.password,
                    "presets": cam_data.presets,
                    "recall_scope": cam_data.recall_scope,
                    "crossfade_duration": cam_data.crossfade_duration
                }
            
            with open(config_file, 'w') as f:
                json.dump(config, f, indent=2)
            
            logger.info("Configuration des caméras sauvegardée")
        except Exception as e:
            logger.error(f"Erreur lors de la sauvegarde de la configuration: {e}")
    
    def get_active_camera_data(self) -> CameraData:
        """Retourne les données de la caméra active."""
        return self.cameras.get(self.active_camera_id, CameraData())
    
    def init_ui(self):
        """Initialise l'interface utilisateur."""
        self.setWindowTitle("Contrôle Focus Blackmagic (Standalone)")
        self.setMinimumSize(1200, 700)
        
        # Activer le focus pour recevoir les événements clavier
        self.setFocusPolicy(Qt.StrongFocus)
        
        # Layout principal vertical
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # Sélecteur de caméra - 8 boutons
        camera_selector_layout = QHBoxLayout()
        camera_selector_layout.setContentsMargins(10, 5, 10, 5)
        camera_selector_layout.setSpacing(5)
        camera_label = QLabel("Caméra:")
        camera_label.setStyleSheet("font-size: 12px; color: #aaa;")
        camera_selector_layout.addWidget(camera_label)
        
        # Créer 8 boutons pour les caméras
        self.camera_buttons = []
        for i in range(1, 9):
            btn = QPushButton(str(i))
            btn.setFixedSize(35, 30)
            btn.setCheckable(True)
            if i == self.active_camera_id:
                btn.setChecked(True)
            btn.clicked.connect(lambda checked, cam_id=i: self.switch_active_camera(cam_id))
            btn.setStyleSheet("""
                QPushButton {
                    padding: 5px;
                    background-color: #333;
                    border: 1px solid #555;
                    border-radius: 4px;
                    color: #fff;
                    font-size: 12px;
                }
                QPushButton:hover {
                    border-color: #777;
                    background-color: #444;
                }
                QPushButton:checked {
                    background-color: #0066cc;
                    border-color: #0088ff;
                }
            """)
            self.camera_buttons.append(btn)
            camera_selector_layout.addWidget(btn)
        
        camera_selector_layout.addStretch()
        
        camera_selector_widget = QWidget()
        camera_selector_widget.setLayout(camera_selector_layout)
        camera_selector_widget.setStyleSheet("background-color: #1a1a1a; border-bottom: 1px solid #444;")
        main_layout.addWidget(camera_selector_widget)
        
        # Widget central avec layout horizontal
        central_widget = QWidget()
        central_layout = QHBoxLayout(central_widget)
        central_layout.setSpacing(20)
        central_layout.setContentsMargins(20, 20, 20, 20)
        
        # Appliquer le style sombre
        self.setStyleSheet("""
            QMainWindow {
                background-color: #2a2a2a;
            }
            QWidget {
                background-color: #2a2a2a;
                color: #fff;
            }
        """)
        
        # Créer les panneaux
        self.focus_panel = self.create_focus_panel()
        self.iris_panel = self.create_iris_panel()
        self.gain_panel = self.create_gain_panel()
        self.shutter_panel = self.create_shutter_panel()
        self.zoom_panel = self.create_zoom_panel()
        self.presets_panel = self.create_presets_panel()
        self.controls_panel = self.create_controls_panel()
        
        # Ajouter les panneaux au layout central
        central_layout.addWidget(self.focus_panel)
        central_layout.addWidget(self.iris_panel)
        central_layout.addWidget(self.gain_panel)
        
        # Conteneur vertical pour shutter et zoom (zoom en dessous de shutter)
        shutter_zoom_container = QWidget()
        shutter_zoom_layout = QVBoxLayout(shutter_zoom_container)
        shutter_zoom_layout.setSpacing(20)
        shutter_zoom_layout.setContentsMargins(0, 0, 0, 0)
        shutter_zoom_layout.addWidget(self.shutter_panel)
        shutter_zoom_layout.addWidget(self.zoom_panel)
        shutter_zoom_layout.addStretch()  # Pour pousser les panneaux vers le haut
        
        central_layout.addWidget(shutter_zoom_container)
        central_layout.addWidget(self.presets_panel)
        central_layout.addWidget(self.controls_panel)
        
        # Ajouter le widget central au layout principal
        main_layout.addWidget(central_widget)
        
        # Créer le widget principal et le définir comme central widget
        main_widget = QWidget()
        main_widget.setLayout(main_layout)
        self.setCentralWidget(main_widget)
        
        # Connecter le redimensionnement de la fenêtre pour adapter le slider
        # Créer un filtre d'événements pour détecter les redimensionnements
        class ResizeEventFilter(QObject):
            def __init__(self, parent, callback):
                super().__init__(parent)
                self.callback = callback
                self.last_size = None
            
            def eventFilter(self, obj, event):
                if event.type() == QEvent.Resize:
                    current_size = obj.size()
                    if self.last_size != current_size:
                        self.last_size = current_size
                        QTimer.singleShot(50, self.callback)
                return super().eventFilter(obj, event)
        
        def schedule_slider_update():
            if hasattr(self.focus_panel, 'force_slider_height'):
                self.focus_panel.force_slider_height()
            if hasattr(self.iris_panel, 'force_slider_height'):
                self.iris_panel.force_slider_height()
            if hasattr(self.gain_panel, 'force_slider_height'):
                self.gain_panel.force_slider_height()
            if hasattr(self.shutter_panel, 'force_slider_height'):
                self.shutter_panel.force_slider_height()
        
        self.resize_filter = ResizeEventFilter(self, schedule_slider_update)
        self.installEventFilter(self.resize_filter)
        
        # Bouton engrenage pour ouvrir les paramètres de connexion
        settings_btn = QPushButton("⚙️")
        settings_btn.setFixedSize(30, 30)
        settings_btn.setStyleSheet("""
            QPushButton {
                background-color: #333;
                border: 1px solid #555;
                border-radius: 4px;
                color: #fff;
                font-size: 16px;
            }
            QPushButton:hover {
                background-color: #444;
            }
        """)
        settings_btn.clicked.connect(self.open_connection_dialog)
        self.statusBar().addPermanentWidget(settings_btn)
        
        # Status bar pour afficher l'état de connexion
        self.status_label = QLabel("Initialisation...")
        self.statusBar().addWidget(self.status_label)
        self.statusBar().setStyleSheet("""
            QStatusBar {
                background-color: #1a1a1a;
                color: #aaa;
                border-top: 1px solid #444;
            }
        """)
    
    def switch_active_camera(self, camera_id: int):
        """Bascule vers la caméra spécifiée (pour l'affichage UI)."""
        if camera_id < 1 or camera_id > 8:
            logger.warning(f"ID de caméra invalide: {camera_id}")
            return
        
        self.active_camera_id = camera_id
        cam_data = self.cameras[camera_id]
        
        # Mettre à jour le StateStore
        self.state_store.set_active_cam(camera_id)
        
        # Mettre à jour le sélecteur
        # Mettre à jour les boutons de caméra
        for i, btn in enumerate(self.camera_buttons, start=1):
            btn.blockSignals(True)
            btn.setChecked(i == camera_id)
            btn.blockSignals(False)
        
        # Charger les valeurs de la caméra sélectionnée dans l'UI
        self._update_ui_from_camera_data(cam_data)
        
        # Mettre à jour l'encadré du preset actif
        self.update_preset_highlight()
        
        # Mettre à jour l'UI du recall scope
        self.update_recall_scope_ui()
        
        # Mettre à jour l'UI du crossfade duration
        self.update_crossfade_duration_ui()
        
        # Mettre à jour le status label
        if cam_data.connected:
            self.status_label.setText(f"✓ Caméra {camera_id} - Connectée à {cam_data.url}")
            self.status_label.setStyleSheet("color: #0f0;")
        else:
            if cam_data.url:
                self.status_label.setText(f"✗ Caméra {camera_id} - Déconnectée ({cam_data.url})")
            else:
                self.status_label.setText(f"✗ Caméra {camera_id} - Non configurée")
            self.status_label.setStyleSheet("color: #f00;")
        
        # Activer/désactiver les contrôles selon l'état de connexion
        self.set_controls_enabled(cam_data.connected)
        
        # Sauvegarder la caméra active dans la config
        self.save_cameras_config()
        
        logger.info(f"Caméra active changée vers {camera_id}")
    
    def _update_ui_from_camera_data(self, cam_data: CameraData):
        """Met à jour l'UI avec les données de la caméra spécifiée."""
        # Focus
        self.focus_sent_value = cam_data.focus_sent_value
        self.focus_actual_value = cam_data.focus_actual_value
        if hasattr(self, 'focus_value_sent'):
            self.focus_value_sent.setText(f"{cam_data.focus_sent_value:.3f}")
        if hasattr(self, 'focus_value_actual'):
            self.focus_value_actual.setText(f"{cam_data.focus_actual_value:.3f}")
        if hasattr(self, 'focus_slider'):
            slider_value = int(cam_data.focus_actual_value * 1000)
            self.focus_slider.blockSignals(True)
            self.focus_slider.setValue(slider_value)
            self.focus_slider.blockSignals(False)
        
        # Iris
        self.iris_sent_value = cam_data.iris_sent_value
        self.iris_actual_value = cam_data.iris_actual_value
        if hasattr(self, 'iris_value_sent'):
            self.iris_value_sent.setText(f"{cam_data.iris_sent_value:.2f}")
        if hasattr(self, 'iris_value_actual') and cam_data.iris_actual_value is not None:
            self.iris_value_actual.setText(f"{cam_data.iris_actual_value:.2f}")
        if hasattr(self, 'iris_slider') and cam_data.iris_actual_value is not None:
            # Avec setInvertedAppearance(True), conversion directe : iris 0.0 = slider 0, iris 1.0 = slider 1000
            slider_value = int(cam_data.iris_actual_value * 1000)
            self.iris_slider.blockSignals(True)
            self.iris_slider.setValue(slider_value)
            self.iris_slider.blockSignals(False)
        
        # Gain
        self.gain_sent_value = cam_data.gain_sent_value
        self.gain_actual_value = cam_data.gain_actual_value
        # TODO: Mettre à jour les widgets gain
        
        # Shutter
        self.shutter_sent_value = cam_data.shutter_sent_value
        self.shutter_actual_value = cam_data.shutter_actual_value
        # TODO: Mettre à jour les widgets shutter
        
        # Zoom
        self.zoom_sent_value = cam_data.zoom_sent_value
        self.zoom_actual_value = cam_data.zoom_actual_value
        # TODO: Mettre à jour les widgets zoom
        
        # Zebra, Focus Assist, False Color, Cleanfeed
        if hasattr(self, 'zebra_toggle'):
            self.zebra_toggle.blockSignals(True)
            self.zebra_toggle.setChecked(cam_data.zebra_enabled)
            self.zebra_toggle.setText(f"Zebra\n{'ON' if cam_data.zebra_enabled else 'OFF'}")
            self.zebra_toggle.blockSignals(False)
            self.zebra_enabled = cam_data.zebra_enabled
        
        if hasattr(self, 'focusAssist_toggle'):
            self.focusAssist_toggle.blockSignals(True)
            self.focusAssist_toggle.setChecked(cam_data.focusAssist_enabled)
            self.focusAssist_toggle.setText(f"Focus Assist\n{'ON' if cam_data.focusAssist_enabled else 'OFF'}")
            self.focusAssist_toggle.blockSignals(False)
            self.focusAssist_enabled = cam_data.focusAssist_enabled
        
        if hasattr(self, 'falseColor_toggle'):
            self.falseColor_toggle.blockSignals(True)
            self.falseColor_toggle.setChecked(cam_data.falseColor_enabled)
            self.falseColor_toggle.setText(f"False Color\n{'ON' if cam_data.falseColor_enabled else 'OFF'}")
            self.falseColor_toggle.blockSignals(False)
            self.falseColor_enabled = cam_data.falseColor_enabled
        
        if hasattr(self, 'cleanfeed_toggle'):
            self.cleanfeed_toggle.blockSignals(True)
            self.cleanfeed_toggle.setChecked(cam_data.cleanfeed_enabled)
            self.cleanfeed_toggle.setText(f"Cleanfeed\n{'ON' if cam_data.cleanfeed_enabled else 'OFF'}")
            self.cleanfeed_toggle.blockSignals(False)
            self.cleanfeed_enabled = cam_data.cleanfeed_enabled
    
    def create_focus_panel(self):
        """Crée le panneau de contrôle du focus."""
        panel = QWidget()
        panel.setFixedWidth(200)
        # Permettre au panneau de s'étirer en hauteur
        panel.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        panel.setStyleSheet("""
            QWidget {
                background-color: #1a1a1a;
                border: 1px solid #444;
                border-radius: 4px;
            }
        """)
        layout = QVBoxLayout(panel)
        layout.setSpacing(15)
        layout.setContentsMargins(30, 30, 30, 30)
        
        # Titre
        title = QLabel("Focus Control")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 16px; color: #fff; margin-bottom: 20px;")
        layout.addWidget(title, stretch=0)  # Pas de stretch pour le titre
        
        # Section d'affichage des valeurs
        focus_display = QWidget()
        focus_display_layout = QVBoxLayout(focus_display)
        focus_display_layout.setSpacing(10)
        
        self.focus_label = QLabel("Focus Normalisé")
        self.focus_label.setAlignment(Qt.AlignCenter)
        self.focus_label.setStyleSheet("font-size: 10px; color: #aaa; text-transform: uppercase;")
        focus_display_layout.addWidget(self.focus_label)
        
        # Container pour les valeurs (vertical : envoyé au-dessus de réel)
        value_container = QWidget()
        value_container.setFixedWidth(90)  # Largeur fixe pour le conteneur
        value_layout = QVBoxLayout(value_container)
        value_layout.setSpacing(5)
        value_layout.setContentsMargins(5, 0, 5, 0)
        
        # Valeur envoyée
        sent_label = QLabel("Envoyé")
        sent_label.setAlignment(Qt.AlignCenter)
        sent_label.setStyleSheet("font-size: 9px; color: #888;")
        value_layout.addWidget(sent_label)
        self.focus_value_sent = QLabel("0.00")
        self.focus_value_sent.setAlignment(Qt.AlignCenter)
        self.focus_value_sent.setStyleSheet("font-size: 12px; font-weight: bold; color: #ff0; font-family: 'Courier New';")
        value_layout.addWidget(self.focus_value_sent)
        
        # Espacement
        value_layout.addSpacing(5)
        
        # Valeur réelle
        actual_label = QLabel("Réel (GET)")
        actual_label.setAlignment(Qt.AlignCenter)
        actual_label.setStyleSheet("font-size: 9px; color: #888;")
        value_layout.addWidget(actual_label)
        self.focus_value_actual = QLabel("0.00")
        self.focus_value_actual.setAlignment(Qt.AlignCenter)
        self.focus_value_actual.setStyleSheet("font-size: 12px; font-weight: bold; color: #0ff; font-family: 'Courier New';")
        value_layout.addWidget(self.focus_value_actual)
        
        focus_display_layout.addWidget(value_container)
        layout.addWidget(focus_display, stretch=0)  # Pas de stretch pour l'affichage
        
        # Slider vertical - utiliser un layout vertical directement au lieu d'un QWidget
        # Cela permet un meilleur contrôle de l'expansion
        slider_container = QWidget()
        slider_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        slider_layout = QHBoxLayout(slider_container)
        slider_layout.setContentsMargins(0, 0, 0, 0)
        slider_layout.setSpacing(0)
        
        # Slider vertical
        self.focus_slider = QSlider(Qt.Vertical)
        self.focus_slider.setMinimum(0)
        self.focus_slider.setMaximum(1000)  # 0.001 de précision
        self.focus_slider.setValue(0)# Forcer le slider à s'étirer pour occuper tout l'espace disponible
        self.focus_slider.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        # Pas de hauteur minimale fixe - le slider doit s'étirer pour occuper tout l'espace disponible
        # Le minimum par défaut de Qt est suffisant
        self.focus_slider.setStyleSheet("""
            QSlider::groove:vertical {
                background: #333;
                width: 24px;
                border: 1px solid #555;
                border-radius: 12px;
            }
            QSlider::handle:vertical {
                background: #666;
                border: 1px solid #888;
                border-radius: 6px;
                width: 36px;
                height: 10px;
                margin: 0 -6px;
            }
            QSlider::handle:vertical:hover {
                background: #777;
            }
        """)
        
        # Labels pour le slider (1.0, 0.5, 0.0)
        slider_labels_container = QWidget()
        slider_labels_layout = QVBoxLayout(slider_labels_container)
        slider_labels_layout.setContentsMargins(10, 0, 0, 0)
        slider_labels_layout.setSpacing(0)
        
        label_1 = QLabel("1.0")
        label_1.setStyleSheet("font-size: 9px; color: #aaa;")
        slider_labels_layout.addWidget(label_1)
        
        slider_labels_layout.addStretch()
        
        label_05 = QLabel("0.5")
        label_05.setStyleSheet("font-size: 9px; color: #aaa;")
        slider_labels_layout.addWidget(label_05)
        
        slider_labels_layout.addStretch()
        
        label_0 = QLabel("0.0")
        label_0.setStyleSheet("font-size: 9px; color: #aaa;")
        slider_labels_layout.addWidget(label_0)
        
        # Le slider doit prendre toute la hauteur disponible dans le container
        slider_layout.addWidget(self.focus_slider, stretch=1)
        slider_layout.addWidget(slider_labels_container)
        slider_layout.addStretch()
        
        # Ajouter le slider container avec un stretch factor pour qu'il prenne tout l'espace disponible
        # Utiliser un stretch factor élevé pour garantir qu'il prend le maximum d'espace
        layout.addWidget(slider_container, stretch=1, alignment=Qt.AlignCenter)
        
        # Stocker slider_container pour pouvoir le forcer à une hauteur
        panel.slider_container = slider_container
        panel.focus_slider = self.focus_slider
        
        # Fonction pour forcer la hauteur du slider
        def force_slider_height():
            try:
                # Calculer la hauteur disponible de manière plus précise
                panel_height = panel.height()
                if panel_height <= 0:
                    return  # Pas encore initialisé
                
                # Obtenir les hauteurs réelles des éléments
                title = layout.itemAt(0).widget() if layout.count() > 0 else None
                focus_display = layout.itemAt(1).widget() if layout.count() > 1 else None
                
                title_height = title.height() if title else 40
                display_height = focus_display.height() if focus_display else 80
                
                # Marges du layout (top + bottom)
                layout_margins = layout.contentsMargins()
                margins_height = layout_margins.top() + layout_margins.bottom()
                
                # Espacement entre les widgets
                spacing = layout.spacing() * 2  # Espacement avant et après le slider
                
                # Calculer la hauteur disponible
                available_height = panel_height - title_height - display_height - margins_height - spacing
                
                # S'assurer qu'on a au moins une hauteur minimale raisonnable
                available_height = max(200, available_height)
                
                slider_container.setMinimumHeight(available_height)
                slider_container.setMaximumHeight(available_height)
            except Exception as e:
                pass
        
        panel.force_slider_height = force_slider_height
        
        # Appeler une première fois après que la fenêtre soit affichée
        QTimer.singleShot(100, force_slider_height)
        
        # Connecter les signaux du slider
        self.focus_slider.sliderPressed.connect(self.on_focus_slider_pressed)
        self.focus_slider.sliderReleased.connect(self.on_focus_slider_released)
        self.focus_slider.valueChanged.connect(self.on_focus_slider_value_changed)
        
        return panel
    
    def create_iris_panel(self):
        """Crée le panneau de contrôle de l'iris."""
        panel = QWidget()
        panel.setFixedWidth(200)
        panel.setStyleSheet("""
            QWidget {
                background-color: #1a1a1a;
                border: 1px solid #444;
                border-radius: 4px;
            }
        """)
        layout = QVBoxLayout(panel)
        layout.setSpacing(15)
        layout.setContentsMargins(30, 30, 30, 30)
        
        title = QLabel("Iris Control")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 20px; color: #fff;")
        layout.addWidget(title)
        
        # Section d'affichage
        iris_display = QWidget()
        iris_display_layout = QVBoxLayout(iris_display)
        iris_display_layout.setSpacing(10)
        
        iris_label = QLabel("Iris Normalisé")
        iris_label.setAlignment(Qt.AlignCenter)
        iris_label.setStyleSheet("font-size: 10px; color: #aaa; text-transform: uppercase;")
        iris_display_layout.addWidget(iris_label)
        
        # Container pour les valeurs (vertical : envoyé au-dessus de réel)
        value_container = QWidget()
        value_container.setFixedWidth(90)
        value_layout = QVBoxLayout(value_container)
        value_layout.setSpacing(5)
        value_layout.setContentsMargins(5, 0, 5, 0)
        
        # Valeur envoyée
        sent_label = QLabel("Envoyé")
        sent_label.setAlignment(Qt.AlignCenter)
        sent_label.setStyleSheet("font-size: 9px; color: #888;")
        value_layout.addWidget(sent_label)
        self.iris_value_sent = QLabel("0.00")
        self.iris_value_sent.setAlignment(Qt.AlignCenter)
        self.iris_value_sent.setStyleSheet("font-size: 12px; font-weight: bold; color: #ff0; font-family: 'Courier New';")
        value_layout.addWidget(self.iris_value_sent)
        
        # Espacement
        value_layout.addSpacing(5)
        
        # Valeur réelle
        actual_label = QLabel("Réel (GET)")
        actual_label.setAlignment(Qt.AlignCenter)
        actual_label.setStyleSheet("font-size: 9px; color: #888;")
        value_layout.addWidget(actual_label)
        self.iris_value_actual = QLabel("0.00")
        self.iris_value_actual.setAlignment(Qt.AlignCenter)
        self.iris_value_actual.setStyleSheet("font-size: 12px; font-weight: bold; color: #0ff; font-family: 'Courier New';")
        value_layout.addWidget(self.iris_value_actual)
        
        iris_display_layout.addWidget(value_container)
        
        # Aperture Stop
        aperture_label = QLabel("Aperture Stop:")
        aperture_label.setAlignment(Qt.AlignCenter)
        aperture_label.setStyleSheet("font-size: 9px; color: #888;")
        iris_display_layout.addWidget(aperture_label)
        self.iris_aperture_stop = QLabel("-")
        self.iris_aperture_stop.setAlignment(Qt.AlignCenter)
        self.iris_aperture_stop.setStyleSheet("font-size: 9px; color: #0ff; font-weight: bold;")
        iris_display_layout.addWidget(self.iris_aperture_stop)
        
        iris_display_layout.addWidget(value_container)
        
        layout.addWidget(iris_display, stretch=0)  # Pas de stretch pour l'affichage
        
        # Slider vertical
        slider_container = QWidget()
        slider_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        slider_layout = QHBoxLayout(slider_container)
        slider_layout.setContentsMargins(0, 0, 0, 0)
        slider_layout.setSpacing(0)
        
        # Slider vertical (inversé : 0 en haut, 1.0 en bas)
        self.iris_slider = QSlider(Qt.Vertical)
        self.iris_slider.setMinimum(0)
        self.iris_slider.setMaximum(1000)  # 0.001 de précision
        self.iris_slider.setValue(0)
        self.iris_slider.setInvertedAppearance(True)  # Inverser pour avoir 0 en haut, 1.0 en bas
        self.iris_slider.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.iris_slider.setStyleSheet("""
            QSlider::groove:vertical {
                background: #333;
                width: 24px;
                border: 1px solid #555;
                border-radius: 12px;
            }
            QSlider::handle:vertical {
                background: #666;
                border: 1px solid #888;
                border-radius: 6px;
                width: 36px;
                height: 10px;
                margin: 0 -6px;
            }
            QSlider::handle:vertical:hover {
                background: #777;
            }
        """)
        
        # Labels pour le slider (inversés : 0.0 en haut, 1.0 en bas)
        slider_labels_container = QWidget()
        slider_labels_layout = QVBoxLayout(slider_labels_container)
        slider_labels_layout.setContentsMargins(10, 0, 0, 0)
        slider_labels_layout.setSpacing(0)
        
        label_0 = QLabel("0.0")
        label_0.setStyleSheet("font-size: 9px; color: #aaa;")
        slider_labels_layout.addWidget(label_0)
        
        slider_labels_layout.addStretch()
        
        label_05 = QLabel("0.5")
        label_05.setStyleSheet("font-size: 9px; color: #aaa;")
        slider_labels_layout.addWidget(label_05)
        
        slider_labels_layout.addStretch()
        
        label_1 = QLabel("1.0")
        label_1.setStyleSheet("font-size: 9px; color: #aaa;")
        slider_labels_layout.addWidget(label_1)
        
        slider_layout.addWidget(self.iris_slider, stretch=1)
        slider_layout.addWidget(slider_labels_container)
        
        layout.addWidget(slider_container, stretch=1, alignment=Qt.AlignCenter)
        
        # Stocker slider_container pour pouvoir le forcer à une hauteur
        panel.slider_container = slider_container
        panel.iris_slider = self.iris_slider
        
        # Fonction pour forcer la hauteur du slider
        def force_slider_height():
            try:
                # Calculer la hauteur disponible de manière plus précise
                panel_height = panel.height()
                if panel_height <= 0:
                    return  # Pas encore initialisé
                
                # Obtenir les hauteurs réelles des éléments
                title = layout.itemAt(0).widget() if layout.count() > 0 else None
                iris_display = layout.itemAt(1).widget() if layout.count() > 1 else None
                
                title_height = title.height() if title else 40
                display_height = iris_display.height() if iris_display else 80
                
                # Marges du layout (top + bottom)
                layout_margins = layout.contentsMargins()
                margins_height = layout_margins.top() + layout_margins.bottom()
                
                # Espacement entre les widgets
                spacing = layout.spacing() * 2  # Espacement avant et après le slider
                
                # Calculer la hauteur disponible
                available_height = panel_height - title_height - display_height - margins_height - spacing
                
                # S'assurer qu'on a au moins une hauteur minimale raisonnable
                available_height = max(200, available_height)
                
                slider_container.setMinimumHeight(available_height)
                slider_container.setMaximumHeight(available_height)
            except Exception as e:
                pass
        
        panel.force_slider_height = force_slider_height
        
        # Appeler une première fois après que la fenêtre soit affichée
        QTimer.singleShot(100, force_slider_height)
        
        # Connecter les signaux du slider
        self.iris_slider.sliderPressed.connect(self.on_iris_slider_pressed)
        self.iris_slider.sliderReleased.connect(self.on_iris_slider_released)
        self.iris_slider.valueChanged.connect(self.on_iris_slider_value_changed)
        
        return panel
    
    def update_iris_value(self, value: float):
        """Met à jour la valeur de l'iris pour la caméra active (utilisé par les mises à jour WebSocket)."""
        cam_data = self.get_active_camera_data()
        value = max(0.0, min(1.0, value))
        cam_data.iris_sent_value = value
        self.iris_value_sent.setText(f"{value:.2f}")
    
    def on_iris_slider_pressed(self):
        """Appelé quand on appuie sur le slider iris."""
        cam_data = self.get_active_camera_data()
        
        # Marquer que l'utilisateur touche le slider
        self.iris_slider_user_touching = True
        
        # Lire la position actuelle du slider au moment du clic
        # Avec setInvertedAppearance(True), slider 0 est visuellement en haut, slider 1000 en bas
        # Conversion directe : slider 0 (haut) = iris 0.0, slider 1000 (bas) = iris 1.0
        current_slider_value = self.iris_slider.value()
        current_iris_value = current_slider_value / 1000.0
        
        # Mettre à jour l'affichage avec la valeur actuelle
        cam_data.iris_sent_value = current_iris_value
        self.iris_value_sent.setText(f"{current_iris_value:.2f}")
        
        # Envoyer immédiatement la valeur sur laquelle l'utilisateur a cliqué (si le verrou est ouvert)
        if not self.iris_sending:
            self._send_iris_value_now(current_iris_value)
    
    def on_iris_slider_released(self):
        """Appelé quand on relâche le slider iris."""
        cam_data = self.get_active_camera_data()
        
        # Marquer que l'utilisateur ne touche plus le slider
        self.iris_slider_user_touching = False
        
        # Remettre immédiatement le slider à la valeur réelle de l'iris
        # Avec setInvertedAppearance(True), conversion directe : iris 0.0 = slider 0, iris 1.0 = slider 1000
        if cam_data.iris_actual_value is not None:
            slider_value = int(cam_data.iris_actual_value * 1000)
            self.iris_slider.blockSignals(True)
            self.iris_slider.setValue(slider_value)
            self.iris_slider.blockSignals(False)
    
    def on_iris_slider_value_changed(self, value: int):
        """Appelé quand la valeur du slider iris change."""
        cam_data = self.get_active_camera_data()
        
        # Envoyer SEULEMENT si l'utilisateur touche physiquement le slider
        if not self.iris_slider_user_touching:
            return
        
        # L'utilisateur touche le slider, mettre à jour l'affichage
        # Avec setInvertedAppearance(True), conversion directe : slider 0 (haut) = iris 0.0, slider 1000 (bas) = iris 1.0
        iris_value = value / 1000.0
        cam_data.iris_sent_value = iris_value
        self.iris_value_sent.setText(f"{iris_value:.2f}")
        
        # Envoyer seulement si le verrou est ouvert (pas de requête en cours)
        if not self.iris_sending:
            self._send_iris_value_now(iris_value)
    
    def send_iris_value(self, value: float):
        """Envoie la valeur de l'iris directement (utilisé par Companion)."""
        cam_data = self.get_active_camera_data()
        if not cam_data.connected or not cam_data.controller:
            return
        
        try:
            success = cam_data.controller.set_iris(value, silent=True)
            if not success:
                logger.error(f"Erreur lors de l'envoi de l'iris")
        except Exception as e:
            logger.error(f"Erreur lors de l'envoi de l'iris: {e}")
    
    def _send_iris_value_now(self, value: float):
        """Envoie la valeur de l'iris à la caméra active, attend la réponse, puis 50ms avant de permettre le prochain envoi."""
        cam_data = self.get_active_camera_data()
        if not cam_data.connected or not cam_data.controller:
            return
        if not self.iris_slider_user_touching:
            self.iris_sending = False
            return
        
        self.iris_sending = True
        
        try:
            # Envoyer la requête (synchrone, attend la réponse)
            success = cam_data.controller.set_iris(value, silent=True)
            
            if not success:
                logger.error(f"Erreur lors de l'envoi de l'iris")
            
            # Attendre 50ms après la réponse avant de permettre le prochain envoi
            QTimer.singleShot(50, self._on_iris_send_complete)
            
        except Exception as e:
            logger.error(f"Erreur lors de l'envoi de l'iris: {e}")
            # En cas d'erreur, attendre quand même 50ms
            QTimer.singleShot(50, self._on_iris_send_complete)
    
    def _on_iris_send_complete(self):
        """Appelé après le délai de 50ms, lit la position actuelle du fader si l'utilisateur le touche encore."""
        self.iris_sending = False
        
        # Si l'utilisateur touche toujours le slider, lire la position actuelle et l'envoyer
        # Avec setInvertedAppearance(True), conversion directe : slider 0 (haut) = iris 0.0, slider 1000 (bas) = iris 1.0
        if self.iris_slider_user_touching:
            cam_data = self.get_active_camera_data()
            current_slider_value = self.iris_slider.value()
            current_iris_value = current_slider_value / 1000.0
            cam_data.iris_sent_value = current_iris_value
            self.iris_value_sent.setText(f"{current_iris_value:.2f}")
            self._send_iris_value_now(current_iris_value)
    
    def create_gain_panel(self):
        """Crée le panneau de contrôle du gain."""
        panel = QWidget()
        panel.setFixedWidth(200)
        panel.setStyleSheet("""
            QWidget {
                background-color: #1a1a1a;
                border: 1px solid #444;
                border-radius: 4px;
            }
        """)
        layout = QVBoxLayout(panel)
        layout.setSpacing(15)
        layout.setContentsMargins(30, 30, 30, 30)
        
        title = QLabel("Gain Control")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 20px; color: #fff;")
        layout.addWidget(title)
        
        # Section d'affichage
        gain_display = QWidget()
        gain_display_layout = QVBoxLayout(gain_display)
        gain_display_layout.setSpacing(10)
        
        gain_label = QLabel("Gain (dB)")
        gain_label.setAlignment(Qt.AlignCenter)
        gain_label.setStyleSheet("font-size: 10px; color: #aaa; text-transform: uppercase;")
        gain_display_layout.addWidget(gain_label)
        
        # Container pour les valeurs (vertical : envoyé au-dessus de réel)
        value_container = QWidget()
        value_container.setFixedWidth(90)
        value_layout = QVBoxLayout(value_container)
        value_layout.setSpacing(5)
        value_layout.setContentsMargins(5, 0, 5, 0)
        
        # Valeur envoyée
        sent_label = QLabel("Envoyé")
        sent_label.setAlignment(Qt.AlignCenter)
        sent_label.setStyleSheet("font-size: 9px; color: #888;")
        value_layout.addWidget(sent_label)
        self.gain_value_sent = QLabel("0")
        self.gain_value_sent.setAlignment(Qt.AlignCenter)
        self.gain_value_sent.setStyleSheet("font-size: 12px; font-weight: bold; color: #ff0; font-family: 'Courier New';")
        value_layout.addWidget(self.gain_value_sent)
        
        # Espacement
        value_layout.addSpacing(5)
        
        # Valeur réelle
        actual_label = QLabel("Réel (GET)")
        actual_label.setAlignment(Qt.AlignCenter)
        actual_label.setStyleSheet("font-size: 9px; color: #888;")
        value_layout.addWidget(actual_label)
        self.gain_value_actual = QLabel("0")
        self.gain_value_actual.setAlignment(Qt.AlignCenter)
        self.gain_value_actual.setStyleSheet("font-size: 12px; font-weight: bold; color: #0ff; font-family: 'Courier New';")
        value_layout.addWidget(self.gain_value_actual)
        
        gain_display_layout.addWidget(value_container)
        layout.addWidget(gain_display)
        
        # Boutons de contrôle
        buttons_container = QWidget()
        buttons_layout = QVBoxLayout(buttons_container)
        buttons_layout.setSpacing(15)
        buttons_layout.setContentsMargins(0, 30, 0, 30)
        
        self.gain_plus_btn = QPushButton("+")
        self.gain_plus_btn.setFixedSize(60, 60)
        self.gain_plus_btn.setStyleSheet("""
            QPushButton {
                font-size: 18px;
                font-weight: bold;
                border: 2px solid #555;
                background-color: #333;
                color: #fff;
                border-radius: 8px;
            }
            QPushButton:hover {
                background-color: #444;
                border-color: #777;
            }
            QPushButton:pressed {
                background-color: #555;
            }
        """)
        self.gain_plus_btn.clicked.connect(self.increment_gain)
        buttons_layout.addWidget(self.gain_plus_btn, alignment=Qt.AlignCenter)
        
        self.gain_minus_btn = QPushButton("-")
        self.gain_minus_btn.setFixedSize(60, 60)
        self.gain_minus_btn.setStyleSheet("""
            QPushButton {
                font-size: 18px;
                font-weight: bold;
                border: 2px solid #555;
                background-color: #333;
                color: #fff;
                border-radius: 8px;
            }
            QPushButton:hover {
                background-color: #444;
                border-color: #777;
            }
            QPushButton:pressed {
                background-color: #555;
            }
        """)
        self.gain_minus_btn.clicked.connect(self.decrement_gain)
        buttons_layout.addWidget(self.gain_minus_btn, alignment=Qt.AlignCenter)
        
        layout.addWidget(buttons_container)
        
        layout.addStretch()
        return panel
    
    def load_supported_gains(self, camera_id: int):
        """Charge la liste des gains supportés pour la caméra spécifiée."""
        if camera_id < 1 or camera_id > 8:
            return
        
        cam_data = self.cameras[camera_id]
        if not cam_data.controller:
            return
        try:
            gains = cam_data.controller.get_supported_gains()
            if gains:
                cam_data.supported_gains = sorted(gains)
                logger.info(f"Caméra {camera_id} - Gains supportés chargés: {cam_data.supported_gains}")
        except Exception as e:
            logger.error(f"Caméra {camera_id} - Erreur lors du chargement des gains supportés: {e}")
    
    def increment_gain(self):
        """Incrémente le gain vers la valeur suivante supportée pour la caméra active."""
        cam_data = self.get_active_camera_data()
        if not cam_data.connected or not cam_data.controller:
            return
        if not cam_data.supported_gains:
            return
        current_value = cam_data.gain_actual_value if cam_data.gain_actual_value is not None else cam_data.gain_sent_value
        try:
            current_index = cam_data.supported_gains.index(current_value)
            if current_index < len(cam_data.supported_gains) - 1:
                new_value = cam_data.supported_gains[current_index + 1]
                self.update_gain_value(new_value)
        except ValueError:
            # Valeur actuelle pas dans la liste, prendre la plus proche
            nearest = min(cam_data.supported_gains, key=lambda x: abs(x - current_value))
            nearest_index = cam_data.supported_gains.index(nearest)
            if nearest_index < len(cam_data.supported_gains) - 1:
                new_value = cam_data.supported_gains[nearest_index + 1]
                self.update_gain_value(new_value)
    
    def decrement_gain(self):
        """Décrémente le gain vers la valeur précédente supportée pour la caméra active."""
        cam_data = self.get_active_camera_data()
        if not cam_data.connected or not cam_data.controller:
            return
        if not cam_data.supported_gains:
            return
        current_value = cam_data.gain_actual_value if cam_data.gain_actual_value is not None else cam_data.gain_sent_value
        try:
            current_index = cam_data.supported_gains.index(current_value)
            if current_index > 0:
                new_value = cam_data.supported_gains[current_index - 1]
                self.update_gain_value(new_value)
        except ValueError:
            # Valeur actuelle pas dans la liste, prendre la plus proche
            nearest = min(cam_data.supported_gains, key=lambda x: abs(x - current_value))
            nearest_index = cam_data.supported_gains.index(nearest)
            if nearest_index > 0:
                new_value = cam_data.supported_gains[nearest_index - 1]
                self.update_gain_value(new_value)
    
    def update_gain_value(self, value: int):
        """Met à jour la valeur du gain pour la caméra active."""
        cam_data = self.get_active_camera_data()
        cam_data.gain_sent_value = value
        self.gain_value_sent.setText(f"{value} dB")
        self.send_gain_value(value)
    
    def send_gain_value(self, value: int):
        """Envoie la valeur du gain directement (sans throttling) pour la caméra active."""
        cam_data = self.get_active_camera_data()
        if not cam_data.connected or not cam_data.controller:
            return
        
        try:
            success = cam_data.controller.set_gain(value, silent=True)
            if not success:
                logger.error(f"Erreur lors de l'envoi du gain")
        except Exception as e:
            logger.error(f"Erreur lors de l'envoi du gain: {e}")
    
    def create_shutter_panel(self):
        """Crée le panneau de contrôle du shutter."""
        panel = QWidget()
        panel.setFixedWidth(200)
        panel.setStyleSheet("""
            QWidget {
                background-color: #1a1a1a;
                border: 1px solid #444;
                border-radius: 4px;
            }
        """)
        layout = QVBoxLayout(panel)
        layout.setSpacing(15)
        layout.setContentsMargins(30, 30, 30, 30)
        
        title = QLabel("⚡ Shutter Control")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 20px; color: #fff;")
        layout.addWidget(title)
        
        # Section d'affichage
        shutter_display = QWidget()
        shutter_display_layout = QVBoxLayout(shutter_display)
        shutter_display_layout.setSpacing(10)
        
        shutter_label = QLabel("Shutter Speed (1/Xs)")
        shutter_label.setAlignment(Qt.AlignCenter)
        shutter_label.setStyleSheet("font-size: 10px; color: #aaa; text-transform: uppercase;")
        shutter_display_layout.addWidget(shutter_label)
        
        # Container pour les valeurs (vertical : envoyé au-dessus de réel)
        value_container = QWidget()
        value_container.setFixedWidth(90)
        value_layout = QVBoxLayout(value_container)
        value_layout.setSpacing(5)
        value_layout.setContentsMargins(5, 0, 5, 0)
        
        # Valeur envoyée
        sent_label = QLabel("Envoyé")
        sent_label.setAlignment(Qt.AlignCenter)
        sent_label.setStyleSheet("font-size: 9px; color: #888;")
        value_layout.addWidget(sent_label)
        self.shutter_value_sent = QLabel("-")
        self.shutter_value_sent.setAlignment(Qt.AlignCenter)
        self.shutter_value_sent.setStyleSheet("font-size: 12px; font-weight: bold; color: #ff0; font-family: 'Courier New';")
        value_layout.addWidget(self.shutter_value_sent)
        
        # Espacement
        value_layout.addSpacing(5)
        
        # Valeur réelle
        actual_label = QLabel("Réel (GET)")
        actual_label.setAlignment(Qt.AlignCenter)
        actual_label.setStyleSheet("font-size: 9px; color: #888;")
        value_layout.addWidget(actual_label)
        self.shutter_value_actual = QLabel("-")
        self.shutter_value_actual.setAlignment(Qt.AlignCenter)
        self.shutter_value_actual.setStyleSheet("font-size: 12px; font-weight: bold; color: #0ff; font-family: 'Courier New';")
        value_layout.addWidget(self.shutter_value_actual)
        
        shutter_display_layout.addWidget(value_container)
        layout.addWidget(shutter_display)
        
        # Boutons de contrôle
        buttons_container = QWidget()
        buttons_layout = QVBoxLayout(buttons_container)
        buttons_layout.setSpacing(15)
        buttons_layout.setContentsMargins(0, 30, 0, 30)
        
        self.shutter_plus_btn = QPushButton("+")
        self.shutter_plus_btn.setFixedSize(60, 60)
        self.shutter_plus_btn.setStyleSheet("""
            QPushButton {
                font-size: 18px;
                font-weight: bold;
                border: 2px solid #555;
                background-color: #333;
                color: #fff;
                border-radius: 8px;
            }
            QPushButton:hover {
                background-color: #444;
                border-color: #777;
            }
            QPushButton:pressed {
                background-color: #555;
            }
        """)
        self.shutter_plus_btn.clicked.connect(self.increment_shutter)
        buttons_layout.addWidget(self.shutter_plus_btn, alignment=Qt.AlignCenter)
        
        self.shutter_minus_btn = QPushButton("-")
        self.shutter_minus_btn.setFixedSize(60, 60)
        self.shutter_minus_btn.setStyleSheet("""
            QPushButton {
                font-size: 18px;
                font-weight: bold;
                border: 2px solid #555;
                background-color: #333;
                color: #fff;
                border-radius: 8px;
            }
            QPushButton:hover {
                background-color: #444;
                border-color: #777;
            }
            QPushButton:pressed {
                background-color: #555;
            }
        """)
        self.shutter_minus_btn.clicked.connect(self.decrement_shutter)
        buttons_layout.addWidget(self.shutter_minus_btn, alignment=Qt.AlignCenter)
        
        layout.addWidget(buttons_container)
        
        layout.addStretch()
        return panel
    
    def load_supported_shutters(self, camera_id: int):
        """Charge la liste des vitesses de shutter supportées pour la caméra spécifiée."""
        if camera_id < 1 or camera_id > 8:
            return
        
        cam_data = self.cameras[camera_id]
        if not cam_data.controller:
            return
        try:
            shutters = cam_data.controller.get_supported_shutters()
            if shutters and 'shutterSpeeds' in shutters:
                cam_data.supported_shutter_speeds = sorted(shutters['shutterSpeeds'])
                logger.info(f"Caméra {camera_id} - Vitesses de shutter supportées chargées: {cam_data.supported_shutter_speeds}")
        except Exception as e:
            logger.error(f"Caméra {camera_id} - Erreur lors du chargement des vitesses de shutter supportées: {e}")
    
    def increment_shutter(self):
        """Incrémente le shutter vers la vitesse suivante supportée pour la caméra active."""
        cam_data = self.get_active_camera_data()
        if not cam_data.connected or not cam_data.controller:
            return
        if not cam_data.supported_shutter_speeds:
            return
        current_value = cam_data.shutter_actual_value if cam_data.shutter_actual_value is not None else cam_data.shutter_sent_value
        try:
            current_index = cam_data.supported_shutter_speeds.index(current_value)
            if current_index < len(cam_data.supported_shutter_speeds) - 1:
                new_value = cam_data.supported_shutter_speeds[current_index + 1]
                self.update_shutter_value(new_value)
        except ValueError:
            # Valeur actuelle pas dans la liste, prendre la plus proche
            nearest = min(cam_data.supported_shutter_speeds, key=lambda x: abs(x - current_value))
            nearest_index = cam_data.supported_shutter_speeds.index(nearest)
            if nearest_index < len(cam_data.supported_shutter_speeds) - 1:
                new_value = cam_data.supported_shutter_speeds[nearest_index + 1]
                self.update_shutter_value(new_value)
    
    def decrement_shutter(self):
        """Décrémente le shutter vers la vitesse précédente supportée pour la caméra active."""
        cam_data = self.get_active_camera_data()
        if not cam_data.connected or not cam_data.controller:
            return
        if not cam_data.supported_shutter_speeds:
            return
        current_value = cam_data.shutter_actual_value if cam_data.shutter_actual_value is not None else cam_data.shutter_sent_value
        try:
            current_index = cam_data.supported_shutter_speeds.index(current_value)
            if current_index > 0:
                new_value = cam_data.supported_shutter_speeds[current_index - 1]
                self.update_shutter_value(new_value)
        except ValueError:
            # Valeur actuelle pas dans la liste, prendre la plus proche
            nearest = min(cam_data.supported_shutter_speeds, key=lambda x: abs(x - current_value))
            nearest_index = cam_data.supported_shutter_speeds.index(nearest)
            if nearest_index > 0:
                new_value = cam_data.supported_shutter_speeds[nearest_index - 1]
                self.update_shutter_value(new_value)
    
    def update_shutter_value(self, value: int):
        """Met à jour la valeur du shutter pour la caméra active."""
        cam_data = self.get_active_camera_data()
        cam_data.shutter_sent_value = value
        self.shutter_value_sent.setText(f"1/{value}s")
        self.send_shutter_value(value)
    
    def send_shutter_value(self, value: int):
        """Envoie la valeur du shutter directement (sans throttling) pour la caméra active."""
        cam_data = self.get_active_camera_data()
        if not cam_data.connected or not cam_data.controller:
            return
        
        try:
            success = cam_data.controller.set_shutter(shutter_speed=value, silent=True)
            if not success:
                logger.error(f"Erreur lors de l'envoi du shutter")
        except Exception as e:
            logger.error(f"Erreur lors de l'envoi du shutter: {e}")
    
    def create_zoom_panel(self):
        """Crée le panneau d'affichage du zoom."""
        panel = QWidget()
        panel.setFixedWidth(200)
        panel.setStyleSheet("""
            QWidget {
                background-color: #1a1a1a;
                border: 1px solid #444;
                border-radius: 4px;
            }
        """)
        layout = QVBoxLayout(panel)
        layout.setSpacing(15)
        layout.setContentsMargins(30, 30, 30, 30)
        
        title = QLabel("🔍 Zoom Control")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 20px; color: #fff;")
        layout.addWidget(title)
        
        # Section d'affichage
        zoom_display = QWidget()
        zoom_display_layout = QVBoxLayout(zoom_display)
        zoom_display_layout.setSpacing(10)
        
        zoom_label = QLabel("Focale (Zoom)")
        zoom_label.setAlignment(Qt.AlignCenter)
        zoom_label.setStyleSheet("font-size: 10px; color: #aaa; text-transform: uppercase;")
        zoom_display_layout.addWidget(zoom_label)
        
        # Row pour les valeurs
        value_row = QWidget()
        value_row_layout = QHBoxLayout(value_row)
        value_row_layout.setSpacing(20)
        
        # Focale
        focal_container = QWidget()
        focal_container.setFixedWidth(90)
        focal_layout = QVBoxLayout(focal_container)
        focal_layout.setSpacing(3)
        focal_layout.setContentsMargins(5, 0, 5, 0)
        focal_label = QLabel("Focale")
        focal_label.setAlignment(Qt.AlignCenter)
        focal_label.setStyleSheet("font-size: 9px; color: #888;")
        focal_layout.addWidget(focal_label)
        self.zoom_focal_length = QLabel("-")
        self.zoom_focal_length.setAlignment(Qt.AlignCenter)
        self.zoom_focal_length.setStyleSheet("font-size: 12px; font-weight: bold; color: #0ff; font-family: 'Courier New';")
        focal_layout.addWidget(self.zoom_focal_length)
        value_row_layout.addWidget(focal_container)
        
        # Normalisé
        norm_container = QWidget()
        norm_container.setFixedWidth(90)
        norm_layout = QVBoxLayout(norm_container)
        norm_layout.setSpacing(3)
        norm_layout.setContentsMargins(5, 0, 5, 0)
        norm_label = QLabel("Normalisé")
        norm_label.setAlignment(Qt.AlignCenter)
        norm_label.setStyleSheet("font-size: 9px; color: #888;")
        norm_layout.addWidget(norm_label)
        self.zoom_normalised = QLabel("-")
        self.zoom_normalised.setAlignment(Qt.AlignCenter)
        self.zoom_normalised.setStyleSheet("font-size: 12px; font-weight: bold; color: #0ff; font-family: 'Courier New';")
        norm_layout.addWidget(self.zoom_normalised)
        value_row_layout.addWidget(norm_container)
        
        zoom_display_layout.addWidget(value_row)
        
        # Info supplémentaire
        zoom_info = QLabel("Focale en millimètres")
        zoom_info.setAlignment(Qt.AlignCenter)
        zoom_info.setStyleSheet("font-size: 9px; color: #888;")
        zoom_display_layout.addWidget(zoom_info)
        
        layout.addWidget(zoom_display)
        
        layout.addStretch()
        return panel
    
    def create_controls_panel(self):
        """Crée le panneau de contrôles."""
        panel = QWidget()
        panel.setFixedWidth(200)
        panel.setStyleSheet("""
            QWidget {
                background-color: #1a1a1a;
                border: 1px solid #444;
                border-radius: 4px;
            }
        """)
        layout = QVBoxLayout(panel)
        layout.setSpacing(15)
        layout.setContentsMargins(30, 30, 30, 30)
        
        title = QLabel("Contrôles")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 20px; color: #fff;")
        layout.addWidget(title)
        
        # Variables pour les états des toggles
        self.zebra_enabled = False
        self.focusAssist_enabled = False
        self.falseColor_enabled = False
        self.cleanfeed_enabled = False
        
        # Boutons toggle
        self.zebra_toggle = QPushButton("Zebra\nOFF")
        self.zebra_toggle.setCheckable(True)
        self.zebra_toggle.setStyleSheet("""
            QPushButton {
                width: 100%;
                padding: 8px;
                font-size: 10px;
                font-weight: bold;
                border: 2px solid #555;
                border-radius: 8px;
                background-color: #2a2a2a;
                color: #aaa;
            }
            QPushButton:checked {
                background-color: #0a5;
                color: #fff;
                border-color: #0f0;
            }
            QPushButton:hover {
                opacity: 0.8;
            }
        """)
        self.zebra_toggle.clicked.connect(self.toggle_zebra)
        layout.addWidget(self.zebra_toggle)
        
        self.focusAssist_toggle = QPushButton("Focus Assist\nOFF")
        self.focusAssist_toggle.setCheckable(True)
        self.focusAssist_toggle.setStyleSheet("""
            QPushButton {
                width: 100%;
                padding: 8px;
                font-size: 10px;
                font-weight: bold;
                border: 2px solid #555;
                border-radius: 8px;
                background-color: #2a2a2a;
                color: #aaa;
            }
            QPushButton:checked {
                background-color: #0a5;
                color: #fff;
                border-color: #0f0;
            }
            QPushButton:hover {
                opacity: 0.8;
            }
        """)
        self.focusAssist_toggle.clicked.connect(self.toggle_focus_assist)
        layout.addWidget(self.focusAssist_toggle)
        
        self.falseColor_toggle = QPushButton("False Color\nOFF")
        self.falseColor_toggle.setCheckable(True)
        self.falseColor_toggle.setStyleSheet("""
            QPushButton {
                width: 100%;
                padding: 8px;
                font-size: 10px;
                font-weight: bold;
                border: 2px solid #555;
                border-radius: 8px;
                background-color: #2a2a2a;
                color: #aaa;
            }
            QPushButton:checked {
                background-color: #0a5;
                color: #fff;
                border-color: #0f0;
            }
            QPushButton:hover {
                opacity: 0.8;
            }
        """)
        self.falseColor_toggle.clicked.connect(self.toggle_false_color)
        layout.addWidget(self.falseColor_toggle)
        
        self.cleanfeed_toggle = QPushButton("Cleanfeed\nOFF")
        self.cleanfeed_toggle.setCheckable(True)
        self.cleanfeed_toggle.setStyleSheet("""
            QPushButton {
                width: 100%;
                padding: 8px;
                font-size: 10px;
                font-weight: bold;
                border: 2px solid #555;
                border-radius: 8px;
                background-color: #2a2a2a;
                color: #aaa;
            }
            QPushButton:checked {
                background-color: #0a5;
                color: #fff;
                border-color: #0f0;
            }
            QPushButton:hover {
                opacity: 0.8;
            }
        """)
        self.cleanfeed_toggle.clicked.connect(self.toggle_cleanfeed)
        layout.addWidget(self.cleanfeed_toggle)
        
        # Bouton Autofocus
        self.autofocus_btn = QPushButton("🔍 Autofocus")
        self.autofocus_btn.setStyleSheet("""
            QPushButton {
                width: 100%;
                padding: 10px;
                font-size: 11px;
                font-weight: bold;
                border: 2px solid #555;
                border-radius: 8px;
                background-color: #333;
                color: #fff;
                margin-top: 10px;
            }
            QPushButton:hover {
                background-color: #444;
                border-color: #777;
            }
            QPushButton:pressed {
                background-color: #555;
            }
            QPushButton:disabled {
                opacity: 0.5;
            }
        """)
        self.autofocus_btn.clicked.connect(lambda: self.do_autofocus())
        layout.addWidget(self.autofocus_btn)
        
        # Bouton pour activer/désactiver la transition progressive
        self.smooth_transition_toggle = QPushButton("Transition\nProgressive\nOFF")
        self.smooth_transition_toggle.setCheckable(True)
        self.smooth_transition_toggle.setChecked(self.smooth_preset_transition)
        self.smooth_transition_toggle.setStyleSheet("""
            QPushButton {
                width: 100%;
                padding: 8px;
                font-size: 9px;
                font-weight: bold;
                border: 2px solid #555;
                border-radius: 4px;
                background-color: #2a2a2a;
                color: #aaa;
            }
            QPushButton:checked {
                background-color: #0a5;
                color: #fff;
                border-color: #0f0;
            }
            QPushButton:hover {
                opacity: 0.8;
            }
        """)
        self.smooth_transition_toggle.clicked.connect(self.toggle_smooth_transition)
        layout.addWidget(self.smooth_transition_toggle)
        
        # Section Crossfade Duration
        layout.addSpacing(20)
        crossfade_label = QLabel("Crossfade Duration (s)")
        crossfade_label.setAlignment(Qt.AlignCenter)
        crossfade_label.setStyleSheet("font-size: 12px; font-weight: bold; color: #aaa; margin-top: 10px;")
        layout.addWidget(crossfade_label)
        
        self.crossfade_duration_spinbox = QDoubleSpinBox()
        self.crossfade_duration_spinbox.setMinimum(0.0)
        self.crossfade_duration_spinbox.setMaximum(30.0)
        self.crossfade_duration_spinbox.setSingleStep(0.1)
        self.crossfade_duration_spinbox.setValue(2.0)
        self.crossfade_duration_spinbox.setDecimals(1)
        self.crossfade_duration_spinbox.setStyleSheet("""
            QDoubleSpinBox {
                padding: 6px;
                font-size: 12px;
                font-weight: bold;
                border: 1px solid #555;
                border-radius: 4px;
                background-color: #2a2a2a;
                color: #fff;
            }
            QDoubleSpinBox:hover {
                border-color: #777;
            }
            QDoubleSpinBox:focus {
                border-color: #0a5;
            }
        """)
        self.crossfade_duration_spinbox.valueChanged.connect(self.on_crossfade_duration_changed)
        layout.addWidget(self.crossfade_duration_spinbox)
        
        layout.addStretch()
        return panel
    
    def create_presets_panel(self):
        """Crée le panneau de presets."""
        panel = QWidget()
        panel.setFixedWidth(200)
        panel.setStyleSheet("""
            QWidget {
                background-color: #1a1a1a;
                border: 1px solid #444;
                border-radius: 4px;
            }
        """)
        layout = QVBoxLayout(panel)
        layout.setSpacing(15)
        layout.setContentsMargins(30, 30, 30, 30)
        
        presets_label = QLabel("Presets")
        presets_label.setAlignment(Qt.AlignCenter)
        presets_label.setStyleSheet("font-size: 20px; font-weight: bold; color: #fff;")
        layout.addWidget(presets_label)
        
        # Conteneur pour les deux colonnes
        presets_container = QHBoxLayout()
        presets_container.setSpacing(10)
        
        # Colonne Save
        save_column = QVBoxLayout()
        save_column.setSpacing(5)
        save_label = QLabel("Save")
        save_label.setAlignment(Qt.AlignCenter)
        save_label.setStyleSheet("font-size: 12px; font-weight: bold; color: #aaa;")
        save_column.addWidget(save_label)
        
        self.preset_save_buttons = []
        for i in range(1, 11):
            save_btn = QPushButton(f"{i}")
            save_btn.setStyleSheet("""
                QPushButton {
                    padding: 8px;
                    font-size: 10px;
                    font-weight: bold;
                    border: 1px solid #555;
                    border-radius: 4px;
                    background-color: #333;
                    color: #fff;
                }
                QPushButton:hover {
                    background-color: #444;
                }
                QPushButton:disabled {
                    opacity: 0.5;
                }
            """)
            save_btn.clicked.connect(lambda checked, n=i: self.save_preset(n))
            save_column.addWidget(save_btn)
            self.preset_save_buttons.append(save_btn)
        
        # Colonne Recall
        recall_column = QVBoxLayout()
        recall_column.setSpacing(5)
        recall_label = QLabel("Recall")
        recall_label.setAlignment(Qt.AlignCenter)
        recall_label.setStyleSheet("font-size: 12px; font-weight: bold; color: #aaa;")
        recall_column.addWidget(recall_label)
        
        self.preset_recall_buttons = []
        for i in range(1, 11):
            recall_btn = QPushButton(f"{i}")
            recall_btn.setStyleSheet("""
                QPushButton {
                    padding: 8px;
                    font-size: 10px;
                    font-weight: bold;
                    border: 1px solid #555;
                    border-radius: 4px;
                    background-color: #0a5;
                    color: #fff;
                }
                QPushButton:hover {
                    background-color: #0c7;
                }
                QPushButton:disabled {
                    opacity: 0.5;
                }
            """)
            recall_btn.clicked.connect(lambda checked, n=i: self.recall_preset(n))
            recall_column.addWidget(recall_btn)
            self.preset_recall_buttons.append(recall_btn)
        
        # Ajouter les deux colonnes au conteneur
        presets_container.addLayout(save_column)
        presets_container.addLayout(recall_column)
        
        layout.addLayout(presets_container)
        
        # Section Recall Scope
        layout.addSpacing(20)
        recall_scope_label = QLabel("Recall Scope")
        recall_scope_label.setAlignment(Qt.AlignCenter)
        recall_scope_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #fff; margin-top: 10px;")
        layout.addWidget(recall_scope_label)
        
        # Conteneur pour les checkboxes
        recall_scope_container = QVBoxLayout()
        recall_scope_container.setSpacing(8)
        
        # Dictionnaire pour stocker les références aux checkboxes
        self.recall_scope_checkboxes = {}
        
        # Checkbox Focus
        focus_checkbox = QPushButton("☐ Focus")
        focus_checkbox.setCheckable(True)
        focus_checkbox.setStyleSheet("""
            QPushButton {
                text-align: left;
                padding: 6px;
                font-size: 11px;
                font-weight: bold;
                border: 1px solid #555;
                border-radius: 4px;
                background-color: #2a2a2a;
                color: #aaa;
            }
            QPushButton:checked {
                background-color: #444;
                color: #fff;
            }
            QPushButton:hover {
                opacity: 0.8;
            }
        """)
        focus_checkbox.clicked.connect(lambda checked: self.on_recall_scope_changed('focus', checked))
        recall_scope_container.addWidget(focus_checkbox)
        self.recall_scope_checkboxes['focus'] = focus_checkbox
        
        # Checkbox Iris
        iris_checkbox = QPushButton("☐ Iris")
        iris_checkbox.setCheckable(True)
        iris_checkbox.setStyleSheet("""
            QPushButton {
                text-align: left;
                padding: 6px;
                font-size: 11px;
                font-weight: bold;
                border: 1px solid #555;
                border-radius: 4px;
                background-color: #2a2a2a;
                color: #aaa;
            }
            QPushButton:checked {
                background-color: #444;
                color: #fff;
            }
            QPushButton:hover {
                opacity: 0.8;
            }
        """)
        iris_checkbox.clicked.connect(lambda checked: self.on_recall_scope_changed('iris', checked))
        recall_scope_container.addWidget(iris_checkbox)
        self.recall_scope_checkboxes['iris'] = iris_checkbox
        
        # Checkbox Gain
        gain_checkbox = QPushButton("☐ Gain")
        gain_checkbox.setCheckable(True)
        gain_checkbox.setStyleSheet("""
            QPushButton {
                text-align: left;
                padding: 6px;
                font-size: 11px;
                font-weight: bold;
                border: 1px solid #555;
                border-radius: 4px;
                background-color: #2a2a2a;
                color: #aaa;
            }
            QPushButton:checked {
                background-color: #444;
                color: #fff;
            }
            QPushButton:hover {
                opacity: 0.8;
            }
        """)
        gain_checkbox.clicked.connect(lambda checked: self.on_recall_scope_changed('gain', checked))
        recall_scope_container.addWidget(gain_checkbox)
        self.recall_scope_checkboxes['gain'] = gain_checkbox
        
        # Checkbox Shutter
        shutter_checkbox = QPushButton("☐ Shutter")
        shutter_checkbox.setCheckable(True)
        shutter_checkbox.setStyleSheet("""
            QPushButton {
                text-align: left;
                padding: 6px;
                font-size: 11px;
                font-weight: bold;
                border: 1px solid #555;
                border-radius: 4px;
                background-color: #2a2a2a;
                color: #aaa;
            }
            QPushButton:checked {
                background-color: #444;
                color: #fff;
            }
            QPushButton:hover {
                opacity: 0.8;
            }
        """)
        shutter_checkbox.clicked.connect(lambda checked: self.on_recall_scope_changed('shutter', checked))
        recall_scope_container.addWidget(shutter_checkbox)
        self.recall_scope_checkboxes['shutter'] = shutter_checkbox
        
        layout.addLayout(recall_scope_container)
        
        layout.addStretch()
        return panel
    
    def toggle_zebra(self):
        """Toggle le zebra."""
        cam_data = self.get_active_camera_data()
        new_state = self.zebra_toggle.isChecked()
        cam_data.zebra_enabled = new_state
        self.zebra_enabled = new_state  # Garder pour compatibilité UI
        self.zebra_toggle.setText(f"Zebra\n{'ON' if new_state else 'OFF'}")
        self.send_zebra(new_state)
    
    def toggle_focus_assist(self):
        """Toggle le focus assist."""
        cam_data = self.get_active_camera_data()
        new_state = self.focusAssist_toggle.isChecked()
        cam_data.focusAssist_enabled = new_state
        self.focusAssist_enabled = new_state  # Garder pour compatibilité UI
        self.focusAssist_toggle.setText(f"Focus Assist\n{'ON' if new_state else 'OFF'}")
        self.send_focus_assist(new_state)
    
    def toggle_false_color(self):
        """Toggle le false color."""
        cam_data = self.get_active_camera_data()
        new_state = self.falseColor_toggle.isChecked()
        cam_data.falseColor_enabled = new_state
        self.falseColor_enabled = new_state  # Garder pour compatibilité UI
        self.falseColor_toggle.setText(f"False Color\n{'ON' if new_state else 'OFF'}")
        self.send_false_color(new_state)
    
    def toggle_cleanfeed(self):
        """Toggle le cleanfeed."""
        cam_data = self.get_active_camera_data()
        new_state = self.cleanfeed_toggle.isChecked()
        cam_data.cleanfeed_enabled = new_state
        self.cleanfeed_enabled = new_state  # Garder pour compatibilité UI
        self.cleanfeed_toggle.setText(f"Cleanfeed\n{'ON' if new_state else 'OFF'}")
        self.send_cleanfeed(new_state)
    
    def send_zebra(self, enabled: bool):
        """Envoie l'état du zebra pour la caméra active."""
        cam_data = self.get_active_camera_data()
        if not cam_data.connected or not cam_data.controller:
            return
        try:
            success = cam_data.controller.set_zebra(enabled, silent=True)
            if not success:
                # Revert on error
                cam_data.zebra_enabled = not enabled
                self.zebra_enabled = not enabled
                self.zebra_toggle.blockSignals(True)
                self.zebra_toggle.setChecked(not enabled)
                self.zebra_toggle.setText(f"Zebra\n{'ON' if not enabled else 'OFF'}")
                self.zebra_toggle.blockSignals(False)
                logger.error(f"Erreur lors de l'envoi du zebra")
            else:
                # Mettre à jour cam_data en cas de succès
                cam_data.zebra_enabled = enabled
        except Exception as e:
            # Revert on error
            cam_data.zebra_enabled = not enabled
            self.zebra_enabled = not enabled
            self.zebra_toggle.blockSignals(True)
            self.zebra_toggle.setChecked(not enabled)
            self.zebra_toggle.setText(f"Zebra: {'ON' if not enabled else 'OFF'}")
            self.zebra_toggle.blockSignals(False)
            logger.error(f"Erreur lors de l'envoi du zebra: {e}")
    
    def send_focus_assist(self, enabled: bool):
        """Envoie l'état du focus assist pour la caméra active."""
        cam_data = self.get_active_camera_data()
        if not cam_data.connected or not cam_data.controller:
            return
        try:
            success = cam_data.controller.set_focus_assist(enabled, silent=True)
            if not success:
                cam_data.focusAssist_enabled = not enabled
                self.focusAssist_enabled = not enabled
                self.focusAssist_toggle.blockSignals(True)
                self.focusAssist_toggle.setChecked(not enabled)
                self.focusAssist_toggle.setText(f"Focus Assist\n{'ON' if not enabled else 'OFF'}")
                self.focusAssist_toggle.blockSignals(False)
                logger.error(f"Erreur lors de l'envoi du focus assist")
            else:
                # Mettre à jour cam_data en cas de succès
                cam_data.focusAssist_enabled = enabled
        except Exception as e:
            cam_data.focusAssist_enabled = not enabled
            self.focusAssist_enabled = not enabled
            self.focusAssist_toggle.blockSignals(True)
            self.focusAssist_toggle.setChecked(not enabled)
            self.focusAssist_toggle.setText(f"Focus Assist: {'ON' if not enabled else 'OFF'}")
            self.focusAssist_toggle.blockSignals(False)
            logger.error(f"Erreur lors de l'envoi du focus assist: {e}")
    
    def send_false_color(self, enabled: bool):
        """Envoie l'état du false color pour la caméra active."""
        cam_data = self.get_active_camera_data()
        if not cam_data.connected or not cam_data.controller:
            return
        try:
            success = cam_data.controller.set_false_color(enabled, silent=True)
            if not success:
                cam_data.falseColor_enabled = not enabled
                self.falseColor_enabled = not enabled
                self.falseColor_toggle.blockSignals(True)
                self.falseColor_toggle.setChecked(not enabled)
                self.falseColor_toggle.setText(f"False Color\n{'ON' if not enabled else 'OFF'}")
                self.falseColor_toggle.blockSignals(False)
                logger.error(f"Erreur lors de l'envoi du false color")
            else:
                # Mettre à jour cam_data en cas de succès
                cam_data.falseColor_enabled = enabled
        except Exception as e:
            cam_data.falseColor_enabled = not enabled
            self.falseColor_enabled = not enabled
            self.falseColor_toggle.blockSignals(True)
            self.falseColor_toggle.setChecked(not enabled)
            self.falseColor_toggle.setText(f"False Color: {'ON' if not enabled else 'OFF'}")
            self.falseColor_toggle.blockSignals(False)
            logger.error(f"Erreur lors de l'envoi du false color: {e}")
    
    def send_cleanfeed(self, enabled: bool):
        """Envoie l'état du cleanfeed pour la caméra active."""
        cam_data = self.get_active_camera_data()
        if not cam_data.connected or not cam_data.controller:
            return
        try:
            success = cam_data.controller.set_cleanfeed(enabled, silent=True)
            if not success:
                cam_data.cleanfeed_enabled = not enabled
                self.cleanfeed_enabled = not enabled
                self.cleanfeed_toggle.blockSignals(True)
                self.cleanfeed_toggle.setChecked(not enabled)
                self.cleanfeed_toggle.setText(f"Cleanfeed\n{'ON' if not enabled else 'OFF'}")
                self.cleanfeed_toggle.blockSignals(False)
                logger.error(f"Erreur lors de l'envoi du cleanfeed")
            else:
                # Mettre à jour cam_data en cas de succès
                cam_data.cleanfeed_enabled = enabled
        except Exception as e:
            cam_data.cleanfeed_enabled = not enabled
            self.cleanfeed_enabled = not enabled
            self.cleanfeed_toggle.blockSignals(True)
            self.cleanfeed_toggle.setChecked(not enabled)
            self.cleanfeed_toggle.setText(f"Cleanfeed: {'ON' if not enabled else 'OFF'}")
            self.cleanfeed_toggle.blockSignals(False)
            logger.error(f"Erreur lors de l'envoi du cleanfeed: {e}")
    
    def do_autofocus(self, camera_id: Optional[int] = None):
        """Déclenche l'autofocus pour la caméra spécifiée ou la caméra active."""
        # Utiliser la caméra spécifiée ou la caméra active
        # Si camera_id est False (venant du signal clicked), le traiter comme None
        if camera_id is None or camera_id is False:
            camera_id = self.active_camera_id
        
        # Vérifier que camera_id est un entier valide
        if not isinstance(camera_id, int) or camera_id < 1 or camera_id > 8:
            logger.warning(f"ID de caméra invalide pour autofocus: {camera_id}")
            return
        
        cam_data = self.cameras[camera_id]
        if not cam_data.connected or not cam_data.controller:
            logger.warning(f"Caméra {camera_id} non connectée pour autofocus")
            return
        
        # Mettre à jour l'UI seulement si c'est la caméra active
        if camera_id == self.active_camera_id:
            self.autofocus_btn.setEnabled(False)
            self.autofocus_btn.setText("🔍 Autofocus...")
        
        try:
            success = cam_data.controller.do_autofocus(0.5, 0.5, silent=True)
            if success:
                if camera_id == self.active_camera_id:
                    self.autofocus_btn.setText("✓ Autofocus OK")
                    # Attendre un peu que l'autofocus se termine, puis récupérer la valeur normalisée
                    QTimer.singleShot(500, lambda: self._update_focus_after_autofocus(camera_id))
                    QTimer.singleShot(2000, lambda: (
                        self.autofocus_btn.setText("🔍 Autofocus"),
                        self.autofocus_btn.setEnabled(True)
                    ))
                else:
                    # Pour les caméras non actives, juste mettre à jour la valeur après un délai
                    QTimer.singleShot(500, lambda: self._update_focus_after_autofocus(camera_id))
                logger.info(f"Autofocus déclenché avec succès pour la caméra {camera_id}")
            else:
                if camera_id == self.active_camera_id:
                    self.autofocus_btn.setText("🔍 Autofocus")
                    self.autofocus_btn.setEnabled(True)
                logger.error(f"Erreur lors de l'autofocus pour la caméra {camera_id}")
        except Exception as e:
            if camera_id == self.active_camera_id:
                self.autofocus_btn.setText("🔍 Autofocus")
                self.autofocus_btn.setEnabled(True)
            logger.error(f"Erreur lors de l'autofocus pour la caméra {camera_id}: {e}")
    
    def _update_focus_after_autofocus(self, camera_id: Optional[int] = None):
        """Récupère la valeur du focus après l'autofocus et met à jour l'affichage."""
        if camera_id is None:
            camera_id = self.active_camera_id
        
        if camera_id < 1 or camera_id > 8:
            return
        
        cam_data = self.cameras[camera_id]
        if not cam_data.connected or not cam_data.controller:
            return
        try:
            focus_data = cam_data.controller.get_focus()
            if focus_data:
                # get_focus() peut retourner soit un dict avec 'normalised', soit directement un float
                if isinstance(focus_data, dict) and 'normalised' in focus_data:
                    focus_value = float(focus_data['normalised'])
                elif isinstance(focus_data, (int, float)):
                    focus_value = float(focus_data)
                else:
                    focus_value = None
                
                if focus_value is not None:
                    # Mettre à jour les données de la caméra
                    cam_data.focus_actual_value = focus_value
                    cam_data.focus_sent_value = focus_value
                    
                    # Mettre à jour le StateStore
                    self.state_store.update_cam(camera_id, focus=focus_value)
                    
                    # Mettre à jour l'UI seulement si c'est la caméra active
                    if camera_id == self.active_camera_id:
                        self.focus_value_actual.setText(f"{focus_value:.3f}")
                        self.focus_value_sent.setText(f"{focus_value:.3f}")
                        
                        # Mettre à jour le slider si l'utilisateur ne le touche pas
                        if not self.focus_slider_user_touching:
                            slider_value = int(focus_value * 1000)
                            self.focus_slider.blockSignals(True)
                            self.focus_slider.setValue(slider_value)
                            self.focus_slider.blockSignals(False)
                else:
                    logger.warning("Aucune valeur de focus récupérée après l'autofocus")
        except Exception as e:
            logger.error(f"Erreur lors de la récupération du focus après autofocus: {e}")
            logger.error(f"Erreur lors de la récupération du focus après autofocus: {e}")
    
    def connect_signals(self):
        """Connecte les signaux Qt aux slots."""
        self.signals.focus_changed.connect(self.on_focus_changed)
        self.signals.iris_changed.connect(self.on_iris_changed)
        self.signals.gain_changed.connect(self.on_gain_changed)
        self.signals.shutter_changed.connect(self.on_shutter_changed)
        self.signals.zoom_changed.connect(self.on_zoom_changed)
        self.signals.zebra_changed.connect(self.on_zebra_changed)
        self.signals.focusAssist_changed.connect(self.on_focusAssist_changed)
        self.signals.falseColor_changed.connect(self.on_falseColor_changed)
        self.signals.cleanfeed_changed.connect(self.on_cleanfeed_changed)
        # Note: websocket_status n'est plus utilisé car on utilise maintenant _handle_websocket_change avec camera_id
    
    def on_parameter_change(self, param_name: str, param_data: dict):
        """Callback appelé quand un paramètre change via WebSocket (déprécié)."""
        # Cette méthode est dépréciée car on utilise maintenant _handle_websocket_change avec camera_id
        # qui est appelée directement depuis connect_websocket
        pass
    
    def on_websocket_connection_status(self, connected: bool, message: str):
        """Callback appelé quand l'état de connexion WebSocket change (déprécié)."""
        # Cette méthode est dépréciée car on utilise maintenant connect_websocket avec camera_id
        # qui appelle directement on_websocket_status avec camera_id
        pass
    
    def open_connection_dialog(self):
        """Ouvre le dialog de connexion pour la caméra active."""
        cam_data = self.get_active_camera_data()
        dialog = ConnectionDialog(
            self,
            camera_id=self.active_camera_id,
            camera_url=cam_data.url,
            username=cam_data.username,
            password=cam_data.password,
            connected=cam_data.connected
        )
        if dialog.exec():
            # Sauvegarder la configuration
            cam_data.url = dialog.url_input.text().rstrip('/')
            cam_data.username = dialog.username_input.text()
            cam_data.password = dialog.password_input.text()
            
            # Sauvegarder dans le fichier
            self.save_cameras_config()
            
            # Optionnel: se connecter si demandé
            if dialog.connected and dialog.connect_btn.text() == "Connecter":
                self.connect_to_camera(self.active_camera_id, cam_data.url, cam_data.username, cam_data.password)
    
    def connect_to_camera(self, camera_id: int, camera_url: str, username: str, password: str):
        """Se connecte à la caméra avec les paramètres fournis."""
        if camera_id < 1 or camera_id > 8:
            logger.error(f"ID de caméra invalide: {camera_id}")
            return
        
        cam_data = self.cameras[camera_id]
        
        try:
            # Mettre à jour les valeurs de connexion
            cam_data.url = camera_url.rstrip('/')
            cam_data.username = username
            cam_data.password = password
            
            # Déconnecter si déjà connecté (pour cette caméra)
            if cam_data.connected:
                self.disconnect_from_camera(camera_id)
            
            # Créer le contrôleur
            cam_data.controller = BlackmagicFocusController(cam_data.url, cam_data.username, cam_data.password)
            
            # Réinitialiser le flag pour cette nouvelle connexion
            cam_data.initial_values_received = False
            
            # Se connecter au WebSocket (qui enverra les valeurs initiales dans la réponse)
            self.connect_websocket(camera_id)
            
            # Charger les gains et shutters supportés (toujours nécessaires)
            self.load_supported_gains(camera_id)
            self.load_supported_shutters(camera_id)
            
            # TEMPORAIRE: Charger aussi les valeurs initiales via GET pour s'assurer qu'on a les bonnes valeurs
            # TODO: Retirer cette ligne une fois que le WebSocket fournit correctement les valeurs initiales
            self.load_initial_values(camera_id)
            
            # Mettre à jour l'UI après le chargement des valeurs initiales si c'est la caméra active
            if camera_id == self.active_camera_id:
                QTimer.singleShot(100, lambda: self._update_ui_from_camera_data(cam_data))
            
            # Garder load_initial_values comme fallback après un délai (si WebSocket ne répond pas)
            QTimer.singleShot(2000, lambda: self._fallback_load_initial_values(camera_id))
            
            # Mettre à jour l'état
            cam_data.connected = True
            
            # Mettre à jour le StateStore avec l'état de connexion
            self.state_store.update_cam(camera_id, connected=True)
            
            # Mettre à jour l'UI seulement si c'est la caméra active
            if camera_id == self.active_camera_id:
                self.status_label.setText(f"✓ Caméra {camera_id} - Connectée à {cam_data.url}")
                self.status_label.setStyleSheet("color: #0f0;")
                # Activer tous les contrôles
                self.set_controls_enabled(True)
            
            logger.info(f"Caméra {camera_id} connectée à {cam_data.url}")
        except Exception as e:
            logger.error(f"Erreur lors de la connexion de la caméra {camera_id}: {e}")
            cam_data.connected = False
            # Mettre à jour le StateStore avec l'état de déconnexion
            self.state_store.update_cam(camera_id, connected=False)
            if camera_id == self.active_camera_id:
                self.status_label.setText(f"✗ Caméra {camera_id} - Erreur de connexion: {e}")
                self.status_label.setStyleSheet("color: #f00;")
                self.set_controls_enabled(False)
            if cam_data.controller:
                cam_data.controller = None
    
    def disconnect_from_camera(self, camera_id: int):
        """Se déconnecte de la caméra spécifiée."""
        if camera_id < 1 or camera_id > 8:
            logger.error(f"ID de caméra invalide: {camera_id}")
            return
        
        cam_data = self.cameras[camera_id]
        
        try:
            # Arrêter le WebSocket
            if cam_data.websocket_client:
                cam_data.websocket_client.stop()
                cam_data.websocket_client = None
            
            # Détruire le contrôleur
            cam_data.controller = None
            
            # Mettre à jour l'état
            cam_data.connected = False
            cam_data.initial_values_received = False  # Réinitialiser le flag pour la prochaine connexion
            
            # Mettre à jour l'UI seulement si c'est la caméra active
            if camera_id == self.active_camera_id:
                self.status_label.setText(f"✗ Caméra {camera_id} - Déconnectée")
                self.status_label.setStyleSheet("color: #f00;")
                # Désactiver tous les contrôles
                self.set_controls_enabled(False)
            
            logger.info(f"Caméra {camera_id} déconnectée")
        except Exception as e:
            logger.error(f"Erreur lors de la déconnexion de la caméra {camera_id}: {e}")
    
    def keyPressEvent(self, event: QKeyEvent):
        """Gère les événements clavier pour ajuster le focus avec les flèches."""
        cam_data = self.get_active_camera_data()
        if not cam_data.connected or not cam_data.controller:
            super().keyPressEvent(event)
            return
        
        # Ajustement très précis du focus avec les flèches haut/bas
        if event.key() == Qt.Key_Up:
            # Arrêter toute répétition en cours
            self._stop_key_repeat()
            # Incrémenter immédiatement
            self._adjust_focus_precise_increment(0.001)
            # Démarrer la répétition
            self._start_key_repeat('up')
            event.accept()
        elif event.key() == Qt.Key_Down:
            # Arrêter toute répétition en cours
            self._stop_key_repeat()
            # Décrémenter immédiatement
            self._adjust_focus_precise_increment(-0.001)
            # Démarrer la répétition
            self._start_key_repeat('down')
            event.accept()
        else:
            self._stop_key_repeat()
            super().keyPressEvent(event)
    
    def keyReleaseEvent(self, event: QKeyEvent):
        """Arrête la répétition quand la touche est relâchée."""
        if event.key() == Qt.Key_Up or event.key() == Qt.Key_Down:
            self._stop_key_repeat()
            event.accept()
        else:
            super().keyReleaseEvent(event)
    
    def _start_key_repeat(self, direction: str):
        """Démarre la répétition automatique de l'ajustement du focus."""
        self.key_repeat_direction = direction# Démarrer un timer qui se répète toutes les 50ms
        # Délai initial de 300ms, puis répétition toutes les 50ms
        def repeat_action():
            if self.key_repeat_direction == 'up':
                self._adjust_focus_precise_increment(0.001)
            elif self.key_repeat_direction == 'down':
                self._adjust_focus_precise_increment(-0.001)
        
        # Premier délai plus long (300ms), puis répétition rapide (50ms)
        QTimer.singleShot(300, lambda: self._continue_key_repeat(repeat_action))
    
    def _continue_key_repeat(self, action):
        """Continue la répétition avec un timer récurrent."""
        if self.key_repeat_direction is None:
            return
        
        # Exécuter l'action immédiatement
        action()
        
        # Programmer la prochaine répétition (50ms)
        if self.key_repeat_direction is not None:
            # Créer le timer s'il n'existe pas
            if self.key_repeat_timer is None:
                self.key_repeat_timer = QTimer()
                self.key_repeat_timer.setSingleShot(False)  # Timer récurrent
                self.key_repeat_timer.timeout.connect(action)
            
            # Démarrer ou redémarrer le timer
            if not self.key_repeat_timer.isActive():
                self.key_repeat_timer.start(50)  # Répéter toutes les 50ms
    
    def _stop_key_repeat(self):
        """Arrête la répétition automatique."""
        self.key_repeat_direction = None
        if self.key_repeat_timer:
            self.key_repeat_timer.stop()
            self.key_repeat_timer = None
    
    def _adjust_focus_precise_increment(self, increment: float):
        """Ajuste le focus d'un incrément donné."""
        cam_data = self.get_active_camera_data()
        # Utiliser focus_sent_value pour s'assurer qu'on part de la dernière valeur envoyée
        current_value = cam_data.focus_sent_value if cam_data.focus_sent_value is not None else (cam_data.focus_actual_value if cam_data.focus_actual_value is not None else 0.0)
        new_value = max(0.0, min(1.0, current_value + increment))
        self._adjust_focus_precise(new_value)
    
    def _adjust_focus_precise(self, value: float):
        """Ajuste le focus de manière très précise."""
        cam_data = self.get_active_camera_data()
        # Note: focus_keyboard_adjusting n'est plus utilisé pour bloquer les mises à jour socket
        # Les valeurs socket sont toujours acceptées et affichées pour refléter l'état réel de la caméra
        
        # Mettre à jour la valeur envoyée
        cam_data.focus_sent_value = value
        self.focus_value_sent.setText(f"{value:.3f}")
        
        # Mettre à jour le slider
        slider_value = int(value * 1000)
        self.focus_slider.blockSignals(True)
        self.focus_slider.setValue(slider_value)
        self.focus_slider.blockSignals(False)
        
        # Ajouter à la file d'attente au lieu d'envoyer directement
        if cam_data.controller:
            # Toujours ajouter la valeur à la file (on gardera seulement la dernière lors du traitement)
            self.keyboard_focus_queue.append(value)
            # Traiter la file d'attente seulement si pas déjà en cours
            if not self.keyboard_focus_processing and not self.focus_sending:
                self._process_keyboard_focus_queue()
    
    def _process_keyboard_focus_queue(self):
        """Traite la file d'attente des valeurs clavier."""
        cam_data = self.get_active_camera_data()
        if not cam_data.controller or self.keyboard_focus_processing or self.focus_sending:
            return
        
        if not self.keyboard_focus_queue:
            return
        
        # Prendre la dernière valeur de la file (la plus récente)
        value = self.keyboard_focus_queue[-1]
        # Vider la file (on envoie seulement la dernière valeur)
        self.keyboard_focus_queue.clear()# Utiliser la méthode directe pour l'envoi
        self._process_keyboard_focus_queue_direct(value)
    
    def _on_keyboard_focus_send_complete(self):
        """Appelé après le délai de 50ms pour permettre le prochain envoi."""
        self.focus_sending = False
        self.keyboard_focus_processing = False# Si la file d'attente n'est pas vide, traiter la dernière valeur (la plus récente)
        # Cela garantit que toutes les valeurs sont envoyées, comme pour le slider
        if self.keyboard_focus_queue:
            # Prendre la dernière valeur (la plus récente) et vider la file
            value = self.keyboard_focus_queue[-1]
            self.keyboard_focus_queue.clear()# Envoyer directement cette valeur
            self._process_keyboard_focus_queue_direct(value)
        else:
            # Si pas de file d'attente, vérifier s'il y a une nouvelle valeur à envoyer
            # (la valeur actuelle du focus_sent_value devrait être à jour)
            # Mais on ne relit pas automatiquement car l'utilisateur doit appuyer à nouveau sur la flèche
            pass
    
    def _process_keyboard_focus_queue_direct(self, value: float):
        """Traite directement une valeur clavier sans passer par la file."""
        cam_data = self.get_active_camera_data()
        if not cam_data.controller:
            self.focus_sending = False
            self.keyboard_focus_processing = False
            return
        
        if self.focus_sending:
            # Si déjà en cours, ne rien faire (sera traité dans _on_keyboard_focus_send_complete)
            return
        
        self.keyboard_focus_processing = True
        self.focus_sending = True
        
        try:
            success = cam_data.controller.set_focus(value, silent=True)
            # Attendre 50ms avant de permettre le prochain envoi (comme pour le slider)
            QTimer.singleShot(50, self._on_keyboard_focus_send_complete)
        except Exception as e:
            logger.error(f"Erreur lors de l'envoi du focus précis: {e}")
            self.focus_sending = False
            self.keyboard_focus_processing = False
    
    def set_controls_enabled(self, enabled: bool):
        """Active ou désactive tous les contrôles."""
        # Focus
        self.focus_slider.setEnabled(enabled)
        
        # Iris
        self.iris_slider.setEnabled(enabled)
        
        # Gain
        self.gain_plus_btn.setEnabled(enabled)
        self.gain_minus_btn.setEnabled(enabled)
        
        # Shutter
        self.shutter_plus_btn.setEnabled(enabled)
        self.shutter_minus_btn.setEnabled(enabled)
        
        # Toggles
        self.zebra_toggle.setEnabled(enabled)
        self.focusAssist_toggle.setEnabled(enabled)
        self.falseColor_toggle.setEnabled(enabled)
        self.cleanfeed_toggle.setEnabled(enabled)
        
        # Autofocus
        self.autofocus_btn.setEnabled(enabled)
    
    def connect_websocket(self, camera_id: int):
        """Se connecte au WebSocket de la caméra spécifiée."""
        if camera_id < 1 or camera_id > 8:
            logger.error(f"ID de caméra invalide: {camera_id}")
            return
        
        cam_data = self.cameras[camera_id]
        if not cam_data.controller:
            return
        
        def on_websocket_status(connected: bool, message: str):
            # Capturer camera_id dans le closure pour éviter les problèmes de référence
            cam_id = camera_id
            # Appeler la méthode avec camera_id de manière thread-safe
            self.on_websocket_status(cam_id, connected, message)
        
        # Créer des callbacks wrappés qui incluent camera_id
        cam_data.websocket_client = BlackmagicWebSocketClient(
            cam_data.url,
            cam_data.username,
            cam_data.password,
            on_change_callback=lambda param_name, data: self._handle_websocket_change(camera_id, param_name, data),
            on_connection_status_callback=on_websocket_status
        )
        
        cam_data.websocket_client.start()
    
    def _handle_websocket_change(self, camera_id: int, param_name: str, data: dict):
        """Gère les changements de paramètres reçus via WebSocket pour une caméra spécifique."""
        if camera_id < 1 or camera_id > 8:
            return
        
        cam_data = self.cameras[camera_id]
        
        # Marquer que nous avons reçu des valeurs du WebSocket (valeurs initiales ou mises à jour)
        # On considère qu'on a reçu les valeurs initiales si on reçoit au moins focus
        if param_name == 'focus' and not cam_data.initial_values_received:
            cam_data.initial_values_received = True
            logger.info(f"Valeurs initiales reçues du WebSocket pour la caméra {camera_id}")
        
        # Mettre à jour le StateStore
        update_kwargs = {}
        
        if param_name == 'focus':
            if 'normalised' in data:
                value = float(data['normalised'])
                # TOUJOURS mettre à jour les données de la caméra
                cam_data.focus_actual_value = value
                update_kwargs['focus'] = value
                # Mettre à jour l'UI seulement si c'est la caméra active
                if camera_id == self.active_camera_id:
                    self.signals.focus_changed.emit(value)
        elif param_name == 'iris':
            # TOUJOURS mettre à jour les données de la caméra
            logger.debug(f"WebSocket iris reçu pour caméra {camera_id}: {data}")
            if 'normalised' in data:
                cam_data.iris_actual_value = float(data['normalised'])
                update_kwargs['iris'] = cam_data.iris_actual_value
            # Toujours émettre le signal pour mettre à jour l'UI, même si 'normalised' n'est pas présent
            # (les données peuvent contenir 'apertureStop' ou d'autres champs)
            if camera_id == self.active_camera_id:
                logger.debug(f"Émission du signal iris_changed pour caméra active {camera_id}")
                self.signals.iris_changed.emit(data)
        elif param_name == 'gain':
            if 'gain' in data:
                value = int(data['gain'])
                cam_data.gain_actual_value = value
                update_kwargs['gain'] = value
                if camera_id == self.active_camera_id:
                    self.signals.gain_changed.emit(value)
        elif param_name == 'shutter':
            if 'shutterSpeed' in data:
                value = int(data['shutterSpeed'])
                cam_data.shutter_actual_value = value
                update_kwargs['shutter'] = value
            if camera_id == self.active_camera_id:
                self.signals.shutter_changed.emit(data)
        elif param_name == 'zebra':
            if 'enabled' in data:
                # TOUJOURS mettre à jour les données de la caméra
                cam_data.zebra_enabled = bool(data['enabled'])
                # Mettre à jour l'UI seulement si c'est la caméra active
                if camera_id == self.active_camera_id:
                    self.signals.zebra_changed.emit(cam_data.zebra_enabled)
        elif param_name == 'focusAssist':
            if 'enabled' in data:
                # TOUJOURS mettre à jour les données de la caméra
                cam_data.focusAssist_enabled = bool(data['enabled'])
                # Mettre à jour l'UI seulement si c'est la caméra active
                if camera_id == self.active_camera_id:
                    self.signals.focusAssist_changed.emit(cam_data.focusAssist_enabled)
        elif param_name == 'falseColor':
            if 'enabled' in data:
                # TOUJOURS mettre à jour les données de la caméra
                cam_data.falseColor_enabled = bool(data['enabled'])
                # Mettre à jour l'UI seulement si c'est la caméra active
                if camera_id == self.active_camera_id:
                    self.signals.falseColor_changed.emit(cam_data.falseColor_enabled)
        elif param_name == 'cleanfeed':
            if 'enabled' in data:
                # TOUJOURS mettre à jour les données de la caméra
                cam_data.cleanfeed_enabled = bool(data['enabled'])
                # Mettre à jour l'UI seulement si c'est la caméra active
                if camera_id == self.active_camera_id:
                    self.signals.cleanfeed_changed.emit(cam_data.cleanfeed_enabled)
        elif param_name == 'zoom':
            if 'normalised' in data:
                update_kwargs['zoom'] = float(data['normalised'])
            if camera_id == self.active_camera_id:
                self.signals.zoom_changed.emit(data)
        
        # Mettre à jour le StateStore si des valeurs ont changé
        if update_kwargs:
            self.state_store.update_cam(camera_id, **update_kwargs)
    
    def _on_application_state_changed(self, state: Qt.ApplicationState):
        """
        Gère les changements d'état de l'application (détection du réveil).
        
        Args:
            state: Nouvel état de l'application (Qt.ApplicationState.ApplicationActive, Qt.ApplicationState.ApplicationSuspended, etc.)
        """
        if state == Qt.ApplicationState.ApplicationActive:
            # L'application vient de repasser en mode actif (réveil)
            logger.info("Application réveillée, vérification des connexions WebSocket...")
            self._reconnect_all_websockets()
    
    def _reconnect_all_websockets(self):
        """
        Reconnecte tous les WebSockets pour les caméras connectées.
        Appelée au réveil de l'ordinateur ou lors de la vérification périodique.
        """
        for camera_id in range(1, 9):
            cam_data = self.cameras[camera_id]
            if cam_data.connected and cam_data.url and cam_data.username and cam_data.password:
                # Vérifier si le WebSocket est mort ou manquant
                if cam_data.websocket_client:
                    if not cam_data.websocket_client.is_connected():
                        logger.info(f"WebSocket mort détecté pour la caméra {camera_id}, reconnexion...")
                        # Arrêter l'ancien WebSocket
                        cam_data.websocket_client.stop()
                        cam_data.websocket_client = None
                        # Reconnecter
                        self.connect_websocket(camera_id)
                    # else: WebSocket est connecté, rien à faire
                else:
                    # Pas de WebSocket mais caméra connectée, créer un nouveau
                    logger.info(f"Pas de WebSocket pour la caméra {camera_id} (mais connectée), création...")
                    self.connect_websocket(camera_id)
    
    def _check_websockets_health(self):
        """
        Vérifie périodiquement l'état de tous les WebSockets et reconnecte ceux qui sont morts.
        Appelée toutes les 10 secondes par un QTimer.
        """
        for camera_id in range(1, 9):
            cam_data = self.cameras[camera_id]
            if cam_data.connected:
                # Vérifier si le WebSocket existe et est connecté
                if cam_data.websocket_client:
                    if not cam_data.websocket_client.is_connected():
                        logger.warning(f"WebSocket mort détecté pour la caméra {camera_id} lors de la vérification périodique, reconnexion...")
                        # Arrêter l'ancien WebSocket
                        cam_data.websocket_client.stop()
                        cam_data.websocket_client = None
                        # Reconnecter
                        self.connect_websocket(camera_id)
                else:
                    # Pas de WebSocket mais caméra connectée, créer un nouveau
                    logger.warning(f"Pas de WebSocket pour la caméra {camera_id} (mais connectée), création...")
                    self.connect_websocket(camera_id)
    
    def load_initial_values(self, camera_id: int):
        """Charge les valeurs initiales depuis la caméra spécifiée."""
        if camera_id < 1 or camera_id > 8:
            logger.warning(f"load_initial_values: ID de caméra invalide: {camera_id}")
            return
        
        cam_data = self.cameras[camera_id]
        if not cam_data.controller:
            logger.warning(f"load_initial_values: Pas de controller pour la caméra {camera_id}")
            return
        
        # Ne pas vérifier cam_data.connected car on peut charger les valeurs même si pas encore connecté
        logger.info(f"Chargement des valeurs initiales pour la caméra {camera_id}")
        
        try:
            # Focus
            focus_data = cam_data.controller.get_focus()
            if focus_data:
                # get_focus() peut retourner soit un dict avec 'normalised', soit directement un float
                if isinstance(focus_data, dict) and 'normalised' in focus_data:
                    value = float(focus_data['normalised'])
                elif isinstance(focus_data, (int, float)):
                    value = float(focus_data)
                else:
                    value = None
                
                if value is not None:
                    cam_data.focus_actual_value = value
                    cam_data.focus_sent_value = value
                    
                    # Mettre à jour l'UI seulement si c'est la caméra active
                    if camera_id == self.active_camera_id:
                        self.focus_value_actual.setText(f"{value:.3f}")
                        self.focus_value_sent.setText(f"{value:.3f}")
                        slider_value = int(value * 1000)
                        self.focus_slider.blockSignals(True)
                        self.focus_slider.setValue(slider_value)
                        self.focus_slider.blockSignals(False)
            
            # Iris
            iris_data = cam_data.controller.get_iris()
            if iris_data and 'normalised' in iris_data:
                value = float(iris_data['normalised'])
                cam_data.iris_actual_value = value
                cam_data.iris_sent_value = value
                if camera_id == self.active_camera_id:
                    self.on_iris_changed(iris_data)
            
            # Gain
            gain_value = cam_data.controller.get_gain()
            if gain_value is not None:
                cam_data.gain_actual_value = gain_value
                cam_data.gain_sent_value = gain_value
                if camera_id == self.active_camera_id:
                    self.on_gain_changed(gain_value)
            
            # Shutter
            shutter_data = cam_data.controller.get_shutter()
            if shutter_data:
                if 'shutterSpeed' in shutter_data:
                    cam_data.shutter_actual_value = int(shutter_data['shutterSpeed'])
                    cam_data.shutter_sent_value = int(shutter_data['shutterSpeed'])
                if camera_id == self.active_camera_id:
                    self.on_shutter_changed(shutter_data)
            
            # Zoom
            zoom_data = cam_data.controller.get_zoom()
            if zoom_data:
                if camera_id == self.active_camera_id:
                    self.on_zoom_changed(zoom_data)
            
            # Zebra
            zebra_value = cam_data.controller.get_zebra()
            if zebra_value is not None:
                # TOUJOURS mettre à jour les données de la caméra
                cam_data.zebra_enabled = zebra_value
                # Mettre à jour l'UI seulement si c'est la caméra active
                if camera_id == self.active_camera_id:
                    self.on_zebra_changed(zebra_value)
            
            # Focus Assist
            focusAssist_value = cam_data.controller.get_focus_assist()
            if focusAssist_value is not None:
                # TOUJOURS mettre à jour les données de la caméra
                cam_data.focusAssist_enabled = focusAssist_value
                # Mettre à jour l'UI seulement si c'est la caméra active
                if camera_id == self.active_camera_id:
                    self.on_focusAssist_changed(focusAssist_value)
            
            # False Color
            falseColor_value = cam_data.controller.get_false_color()
            if falseColor_value is not None:
                # TOUJOURS mettre à jour les données de la caméra
                cam_data.falseColor_enabled = falseColor_value
                # Mettre à jour l'UI seulement si c'est la caméra active
                if camera_id == self.active_camera_id:
                    self.on_falseColor_changed(falseColor_value)
            
            # Cleanfeed
            cleanfeed_value = cam_data.controller.get_cleanfeed()
            if cleanfeed_value is not None:
                # TOUJOURS mettre à jour les données de la caméra
                cam_data.cleanfeed_enabled = cleanfeed_value
                # Mettre à jour l'UI seulement si c'est la caméra active
                if camera_id == self.active_camera_id:
                    self.on_cleanfeed_changed(cleanfeed_value)
            
            # Mettre à jour le StateStore avec toutes les valeurs initiales
            update_kwargs = {}
            if cam_data.focus_actual_value is not None:
                update_kwargs['focus'] = cam_data.focus_actual_value
            if cam_data.iris_actual_value is not None:
                update_kwargs['iris'] = cam_data.iris_actual_value
            if cam_data.gain_actual_value is not None:
                update_kwargs['gain'] = cam_data.gain_actual_value
            if cam_data.shutter_actual_value is not None:
                update_kwargs['shutter'] = cam_data.shutter_actual_value
            if update_kwargs:
                self.state_store.update_cam(camera_id, **update_kwargs)
            
            # Marquer que les valeurs initiales ont été chargées via GET
            cam_data.initial_values_received = True
            logger.info(f"Valeurs initiales chargées pour la caméra {camera_id}: focus={cam_data.focus_actual_value}, iris={cam_data.iris_actual_value}, gain={cam_data.gain_actual_value}, shutter={cam_data.shutter_actual_value}")
        except Exception as e:
            logger.error(f"Erreur lors du chargement des valeurs initiales pour la caméra {camera_id}: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    def _fallback_load_initial_values(self, camera_id: int):
        """Charge les valeurs initiales via GET si le WebSocket ne les a pas fournies."""
        if camera_id < 1 or camera_id > 8:
            return
        
        cam_data = self.cameras[camera_id]
        
        # Vérifier si on a déjà reçu des valeurs du WebSocket
        # Si focus_actual_value est None, on fait les GET
        if not cam_data.initial_values_received and cam_data.focus_actual_value is None:
            logger.info(f"Fallback: Chargement des valeurs initiales via GET pour la caméra {camera_id}")
            self.load_initial_values(camera_id)
    
    # Slots pour les signaux
    def on_focus_changed(self, value: float):
        """Slot appelé quand le focus change."""
        # Arrondir la valeur à la même précision que le slider (0.001)
        # Cela garantit une résolution cohérente entre le fader et les flèches
        value_rounded = round(value, 3)# TOUJOURS accepter les mises à jour socket et les afficher en bleu
        # Les valeurs socket reflètent l'état réel de la caméra et doivent toujours être affichées
        self.focus_actual_value = value_rounded
        
        # Mettre à jour l'affichage de la valeur réelle avec la valeur arrondie (affichage bleu)
        self.focus_value_actual.setText(f"{value_rounded:.3f}")
        
        # Mettre à jour le slider avec la valeur socket
        # Même pendant l'ajustement clavier, on peut mettre à jour le slider pour refléter la valeur réelle
        # Le flag focus_keyboard_adjusting n'empêche plus les mises à jour
        if not self.focus_slider_user_touching:
            slider_value = int(value_rounded * 1000)
            self.focus_slider.blockSignals(True)
            self.focus_slider.setValue(slider_value)
            self.focus_slider.blockSignals(False)
    
    def on_focus_slider_pressed(self):
        """Appelé quand on appuie sur le slider."""
        cam_data = self.get_active_camera_data()
        
        # Marquer que l'utilisateur touche le slider
        self.focus_slider_user_touching = True
        
        # Lire la position actuelle du slider au moment du clic
        current_slider_value = self.focus_slider.value()
        current_focus_value = current_slider_value / 1000.0
        
        # Mettre à jour l'affichage avec la valeur actuelle
        cam_data.focus_sent_value = current_focus_value
        self.focus_value_sent.setText(f"{current_focus_value:.3f}")
        
        # Envoyer immédiatement la valeur sur laquelle l'utilisateur a cliqué (si le verrou est ouvert)
        if not self.focus_sending:
            self._send_focus_value_now(current_focus_value)
    
    def on_focus_slider_released(self):
        """Appelé quand on relâche le slider."""
        cam_data = self.get_active_camera_data()
        
        # Marquer que l'utilisateur ne touche plus le slider
        self.focus_slider_user_touching = False
        
        # Remettre immédiatement le slider à la valeur réelle du focus
        slider_value = int(cam_data.focus_actual_value * 1000)
        self.focus_slider.blockSignals(True)
        self.focus_slider.setValue(slider_value)
        self.focus_slider.blockSignals(False)
    
    def on_focus_slider_value_changed(self, value: int):
        """Appelé quand la valeur du slider change."""
        cam_data = self.get_active_camera_data()
        
        # Envoyer SEULEMENT si l'utilisateur touche physiquement le slider
        if not self.focus_slider_user_touching:
            return
        
        # L'utilisateur touche le slider, mettre à jour l'affichage
        focus_value = value / 1000.0
        cam_data.focus_sent_value = focus_value
        self.focus_value_sent.setText(f"{focus_value:.3f}")
        
        # Envoyer seulement si le verrou est ouvert (pas de requête en cours)
        if not self.focus_sending:
            self._send_focus_value_now(focus_value)
    
    def _send_focus_value_now(self, value: float):
        """Envoie la valeur du focus à la caméra active, attend la réponse, puis 50ms avant de permettre le prochain envoi."""
        cam_data = self.get_active_camera_data()
        if not cam_data.connected or not cam_data.controller:
            return
        if not self.focus_slider_user_touching:
            self.focus_sending = False
            return
        
        self.focus_sending = True
        
        try:
            # Envoyer la requête (synchrone, attend la réponse)
            success = cam_data.controller.set_focus(value, silent=True)
            
            if not success:
                logger.error(f"Erreur lors de l'envoi du focus")
            
            # Attendre 50ms après la réponse avant de permettre le prochain envoi
            QTimer.singleShot(50, self._on_focus_send_complete)
            
        except Exception as e:
            logger.error(f"Erreur lors de l'envoi du focus: {e}")
            # En cas d'erreur, attendre quand même 50ms
            QTimer.singleShot(50, self._on_focus_send_complete)
    
    def _on_focus_send_complete(self):
        """Appelé après le délai de 50ms, lit la position actuelle du fader si l'utilisateur le touche encore."""
        self.focus_sending = False
        
        # Si l'utilisateur touche toujours le slider, lire la position actuelle et l'envoyer
        if self.focus_slider_user_touching:
            cam_data = self.get_active_camera_data()
            current_slider_value = self.focus_slider.value()
            current_focus_value = current_slider_value / 1000.0
            cam_data.focus_sent_value = current_focus_value
            self.focus_value_sent.setText(f"{current_focus_value:.3f}")
            self._send_focus_value_now(current_focus_value)
    
    
    def on_iris_changed(self, data: dict):
        """Slot appelé quand l'iris change."""
        logger.debug(f"on_iris_changed appelé avec données: {data}")
        cam_data = self.get_active_camera_data()
        
        # Les données iris peuvent contenir 'normalised' et/ou 'apertureStop'
        # On met toujours à jour 'iris_actual_value' si 'normalised' est présent
        if 'normalised' in data:
            logger.debug(f"Mise à jour iris avec normalised: {data['normalised']}")
            value = float(data['normalised'])
            cam_data.iris_actual_value = value
            self.iris_value_actual.setText(f"{value:.2f}")
            
            # Mettre à jour le slider seulement si l'utilisateur ne le touche pas
            # Avec setInvertedAppearance(True), conversion directe : iris 0.0 = slider 0, iris 1.0 = slider 1000
            if not self.iris_slider_user_touching:
                slider_value = int(value * 1000)
                self.iris_slider.blockSignals(True)
                self.iris_slider.setValue(slider_value)
                self.iris_slider.blockSignals(False)
        
        # Toujours mettre à jour l'aperture stop si présent
        if 'apertureStop' in data:
            self.iris_aperture_stop.setText(f"{data['apertureStop']:.2f}")
    
    def on_gain_changed(self, value: int):
        """Slot appelé quand le gain change."""
        self.gain_actual_value = value
        self.gain_value_actual.setText(f"{value} dB")
    
    def on_shutter_changed(self, data: dict):
        """Slot appelé quand le shutter change."""
        if 'shutterSpeed' in data:
            self.shutter_actual_value = data['shutterSpeed']
            self.shutter_value_actual.setText(f"1/{data['shutterSpeed']}s")
    
    def on_zoom_changed(self, data: dict):
        """Slot appelé quand le zoom change."""
        if 'focalLength' in data:
            self.zoom_focal_length.setText(f"{data['focalLength']} mm")
        if 'normalised' in data:
            self.zoom_normalised.setText(f"{data['normalised']:.2f}")
    
    def on_zebra_changed(self, enabled: bool):
        """Slot appelé quand le zebra change."""
        cam_data = self.get_active_camera_data()
        cam_data.zebra_enabled = enabled
        self.zebra_enabled = enabled  # Garder pour compatibilité UI
        self.zebra_toggle.blockSignals(True)
        self.zebra_toggle.setChecked(enabled)
        self.zebra_toggle.setText(f"Zebra\n{'ON' if enabled else 'OFF'}")
        self.zebra_toggle.blockSignals(False)
    
    def on_focusAssist_changed(self, enabled: bool):
        """Slot appelé quand le focus assist change."""
        cam_data = self.get_active_camera_data()
        cam_data.focusAssist_enabled = enabled
        self.focusAssist_enabled = enabled  # Garder pour compatibilité UI
        self.focusAssist_toggle.blockSignals(True)
        self.focusAssist_toggle.setChecked(enabled)
        self.focusAssist_toggle.setText(f"Focus Assist\n{'ON' if enabled else 'OFF'}")
        self.focusAssist_toggle.blockSignals(False)
    
    def on_falseColor_changed(self, enabled: bool):
        """Slot appelé quand le false color change."""
        cam_data = self.get_active_camera_data()
        cam_data.falseColor_enabled = enabled
        self.falseColor_enabled = enabled  # Garder pour compatibilité UI
        self.falseColor_toggle.blockSignals(True)
        self.falseColor_toggle.setChecked(enabled)
        self.falseColor_toggle.setText(f"False Color\n{'ON' if enabled else 'OFF'}")
        self.falseColor_toggle.blockSignals(False)
    
    def on_cleanfeed_changed(self, enabled: bool):
        """Slot appelé quand le cleanfeed change."""
        cam_data = self.get_active_camera_data()
        cam_data.cleanfeed_enabled = enabled
        self.cleanfeed_enabled = enabled  # Garder pour compatibilité UI
        self.cleanfeed_toggle.blockSignals(True)
        self.cleanfeed_toggle.setChecked(enabled)
        self.cleanfeed_toggle.setText(f"Cleanfeed\n{'ON' if enabled else 'OFF'}")
        self.cleanfeed_toggle.blockSignals(False)
    
    def on_websocket_status(self, camera_id: int, connected: bool, message: str):
        """Slot appelé quand le statut WebSocket change pour une caméra spécifique."""
        if camera_id < 1 or camera_id > 8:
            return
        
        cam_data = self.cameras[camera_id]
        cam_data.connected = connected
        
        # Mettre à jour le StateStore
        self.state_store.update_cam(camera_id, connected=connected)
        
        # Mettre à jour l'UI seulement si c'est la caméra active
        if camera_id == self.active_camera_id:
            if connected:
                self.status_label.setText(f"✓ Caméra {camera_id} - Connectée à {cam_data.url}")
                self.status_label.setStyleSheet("color: #0f0;")
                self.set_controls_enabled(True)
            else:
                self.status_label.setText(f"✗ Caméra {camera_id} - Déconnectée ({cam_data.url})")
                self.status_label.setStyleSheet("color: #f00;")
                self.set_controls_enabled(False)
        
        logger.info(f"Caméra {camera_id} - WebSocket status: {connected} - {message}")
    
    def _handle_companion_command(self, client, cmd: dict):
        """Traite une commande reçue de Companion via WebSocket."""
        try:
            ok, error = self.command_handler.handle(self, cmd)
            self.companion_server.send_ack(client, ok, error)
        except Exception as e:
            logger.error(f"Erreur lors du traitement de la commande Companion: {e}")
            self.companion_server.send_ack(client, False, str(e))
    
    def save_preset(self, preset_number: int):
        """Sauvegarde les valeurs actuelles dans un preset pour la caméra active."""
        cam_data = self.get_active_camera_data()
        if not cam_data.connected or not cam_data.controller:
            logger.warning("Impossible de sauvegarder le preset : non connecté")
            return
        
        try:
            # Récupérer les valeurs actuelles
            preset_data = {
                "focus": cam_data.focus_actual_value,
                "iris": cam_data.iris_actual_value,
                "gain": cam_data.gain_actual_value,
                "shutter": cam_data.shutter_actual_value,
                "zoom": 0.0  # Valeur par défaut si non disponible
            }
            
            # Récupérer la valeur de zoom normalisée si disponible
            try:
                zoom_data = cam_data.controller.get_zoom()
                if zoom_data and 'normalised' in zoom_data:
                    preset_data["zoom"] = zoom_data['normalised']
            except:
                pass
            
            # Sauvegarder le preset dans la caméra active
            cam_data.presets[f"preset_{preset_number}"] = preset_data
            
            # Mettre à jour le StateStore
            self.state_store.set_preset(self.active_camera_id, f"preset_{preset_number}", preset_data)
            
            # Sauvegarder dans le fichier
            self.save_cameras_config()
            
            logger.info(f"Caméra {self.active_camera_id} - Preset {preset_number} sauvegardé: {preset_data}")
        except Exception as e:
            logger.error(f"Erreur lors de la sauvegarde du preset {preset_number}: {e}")
    
    def toggle_smooth_transition(self):
        """Active/désactive la transition progressive entre presets."""
        self.smooth_preset_transition = self.smooth_transition_toggle.isChecked()
        state_text = "ON" if self.smooth_preset_transition else "OFF"
        self.smooth_transition_toggle.setText(f"Transition\nProgressive\n{state_text}")
        logger.info(f"Transition progressive: {state_text}")
    
    def recall_preset(self, preset_number: int):
        """Rappelle et applique un preset sauvegardé pour la caméra active."""
        cam_data = self.get_active_camera_data()
        if not cam_data.connected or not cam_data.controller:
            logger.warning("Impossible de rappeler le preset : non connecté")
            return
        
        try:
            preset_key = f"preset_{preset_number}"
            if preset_key not in cam_data.presets:
                logger.warning(f"Preset {preset_number} introuvable pour la caméra {self.active_camera_id}")
                return
            
            preset_data = cam_data.presets[preset_key]
            
            # Filtrer les paramètres selon le recall scope (exclure ceux où recall_scope[param] == True)
            filtered_preset_data = {
                param: value for param, value in preset_data.items()
                if param not in cam_data.recall_scope or not cam_data.recall_scope[param]
            }
            
            # Arrêter toute transition en cours
            if self.preset_transition_timer:
                self.preset_transition_timer.stop()
                self.preset_transition_timer = None
            
            # Si transition progressive activée, faire une transition
            if self.smooth_preset_transition:
                try:
                    self._start_smooth_preset_transition(filtered_preset_data, preset_number)
                except Exception as e:
                    logger.error(f"Erreur dans _start_smooth_preset_transition: {e}")
                    raise
            else:
                # Appliquer les valeurs instantanément
                self._apply_preset_values_instant(filtered_preset_data, preset_number)
            
        except Exception as e:
            logger.error(f"Erreur lors du rappel du preset {preset_number}: {e}")
    
    def _apply_preset_values_instant(self, preset_data: dict, preset_number: int):
        """Applique les valeurs du preset instantanément (sauf focus si transition progressive activée)."""
        cam_data = self.get_active_camera_data()
        
        # Focus - seulement si transition progressive désactivée
        if 'focus' in preset_data and not self.smooth_preset_transition:
            focus_value = float(preset_data['focus'])
            cam_data.controller.set_focus(focus_value, silent=True)
            cam_data.focus_sent_value = focus_value
            self.focus_value_sent.setText(f"{focus_value:.3f}")
            slider_value = int(focus_value * 1000)
            self.focus_slider.blockSignals(True)
            self.focus_slider.setValue(slider_value)
            self.focus_slider.blockSignals(False)
        
        # Iris - toujours instantané
        if 'iris' in preset_data:
            iris_value = float(preset_data['iris'])
            self.update_iris_value(iris_value)
        
        # Gain - toujours instantané
        if 'gain' in preset_data:
            gain_value = int(preset_data['gain'])
            self.update_gain_value(gain_value)
        
        # Shutter - toujours instantané
        if 'shutter' in preset_data:
            shutter_value = int(preset_data['shutter'])
            self.update_shutter_value(shutter_value)
        
        # Zoom - toujours instantané
        if 'zoom' in preset_data:
            zoom_value = float(preset_data['zoom'])
            try:
                if hasattr(cam_data.controller, 'set_zoom'):
                    cam_data.controller.set_zoom(zoom_value, silent=True)
            except:
                pass
        
        # Marquer ce preset comme actif
        cam_data.active_preset = preset_number
        self.save_cameras_config()
        self.update_preset_highlight()
        
        logger.info(f"Caméra {self.active_camera_id} - Preset {preset_number} rappelé instantanément")
    
    def _start_smooth_preset_transition(self, preset_data: dict, preset_number: int):
        """Démarre une transition progressive vers les valeurs du preset (focus uniquement)."""
        cam_data = self.get_active_camera_data()
        
        # Appliquer les autres paramètres instantanément (iris, gain, shutter, zoom)
        if 'iris' in preset_data:
            iris_value = float(preset_data['iris'])
            self.update_iris_value(iris_value)
        
        if 'gain' in preset_data:
            gain_value = int(preset_data['gain'])
            self.update_gain_value(gain_value)
        
        if 'shutter' in preset_data:
            shutter_value = int(preset_data['shutter'])
            self.update_shutter_value(shutter_value)
        
        if 'zoom' in preset_data:
            zoom_value = float(preset_data['zoom'])
            try:
                if hasattr(cam_data.controller, 'set_zoom'):
                    cam_data.controller.set_zoom(zoom_value, silent=True)
            except:
                pass
        
        # Stocker les valeurs de départ et cibles pour le focus uniquement
        if 'focus' in preset_data:
            start_focus = cam_data.focus_actual_value
            target_focus = float(preset_data['focus'])
            
            self.preset_transition_start_values = {
                'focus': start_focus
            }
            
            self.preset_transition_target_values = {
                'focus': target_focus
            }
            
            # Démarrer le timer pour la transition du focus
            self.preset_transition_start_time = time.time() * 1000  # en millisecondes
            self.preset_transition_timer = QTimer()
            self.preset_transition_timer.timeout.connect(self._update_smooth_preset_transition)
            self.preset_transition_timer.start(20)  # Mise à jour toutes les 20ms (50 FPS)
        else:
            # Pas de focus dans le preset, pas de transition nécessaire
            self.preset_transition_timer = None
        
        # Marquer ce preset comme actif immédiatement
        cam_data.active_preset = preset_number
        self.save_cameras_config()
        self.update_preset_highlight()
        
        logger.info(f"Caméra {self.active_camera_id} - Début transition progressive du focus vers preset {preset_number}")
    
    def _update_smooth_preset_transition(self):
        """Met à jour la transition progressive du focus uniquement (appelé par le timer)."""
        if not self.preset_transition_timer:
            return
        
        cam_data = self.get_active_camera_data()
        crossfade_duration_ms = cam_data.crossfade_duration * 1000  # Convertir en millisecondes
        
        current_time = time.time() * 1000
        elapsed = current_time - self.preset_transition_start_time
        progress = min(elapsed / crossfade_duration_ms, 1.0)  # 0.0 à 1.0
        
        # Fonction d'interpolation linéaire
        def lerp(start, end, t):
            return start + (end - start) * t
        
        cam_data = self.get_active_camera_data()
        
        # Interpoler uniquement le focus
        if 'focus' in self.preset_transition_target_values:
            focus_current = lerp(
                self.preset_transition_start_values['focus'],
                self.preset_transition_target_values['focus'],
                progress
            )
            
            # Forcer l'envoi même si focus_sending est True (on ignore le verrou pendant la transition)
            # On appelle directement set_focus sur le controller, sans passer par _send_focus_value_now
            try:
                success = cam_data.controller.set_focus(focus_current, silent=True)
            except Exception as e:
                pass
            
            cam_data.focus_sent_value = focus_current
            self.focus_value_sent.setText(f"{focus_current:.3f}")
            slider_value = int(focus_current * 1000)
            self.focus_slider.blockSignals(True)
            self.focus_slider.setValue(slider_value)
            self.focus_slider.blockSignals(False)
        
        # Si la transition est terminée
        if progress >= 1.0:
            self.preset_transition_timer.stop()
            self.preset_transition_timer = None
            logger.info(f"Transition progressive du focus terminée")
    
    def on_recall_scope_changed(self, param: str, excluded: bool):
        """Appelé quand une checkbox de recall scope change."""
        cam_data = self.get_active_camera_data()
        cam_data.recall_scope[param] = excluded
        
        # Mettre à jour le texte de la checkbox
        checkbox = self.recall_scope_checkboxes.get(param)
        if checkbox:
            checkbox.setText(f"{'☑' if excluded else '☐'} {param.capitalize()}")
        
        # Sauvegarder la configuration
        self.save_cameras_config()
        
        logger.info(f"Recall scope pour {param}: {'exclu' if excluded else 'inclus'}")
    
    def update_recall_scope_ui(self):
        """Met à jour l'UI des checkboxes de recall scope selon les valeurs de la caméra active."""
        if not hasattr(self, 'recall_scope_checkboxes') or not self.recall_scope_checkboxes:
            return
        
        cam_data = self.get_active_camera_data()
        
        for param, checkbox in self.recall_scope_checkboxes.items():
            if checkbox:
                excluded = cam_data.recall_scope.get(param, False)
                checkbox.blockSignals(True)
                checkbox.setChecked(excluded)
                checkbox.setText(f"{'☑' if excluded else '☐'} {param.capitalize()}")
                checkbox.blockSignals(False)
    
    def on_crossfade_duration_changed(self, value: float):
        """Appelé quand la valeur du crossfade duration change."""
        cam_data = self.get_active_camera_data()
        cam_data.crossfade_duration = value
        
        # Sauvegarder la configuration
        self.save_cameras_config()
        
        logger.info(f"Crossfade duration pour caméra {self.active_camera_id}: {value}s")
    
    def update_crossfade_duration_ui(self):
        """Met à jour l'UI du spinbox de crossfade duration selon la valeur de la caméra active."""
        if not hasattr(self, 'crossfade_duration_spinbox') or not self.crossfade_duration_spinbox:
            return
        
        cam_data = self.get_active_camera_data()
        self.crossfade_duration_spinbox.blockSignals(True)
        self.crossfade_duration_spinbox.setValue(cam_data.crossfade_duration)
        self.crossfade_duration_spinbox.blockSignals(False)
    
    def update_preset_highlight(self):
        """Met à jour l'encadré coloré autour du preset actif."""
        cam_data = self.get_active_camera_data()
        active_preset_num = cam_data.active_preset
        
        for i, recall_btn in enumerate(self.preset_recall_buttons, start=1):
            if i == active_preset_num:
                # Style pour le preset actif - encadré coloré
                recall_btn.setStyleSheet("""
                    QPushButton {
                        padding: 8px;
                        font-size: 10px;
                        font-weight: bold;
                        border: 3px solid #ff0;
                        border-radius: 4px;
                        background-color: #0a5;
                        color: #fff;
                    }
                    QPushButton:hover {
                        background-color: #0c7;
                        border: 3px solid #ffa;
                    }
                    QPushButton:disabled {
                        opacity: 0.5;
                    }
                """)
            else:
                # Style normal pour les autres presets
                recall_btn.setStyleSheet("""
                    QPushButton {
                        padding: 8px;
                        font-size: 10px;
                        font-weight: bold;
                        border: 1px solid #555;
                        border-radius: 4px;
                        background-color: #0a5;
                        color: #fff;
                    }
                    QPushButton:hover {
                        background-color: #0c7;
                    }
                    QPushButton:disabled {
                        opacity: 0.5;
                    }
                """)


def main():
    """Fonction principale."""
    parser = argparse.ArgumentParser(
        description="Interface PySide6 standalone pour contrôler le focus Blackmagic (multi-caméras)",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    # Les arguments sont ignorés maintenant car la configuration est chargée depuis cameras_config.json
    # Gardons-les pour compatibilité mais sans effet
    
    args = parser.parse_args()
    
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

