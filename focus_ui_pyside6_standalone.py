#!/usr/bin/env python3
"""
Interface PySide6 pour contrôler le focus de la caméra Blackmagic.
Application standalone qui communique directement avec la caméra.
"""

import sys
import argparse
import logging
import time
from typing import Optional
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QSlider, QPushButton
)
from PySide6.QtCore import Qt, Signal, QObject, QTimer

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


class MainWindow(QMainWindow):
    """Fenêtre principale de l'application PySide6."""
    
    def __init__(self, camera_url: str = "http://Micro-Studio-Camera-4K-G2.local", 
                 username: str = "roo", password: str = "koko"):
        super().__init__()
        self.camera_url = camera_url.rstrip('/')
        self.username = username
        self.password = password
        self.signals = CameraSignals()
        
        # Créer le contrôleur de caméra
        self.controller = BlackmagicFocusController(self.camera_url, self.username, self.password)
        
        # Variables pour le throttling
        self.last_iris_send_time = 0
        self.last_gain_send_time = 0
        self.last_shutter_send_time = 0
        self.OTHER_MIN_INTERVAL = 500  # ms
        
        # Variables pour le slider focus
        self.focus_slider_user_touching = False  # True seulement quand l'utilisateur touche physiquement le slider
        self.focus_send_sequence = 0  # Compteur pour annuler les envois différés
        self.focus_sending = False  # True pendant qu'une requête PUT est en cours ou en attente de délai
        
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
        
        # WebSocket client
        self.websocket_client = None
        self.websocket_connected = False
        
        # Initialiser l'UI
        self.init_ui()
        
        # Connecter les signaux
        self.connect_signals()
        
        # Se connecter au WebSocket
        self.connect_websocket()
        
        # Charger les valeurs initiales
        self.load_initial_values()
        
        # Charger les gains et shutters supportés
        self.load_supported_gains()
        self.load_supported_shutters()
    
    def init_ui(self):
        """Initialise l'interface utilisateur."""
        self.setWindowTitle("Contrôle Focus Blackmagic (Standalone)")
        self.setMinimumSize(1200, 700)
        
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
        layout.addWidget(title)
        
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
        layout.addWidget(focus_display)
        
        # Slider vertical
        slider_container = QWidget()
        slider_layout = QHBoxLayout(slider_container)
        slider_layout.setContentsMargins(0, 0, 0, 0)
        
        # Slider vertical
        self.focus_slider = QSlider(Qt.Vertical)
        self.focus_slider.setMinimum(0)
        self.focus_slider.setMaximum(1000)  # 0.001 de précision
        self.focus_slider.setValue(0)
        self.focus_slider.setFixedHeight(320)
        self.focus_slider.setStyleSheet("""
            QSlider::groove:vertical {
                background: #333;
                width: 8px;
                border: 1px solid #555;
                border-radius: 4px;
            }
            QSlider::handle:vertical {
                background: #666;
                border: 1px solid #888;
                border-radius: 3px;
                width: 20px;
                height: 50px;
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
        
        slider_layout.addWidget(self.focus_slider)
        slider_layout.addWidget(slider_labels_container)
        slider_layout.addStretch()
        
        layout.addWidget(slider_container, alignment=Qt.AlignCenter)
        
        # Connecter les signaux du slider
        self.focus_slider.sliderPressed.connect(self.on_focus_slider_pressed)
        self.focus_slider.sliderReleased.connect(self.on_focus_slider_released)
        self.focus_slider.valueChanged.connect(self.on_focus_slider_value_changed)
        
        layout.addStretch()
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
        current_value = self.iris_actual_value if self.iris_actual_value is not None else self.iris_sent_value
        new_value = min(1.0, current_value + 0.05)
        self.update_iris_value(new_value)
    
    def decrement_iris(self):
        """Décrémente l'iris de 0.05."""
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
        try:
            gains = self.controller.get_supported_gains()
            if gains:
                self.supported_gains = sorted(gains)
                logger.info(f"Gains supportés chargés: {self.supported_gains}")
        except Exception as e:
            logger.error(f"Erreur lors du chargement des gains supportés: {e}")
    
    def increment_gain(self):
        """Incrémente le gain vers la valeur suivante supportée."""
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
        try:
            shutters = self.controller.get_supported_shutters()
            if shutters and 'shutterSpeeds' in shutters:
                self.supported_shutter_speeds = sorted(shutters['shutterSpeeds'])
                logger.info(f"Vitesses de shutter supportées chargées: {self.supported_shutter_speeds}")
        except Exception as e:
            logger.error(f"Erreur lors du chargement des vitesses de shutter supportées: {e}")
    
    def increment_shutter(self):
        """Incrémente le shutter vers la vitesse suivante supportée."""
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
        try:
            focus_value = self.controller.get_focus()
            if focus_value is not None:
                # Mettre à jour la valeur réelle
                self.focus_actual_value = focus_value
                self.focus_value_actual.setText(f"{focus_value:.2f}")
                
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
    
    def connect_websocket(self):
        """Se connecte au WebSocket de la caméra."""
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
        self.focus_actual_value = value
        
        # Mettre à jour l'affichage de la valeur réelle
        self.focus_value_actual.setText(f"{value:.2f}")
        
        # Mettre à jour le slider seulement si l'utilisateur ne le touche pas
        if not self.focus_slider_user_touching:
            slider_value = int(value * 1000)
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
        self.focus_value_sent.setText(f"{current_focus_value:.2f}")
        
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
        self.focus_value_sent.setText(f"{focus_value:.2f}")
        
        # Envoyer seulement si le verrou est ouvert (pas de requête en cours)
        if not self.focus_sending:
            self._send_focus_value_now(focus_value)
    
    def _send_focus_value_now(self, value: float):
        """Envoie la valeur du focus, attend la réponse, puis 50ms avant de permettre le prochain envoi."""
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
            self.focus_value_sent.setText(f"{current_focus_value:.2f}")
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
        if connected:
            self.status_label.setText(f"✓ {message}")
            self.status_label.setStyleSheet("color: #0f0;")
        else:
            self.status_label.setText(f"✗ {message}")
            self.status_label.setStyleSheet("color: #f00;")


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

