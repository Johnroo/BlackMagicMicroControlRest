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
    QDialogButtonBox, QSizePolicy
)
from PySide6.QtCore import Qt, Signal, QObject, QTimer, QEvent
from PySide6.QtGui import QResizeEvent, QKeyEvent

from blackmagic_focus_control import BlackmagicFocusController, BlackmagicWebSocketClient

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
    
    # État
    supported_gains: list = field(default_factory=list)
    supported_shutter_speeds: list = field(default_factory=list)
    
    # Presets
    presets: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    active_preset: Optional[int] = None  # Numéro du preset actuellement actif (1-10)


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
        
        # Variables de connexion (remplacées par cameras dict)
        self.cameras: Dict[int, CameraData] = {}
        self.active_camera_id: int = 1
        
        # Variables pour le throttling
        self.last_iris_send_time = 0
        self.last_gain_send_time = 0
        self.last_shutter_send_time = 0
        self.OTHER_MIN_INTERVAL = 500  # ms
        
        # Variables pour le slider focus
        self.focus_slider_user_touching = False  # True seulement quand l'utilisateur touche physiquement le slider
        self.focus_send_sequence = 0  # Compteur pour annuler les envois différés
        self.focus_sending = False  # True pendant qu'une requête PUT est en cours ou en attente de délai
        self.focus_keyboard_adjusting = False  # True quand on ajuste avec les flèches clavier
        
        # Variables pour la répétition des touches flèches
        self.key_repeat_timer = None
        self.key_repeat_direction = None  # 'up' ou 'down'
        
        # File d'attente pour les valeurs clavier (pour ne pas perdre de valeurs)
        self.keyboard_focus_queue = []
        self.keyboard_focus_processing = False
        
        # Charger la configuration des caméras
        self.load_cameras_config()
        
        # Initialiser l'UI
        self.init_ui()
        
        # Connecter les signaux
        self.connect_signals()
        
        # Charger les valeurs de la caméra active dans l'UI
        self._update_ui_from_camera_data(self.get_active_camera_data())
        
        # Connexion automatique si la caméra active a des paramètres configurés
        cam_data = self.get_active_camera_data()
        if cam_data.url and cam_data.username and cam_data.password:
            self.connect_to_camera(self.active_camera_id, cam_data.url, cam_data.username, cam_data.password)
    
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
                    
                    self.cameras[i] = CameraData(
                        url=cam_config.get("url", "").rstrip('/'),
                        username=cam_config.get("username", ""),
                        password=cam_config.get("password", ""),
                        presets=cam_config.get("presets", {})
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
                    "presets": cam_data.presets
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
        self.controls_panel = self.create_controls_panel()
        
        # Ajouter les panneaux au layout central
        central_layout.addWidget(self.focus_panel)
        central_layout.addWidget(self.iris_panel)
        central_layout.addWidget(self.gain_panel)
        central_layout.addWidget(self.shutter_panel)
        central_layout.addWidget(self.zoom_panel)
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
        # TODO: Mettre à jour les widgets iris
        
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
        self.iris_aperture_stop.setStyleSheet("font-size: 9px; color: #888;")
        iris_display_layout.addWidget(self.iris_aperture_stop)
        
        layout.addWidget(iris_display)
        
        # Boutons de contrôle
        buttons_container = QWidget()
        buttons_layout = QVBoxLayout(buttons_container)
        buttons_layout.setSpacing(15)
        buttons_layout.setContentsMargins(0, 30, 0, 30)
        
        self.iris_plus_btn = QPushButton("+")
        self.iris_plus_btn.setFixedSize(60, 60)
        self.iris_plus_btn.setStyleSheet("""
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
                transform: scale(0.95);
            }
        """)
        self.iris_plus_btn.clicked.connect(self.increment_iris)
        buttons_layout.addWidget(self.iris_plus_btn, alignment=Qt.AlignCenter)
        
        self.iris_minus_btn = QPushButton("-")
        self.iris_minus_btn.setFixedSize(60, 60)
        self.iris_minus_btn.setStyleSheet("""
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
                transform: scale(0.95);
            }
        """)
        self.iris_minus_btn.clicked.connect(self.decrement_iris)
        buttons_layout.addWidget(self.iris_minus_btn, alignment=Qt.AlignCenter)
        
        layout.addWidget(buttons_container)
        
        layout.addStretch()
        return panel
    
    def increment_iris(self):
        """Incrémente l'iris de 0.05 pour la caméra active."""
        cam_data = self.get_active_camera_data()
        if not cam_data.connected or not cam_data.controller:
            return
        current_value = cam_data.iris_actual_value if cam_data.iris_actual_value is not None else cam_data.iris_sent_value
        new_value = min(1.0, current_value + 0.05)
        self.update_iris_value(new_value)
    
    def decrement_iris(self):
        """Décrémente l'iris de 0.05 pour la caméra active."""
        cam_data = self.get_active_camera_data()
        if not cam_data.connected or not cam_data.controller:
            return
        current_value = cam_data.iris_actual_value if cam_data.iris_actual_value is not None else cam_data.iris_sent_value
        new_value = max(0.0, current_value - 0.05)
        self.update_iris_value(new_value)
    
    def update_iris_value(self, value: float):
        """Met à jour la valeur de l'iris."""
        value = max(0.0, min(1.0, value))
        self.iris_sent_value = value
        self.iris_value_sent.setText(f"{value:.2f}")
        self.send_iris_value(value)
    
    def send_iris_value(self, value: float):
        """Envoie la valeur de l'iris avec throttling."""
        if not self.connected or not self.controller:
            return
        now = int(time.time() * 1000)
        time_since_last_send = now - self.last_iris_send_time
        
        if time_since_last_send < self.OTHER_MIN_INTERVAL:
            QTimer.singleShot(self.OTHER_MIN_INTERVAL - time_since_last_send,
                            lambda: self.send_iris_value(value))
            return
        
        self.last_iris_send_time = now
        
        try:
            success = self.controller.set_iris(value, silent=True)
            if not success:
                logger.error(f"Erreur lors de l'envoi de l'iris")
        except Exception as e:
            logger.error(f"Erreur lors de l'envoi de l'iris: {e}")
    
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
        """Envoie la valeur du gain avec throttling."""
        if not self.connected or not self.controller:
            return
        now = int(time.time() * 1000)
        time_since_last_send = now - self.last_gain_send_time
        
        if time_since_last_send < self.OTHER_MIN_INTERVAL:
            QTimer.singleShot(self.OTHER_MIN_INTERVAL - time_since_last_send,
                            lambda: self.send_gain_value(value))
            return
        
        self.last_gain_send_time = now
        
        try:
            success = self.controller.set_gain(value, silent=True)
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
        """Met à jour la valeur du shutter."""
        self.shutter_sent_value = value
        self.shutter_value_sent.setText(f"1/{value}s")
        self.send_shutter_value(value)
    
    def send_shutter_value(self, value: int):
        """Envoie la valeur du shutter avec throttling."""
        if not self.connected or not self.controller:
            return
        now = int(time.time() * 1000)
        time_since_last_send = now - self.last_shutter_send_time
        
        if time_since_last_send < self.OTHER_MIN_INTERVAL:
            QTimer.singleShot(self.OTHER_MIN_INTERVAL - time_since_last_send,
                            lambda: self.send_shutter_value(value))
            return
        
        self.last_shutter_send_time = now
        
        try:
            success = self.controller.set_shutter(shutter_speed=value, silent=True)
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
        self.autofocus_btn.clicked.connect(self.do_autofocus)
        layout.addWidget(self.autofocus_btn)
        
        # Section Presets
        layout.addSpacing(10)
        presets_label = QLabel("Presets")
        presets_label.setAlignment(Qt.AlignCenter)
        presets_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #fff; margin-top: 10px;")
        layout.addWidget(presets_label)
        
        # Grille de presets (2 colonnes x 5 lignes)
        presets_grid = QGridLayout()
        presets_grid.setSpacing(5)
        
        self.preset_save_buttons = []
        self.preset_recall_buttons = []
        
        for i in range(1, 11):
            row = (i - 1) // 2
            col = (i - 1) % 2
            
            # Bouton Save
            save_btn = QPushButton(f"Save {i}")
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
            presets_grid.addWidget(save_btn, row * 2, col)
            self.preset_save_buttons.append(save_btn)
            
            # Bouton Recall
            recall_btn = QPushButton(f"Recall {i}")
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
            presets_grid.addWidget(recall_btn, row * 2 + 1, col)
            self.preset_recall_buttons.append(recall_btn)
        
        layout.addLayout(presets_grid)
        
        layout.addStretch()
        return panel
    
    def toggle_zebra(self):
        """Toggle le zebra."""
        new_state = self.zebra_toggle.isChecked()
        self.zebra_enabled = new_state
        self.zebra_toggle.setText(f"Zebra\n{'ON' if new_state else 'OFF'}")
        self.send_zebra(new_state)
    
    def toggle_focus_assist(self):
        """Toggle le focus assist."""
        new_state = self.focusAssist_toggle.isChecked()
        self.focusAssist_enabled = new_state
        self.focusAssist_toggle.setText(f"Focus Assist\n{'ON' if new_state else 'OFF'}")
        self.send_focus_assist(new_state)
    
    def toggle_false_color(self):
        """Toggle le false color."""
        new_state = self.falseColor_toggle.isChecked()
        self.falseColor_enabled = new_state
        self.falseColor_toggle.setText(f"False Color\n{'ON' if new_state else 'OFF'}")
        self.send_false_color(new_state)
    
    def toggle_cleanfeed(self):
        """Toggle le cleanfeed."""
        new_state = self.cleanfeed_toggle.isChecked()
        self.cleanfeed_enabled = new_state
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
                self.zebra_enabled = not enabled
                self.zebra_toggle.blockSignals(True)
                self.zebra_toggle.setChecked(not enabled)
                self.zebra_toggle.setText(f"Zebra\n{'ON' if not enabled else 'OFF'}")
                self.zebra_toggle.blockSignals(False)
                logger.error(f"Erreur lors de l'envoi du zebra")
        except Exception as e:
            # Revert on error
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
                self.focusAssist_enabled = not enabled
                self.focusAssist_toggle.blockSignals(True)
                self.focusAssist_toggle.setChecked(not enabled)
                self.focusAssist_toggle.setText(f"Focus Assist\n{'ON' if not enabled else 'OFF'}")
                self.focusAssist_toggle.blockSignals(False)
                logger.error(f"Erreur lors de l'envoi du focus assist")
        except Exception as e:
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
                self.falseColor_enabled = not enabled
                self.falseColor_toggle.blockSignals(True)
                self.falseColor_toggle.setChecked(not enabled)
                self.falseColor_toggle.setText(f"False Color\n{'ON' if not enabled else 'OFF'}")
                self.falseColor_toggle.blockSignals(False)
                logger.error(f"Erreur lors de l'envoi du false color")
        except Exception as e:
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
                self.cleanfeed_enabled = not enabled
                self.cleanfeed_toggle.blockSignals(True)
                self.cleanfeed_toggle.setChecked(not enabled)
                self.cleanfeed_toggle.setText(f"Cleanfeed\n{'ON' if not enabled else 'OFF'}")
                self.cleanfeed_toggle.blockSignals(False)
                logger.error(f"Erreur lors de l'envoi du cleanfeed")
        except Exception as e:
            self.cleanfeed_enabled = not enabled
            self.cleanfeed_toggle.blockSignals(True)
            self.cleanfeed_toggle.setChecked(not enabled)
            self.cleanfeed_toggle.setText(f"Cleanfeed: {'ON' if not enabled else 'OFF'}")
            self.cleanfeed_toggle.blockSignals(False)
            logger.error(f"Erreur lors de l'envoi du cleanfeed: {e}")
    
    def do_autofocus(self):
        """Déclenche l'autofocus pour la caméra active."""
        cam_data = self.get_active_camera_data()
        if not cam_data.connected or not cam_data.controller:
            return
        self.autofocus_btn.setEnabled(False)
        self.autofocus_btn.setText("🔍 Autofocus...")
        
        try:
            success = cam_data.controller.do_autofocus(0.5, 0.5, silent=True)
            if success:
                self.autofocus_btn.setText("✓ Autofocus OK")
                # Attendre un peu que l'autofocus se termine, puis récupérer la valeur normalisée
                QTimer.singleShot(500, self._update_focus_after_autofocus)
                QTimer.singleShot(2000, lambda: (
                    self.autofocus_btn.setText("🔍 Autofocus"),
                    self.autofocus_btn.setEnabled(True)
                ))
            else:
                self.autofocus_btn.setText("🔍 Autofocus")
                self.autofocus_btn.setEnabled(True)
                logger.error(f"Erreur lors de l'autofocus")
        except Exception as e:
            self.autofocus_btn.setText("🔍 Autofocus")
            self.autofocus_btn.setEnabled(True)
            logger.error(f"Erreur lors de l'autofocus: {e}")
    
    def _update_focus_after_autofocus(self):
        """Récupère la valeur du focus après l'autofocus et met à jour l'affichage."""
        cam_data = self.get_active_camera_data()
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
                    
                    # Mettre à jour l'UI
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
            
            # Se connecter au WebSocket
            self.connect_websocket(camera_id)
            
            # Charger les valeurs initiales
            self.load_initial_values(camera_id)
            
            # Charger les gains et shutters supportés
            self.load_supported_gains(camera_id)
            self.load_supported_shutters(camera_id)
            
            # Mettre à jour l'état
            cam_data.connected = True
            
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
        self.iris_plus_btn.setEnabled(enabled)
        self.iris_minus_btn.setEnabled(enabled)
        
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
        
        if param_name == 'focus':
            if 'normalised' in data:
                value = float(data['normalised'])
                # TOUJOURS mettre à jour les données de la caméra
                cam_data.focus_actual_value = value
                # Mettre à jour l'UI seulement si c'est la caméra active
                if camera_id == self.active_camera_id:
                    self.signals.focus_changed.emit(value)
        elif param_name == 'iris':
            # TOUJOURS mettre à jour les données de la caméra
            if 'normalised' in data:
                cam_data.iris_actual_value = float(data['normalised'])
            if camera_id == self.active_camera_id:
                self.signals.iris_changed.emit(data)
        elif param_name == 'gain':
            if 'gain' in data:
                value = int(data['gain'])
                cam_data.gain_actual_value = value
                if camera_id == self.active_camera_id:
                    self.signals.gain_changed.emit(value)
        elif param_name == 'shutter':
            if camera_id == self.active_camera_id:
                self.signals.shutter_changed.emit(data)
        elif param_name == 'zebra':
            if 'enabled' in data:
                if camera_id == self.active_camera_id:
                    self.signals.zebra_changed.emit(bool(data['enabled']))
        elif param_name == 'focusAssist':
            if 'enabled' in data:
                if camera_id == self.active_camera_id:
                    self.signals.focusAssist_changed.emit(bool(data['enabled']))
        elif param_name == 'falseColor':
            if 'enabled' in data:
                if camera_id == self.active_camera_id:
                    self.signals.falseColor_changed.emit(bool(data['enabled']))
        elif param_name == 'cleanfeed':
            if 'enabled' in data:
                if camera_id == self.active_camera_id:
                    self.signals.cleanfeed_changed.emit(bool(data['enabled']))
        elif param_name == 'zoom':
            if camera_id == self.active_camera_id:
                self.signals.zoom_changed.emit(data)
    
    def load_initial_values(self, camera_id: int):
        """Charge les valeurs initiales depuis la caméra spécifiée."""
        if camera_id < 1 or camera_id > 8:
            return
        
        cam_data = self.cameras[camera_id]
        if not cam_data.connected or not cam_data.controller:
            return
        
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
                if camera_id == self.active_camera_id:
                    self.on_zebra_changed(zebra_value)
            
            # Focus Assist
            focusAssist_value = cam_data.controller.get_focus_assist()
            if focusAssist_value is not None:
                if camera_id == self.active_camera_id:
                    self.on_focusAssist_changed(focusAssist_value)
            
            # False Color
            falseColor_value = cam_data.controller.get_false_color()
            if falseColor_value is not None:
                if camera_id == self.active_camera_id:
                    self.on_falseColor_changed(falseColor_value)
            
            # Cleanfeed
            cleanfeed_value = cam_data.controller.get_cleanfeed()
            if cleanfeed_value is not None:
                if camera_id == self.active_camera_id:
                    self.on_cleanfeed_changed(cleanfeed_value)
        except Exception as e:
            logger.error(f"Erreur lors du chargement des valeurs initiales pour la caméra {camera_id}: {e}")
    
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
        if 'normalised' in data:
            self.iris_actual_value = data['normalised']
            self.iris_value_actual.setText(f"{data['normalised']:.2f}")
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
        self.zebra_enabled = enabled
        self.zebra_toggle.blockSignals(True)
        self.zebra_toggle.setChecked(enabled)
        self.zebra_toggle.setText(f"Zebra\n{'ON' if enabled else 'OFF'}")
        self.zebra_toggle.blockSignals(False)
    
    def on_focusAssist_changed(self, enabled: bool):
        """Slot appelé quand le focus assist change."""
        self.focusAssist_enabled = enabled
        self.focusAssist_toggle.blockSignals(True)
        self.focusAssist_toggle.setChecked(enabled)
        self.focusAssist_toggle.setText(f"Focus Assist\n{'ON' if enabled else 'OFF'}")
        self.focusAssist_toggle.blockSignals(False)
    
    def on_falseColor_changed(self, enabled: bool):
        """Slot appelé quand le false color change."""
        self.falseColor_enabled = enabled
        self.falseColor_toggle.blockSignals(True)
        self.falseColor_toggle.setChecked(enabled)
        self.falseColor_toggle.setText(f"False Color\n{'ON' if enabled else 'OFF'}")
        self.falseColor_toggle.blockSignals(False)
    
    def on_cleanfeed_changed(self, enabled: bool):
        """Slot appelé quand le cleanfeed change."""
        self.cleanfeed_enabled = enabled
        self.cleanfeed_toggle.blockSignals(True)
        self.cleanfeed_toggle.setChecked(enabled)
        self.cleanfeed_toggle.setText(f"Cleanfeed\n{'ON' if enabled else 'OFF'}")
        self.cleanfeed_toggle.blockSignals(False)
    
    def on_websocket_status(self, connected: bool, message: str):
        """Slot appelé quand le statut WebSocket change (déprécié - utiliser on_websocket_status avec camera_id)."""
        # Cette méthode est appelée par les anciens signaux, on l'ignore car on utilise maintenant _handle_websocket_change
        pass
    
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
            
            # Sauvegarder dans le fichier
            self.save_cameras_config()
            
            logger.info(f"Caméra {self.active_camera_id} - Preset {preset_number} sauvegardé: {preset_data}")
        except Exception as e:
            logger.error(f"Erreur lors de la sauvegarde du preset {preset_number}: {e}")
    
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
            
            # Appliquer les valeurs
            # Focus
            if 'focus' in preset_data:
                focus_value = float(preset_data['focus'])
                cam_data.controller.set_focus(focus_value, silent=True)
                cam_data.focus_sent_value = focus_value
                self.focus_value_sent.setText(f"{focus_value:.3f}")
                # Mettre à jour le slider
                slider_value = int(focus_value * 1000)
                self.focus_slider.blockSignals(True)
                self.focus_slider.setValue(slider_value)
                self.focus_slider.blockSignals(False)
            
            # Iris
            if 'iris' in preset_data:
                iris_value = float(preset_data['iris'])
                self.update_iris_value(iris_value)
            
            # Gain
            if 'gain' in preset_data:
                gain_value = int(preset_data['gain'])
                self.update_gain_value(gain_value)
            
            # Shutter
            if 'shutter' in preset_data:
                shutter_value = int(preset_data['shutter'])
                self.update_shutter_value(shutter_value)
            
            # Zoom (si la méthode existe)
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
            
            # Mettre à jour l'affichage visuel
            self.update_preset_highlight()
            
            # Marquer ce preset comme actif
            cam_data.active_preset = preset_number
            self.save_cameras_config()
            
            # Mettre à jour l'affichage visuel
            self.update_preset_highlight()
            
            logger.info(f"Caméra {self.active_camera_id} - Preset {preset_number} rappelé: {preset_data}")
        except Exception as e:
            logger.error(f"Erreur lors du rappel du preset {preset_number}: {e}")
    
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

