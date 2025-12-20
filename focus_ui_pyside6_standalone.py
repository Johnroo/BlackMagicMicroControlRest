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
from typing import Optional
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
    
    def __init__(self, parent=None, camera_url: str = "", username: str = "", password: str = "", connected: bool = False):
        super().__init__(parent)
        self.setWindowTitle("Paramètres de connexion")
        self.setMinimumWidth(400)
        self.setModal(True)
        
        # Variables
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
    
    def __init__(self, camera_url: str = "http://Micro-Studio-Camera-4K-G2.local", 
                 username: str = "roo", password: str = "koko"):
        super().__init__()
        self.camera_url = camera_url.rstrip('/')
        self.username = username
        self.password = password
        self.signals = CameraSignals()
        
        # Variables de connexion
        self.controller = None
        self.websocket_client = None
        self.websocket_connected = False
        self.connected = False
        
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
        
        # Variables pour les valeurs
        self.focus_sent_value = 0.0
        self.focus_actual_value = 0.0
        self.iris_sent_value = 0.0
        self.iris_actual_value = 0.0
        self.gain_sent_value = 0
        self.gain_actual_value = 0
        self.shutter_sent_value = 0
        self.shutter_actual_value = 0
        self.supported_gains = []
        self.supported_shutter_speeds = []
        
        # Initialiser l'UI
        self.init_ui()
        
        # Connecter les signaux
        self.connect_signals()
        
        # Connexion automatique si des valeurs sont disponibles
        if self.camera_url and self.username and self.password:
            self.connect_to_camera(self.camera_url, self.username, self.password)
    
    def init_ui(self):
        """Initialise l'interface utilisateur."""
        self.setWindowTitle("Contrôle Focus Blackmagic (Standalone)")
        self.setMinimumSize(1200, 700)
        
        # Activer le focus pour recevoir les événements clavier
        self.setFocusPolicy(Qt.StrongFocus)
        
        
        # Widget central avec layout horizontal
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        main_layout.setSpacing(20)
        main_layout.setContentsMargins(20, 20, 20, 20)
        
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
        
        # Ajouter les panneaux au layout
        main_layout.addWidget(self.focus_panel)
        main_layout.addWidget(self.iris_panel)
        main_layout.addWidget(self.gain_panel)
        main_layout.addWidget(self.shutter_panel)
        main_layout.addWidget(self.zoom_panel)
        main_layout.addWidget(self.controls_panel)
        
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
        """Incrémente l'iris de 0.05."""
        if not self.connected or not self.controller:
            return
        current_value = self.iris_actual_value if self.iris_actual_value is not None else self.iris_sent_value
        new_value = min(1.0, current_value + 0.05)
        self.update_iris_value(new_value)
    
    def decrement_iris(self):
        """Décrémente l'iris de 0.05."""
        if not self.connected or not self.controller:
            return
        current_value = self.iris_actual_value if self.iris_actual_value is not None else self.iris_sent_value
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
    
    def load_supported_gains(self):
        """Charge la liste des gains supportés."""
        if not self.controller:
            return
        try:
            gains = self.controller.get_supported_gains()
            if gains:
                self.supported_gains = sorted(gains)
                logger.info(f"Gains supportés chargés: {self.supported_gains}")
        except Exception as e:
            logger.error(f"Erreur lors du chargement des gains supportés: {e}")
    
    def increment_gain(self):
        """Incrémente le gain vers la valeur suivante supportée."""
        if not self.connected or not self.controller:
            return
        if not self.supported_gains:
            return
        current_value = self.gain_actual_value if self.gain_actual_value is not None else self.gain_sent_value
        try:
            current_index = self.supported_gains.index(current_value)
            if current_index < len(self.supported_gains) - 1:
                new_value = self.supported_gains[current_index + 1]
                self.update_gain_value(new_value)
        except ValueError:
            # Valeur actuelle pas dans la liste, prendre la plus proche
            nearest = min(self.supported_gains, key=lambda x: abs(x - current_value))
            nearest_index = self.supported_gains.index(nearest)
            if nearest_index < len(self.supported_gains) - 1:
                new_value = self.supported_gains[nearest_index + 1]
                self.update_gain_value(new_value)
    
    def decrement_gain(self):
        """Décrémente le gain vers la valeur précédente supportée."""
        if not self.connected or not self.controller:
            return
        if not self.supported_gains:
            return
        current_value = self.gain_actual_value if self.gain_actual_value is not None else self.gain_sent_value
        try:
            current_index = self.supported_gains.index(current_value)
            if current_index > 0:
                new_value = self.supported_gains[current_index - 1]
                self.update_gain_value(new_value)
        except ValueError:
            # Valeur actuelle pas dans la liste, prendre la plus proche
            nearest = min(self.supported_gains, key=lambda x: abs(x - current_value))
            nearest_index = self.supported_gains.index(nearest)
            if nearest_index > 0:
                new_value = self.supported_gains[nearest_index - 1]
                self.update_gain_value(new_value)
    
    def update_gain_value(self, value: int):
        """Met à jour la valeur du gain."""
        self.gain_sent_value = value
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
    
    def load_supported_shutters(self):
        """Charge la liste des vitesses de shutter supportées."""
        if not self.controller:
            return
        try:
            shutters = self.controller.get_supported_shutters()
            if shutters and 'shutterSpeeds' in shutters:
                self.supported_shutter_speeds = sorted(shutters['shutterSpeeds'])
                logger.info(f"Vitesses de shutter supportées chargées: {self.supported_shutter_speeds}")
        except Exception as e:
            logger.error(f"Erreur lors du chargement des vitesses de shutter supportées: {e}")
    
    def increment_shutter(self):
        """Incrémente le shutter vers la vitesse suivante supportée."""
        if not self.connected or not self.controller:
            return
        if not self.supported_shutter_speeds:
            return
        current_value = self.shutter_actual_value if self.shutter_actual_value is not None else self.shutter_sent_value
        try:
            current_index = self.supported_shutter_speeds.index(current_value)
            if current_index < len(self.supported_shutter_speeds) - 1:
                new_value = self.supported_shutter_speeds[current_index + 1]
                self.update_shutter_value(new_value)
        except ValueError:
            # Valeur actuelle pas dans la liste, prendre la plus proche
            nearest = min(self.supported_shutter_speeds, key=lambda x: abs(x - current_value))
            nearest_index = self.supported_shutter_speeds.index(nearest)
            if nearest_index < len(self.supported_shutter_speeds) - 1:
                new_value = self.supported_shutter_speeds[nearest_index + 1]
                self.update_shutter_value(new_value)
    
    def decrement_shutter(self):
        """Décrémente le shutter vers la vitesse précédente supportée."""
        if not self.connected or not self.controller:
            return
        if not self.supported_shutter_speeds:
            return
        current_value = self.shutter_actual_value if self.shutter_actual_value is not None else self.shutter_sent_value
        try:
            current_index = self.supported_shutter_speeds.index(current_value)
            if current_index > 0:
                new_value = self.supported_shutter_speeds[current_index - 1]
                self.update_shutter_value(new_value)
        except ValueError:
            # Valeur actuelle pas dans la liste, prendre la plus proche
            nearest = min(self.supported_shutter_speeds, key=lambda x: abs(x - current_value))
            nearest_index = self.supported_shutter_speeds.index(nearest)
            if nearest_index > 0:
                new_value = self.supported_shutter_speeds[nearest_index - 1]
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
                padding: 15px;
                font-size: 12px;
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
                padding: 15px;
                font-size: 12px;
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
                padding: 15px;
                font-size: 12px;
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
                padding: 15px;
                font-size: 12px;
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
                padding: 20px;
                font-size: 12px;
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
        layout.addSpacing(20)
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
        """Envoie l'état du zebra."""
        if not self.connected or not self.controller:
            return
        try:
            success = self.controller.set_zebra(enabled, silent=True)
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
        """Envoie l'état du focus assist."""
        if not self.connected or not self.controller:
            return
        try:
            success = self.controller.set_focus_assist(enabled, silent=True)
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
        """Envoie l'état du false color."""
        if not self.connected or not self.controller:
            return
        try:
            success = self.controller.set_false_color(enabled, silent=True)
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
        """Envoie l'état du cleanfeed."""
        if not self.connected or not self.controller:
            return
        try:
            success = self.controller.set_cleanfeed(enabled, silent=True)
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
        """Déclenche l'autofocus."""
        if not self.connected or not self.controller:
            return
        self.autofocus_btn.setEnabled(False)
        self.autofocus_btn.setText("🔍 Autofocus...")
        
        try:
            success = self.controller.do_autofocus(0.5, 0.5, silent=True)
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
        if not self.connected or not self.controller:
            return
        try:
            focus_value = self.controller.get_focus()
            if focus_value is not None:
                # Mettre à jour la valeur réelle
                self.focus_actual_value = focus_value
                self.focus_value_actual.setText(f"{focus_value:.3f}")
                
                # Mettre à jour le slider si l'utilisateur ne le touche pas
                if not self.focus_slider_user_touching:
                    slider_value = int(focus_value * 1000)
                    self.focus_slider.blockSignals(True)
                    self.focus_slider.setValue(slider_value)
                    self.focus_slider.blockSignals(False)
        except Exception as e:
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
        self.signals.websocket_status.connect(self.on_websocket_status)
    
    def on_parameter_change(self, param_name: str, param_data: dict):
        """Callback appelé quand un paramètre change via WebSocket."""
        try:
            if param_name == 'focus':
                value = param_data.get('normalised') or param_data.get('value')
                if value is not None:
                    self.signals.focus_changed.emit(float(value))
            elif param_name == 'iris':
                self.signals.iris_changed.emit(param_data)
            elif param_name == 'gain':
                value = param_data.get('gain') or param_data.get('value')
                if value is not None:
                    self.signals.gain_changed.emit(int(value))
            elif param_name == 'shutter':
                self.signals.shutter_changed.emit(param_data)
            elif param_name == 'zoom':
                self.signals.zoom_changed.emit(param_data)
            elif param_name == 'zebra':
                enabled = param_data.get('enabled') or param_data.get('value', False)
                self.signals.zebra_changed.emit(bool(enabled))
            elif param_name == 'focusAssist':
                enabled = param_data.get('enabled') or param_data.get('value', False)
                self.signals.focusAssist_changed.emit(bool(enabled))
            elif param_name == 'falseColor':
                enabled = param_data.get('enabled') or param_data.get('value', False)
                self.signals.falseColor_changed.emit(bool(enabled))
            elif param_name == 'cleanfeed':
                enabled = param_data.get('enabled') or param_data.get('value', False)
                self.signals.cleanfeed_changed.emit(bool(enabled))
        except Exception as e:
            logger.error(f"Erreur dans on_parameter_change pour {param_name}: {e}")
    
    def on_websocket_connection_status(self, connected: bool, message: str):
        """Callback appelé quand l'état de connexion WebSocket change."""
        self.websocket_connected = connected
        self.signals.websocket_status.emit(connected, message)
    
    def open_connection_dialog(self):
        """Ouvre le dialog de connexion."""
        dialog = ConnectionDialog(
            self,
            camera_url=self.camera_url,
            username=self.username,
            password=self.password,
            connected=self.connected
        )
        dialog.exec()
    
    def connect_to_camera(self, camera_url: str, username: str, password: str):
        """Se connecte à la caméra avec les paramètres fournis."""
        try:
            # Mettre à jour les valeurs de connexion
            self.camera_url = camera_url.rstrip('/')
            self.username = username
            self.password = password
            
            # Déconnecter si déjà connecté
            if self.connected:
                self.disconnect_from_camera()
            
            # Créer le contrôleur
            self.controller = BlackmagicFocusController(self.camera_url, self.username, self.password)
            
            # Se connecter au WebSocket
            self.connect_websocket()
            
            # Charger les valeurs initiales
            self.load_initial_values()
            
            # Charger les gains et shutters supportés
            self.load_supported_gains()
            self.load_supported_shutters()
            
            # Mettre à jour l'état
            self.connected = True
            self.status_label.setText(f"✓ Connecté à {self.camera_url}")
            self.status_label.setStyleSheet("color: #0f0;")
            
            # Activer tous les contrôles
            self.set_controls_enabled(True)
            
            logger.info(f"Connecté à {self.camera_url}")
        except Exception as e:
            logger.error(f"Erreur lors de la connexion: {e}")
            self.connected = False
            self.status_label.setText(f"✗ Erreur de connexion: {e}")
            self.status_label.setStyleSheet("color: #f00;")
            self.set_controls_enabled(False)
            if self.controller:
                self.controller = None
    
    def disconnect_from_camera(self):
        """Se déconnecte de la caméra."""
        try:
            # Arrêter le WebSocket
            if self.websocket_client:
                self.websocket_client.stop()
                self.websocket_client = None
            
            # Détruire le contrôleur
            self.controller = None
            
            # Mettre à jour l'état
            self.connected = False
            self.websocket_connected = False
            self.status_label.setText("✗ Déconnecté")
            self.status_label.setStyleSheet("color: #f00;")
            
            # Désactiver tous les contrôles
            self.set_controls_enabled(False)
            
            logger.info("Déconnecté de la caméra")
        except Exception as e:
            logger.error(f"Erreur lors de la déconnexion: {e}")
    
    def keyPressEvent(self, event: QKeyEvent):
        """Gère les événements clavier pour ajuster le focus avec les flèches."""
        if not self.connected or not self.controller:
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
        # Utiliser focus_sent_value pour s'assurer qu'on part de la dernière valeur envoyée
        current_value = self.focus_sent_value if self.focus_sent_value is not None else (self.focus_actual_value if self.focus_actual_value is not None else 0.0)
        new_value = max(0.0, min(1.0, current_value + increment))
        self._adjust_focus_precise(new_value)
    
    def _adjust_focus_precise(self, value: float):
        """Ajuste le focus de manière très précise."""
        # Note: focus_keyboard_adjusting n'est plus utilisé pour bloquer les mises à jour socket
        # Les valeurs socket sont toujours acceptées et affichées pour refléter l'état réel de la caméra
        
        # Mettre à jour la valeur envoyée
        self.focus_sent_value = value
        self.focus_value_sent.setText(f"{value:.3f}")
        
        # Mettre à jour le slider
        slider_value = int(value * 1000)
        self.focus_slider.blockSignals(True)
        self.focus_slider.setValue(slider_value)
        self.focus_slider.blockSignals(False)
        
        # Ajouter à la file d'attente au lieu d'envoyer directement
        if self.controller:
            # Toujours ajouter la valeur à la file (on gardera seulement la dernière lors du traitement)
            self.keyboard_focus_queue.append(value)
            # Traiter la file d'attente seulement si pas déjà en cours
            if not self.keyboard_focus_processing and not self.focus_sending:
                self._process_keyboard_focus_queue()
    
    def _process_keyboard_focus_queue(self):
        """Traite la file d'attente des valeurs clavier."""
        if not self.controller or self.keyboard_focus_processing or self.focus_sending:
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
        if not self.controller:
            self.focus_sending = False
            self.keyboard_focus_processing = False
            return
        
        if self.focus_sending:
            # Si déjà en cours, ne rien faire (sera traité dans _on_keyboard_focus_send_complete)
            return
        
        self.keyboard_focus_processing = True
        self.focus_sending = True
        
        try:
            success = self.controller.set_focus(value, silent=True)
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
    
    def connect_websocket(self):
        """Se connecte au WebSocket de la caméra."""
        if not self.controller:
            return
        try:
            self.websocket_client = BlackmagicWebSocketClient(
                self.camera_url,
                self.username,
                self.password,
                on_change_callback=self.on_parameter_change,
                on_connection_status_callback=self.on_websocket_connection_status
            )
            self.websocket_client.start()
            logger.info(f"WebSocket client démarré pour {self.camera_url}")
        except Exception as e:
            logger.error(f"Erreur lors du démarrage du WebSocket: {e}")
            self.signals.websocket_status.emit(False, f"Erreur WebSocket: {e}")
    
    def load_initial_values(self):
        """Charge les valeurs initiales depuis la caméra."""
        if not self.controller:
            return
        try:
            # Focus
            focus_value = self.controller.get_focus()
            if focus_value is not None:
                self.on_focus_changed(focus_value)
            
            # Iris
            iris_data = self.controller.get_iris()
            if iris_data:
                self.on_iris_changed(iris_data)
            
            # Gain
            gain_value = self.controller.get_gain()
            if gain_value is not None:
                self.on_gain_changed(gain_value)
            
            # Shutter
            shutter_data = self.controller.get_shutter()
            if shutter_data:
                self.on_shutter_changed(shutter_data)
            
            # Zoom
            zoom_data = self.controller.get_zoom()
            if zoom_data:
                self.on_zoom_changed(zoom_data)
            
            # Zebra
            zebra_value = self.controller.get_zebra()
            if zebra_value is not None:
                self.on_zebra_changed(zebra_value)
            
            # Focus Assist
            focusAssist_value = self.controller.get_focus_assist()
            if focusAssist_value is not None:
                self.on_focusAssist_changed(focusAssist_value)
            
            # False Color
            falseColor_value = self.controller.get_false_color()
            if falseColor_value is not None:
                self.on_falseColor_changed(falseColor_value)
            
            # Cleanfeed
            cleanfeed_value = self.controller.get_cleanfeed()
            if cleanfeed_value is not None:
                self.on_cleanfeed_changed(cleanfeed_value)
        except Exception as e:
            logger.error(f"Erreur lors du chargement des valeurs initiales: {e}")
    
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
        # Marquer que l'utilisateur touche le slider
        self.focus_slider_user_touching = True
        
        # Lire la position actuelle du slider au moment du clic
        current_slider_value = self.focus_slider.value()
        current_focus_value = current_slider_value / 1000.0
        
        # Mettre à jour l'affichage avec la valeur actuelle
        self.focus_sent_value = current_focus_value
        self.focus_value_sent.setText(f"{current_focus_value:.3f}")
        
        # Envoyer immédiatement la valeur sur laquelle l'utilisateur a cliqué (si le verrou est ouvert)
        if not self.focus_sending:
            self._send_focus_value_now(current_focus_value)
    
    def on_focus_slider_released(self):
        """Appelé quand on relâche le slider."""
        # Marquer que l'utilisateur ne touche plus le slider
        self.focus_slider_user_touching = False
        
        # Remettre immédiatement le slider à la valeur réelle du focus
        slider_value = int(self.focus_actual_value * 1000)
        self.focus_slider.blockSignals(True)
        self.focus_slider.setValue(slider_value)
        self.focus_slider.blockSignals(False)
    
    def on_focus_slider_value_changed(self, value: int):
        """Appelé quand la valeur du slider change."""
        # Envoyer SEULEMENT si l'utilisateur touche physiquement le slider
        if not self.focus_slider_user_touching:
            return
        
        # L'utilisateur touche le slider, mettre à jour l'affichage
        focus_value = value / 1000.0
        self.focus_sent_value = focus_value
        self.focus_value_sent.setText(f"{focus_value:.3f}")
        
        # Envoyer seulement si le verrou est ouvert (pas de requête en cours)
        if not self.focus_sending:
            self._send_focus_value_now(focus_value)
    
    def _send_focus_value_now(self, value: float):
        """Envoie la valeur du focus, attend la réponse, puis 50ms avant de permettre le prochain envoi."""
        if not self.connected or not self.controller:
            return
        if not self.focus_slider_user_touching:
            self.focus_sending = False
            return
        
        self.focus_sending = True
        
        try:
            # Envoyer la requête (synchrone, attend la réponse)
            success = self.controller.set_focus(value, silent=True)
            
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
            current_slider_value = self.focus_slider.value()
            current_focus_value = current_slider_value / 1000.0
            self.focus_sent_value = current_focus_value
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
        """Slot appelé quand le statut WebSocket change."""
        self.websocket_connected = connected
        if connected:
            self.status_label.setText(f"✓ {message}")
            self.status_label.setStyleSheet("color: #0f0;")
            self.connected = True
        else:
            self.status_label.setText(f"✗ {message}")
            self.status_label.setStyleSheet("color: #f00;")
            self.connected = False
    
    def save_preset(self, preset_number: int):
        """Sauvegarde les valeurs actuelles dans un preset."""
        if not self.connected or not self.controller:
            logger.warning("Impossible de sauvegarder le preset : non connecté")
            return
        
        try:
            # Récupérer les valeurs actuelles
            preset_data = {
                "focus": self.focus_actual_value,
                "iris": self.iris_actual_value,
                "gain": self.gain_actual_value,
                "shutter": self.shutter_actual_value,
                "zoom": 0.0  # Valeur par défaut si non disponible
            }
            
            # Récupérer la valeur de zoom normalisée si disponible
            try:
                zoom_data = self.controller.get_zoom()
                if zoom_data and 'normalised' in zoom_data:
                    preset_data["zoom"] = zoom_data['normalised']
            except:
                pass
            
            # Charger ou créer le fichier presets.json
            presets_file = "presets.json"
            if os.path.exists(presets_file):
                with open(presets_file, 'r') as f:
                    presets = json.load(f)
            else:
                presets = {}
            
            # Sauvegarder le preset
            presets[f"preset_{preset_number}"] = preset_data
            
            # Écrire le fichier
            with open(presets_file, 'w') as f:
                json.dump(presets, f, indent=2)
            
            logger.info(f"Preset {preset_number} sauvegardé: {preset_data}")
        except Exception as e:
            logger.error(f"Erreur lors de la sauvegarde du preset {preset_number}: {e}")
    
    def recall_preset(self, preset_number: int):
        """Rappelle et applique un preset sauvegardé."""
        if not self.connected or not self.controller:
            logger.warning("Impossible de rappeler le preset : non connecté")
            return
        
        try:
            # Charger le fichier presets.json
            presets_file = "presets.json"
            if not os.path.exists(presets_file):
                logger.warning(f"Fichier {presets_file} introuvable")
                return
            
            with open(presets_file, 'r') as f:
                presets = json.load(f)
            
            preset_key = f"preset_{preset_number}"
            if preset_key not in presets:
                logger.warning(f"Preset {preset_number} introuvable")
                return
            
            preset_data = presets[preset_key]
            
            # Appliquer les valeurs
            # Focus
            if 'focus' in preset_data:
                focus_value = float(preset_data['focus'])
                self.controller.set_focus(focus_value, silent=True)
                self.focus_sent_value = focus_value
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
                    if hasattr(self.controller, 'set_zoom'):
                        self.controller.set_zoom(zoom_value, silent=True)
                except:
                    pass
            
            logger.info(f"Preset {preset_number} rappelé: {preset_data}")
        except Exception as e:
            logger.error(f"Erreur lors du rappel du preset {preset_number}: {e}")


def main():
    """Fonction principale."""
    parser = argparse.ArgumentParser(
        description="Interface PySide6 standalone pour contrôler le focus Blackmagic",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument(
        "--url",
        default="http://Micro-Studio-Camera-4K-G2.local",
        help="URL de base de la caméra (défaut: http://Micro-Studio-Camera-4K-G2.local)"
    )
    parser.add_argument(
        "--user",
        default="roo",
        help="Nom d'utilisateur pour l'authentification (défaut: roo)"
    )
    parser.add_argument(
        "--pass",
        dest="password",
        default="koko",
        help="Mot de passe pour l'authentification (défaut: koko)"
    )
    
    args = parser.parse_args()
    
    app = QApplication(sys.argv)
    window = MainWindow(camera_url=args.url, username=args.user, password=args.password)
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

