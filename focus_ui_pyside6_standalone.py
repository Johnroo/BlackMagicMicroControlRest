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
import math
from functools import partial
from typing import Optional, Dict, Any
from dataclasses import dataclass, field
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QSlider, QPushButton, QLineEdit, QDialog, QGridLayout,
    QDialogButtonBox, QSizePolicy, QDoubleSpinBox, QStackedWidget,
    QTableWidget, QTableWidgetItem, QHeaderView, QMenu, QCheckBox,
    QComboBox, QScrollArea, QGroupBox, QSpinBox
)
from PySide6.QtCore import Qt, Signal, QObject, QTimer, QEvent, QRect
from PySide6.QtGui import QResizeEvent, QKeyEvent, QPainter, QPen, QBrush, QColor, QMouseEvent, QDoubleValidator

from blackmagic_focus_control import BlackmagicFocusController, BlackmagicWebSocketClient
from state_store import StateStore
from ws_server import CompanionWsServer
from command_handler import CommandHandler
from slider_controller import SliderController
from slider_websocket_client import SliderWebSocketClient
from focus_lut import FocusLUT
from companion_controller import CompanionController
from atem_controller import AtemController
from preset_description_manager import (
    load_preset_descriptions, save_preset_descriptions,
    get_musicians, add_musician, remove_musician,
    set_preset_musician_plan, get_preset_musician_plan,
    ensure_camera_exists
)
# from zoom_lut import ZoomLUT  # Désactivé - seule la LUT 3D est utilisée

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class XYMatrixWidget(QWidget):
    """Widget personnalisé pour contrôler pan (X) et tilt (Y) via une matrice XY."""
    
    # Signal émis quand la position change (pan, tilt en valeurs normalisées 0.0-1.0)
    positionChanged = Signal(float, float)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.pan_value = 0.5  # Valeur normalisée 0.0-1.0
        self.tilt_value = 0.5  # Valeur normalisée 0.0-1.0
        self.pan_steps = 0
        self.tilt_steps = 0
        self.dragging = False
        self.setMinimumSize(200, 200)
        self.setMouseTracking(True)
    
    def setPosition(self, pan: float, tilt: float):
        """Met à jour la position (valeurs normalisées 0.0-1.0)."""
        self.pan_value = max(0.0, min(1.0, pan))
        self.tilt_value = max(0.0, min(1.0, tilt))
        self.update()
    
    def setSteps(self, pan_steps: int, tilt_steps: int):
        """Met à jour les valeurs en steps."""
        self.pan_steps = pan_steps
        self.tilt_steps = tilt_steps
        self.update()
    
    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            self.dragging = True
            self._updatePositionFromMouse(event)
    
    def mouseMoveEvent(self, event: QMouseEvent):
        if self.dragging:
            self._updatePositionFromMouse(event)
    
    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            self.dragging = False
    
    def _updatePositionFromMouse(self, event: QMouseEvent):
        """Met à jour la position à partir de la position de la souris."""
        width = self.width()
        height = self.height()
        margin = 20
        matrix_width = width - 2 * margin
        matrix_height = height - 2 * margin
        
        # Calculer la position relative dans la matrice (0.0-1.0)
        x = (event.x() - margin) / matrix_width if matrix_width > 0 else 0.5
        y = (event.y() - margin) / matrix_height if matrix_height > 0 else 0.5
        
        # Inverser Y (0.0 en haut, 1.0 en bas -> 0.0 en bas, 1.0 en haut pour tilt)
        y = 1.0 - y
        
        # Clamper les valeurs
        pan = max(0.0, min(1.0, x))
        tilt = max(0.0, min(1.0, y))
        
        self.pan_value = pan
        self.tilt_value = tilt
        self.update()
        
        # Émettre le signal
        self.positionChanged.emit(pan, tilt)
    
    def paintEvent(self, event):
        """Dessine la matrice XY."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        width = self.width()
        height = self.height()
        margin = 20
        
        # Zone de la matrice
        matrix_rect = QRect(margin, margin, width - 2 * margin, height - 2 * margin)
        
        # Dessiner le fond de la matrice
        painter.fillRect(matrix_rect, QColor(30, 30, 30))
        painter.setPen(QPen(QColor(100, 100, 100), 1))
        painter.drawRect(matrix_rect)
        
        # Dessiner la grille (lignes verticales et horizontales)
        grid_pen = QPen(QColor(60, 60, 60), 1)
        painter.setPen(grid_pen)
        
        # Lignes verticales (pour pan)
        for i in range(5):
            x = margin + (matrix_rect.width() / 4) * i
            painter.drawLine(int(x), margin, int(x), margin + matrix_rect.height())
        
        # Lignes horizontales (pour tilt)
        for i in range(5):
            y = margin + (matrix_rect.height() / 4) * i
            painter.drawLine(margin, int(y), margin + matrix_rect.width(), int(y))
        
        # Dessiner les axes centraux
        center_pen = QPen(QColor(150, 150, 150), 2)
        painter.setPen(center_pen)
        center_x = margin + matrix_rect.width() / 2
        center_y = margin + matrix_rect.height() / 2
        painter.drawLine(int(center_x), margin, int(center_x), margin + matrix_rect.height())
        painter.drawLine(margin, int(center_y), margin + matrix_rect.width(), int(center_y))
        
        # Dessiner le point de position actuelle
        point_x = margin + matrix_rect.width() * self.pan_value
        point_y = margin + matrix_rect.height() * (1.0 - self.tilt_value)  # Inverser Y
        
        # Cercle extérieur (blanc)
        painter.setPen(QPen(QColor(255, 255, 255), 2))
        painter.setBrush(QBrush(QColor(255, 255, 255)))
        painter.drawEllipse(int(point_x - 6), int(point_y - 6), 12, 12)
        
        # Cercle intérieur (cyan)
        painter.setPen(QPen(QColor(0, 255, 255), 1))
        painter.setBrush(QBrush(QColor(0, 255, 255)))
        painter.drawEllipse(int(point_x - 4), int(point_y - 4), 8, 8)
        
        # Labels des axes
        label_pen = QPen(QColor(200, 200, 200), 1)
        painter.setPen(label_pen)
        font = painter.font()
        font.setPointSize(9)
        painter.setFont(font)
        
        # Label Pan (X) en bas
        painter.drawText(margin, height - 5, "Pan (X)")
        # Label Tilt (Y) à gauche (rotation)
        painter.save()
        painter.translate(10, margin + matrix_rect.height() / 2)
        painter.rotate(-90)
        painter.drawText(0, 0, "Tilt (Y)")
        painter.restore()


class Joystick2DWidget(QWidget):
    """Widget personnalisé pour contrôler pan (X) et tilt (Y) via un joystick circulaire 2D."""
    
    # Signal émis quand la position change (pan, tilt en valeurs -1.0 à +1.0)
    positionChanged = Signal(float, float)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.pan_value = 0.0  # Valeur -1.0 à +1.0
        self.tilt_value = 0.0  # Valeur -1.0 à +1.0
        self.dragging = False
        self.setMinimumSize(200, 200)
        self.setMouseTracking(True)
    
    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            self.dragging = True
            self._updatePositionFromMouse(event)
    
    def mouseMoveEvent(self, event: QMouseEvent):
        if self.dragging:
            self._updatePositionFromMouse(event)
    
    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            self.dragging = False
            # Revenir au centre
            self.pan_value = 0.0
            self.tilt_value = 0.0
            self.update()
            # Émettre le signal avec les valeurs à 0.0
            self.positionChanged.emit(0.0, 0.0)
    
    def setPosition(self, pan: float, tilt: float):
        """Met à jour la position programmatiquement sans émettre le signal (pour mise à jour visuelle depuis le clavier)."""
        # Clamper les valeurs entre -1.0 et 1.0
        self.pan_value = max(-1.0, min(1.0, pan))
        self.tilt_value = max(-1.0, min(1.0, tilt))
        self.update()  # Redessiner sans émettre le signal
    
    def _updatePositionFromMouse(self, event: QMouseEvent):
        """Met à jour la position à partir de la position de la souris."""
        width = self.width()
        height = self.height()
        center_x = width / 2
        center_y = height / 2
        radius = min(width, height) / 2 - 20  # Marge de 20px
        
        # Calculer la distance et l'angle depuis le centre
        dx = event.x() - center_x
        dy = event.y() - center_y
        distance = math.sqrt(dx * dx + dy * dy)
        
        # Normaliser la distance (0.0 au centre, 1.0 au bord)
        normalized_distance = min(1.0, distance / radius) if radius > 0 else 0.0
        
        # Calculer l'angle
        angle = math.atan2(dy, dx)
        
        # Convertir en valeurs pan/tilt (-1.0 à +1.0)
        # Inverser tilt pour que descendre = négatif
        pan = normalized_distance * math.cos(angle)
        tilt = -normalized_distance * math.sin(angle)  # Inversé : quand on descend (dy positif), tilt devient négatif
        
        # Clamper les valeurs
        pan = max(-1.0, min(1.0, pan))
        tilt = max(-1.0, min(1.0, tilt))
        
        self.pan_value = pan
        self.tilt_value = tilt
        self.update()
        
        # Émettre le signal
        self.positionChanged.emit(pan, tilt)
    
    def paintEvent(self, event):
        """Dessine le joystick 2D."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        width = self.width()
        height = self.height()
        center_x = width / 2
        center_y = height / 2
        radius = min(width, height) / 2 - 20
        
        # Dessiner le cercle extérieur
        circle_rect = QRect(int(center_x - radius), int(center_y - radius), 
                           int(radius * 2), int(radius * 2))
        painter.setPen(QPen(QColor(100, 100, 100), 2))
        painter.setBrush(QBrush(QColor(30, 30, 30)))
        painter.drawEllipse(circle_rect)
        
        # Dessiner la grille (lignes de centre)
        painter.setPen(QPen(QColor(60, 60, 60), 1))
        painter.drawLine(int(center_x), int(center_y - radius), 
                        int(center_x), int(center_y + radius))
        painter.drawLine(int(center_x - radius), int(center_y), 
                        int(center_x + radius), int(center_y))
        
        # Dessiner le point de position actuelle
        # tilt est inversé dans le calcul, donc on inverse aussi pour l'affichage
        point_x = center_x + self.pan_value * radius
        point_y = center_y - self.tilt_value * radius  # Inversé pour l'affichage
        
        # Cercle extérieur (blanc)
        painter.setPen(QPen(QColor(255, 255, 255), 2))
        painter.setBrush(QBrush(QColor(255, 255, 255)))
        painter.drawEllipse(int(point_x - 8), int(point_y - 8), 16, 16)
        
        # Cercle intérieur (cyan)
        painter.setPen(QPen(QColor(0, 255, 255), 1))
        painter.setBrush(QBrush(QColor(0, 255, 255)))
        painter.drawEllipse(int(point_x - 5), int(point_y - 5), 10, 10)
        
        # Labels des axes
        label_pen = QPen(QColor(200, 200, 200), 1)
        painter.setPen(label_pen)
        font = painter.font()
        font.setPointSize(9)
        painter.setFont(font)
        
        # Label Pan (X) en bas
        painter.drawText(int(center_x - 20), int(height - 5), "Pan")
        # Label Tilt (Y) à gauche
        painter.save()
        painter.translate(10, int(center_y))
        painter.rotate(-90)
        painter.drawText(0, 0, "Tilt")
        painter.restore()


class RotaryKnobWidget(QWidget):
    """Widget personnalisé pour contrôler un axe via un bouton rotatif."""
    
    # Signal émis quand la valeur change (-1.0 à +1.0)
    valueChanged = Signal(float)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.value = 0.0  # Valeur -1.0 à +1.0
        self.dragging = False
        self.initial_angle = 0.0
        self.accumulated_rotation = 0.0
        self.setMinimumSize(120, 120)
        self.setMouseTracking(True)
    
    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            self.dragging = True
            self.initial_angle = self._getAngleFromMouse(event)
            self.accumulated_rotation = 0.0
    
    def mouseMoveEvent(self, event: QMouseEvent):
        if self.dragging:
            current_angle = self._getAngleFromMouse(event)
            # Calculer la différence d'angle
            angle_diff = current_angle - self.initial_angle
            
            # Gérer le passage par -π/+π
            if angle_diff > math.pi:
                angle_diff -= 2 * math.pi
            elif angle_diff < -math.pi:
                angle_diff += 2 * math.pi
            
            # Accumuler la rotation
            self.accumulated_rotation += angle_diff
            self.initial_angle = current_angle
            
            # Convertir la rotation accumulée en valeur -1.0 à +1.0
            # Une rotation complète (2π) = 1.0
            self.value = max(-1.0, min(1.0, self.accumulated_rotation / (2 * math.pi)))
            self.update()
            
            # Émettre le signal
            self.valueChanged.emit(self.value)
    
    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            self.dragging = False
            # Revenir à 0.0
            self.value = 0.0
            self.accumulated_rotation = 0.0
            self.update()
            # Émettre le signal avec la valeur à 0.0
            self.valueChanged.emit(0.0)
    
    def _getAngleFromMouse(self, event: QMouseEvent) -> float:
        """Calcule l'angle de la souris par rapport au centre."""
        width = self.width()
        height = self.height()
        center_x = width / 2
        center_y = height / 2
        
        dx = event.x() - center_x
        dy = center_y - event.y()  # Inverser Y pour avoir 0° en haut
        
        return math.atan2(dy, dx)
    
    def paintEvent(self, event):
        """Dessine le bouton rotatif."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        width = self.width()
        height = self.height()
        center_x = width / 2
        center_y = height / 2
        radius = min(width, height) / 2 - 10
        
        # Dessiner le cercle extérieur
        circle_rect = QRect(int(center_x - radius), int(center_y - radius), 
                           int(radius * 2), int(radius * 2))
        painter.setPen(QPen(QColor(100, 100, 100), 2))
        painter.setBrush(QBrush(QColor(30, 30, 30)))
        painter.drawEllipse(circle_rect)
        
        # Dessiner les marqueurs aux positions -1.0, 0.0, +1.0
        marker_pen = QPen(QColor(80, 80, 80), 1)
        painter.setPen(marker_pen)
        
        # Marqueur à 12h (0.0)
        marker_length = 8
        painter.drawLine(int(center_x), int(center_y - radius), 
                        int(center_x), int(center_y - radius + marker_length))
        
        # Marqueur à 3h (+1.0)
        marker_x = center_x + radius * math.cos(0)
        marker_y = center_y - radius * math.sin(0)
        painter.drawLine(int(marker_x), int(marker_y), 
                        int(marker_x - marker_length), int(marker_y))
        
        # Marqueur à 9h (-1.0)
        marker_x = center_x + radius * math.cos(math.pi)
        marker_y = center_y - radius * math.sin(math.pi)
        painter.drawLine(int(marker_x), int(marker_y), 
                        int(marker_x + marker_length), int(marker_y))
        
        # Calculer l'angle de l'indicateur basé sur la valeur
        # 0.0 = 12h (angle 0), +1.0 = rotation complète horaire, -1.0 = rotation complète anti-horaire
        indicator_angle = self.value * 2 * math.pi
        
        # Dessiner l'indicateur (ligne pointant vers la position)
        indicator_length = radius - 5
        indicator_end_x = center_x + indicator_length * math.cos(indicator_angle)
        indicator_end_y = center_y - indicator_length * math.sin(indicator_angle)
        
        painter.setPen(QPen(QColor(0, 255, 255), 3))
        painter.drawLine(int(center_x), int(center_y), 
                        int(indicator_end_x), int(indicator_end_y))
        
        # Dessiner un point au centre
        painter.setPen(QPen(QColor(255, 255, 255), 1))
        painter.setBrush(QBrush(QColor(255, 255, 255)))
        painter.drawEllipse(int(center_x - 3), int(center_y - 3), 6, 6)


@dataclass
class CameraData:
    """Données pour une caméra."""
    # Configuration
    url: str = ""
    username: str = ""
    password: str = ""
    slider_ip: str = ""
    companion_page: int = 1  # Numéro de page Companion pour cette caméra
    
    # Connexions
    controller: Optional[Any] = None  # BlackmagicFocusController
    websocket_client: Optional[Any] = None  # BlackmagicWebSocketClient
    slider_websocket_client: Optional[Any] = None  # SliderWebSocketClient
    connected: bool = False
    connecting: bool = False  # Flag pour indiquer qu'une connexion est en cours
    slider_connecting: bool = False  # Flag pour indiquer qu'une connexion slider est en cours
    auto_reconnect_enabled: bool = True  # Flag pour activer/désactiver les reconnexions automatiques de la caméra
    slider_auto_reconnect_enabled: bool = True  # Flag pour activer/désactiver les reconnexions automatiques du slider
    
    # Valeurs
    focus_sent_value: float = 0.0
    focus_actual_value: float = 0.0
    iris_sent_value: float = 0.0
    iris_actual_value: float = 0.0
    iris_aperture_stop: Optional[float] = None  # Aperture stop (f/2.8, f/4, etc.) pour Companion
    iris_aperture_number: Optional[int] = None  # Aperture number (entier) pour les ajustements relatifs
    gain_sent_value: int = 0
    gain_actual_value: int = 0
    shutter_sent_value: int = 0
    shutter_actual_value: int = 0
    whitebalance_sent_value: int = 0
    whitebalance_actual_value: int = 0
    whitebalance_min: int = 0
    whitebalance_max: int = 0
    tint_sent_value: int = 0
    tint_actual_value: int = 0
    tint_min: int = 0
    tint_max: int = 0
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
    
    # Sequences
    sequences: list = field(default_factory=list)  # Liste des séquences sauvegardées
    
    # Presets
    presets: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    active_preset: Optional[int] = None  # Numéro du preset actuellement actif (1-10)
    
    # Recall Scope - paramètres à exclure lors du recall (True = exclu, False = inclus)
    recall_scope: Dict[str, bool] = field(default_factory=lambda: {
        'focus': False,
        'iris': False,
        'gain': False,
        'shutter': False,
        'whitebalance': False,
        'slider': False
    })
    
    # Crossfade duration - durée du crossfade entre presets en secondes
    crossfade_duration: float = 2.0  # Durée du crossfade en secondes (défaut: 2.0)
    
    # Throttling pour les autres paramètres
    last_iris_send_time: int = 0
    last_gain_send_time: int = 0
    last_shutter_send_time: int = 0
    
    # Valeurs actuelles du slider (normalized 0.0-1.0)
    slider_pan_value: float = 0.0
    slider_tilt_value: float = 0.0
    slider_zoom_value: float = 0.0
    slider_slide_value: float = 0.0
    
    # Steps actuels du slider
    slider_pan_steps: int = 0
    slider_tilt_steps: int = 0
    slider_zoom_steps: int = 0
    slider_slide_steps: int = 0
    
    # Offsets joystick actuels (normalized -1.0 à +1.0)
    slider_joystick_pan_offset: float = 0.0
    slider_joystick_tilt_offset: float = 0.0
    slider_joystick_zoom_offset: float = 0.0
    slider_joystick_slide_offset: float = 0.0


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
    whitebalance_changed = Signal(int)
    tint_changed = Signal(int)
    websocket_status = Signal(bool, str)


class ConnectionDialog(QDialog):
    """Dialog pour la configuration ATEM Switcher."""
    
    def __init__(self, parent=None, atem_config: dict = None):
        super().__init__(parent)
        self.setWindowTitle("Configuration ATEM Switcher")
        self.setMinimumWidth(450)
        self.setModal(True)
        
        # Variables
        self.atem_config = atem_config or {}
        
        # Layout principal
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Titre
        title = QLabel("Configuration ATEM Switcher")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #fff;")
        layout.addWidget(title)
        
        # Section Configuration
        config_group = QGroupBox("Configuration")
        config_group.setStyleSheet("""
            QGroupBox {
                font-size: 14px;
                font-weight: bold;
                color: #fff;
                border: 2px solid #555;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
        """)
        config_layout = QVBoxLayout(config_group)
        config_layout.setSpacing(15)
        
        # IP ATEM
        ip_layout = QHBoxLayout()
        ip_label = QLabel("IP ATEM:")
        ip_label.setMinimumWidth(120)
        ip_label.setStyleSheet("font-size: 12px; color: #aaa;")
        ip_layout.addWidget(ip_label)
        self.atem_ip_input = QLineEdit()
        self.atem_ip_input.setPlaceholderText("192.168.1.100")
        self.atem_ip_input.setText(self.atem_config.get("ip", ""))
        self.atem_ip_input.setStyleSheet("""
            QLineEdit {
                padding: 8px;
                background-color: #333;
                border: 1px solid #555;
                border-radius: 4px;
                color: #fff;
            }
            QLineEdit:focus {
                border: 2px solid #0a5;
            }
        """)
        ip_layout.addWidget(self.atem_ip_input)
        config_layout.addLayout(ip_layout)
        
        # AUX Output
        aux_layout = QHBoxLayout()
        aux_label = QLabel("AUX Output:")
        aux_label.setMinimumWidth(120)
        aux_label.setStyleSheet("font-size: 12px; color: #aaa;")
        aux_layout.addWidget(aux_label)
        self.atem_aux_spinbox = QSpinBox()
        self.atem_aux_spinbox.setMinimum(1)
        self.atem_aux_spinbox.setMaximum(6)
        self.atem_aux_spinbox.setValue(self.atem_config.get("aux_output", 2))
        self.atem_aux_spinbox.setStyleSheet("""
            QSpinBox {
                padding: 8px;
                background-color: #333;
                border: 1px solid #555;
                border-radius: 4px;
                color: #fff;
                font-size: 12px;
                min-width: 100px;
            }
            QSpinBox:focus {
                border: 2px solid #0a5;
            }
        """)
        aux_layout.addWidget(self.atem_aux_spinbox)
        config_layout.addLayout(aux_layout)
        
        # Bouton Sauvegarder
        save_btn = QPushButton("Sauvegarder")
        save_btn.clicked.connect(self.save_config)
        save_btn.setStyleSheet("""
            QPushButton {
                padding: 10px 20px;
                background-color: #0a5;
                border: none;
                border-radius: 6px;
                color: #fff;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #0b6;
            }
            QPushButton:pressed {
                background-color: #094;
            }
        """)
        config_layout.addWidget(save_btn)
        layout.addWidget(config_group)
        
        # Section État de connexion
        status_group = QGroupBox("État de connexion")
        status_group.setStyleSheet("""
            QGroupBox {
                font-size: 14px;
                font-weight: bold;
                color: #fff;
                border: 2px solid #555;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
        """)
        status_layout = QVBoxLayout(status_group)
        status_layout.setSpacing(15)
        
        # Indicateur LED et label d'état
        status_indicator_layout = QHBoxLayout()
        self.status_indicator = QLabel("●")
        self.status_indicator.setStyleSheet("font-size: 24px; color: #f00;")
        status_indicator_layout.addWidget(self.status_indicator)
        self.status_text = QLabel("Déconnecté")
        self.status_text.setStyleSheet("font-size: 14px; color: #f00; font-weight: bold;")
        status_indicator_layout.addWidget(self.status_text)
        status_indicator_layout.addStretch()
        status_layout.addLayout(status_indicator_layout)
        
        # Bouton Connecter/Déconnecter
        self.connect_btn = QPushButton("Connecter")
        self.connect_btn.clicked.connect(self.toggle_connection)
        self.connect_btn.setStyleSheet("""
            QPushButton {
                padding: 10px 20px;
                background-color: #0a5;
                border: none;
                border-radius: 6px;
                color: #fff;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #0b6;
            }
            QPushButton:pressed {
                background-color: #094;
            }
        """)
        status_layout.addWidget(self.connect_btn)
        layout.addWidget(status_group)
        
        # Section Informations
        info_group = QGroupBox("Informations")
        info_group.setStyleSheet("""
            QGroupBox {
                font-size: 14px;
                font-weight: bold;
                color: #fff;
                border: 2px solid #555;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
        """)
        info_layout = QVBoxLayout(info_group)
        info_layout.setSpacing(10)
        
        self.info_ip = QLabel("IP: -")
        self.info_ip.setStyleSheet("font-size: 12px; color: #aaa;")
        info_layout.addWidget(self.info_ip)
        
        self.info_aux = QLabel("AUX Output: -")
        self.info_aux.setStyleSheet("font-size: 12px; color: #aaa;")
        info_layout.addWidget(self.info_aux)
        
        self.info_last_camera = QLabel("Dernière caméra: -")
        self.info_last_camera.setStyleSheet("font-size: 12px; color: #aaa;")
        info_layout.addWidget(self.info_last_camera)
        
        layout.addWidget(info_group)
        
        # Boutons de dialog
        button_box = QDialogButtonBox(QDialogButtonBox.Close)
        button_box.rejected.connect(self.accept)
        layout.addWidget(button_box)
        
        # Mettre à jour l'affichage initial
        self.update_atem_status()
    
    def toggle_connection(self):
        """Gère la connexion/déconnexion ATEM."""
        if self.parent():
            self.parent().on_atem_connect_clicked()
            # Mettre à jour l'affichage après un court délai pour laisser le temps à la connexion
            QTimer.singleShot(100, self.update_atem_status)
    
    def save_config(self):
        """Sauvegarde la configuration ATEM."""
        if not self.parent():
            return
        
        new_ip = self.atem_ip_input.text().strip()
        new_aux_output = self.atem_aux_spinbox.value()
        
        if not new_ip:
            logger.warning("IP ATEM non renseignée")
            return
        
        # Mettre à jour la config via le parent
        old_ip = self.atem_config.get("ip", "")
        self.atem_config["ip"] = new_ip
        self.atem_config["aux_output"] = new_aux_output
        
        # Sauvegarder dans le fichier
        self.parent().atem_config = self.atem_config
        self.parent().save_cameras_config()
        
        # Si l'IP a changé, réinitialiser le controller
        if old_ip != new_ip:
            if self.parent().atem_controller:
                self.parent().atem_controller.disconnect()
            self.parent().init_atem_controller()
        elif self.parent().atem_controller:
            # Si seul l'AUX output a changé, mettre à jour
            self.parent().atem_controller.aux_output = new_aux_output
        
        logger.info(f"Configuration ATEM sauvegardée: IP={new_ip}, AUX={new_aux_output}")
        self.update_atem_status()
    
    def update_atem_status(self):
        """Met à jour l'affichage du statut ATEM."""
        if not self.parent():
            return
        
        connected = self.parent().atem_config.get("connected", False)
        auto_reconnect = self.parent().atem_config.get("auto_reconnect_enabled", True)
        controller_running = False
        if self.parent().atem_controller:
            controller_running = getattr(self.parent().atem_controller, 'running', False)
        
        # Mettre à jour l'indicateur LED
        if connected:
            self.status_indicator.setStyleSheet("font-size: 24px; color: #0f0;")
            self.status_text.setText("Connecté")
            self.status_text.setStyleSheet("font-size: 14px; color: #0f0; font-weight: bold;")
            self.connect_btn.setText("Déconnecter")
            self.connect_btn.setEnabled(True)
            self.connect_btn.setStyleSheet("""
                QPushButton {
                    padding: 10px 20px;
                    background-color: #a50;
                    border: none;
                    border-radius: 6px;
                    color: #fff;
                    font-size: 14px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #b60;
                }
                QPushButton:pressed {
                    background-color: #940;
                }
            """)
        else:
            if auto_reconnect and controller_running:
                # Des tentatives automatiques sont en cours
                self.status_indicator.setStyleSheet("font-size: 24px; color: #ffa500;")
                self.status_text.setText("Déconnecté (reconnexion auto...)")
                self.status_text.setStyleSheet("font-size: 14px; color: #ffa500; font-weight: bold;")
                self.connect_btn.setText("Arrêter les tentatives")
                self.connect_btn.setEnabled(True)
                self.connect_btn.setStyleSheet("""
                    QPushButton {
                        padding: 10px 20px;
                        background-color: #ff8c00;
                    border: none;
                        border-radius: 6px;
                        color: #fff;
                        font-size: 14px;
                        font-weight: bold;
                }
                QPushButton:hover {
                        background-color: #ff9f33;
                    }
                    QPushButton:pressed {
                        background-color: #e67e00;
                }
            """)
            else:
                # Aucune tentative automatique
                self.status_indicator.setStyleSheet("font-size: 24px; color: #f00;")
                self.status_text.setText("Déconnecté")
                self.status_text.setStyleSheet("font-size: 14px; color: #f00; font-weight: bold;")
                self.connect_btn.setText("Connecter")
                self.connect_btn.setEnabled(True)
                self.connect_btn.setStyleSheet("""
                    QPushButton {
                        padding: 10px 20px;
                        background-color: #0a5;
                        border: none;
                        border-radius: 6px;
                        color: #fff;
                        font-size: 14px;
                        font-weight: bold;
                    }
                    QPushButton:hover {
                        background-color: #0b6;
                    }
                    QPushButton:pressed {
                        background-color: #094;
                    }
                """)
        
        # Mettre à jour les informations
        ip = self.parent().atem_config.get("ip", "")
        aux_output = self.parent().atem_config.get("aux_output", 2)
        self.info_ip.setText(f"IP: {ip if ip else '-'}")
        self.info_aux.setText(f"AUX Output: {aux_output} (HDMI {aux_output})")
        
        # Dernière caméra
        if self.parent().atem_controller:
            last_camera = self.parent().atem_controller.get_last_camera_id()
            if last_camera:
                self.info_last_camera.setText(f"Dernière caméra: Caméra {last_camera}")
            else:
                self.info_last_camera.setText("Dernière caméra: -")
        else:
            self.info_last_camera.setText("Dernière caméra: -")


class UIScaler:
    """Gère le scaling adaptatif de l'UI basé sur la taille de la fenêtre."""
    
    # Taille de référence (base pour tous les calculs)
    REFERENCE_WIDTH = 1512
    REFERENCE_HEIGHT = 982
    
    def __init__(self, window: QMainWindow):
        self.window = window
        self._update_scale()
        # Écouter les changements de taille
        window.resizeEvent = self._on_resize
    
    def _on_resize(self, event):
        """Appelé quand la fenêtre est redimensionnée."""
        QMainWindow.resizeEvent(self.window, event)
        self._update_scale()
        # Notifier que le scale a changé pour mettre à jour l'UI
        if hasattr(self.window, '_update_ui_scaling'):
            QTimer.singleShot(50, self.window._update_ui_scaling)
    
    def _update_scale(self):
        """Met à jour les facteurs d'échelle basés sur la taille actuelle de la fenêtre."""
        size = self.window.size()
        self.scale_x = size.width() / self.REFERENCE_WIDTH
        self.scale_y = size.height() / self.REFERENCE_HEIGHT
        # Utiliser le plus petit facteur pour maintenir les proportions
        self.scale = min(self.scale_x, self.scale_y)
        # Limiter le scale entre 0.5 et 2.0 pour éviter les tailles extrêmes
        self.scale = max(0.5, min(2.0, self.scale))
    
    def scale_value(self, value: float) -> int:
        """Convertit une valeur de référence en valeur scaled."""
        return int(value * self.scale)
    
    def scale_font_size(self, size: float) -> str:
        """Retourne une taille de police scaled en string pour CSS."""
        return f"{int(size * self.scale)}px"
    
    def scale_style(self, style: str) -> str:
        """Applique le scaling à un style CSS en remplaçant les valeurs numériques."""
        import re
        # Éviter de modifier les couleurs hexadécimales (#666, #123456, etc.)
        # D'abord, protéger les couleurs hexadécimales en les remplaçant temporairement
        hex_color_pattern = r'#([0-9a-fA-F]{3,6})(?![0-9a-fA-F])'
        hex_colors = {}
        hex_counter = [0]  # Utiliser une liste pour la mutabilité dans la closure
        
        def protect_hex(match):
            hex_value = match.group(0)
            placeholder = f"__HEX_COLOR_{hex_counter[0]}__"
            hex_colors[placeholder] = hex_value
            hex_counter[0] += 1
            return placeholder
        
        # Protéger les couleurs hex
        protected_style = re.sub(hex_color_pattern, protect_hex, style)
        
        # Maintenant, remplacer les valeurs px
        def replace_px(match):
            value = float(match.group(1))
            scaled_value = int(value * self.scale)
            # Limiter les valeurs à une plage raisonnable pour éviter les problèmes
            scaled_value = max(0, min(99999, scaled_value))
            return f"{scaled_value}px"
        
        # Pattern pour les valeurs px (maintenant sans risque de toucher aux couleurs)
        px_pattern = r'(\d+(?:\.\d+)?)px'
        scaled_style = re.sub(px_pattern, replace_px, protected_style)
        
        # Restaurer les couleurs hex
        for placeholder, hex_color in hex_colors.items():
            scaled_style = scaled_style.replace(placeholder, hex_color)
        
        return scaled_style


class UIScaler:
    """Gère le scaling adaptatif de l'UI basé sur la taille de la fenêtre."""
    
    # Taille de référence (base pour tous les calculs)
    REFERENCE_WIDTH = 1512
    REFERENCE_HEIGHT = 982
    
    def __init__(self, window: QMainWindow):
        self.window = window
        self._update_scale()
        # Sauvegarder la méthode resizeEvent originale
        self._original_resize_event = window.resizeEvent
    
    def _update_scale(self):
        """Met à jour les facteurs d'échelle basés sur la taille actuelle de la fenêtre."""
        size = self.window.size()
        self.scale_x = size.width() / self.REFERENCE_WIDTH
        self.scale_y = size.height() / self.REFERENCE_HEIGHT
        # Utiliser le plus petit facteur pour maintenir les proportions
        self.scale = min(self.scale_x, self.scale_y)
        # Limiter le scale entre 0.5 et 2.0 pour éviter les tailles extrêmes
        self.scale = max(0.5, min(2.0, self.scale))
    
    def scale_value(self, value: float) -> int:
        """Convertit une valeur de référence en valeur scaled."""
        return int(value * self.scale)
    
    def scale_font_size(self, size: float) -> str:
        """Retourne une taille de police scaled en string pour CSS."""
        return f"{int(size * self.scale)}px"
    
    def scale_style(self, style: str) -> str:
        """Applique le scaling à un style CSS en remplaçant les valeurs numériques."""
        import re
        # Éviter de modifier les couleurs hexadécimales (#666, #123456, etc.)
        # D'abord, protéger les couleurs hexadécimales en les remplaçant temporairement
        hex_color_pattern = r'#([0-9a-fA-F]{3,6})(?![0-9a-fA-F])'
        hex_colors = {}
        hex_counter = [0]  # Utiliser une liste pour la mutabilité dans la closure
        
        def protect_hex(match):
            hex_value = match.group(0)
            placeholder = f"__HEX_COLOR_{hex_counter[0]}__"
            hex_colors[placeholder] = hex_value
            hex_counter[0] += 1
            return placeholder
        
        # Protéger les couleurs hex
        protected_style = re.sub(hex_color_pattern, protect_hex, style)
        
        # Maintenant, remplacer les valeurs px
        def replace_px(match):
            value = float(match.group(1))
            scaled_value = int(value * self.scale)
            # Limiter les valeurs à une plage raisonnable pour éviter les problèmes
            scaled_value = max(0, min(99999, scaled_value))
            return f"{scaled_value}px"
        
        # Pattern pour les valeurs px (maintenant sans risque de toucher aux couleurs)
        px_pattern = r'(\d+(?:\.\d+)?)px'
        scaled_style = re.sub(px_pattern, replace_px, protected_style)
        
        # Restaurer les couleurs hex
        for placeholder, hex_color in hex_colors.items():
            scaled_style = scaled_style.replace(placeholder, hex_color)
        
        return scaled_style


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
        
        # UIScaler pour le scaling adaptatif (sera initialisé après init_ui)
        self.ui_scaler = None
        
        # UIScaler pour le scaling adaptatif (sera initialisé après init_ui)
        self.ui_scaler = None
        
        # CommandHandler pour traiter les commandes Companion
        self.command_handler = CommandHandler()
        
        # Companion Controller sera initialisé après le chargement de la config
        self.companion_controller = None
        
        # ATEM Controller sera initialisé après le chargement de la config
        self.atem_controller: Optional[AtemController] = None
        self.atem_config = {"ip": "", "aux_output": 2, "connected": False, "auto_reconnect_enabled": True}
        self.atem_dialog = None  # Référence au dialog ATEM si ouvert
        
        # Variables de connexion (remplacées par cameras dict)
        self.cameras: Dict[int, CameraData] = {}
        self.active_camera_id: int = 1
        
        # Configuration globale (pas par caméra)
        self.sequences_column_widths: Optional[Dict[str, float]] = None  # Largeurs des colonnes du tableau Sequences (global)
        
        # Variables pour le throttling (les timestamps sont maintenant dans CameraData)
        self.OTHER_MIN_INTERVAL = 500  # ms
        
        # Variables pour le slider focus
        self.focus_slider_user_touching = False  # True seulement quand l'utilisateur touche physiquement le slider
        self.focus_send_sequence = 0  # Compteur pour annuler les envois différés
        self.focus_sending = False  # True pendant qu'une requête PUT est en cours ou en attente de délai
        self.focus_keyboard_adjusting = False  # True quand on ajuste avec les flèches clavier
        
        
        # Variables pour white balance
        self.whitebalance_sending = False  # True pendant qu'une requête PUT est en cours ou en attente de délai
        self.tint_sending = False  # True pendant qu'une requête PUT est en cours ou en attente de délai
        
        # Variables pour la répétition des touches flèches
        self.key_repeat_timer = None
        self.key_repeat_direction = None  # 'up' ou 'down'
        self.joystick_key_repeat_timer: Optional[QTimer] = None  # Timer pour répétition des touches joystick
        
        # File d'attente pour les valeurs clavier (pour ne pas perdre de valeurs)
        self.keyboard_focus_queue = []
        self.keyboard_focus_processing = False
        
        # Transition progressive entre presets
        self.smooth_preset_transition = True  # Activé par défaut
        self.preset_transition_timer = None
        self.preset_transition_start_time = None
        self.preset_transition_start_values = {}
        self.preset_transition_target_values = {}
        
        # Recall scope checkboxes (initialisé dans create_presets_panel)
        self.recall_scope_checkboxes = {}
        
        # Champs distance pour les presets (initialisé dans create_presets_panel)
        self.preset_distance_inputs: list = []
        
        # Sequences data (20 séquences)
        self.sequences_data: list = [{
            "name": "",
            "points": {0.0: None, 0.25: None, 0.5: None, 0.75: None, 1.0: None},
            "duration": 5.0,
            "baked": False
        } for _ in range(20)]
        self.sequences_table: Optional[QTableWidget] = None
        self.active_sequence_row: Optional[int] = None  # Ligne de la séquence active
        self.focus_transition_timer: Optional[QTimer] = None  # Timer pour la transition de focus
        self.focus_transition_start: Optional[float] = None  # Valeur de départ de la transition
        self.focus_transition_end: Optional[float] = None  # Valeur d'arrivée de la transition
        self.focus_transition_start_time: Optional[float] = None  # Temps de début de la transition
        self.focus_transition_duration: float = 3.0  # Durée de la transition en secondes
        
        # Slider controllers pour chaque caméra (initialisés après chargement de la config)
        self.slider_controllers: Dict[int, Optional[SliderController]] = {}
        
        # Variables pour les sliders (pan, tilt, slide, zoom motor)
        self.slider_user_touching = {
            'pan': False,
            'tilt': False,
            'slide': False,
            'zoom': False
        }
        # Tracker si une commande a été envoyée pendant l'interaction (pour gérer les clics courts)
        self.slider_command_sent = {
            'pan': False,
            'tilt': False,
            'slide': False,
            'zoom': False
        }
        
        # Variables pour le LFO (Low Frequency Oscillator)
        self.lfo_active: bool = False
        self.lfo_amplitude: float = 0.4  # Amplitude normalisée (0.0-1.0)
        self.lfo_speed: float = 15.0  # Vitesse en secondes/cycle (1-60)
        self.lfo_distance: float = 1.0  # Distance du sujet en mètres (0.5-20)
        self.lfo_timer: Optional[QTimer] = None
        self.lfo_position_plus: Optional[dict] = None  # {slide: float, pan: float} - valeurs calculées
        self.lfo_position_minus: Optional[dict] = None  # {slide: float, pan: float} - valeurs calculées
        self.lfo_base_position: Optional[dict] = None  # {slide: float, pan: float} - position de base
        self.lfo_panel: Optional[QWidget] = None  # Référence au panneau LFO
        
        # Attributs pour la surveillance en temps réel
        self.lfo_monitor_timer: Optional[QTimer] = None  # Timer pour surveiller les changements (200ms)
        self.lfo_last_pan_base: Optional[float] = None  # Dernière valeur de pan de base (hors compensation)
        self.lfo_last_amplitude: float = 0.0  # Dernière valeur d'amplitude
        self.lfo_last_distance: float = 1.0  # Dernière valeur de distance
        self.lfo_last_speed: float = 1.0  # Dernière valeur de vitesse
        self.lfo_update_pending: bool = False  # Flag pour éviter les mises à jour simultanées
        self.lfo_debounce_timer: Optional[QTimer] = None  # Timer pour debounce des changements de paramètres
        self.lfo_sequence_initialized: bool = False  # Flag pour savoir si la séquence a été initialisée (POST vs PATCH)
        self.lfo_initial_joystick_pan_offset: float = 0.0  # Offset joystick initial capturé au démarrage du LFO
        
        # LUT Focus pour synchronisation automatique du D du LFO
        # Utilise uniquement la LUT 3D (zoom × focus → distance)
        self.focus_lut = FocusLUT(None, "focus_zoom_lut_3d.json")
        self.lfo_auto_sync_distance: bool = True  # Synchronisation automatique activée par défaut
        self.last_synced_focus_value: Optional[float] = None  # Pour éviter les mises à jour continues
        
        # LUT Zoom n'est plus nécessaire (remplacée par la LUT 3D)
        # self.zoom_lut = ZoomLUT("zoomlut.json")  # Désactivé - seule la LUT 3D est utilisée
        self.last_synced_zoom_value: Optional[float] = None  # Pour éviter les mises à jour continues
        
        # Références aux faders du workspace 2
        self.workspace_2_zoom_fader: Optional[QSlider] = None
        self.workspace_2_slide_fader: Optional[QSlider] = None
        self.workspace_2_joystick_2d: Optional[Joystick2DWidget] = None
        
        # Vitesse des flèches pour le contrôle joystick (par défaut 0.5)
        self.arrow_keys_speed: float = 0.5
        # Ensemble des touches actuellement pressées pour gérer les répétitions
        self.active_arrow_keys: set = set()
        # Ensemble des axes qui ont été utilisés récemment (pour envoyer 0.0 au relâchement)
        self.recently_used_axes: set = set()  # Peut contenir 'pan', 'tilt', 'zoom', 'slide'
        
        # Charger la configuration des caméras
        self.load_cameras_config()
        
        # Initialiser les SliderController pour chaque caméra
        for camera_id in range(1, 9):
            cam_data = self.cameras.get(camera_id)
            if cam_data and cam_data.slider_ip:
                self.slider_controllers[camera_id] = SliderController(cam_data.slider_ip)
            else:
                self.slider_controllers[camera_id] = None
        
        # Initialiser l'UI
        self.init_ui()
        
        # Connecter les signaux
        self.connect_signals()
        
        # Initialiser la page Companion pour la caméra active au démarrage
        QTimer.singleShot(500, lambda: self._init_companion_page())
        
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
        
        # Mettre à jour le statut initial de l'UI (sans bloquer)
        cam_data = self.get_active_camera_data()
        if cam_data.connected:
            self.status_label.setText(f"✓ Caméra {self.active_camera_id} - Connectée à {cam_data.url}")
            self.status_label.setStyleSheet("color: #0f0;")
            self.set_controls_enabled(True)
        elif cam_data.url:
            self.status_label.setText(f"✗ Caméra {self.active_camera_id} - Déconnectée ({cam_data.url})")
            self.status_label.setStyleSheet("color: #f00;")
            self.set_controls_enabled(False)
        else:
            self.status_label.setText(f"Caméra {self.active_camera_id} - Non configurée")
            self.status_label.setStyleSheet("color: #aaa;")
            self.set_controls_enabled(False)
        
        # Connexion automatique pour toutes les caméras configurées
        # Utiliser QTimer pour ne pas bloquer l'ouverture de l'UI
        # Délai initial plus long (2 secondes) pour laisser le système réseau se stabiliser
        QTimer.singleShot(2000, lambda: self._try_auto_connect_all_cameras())
        
        # Détection du réveil de l'ordinateur pour reconnecter les WebSockets
        app = QApplication.instance()
        if app:
            app.applicationStateChanged.connect(self._on_application_state_changed)
        
        # Timer périodique pour vérifier l'état des WebSockets (toutes les 10 secondes)
        self.websocket_check_timer = QTimer()
        self.websocket_check_timer.timeout.connect(self._check_websockets_health)
        self.websocket_check_timer.start(10000)  # 10 secondes
        
        # Timer périodique pour vérifier l'état de l'ATEM (toutes les 2 secondes)
        self.atem_status_timer = QTimer()
        self.atem_status_timer.timeout.connect(self._check_atem_status)
        self.atem_status_timer.start(2000)  # 2 secondes
    
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
                    "global": {
                        "companion_surface_id": "emulator:wTUoZejUfSzyNq2IIy5KW",
                        "companion_host": "127.0.0.1",
                        "companion_port": 16759
                    },
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
            
            # Charger la configuration globale Companion
            global_config = config.get("global", {})
            companion_surface_id = global_config.get("companion_surface_id", "emulator:wTUoZejUfSzyNq2IIy5KW")
            companion_host = global_config.get("companion_host", "127.0.0.1")
            companion_port = global_config.get("companion_port", 16759)
            
            # Charger sequences_column_widths depuis la config globale (pas par caméra)
            # Migration: si présent dans une caméra, le déplacer vers global
            if "sequences_column_widths" in global_config:
                self.sequences_column_widths = global_config.get("sequences_column_widths")
            else:
                # Migration: chercher dans les caméras pour migrer vers global
                migration_needed = False
                for i in range(1, 9):
                    cam_key = f"camera_{i}"
                    if cam_key in config:
                        cam_config = config.get(cam_key, {})
                        if "sequences_column_widths" in cam_config:
                            # Migrer vers global
                            if not self.sequences_column_widths:
                                self.sequences_column_widths = cam_config["sequences_column_widths"]
                                logger.info(f"Migration: sequences_column_widths déplacé de {cam_key} vers config globale")
                            migration_needed = True
                            # Supprimer de la caméra (sera nettoyé lors de la prochaine sauvegarde)
                            del config[cam_key]["sequences_column_widths"]
                if migration_needed and self.sequences_column_widths:
                    # Sauvegarder la migration
                    global_config["sequences_column_widths"] = self.sequences_column_widths
                    config["global"] = global_config
                    try:
                        with open("cameras_config.json", 'w') as f:
                            json.dump(config, f, indent=2)
                        logger.info("Migration sequences_column_widths terminée et sauvegardée")
                    except Exception as e:
                        logger.warning(f"Erreur lors de la sauvegarde de la migration: {e}")
            
            # Initialiser le Companion Controller avec la config chargée
            self.companion_controller = CompanionController(
                host=companion_host,
                port=companion_port,
                surface_ids=[companion_surface_id]
            )
            
            # Charger la configuration ATEM depuis global
            atem_config = global_config.get("atem", {})
            self.atem_config = {
                "ip": atem_config.get("ip", ""),
                "aux_output": atem_config.get("aux_output", 2),
                "connected": False  # État de connexion, pas sauvegardé
            }
            
            # Initialiser l'ATEM Controller si IP configurée
            if self.atem_config["ip"]:
                self.init_atem_controller()
            
            # Initialiser les 8 caméras
            for i in range(1, 9):
                cam_key = f"camera_{i}"
                if cam_key in config:
                    cam_config = config[cam_key]
                    # Initialiser les presets vides si absents
                    if "presets" not in cam_config:
                        cam_config["presets"] = {}
                    
                    # Initialiser les séquences vides si absentes
                    if "sequences" not in cam_config:
                        cam_config["sequences"] = []
                    
                    # Charger recall_scope avec valeurs par défaut si absent
                    default_recall_scope = {
                        'focus': False,
                        'iris': False,
                        'gain': False,
                        'shutter': False,
                        'whitebalance': False,
                        'slider': False
                    }
                    recall_scope = cam_config.get("recall_scope", default_recall_scope)
                    # S'assurer que tous les paramètres sont présents (migration automatique)
                    for param in ['focus', 'iris', 'gain', 'shutter', 'whitebalance', 'slider']:
                        if param not in recall_scope:
                            recall_scope[param] = False
                    
                    # Charger crossfade_duration avec valeur par défaut si absent
                    crossfade_duration = cam_config.get("crossfade_duration", 2.0)
                    
                    # Normaliser les séquences : convertir les clés string en float pour les points
                    sequences = cam_config.get("sequences", [])
                    normalized_sequences = []
                    for seq in sequences:
                        seq_copy = seq.copy()
                        if "points" in seq_copy:
                            points_normalized = {}
                            for key, value in seq_copy["points"].items():
                                # Convertir la clé string en float si nécessaire
                                if isinstance(key, str):
                                    try:
                                        float_key = float(key)
                                        points_normalized[float_key] = value
                                    except ValueError:
                                        # Si la conversion échoue, garder la clé originale
                                        points_normalized[key] = value
                                else:
                                    points_normalized[key] = value
                            seq_copy["points"] = points_normalized
                        normalized_sequences.append(seq_copy)
                    
                    cam_data = CameraData(
                        url=cam_config.get("url", "").rstrip('/'),
                        username=cam_config.get("username", ""),
                        password=cam_config.get("password", ""),
                        slider_ip=cam_config.get("slider_ip", ""),
                        companion_page=cam_config.get("companion_page", i),  # Par défaut, page = ID caméra
                        presets=cam_config.get("presets", {}),
                        sequences=normalized_sequences,
                        recall_scope=recall_scope,
                        crossfade_duration=float(crossfade_duration)
                    )
                    # sequences_column_widths est maintenant global, pas par caméra
                    self.cameras[i] = cam_data
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
            # Charger la config existante pour préserver la section globale
            global_config = {}
            if os.path.exists(config_file):
                try:
                    with open(config_file, 'r') as f:
                        existing_config = json.load(f)
                        global_config = existing_config.get("global", {})
                except:
                    pass
            
            # Si pas de config globale, utiliser les valeurs par défaut
            if not global_config:
                global_config = {
                    "companion_surface_id": "emulator:wTUoZejUfSzyNq2IIy5KW",
                    "companion_host": "127.0.0.1",
                    "companion_port": 16759
                }
            
            # Ajouter sequences_column_widths à la config globale si présent
            if self.sequences_column_widths:
                global_config["sequences_column_widths"] = self.sequences_column_widths
            
            # Ajouter la config ATEM à la config globale (sans l'état connected)
            global_config["atem"] = {
                "ip": self.atem_config.get("ip", ""),
                "aux_output": self.atem_config.get("aux_output", 2)
                }
            
            config = {
                "global": global_config,
                "active_camera": self.active_camera_id
            }
            
            for i in range(1, 9):
                cam_data = self.cameras[i]
                config[f"camera_{i}"] = {
                    "url": cam_data.url,
                    "username": cam_data.username,
                    "password": cam_data.password,
                    "slider_ip": cam_data.slider_ip,
                    "companion_page": cam_data.companion_page,
                    "presets": cam_data.presets,
                    "sequences": cam_data.sequences,
                    "recall_scope": cam_data.recall_scope,
                    "crossfade_duration": cam_data.crossfade_duration
                }
                # sequences_column_widths est maintenant global, pas sauvegardé par caméra
            
            with open(config_file, 'w') as f:
                json.dump(config, f, indent=2)
            
            logger.info("Configuration des caméras sauvegardée")
        except Exception as e:
            logger.error(f"Erreur lors de la sauvegarde de la configuration: {e}")
    
    def get_active_camera_data(self) -> CameraData:
        """Retourne les données de la caméra active."""
        return self.cameras.get(self.active_camera_id, CameraData())
    
    def init_atem_controller(self):
        """Initialise l'ATEM Controller avec la configuration actuelle."""
        if not self.atem_config.get("ip"):
            logger.debug("Pas d'IP ATEM configurée, initialisation ignorée")
            return
        
        try:
            # Déconnecter l'ancien controller s'il existe
            if self.atem_controller:
                self.atem_controller.disconnect()
            
            # Créer le nouveau controller
            def status_callback(connected: bool, ip: str):
                """Callback appelé quand l'état de connexion ATEM change."""
                self.atem_config["connected"] = connected
                # Mettre à jour l'UI du dialog ATEM s'il est ouvert
                self.update_atem_status()
            
            # Utiliser le flag auto_reconnect_enabled pour contrôler les tentatives automatiques
            auto_reconnect = self.atem_config.get("auto_reconnect_enabled", True)
            self.atem_controller = AtemController(
                ip=self.atem_config["ip"],
                aux_output=self.atem_config.get("aux_output", 2),
                auto_retry=auto_reconnect,
                retry_delay=5,
                max_retry_delay=30,
                max_retry_attempts=-1 if auto_reconnect else 0,  # Tentatives illimitées si activé, sinon aucune
                status_callback=status_callback
            )
            
            # Lancer la connexion dans un thread séparé pour ne pas bloquer l'UI
            import threading
            connect_thread = threading.Thread(target=self.atem_controller.connect, daemon=True)
            connect_thread.start()
            
            logger.info(f"ATEM Controller initialisé pour {self.atem_config['ip']}")
        except Exception as e:
            logger.error(f"Erreur lors de l'initialisation de l'ATEM Controller: {e}")
            self.atem_controller = None
    
    def connect_atem(self):
        """Établit la connexion avec l'ATEM."""
        if not self.atem_controller:
            if not self.atem_config.get("ip"):
                logger.warning("IP ATEM non configurée, impossible de se connecter")
                return
            self.init_atem_controller()
        else:
            if not self.atem_controller.is_connected():
                import threading
                connect_thread = threading.Thread(target=self.atem_controller.connect, daemon=True)
                connect_thread.start()
    
    def disconnect_atem(self):
        """Ferme la connexion ATEM et désactive la reconnexion automatique."""
        # Désactiver la reconnexion automatique
        self.atem_config["auto_reconnect_enabled"] = False
        
        if self.atem_controller:
            # Désactiver auto_retry dans le controller
            self.atem_controller.auto_retry = False
            # Arrêter le thread de reconnexion si en cours
            self.atem_controller.running = False
            self.atem_controller.disconnect()
            self.atem_config["connected"] = False
        
        self.update_atem_status()
    
    def _init_companion_page(self):
        """Initialise la page Companion au démarrage."""
        if hasattr(self, 'companion_controller') and self.companion_controller:
            cam_data = self.get_active_camera_data()
            companion_page = cam_data.companion_page
            self.companion_controller.switch_camera_page(self.active_camera_id, companion_page)
    
    def init_ui(self):
        """Initialise l'interface utilisateur."""
        self.setWindowTitle("Contrôle Focus Blackmagic (Standalone)")
        # Taille de référence pour le scaling (1512x982)
        self.setMinimumSize(int(1512 * 0.5), int(982 * 0.5))  # Minimum 50% de la taille de référence
        self.resize(1512, 982)  # Taille par défaut = taille de référence
        
        # Initialiser le scaler après avoir défini la taille
        self.ui_scaler = UIScaler(self)
        
        # Connecter le redimensionnement pour mettre à jour le scaling
        def on_resize(event):
            if self.ui_scaler:
                self.ui_scaler._update_scale()
                # Mettre à jour tous les panneaux
                self._update_ui_scaling()
            QMainWindow.resizeEvent(self, event)
        
        self.resizeEvent = on_resize
        
        # Activer le focus pour recevoir les événements clavier
        self.setFocusPolicy(Qt.StrongFocus)
        
        # Initialiser l'onglet actif
        self.active_workspace_id = 1
        
        # Layout principal vertical
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # Ligne supérieure : Sélecteur de caméra (gauche) + Sélecteur d'onglets (droite)
        top_bar_layout = QHBoxLayout()
        margin_h = self._scale_value(10)
        margin_v = self._scale_value(5)
        top_bar_layout.setContentsMargins(margin_h, margin_v, margin_h, margin_v)
        top_bar_layout.setSpacing(self._scale_value(5))
        
        # Sélecteur de caméra - 8 boutons (gauche)
        camera_label = QLabel("Caméra:")
        camera_label.setStyleSheet(f"font-size: {self._scale_font(12)}; color: #aaa;")
        top_bar_layout.addWidget(camera_label)
        
        # Créer 8 boutons pour les caméras
        self.camera_buttons = []
        for i in range(1, 9):
            btn = QPushButton(str(i))
            btn_width = self._scale_value(35)
            btn_height = self._scale_value(30)
            btn.setMinimumSize(btn_width, btn_height)
            btn.setMaximumSize(btn_width, btn_height)
            btn.setCheckable(True)
            if i == self.active_camera_id:
                btn.setChecked(True)
            btn.clicked.connect(lambda checked, cam_id=i: self.switch_active_camera(cam_id))
            btn.setStyleSheet(self._scale_style("""
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
            """))
            self.camera_buttons.append(btn)
            top_bar_layout.addWidget(btn)
        
        # Espacement pour pousser le sélecteur d'onglets à droite
        top_bar_layout.addStretch()
        
        # Sélecteur d'onglets (droite)
        workspace_label = QLabel("Workspace:")
        workspace_label.setStyleSheet(f"font-size: {self._scale_font(12)}; color: #aaa;")
        top_bar_layout.addWidget(workspace_label)
        
        # Créer 2 boutons pour les workspaces
        self.workspace_buttons = []
        for i in range(1, 5):
            btn = QPushButton(f"Workspace {i}")
            btn_width = self._scale_value(100)
            btn_height = self._scale_value(30)
            btn.setMinimumSize(btn_width, btn_height)
            btn.setMaximumSize(btn_width, btn_height)
            btn.setCheckable(True)
            if i == self.active_workspace_id:
                btn.setChecked(True)
            btn.clicked.connect(lambda checked, ws_id=i: self.switch_workspace(ws_id))
            btn.setStyleSheet(self._scale_style("""
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
            """))
            self.workspace_buttons.append(btn)
            top_bar_layout.addWidget(btn)
        
        top_bar_widget = QWidget()
        top_bar_widget.setLayout(top_bar_layout)
        top_bar_widget.setStyleSheet("background-color: #1a1a1a; border-bottom: 1px solid #444;")
        main_layout.addWidget(top_bar_widget)
        
        # Widget central avec layout horizontal
        central_widget = QWidget()
        central_layout = QHBoxLayout(central_widget)
        central_layout.setSpacing(self._scale_value(5))  # Espacement minimal pour coller les colonnes
        margin = self._scale_value(20)
        central_layout.setContentsMargins(margin, margin, margin, margin)
        
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
        self.whitebalance_panel = self.create_whitebalance_panel()
        self.shutter_panel = self.create_shutter_panel()
        # Le panneau zoom a été supprimé, la focale est maintenant affichée dans zoom_motor_panel
        self.presets_panel = self.create_presets_panel()
        self.controls_panel = self.create_controls_panel()
        
        # Créer les panneaux de contrôle du slider
        self.pan_tilt_panel = self.create_pan_tilt_matrix_panel()  # Matrice XY pour pan/tilt
        self.slide_panel = self.create_slide_panel()
        self.zoom_motor_panel = self.create_zoom_motor_panel()
        
        # Ajouter les panneaux au layout central
        central_layout.addWidget(self.focus_panel)
        
        # Conteneur avec grille 2x2 pour les 4 panneaux (Iris, Gain, White Balance, Shutter)
        grid_container = QWidget()
        grid_layout = QGridLayout(grid_container)
        grid_layout.setSpacing(20)
        grid_layout.setContentsMargins(0, 0, 0, 0)
        
        # Grille 2x2 :
        # Ligne 0, Colonne 0 : Iris Control
        # Ligne 0, Colonne 1 : Gain Control
        # Ligne 1, Colonne 0 : White Balance
        # Ligne 1, Colonne 1 : Shutter Control
        grid_layout.addWidget(self.iris_panel, 0, 0, 1, 1)
        grid_layout.addWidget(self.gain_panel, 0, 1, 1, 1)
        grid_layout.addWidget(self.whitebalance_panel, 1, 0, 1, 1)
        grid_layout.addWidget(self.shutter_panel, 1, 1, 1, 1)
        
        # Définir les stretch factors pour que chaque panneau ait la même taille
        grid_layout.setRowStretch(0, 1)  # Ligne 0 : même hauteur
        grid_layout.setRowStretch(1, 1)  # Ligne 1 : même hauteur
        grid_layout.setColumnStretch(0, 1)  # Colonne 0 : même largeur
        grid_layout.setColumnStretch(1, 1)  # Colonne 1 : même largeur
        
        central_layout.addWidget(grid_container)
        
        # Le panneau zoom a été supprimé, la focale est maintenant affichée dans zoom_motor_panel
        
        # Conteneur vertical pour les panneaux de contrôle du slider (pan, tilt, zoom, slide)
        slider_container = QWidget()
        self.slider_container = slider_container  # Stocker la référence pour _update_ui_scaling
        slider_container_layout = QVBoxLayout(slider_container)
        slider_container_layout.setSpacing(10)  # Réduire l'espacement pour donner plus d'espace aux faders
        slider_container_layout.setContentsMargins(0, 0, 0, 0)
        # Ajouter chaque panneau avec un stretch factor pour qu'ils prennent plus d'espace vertical
        # Ordre : pan/tilt (matrice XY), zoom, slide
        slider_container_layout.addWidget(self.pan_tilt_panel, stretch=1)
        slider_container_layout.addWidget(self.zoom_motor_panel, stretch=1)
        slider_container_layout.addWidget(self.slide_panel, stretch=1)
        # Pas de stretch à la fin pour que les panneaux prennent tout l'espace disponible
        
        # Conteneur horizontal pour slider et presets (slider à gauche, collé)
        slider_presets_container = QWidget()
        slider_presets_layout = QHBoxLayout(slider_presets_container)
        slider_presets_layout.setSpacing(0)  # Collé
        slider_presets_layout.setContentsMargins(0, 0, 0, 0)
        slider_presets_layout.addWidget(slider_container, stretch=1)
        slider_presets_layout.addWidget(self.presets_panel)
        
        central_layout.addWidget(slider_presets_container, stretch=1)
        central_layout.addWidget(self.controls_panel)
        
        # Créer le QStackedWidget pour gérer les différents workspaces
        self.workspace_stack = QStackedWidget()
        
        # Page 1 (Workspace 1) : Contenu actuel
        workspace_1_page = central_widget
        self.workspace_stack.addWidget(workspace_1_page)
        
        # Page 2 (Workspace 2) : Nouvelle page avec Joystick Control
        workspace_2_page = self.create_workspace_2_page()
        self.workspace_stack.addWidget(workspace_2_page)
        
        # Page 3 (Workspace 3) : Vue caméras (style AUTOREAL)
        workspace_3_page = self.create_workspace_3_page()
        self.workspace_stack.addWidget(workspace_3_page)
        
        # Page 4 (Workspace 4) : Configuration et état ATEM
        workspace_4_page = self.create_workspace_4_page()
        self.workspace_stack.addWidget(workspace_4_page)
        
        # Connecter les signaux du panneau joystick et LFO
        if hasattr(workspace_2_page, 'layout') and workspace_2_page.layout():
            # Trouver les panneaux dans la page
            for i in range(workspace_2_page.layout().count()):
                item = workspace_2_page.layout().itemAt(i)
                if item and item.widget():
                    widget = item.widget()
                    if hasattr(widget, 'joystick_2d'):
                        # Joystick 2D pour pan/tilt
                        widget.joystick_2d.positionChanged.connect(self.on_joystick_pan_tilt_changed)
                    if hasattr(widget, 'zoom_fader'):
                        # Fader zoom motor (slider) - revient à 0 au relâchement
                        self.workspace_2_zoom_fader = widget.zoom_fader
                        widget.zoom_fader.valueChanged.connect(self.on_joystick_zoom_fader_changed)
                        widget.zoom_fader.sliderReleased.connect(self.on_joystick_zoom_fader_released)
                    if hasattr(widget, 'slide_fader'):
                        # Fader slide
                        self.workspace_2_slide_fader = widget.slide_fader
                        widget.slide_fader.valueChanged.connect(self.on_joystick_slide_fader_changed)
                        widget.slide_fader.sliderReleased.connect(self.on_joystick_slide_fader_released)
                    if hasattr(widget, 'amplitude_slider'):
                        # LFO controls
                        widget.amplitude_slider.valueChanged.connect(self.on_lfo_amplitude_changed)
                        widget.speed_slider.valueChanged.connect(self.on_lfo_speed_changed)
                        widget.distance_slider.valueChanged.connect(self.on_lfo_distance_changed)
                        widget.lfo_toggle_btn.clicked.connect(self.toggle_lfo)
                        # Stocker la référence du panneau LFO
                        self.lfo_panel = widget
        
        # Définir la page active (Workspace 1)
        self.workspace_stack.setCurrentIndex(0)
        
        # Ajouter le QStackedWidget au layout principal
        main_layout.addWidget(self.workspace_stack)
        
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
        btn_size = self._scale_value(30)
        settings_btn.setMinimumSize(btn_size, btn_size)
        settings_btn.setMaximumSize(btn_size, btn_size)
        settings_btn.setStyleSheet(self._scale_style("""
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
        """))
        # Status bar pour afficher l'état de connexion
        self.status_label = QLabel("Initialisation...")
        self.statusBar().addWidget(self.status_label)
        
        # Indicateur de statut du slider (à gauche de l'engrenage) - affiche le statut du slider de la caméra active
        # Note: addPermanentWidget ajoute de gauche à droite, donc le slider doit être ajouté en premier
        self.slider_status_label = QLabel("● Slider Cam1")
        self.slider_status_label.setStyleSheet("font-size: 12px; color: #666; margin-right: 10px;")
        self.statusBar().addPermanentWidget(self.slider_status_label)
        
        # Bouton engrenage pour ouvrir les paramètres de connexion (à droite du slider)
        settings_btn.clicked.connect(self.open_connection_dialog)
        self.statusBar().addPermanentWidget(settings_btn)
        
        # Timer pour vérifier périodiquement le statut du slider
        self.slider_status_timer = QTimer()
        self.slider_status_timer.timeout.connect(self.update_slider_status_indicator)
        self.slider_status_timer.start(2000)  # Vérifier toutes les 2 secondes
        # Mettre à jour immédiatement
        QTimer.singleShot(500, self.update_slider_status_indicator)
        
        self.statusBar().setStyleSheet("""
            QStatusBar {
                background-color: #1a1a1a;
                color: #aaa;
                border-top: 1px solid #444;
            }
        """)
    
    def switch_workspace(self, workspace_id: int):
        """Change l'onglet workspace actif."""
        if workspace_id < 1 or workspace_id > 4:
            logger.warning(f"ID de workspace invalide: {workspace_id}")
            return
        
        # Le LFO continue de fonctionner en arrière-plan même quand on change d'onglet
        # pour permettre un fonctionnement simultané des deux workspaces
        
        self.active_workspace_id = workspace_id
        
        # Changer la page affichée dans le QStackedWidget (index 0-based)
        self.workspace_stack.setCurrentIndex(workspace_id - 1)
        
        # Mettre à jour l'état des boutons d'onglets
        for i, btn in enumerate(self.workspace_buttons, start=1):
            btn.setChecked(i == workspace_id)
        
        # Mettre à jour l'affichage du Workspace 3 si on y accède
        if workspace_id == 3:
            self.update_workspace_3_camera_display()
            # Rafraîchir aussi les musiciens
            if hasattr(self, 'workspace_3_refresh_musicians'):
                self.workspace_3_refresh_musicians()
        
        # Mettre à jour l'affichage du Workspace 4 si on y accède
        if workspace_id == 4:
            # Recharger les paramètres de la caméra active
            self.update_workspace_4_for_active_camera()
        
        logger.debug(f"Workspace changé vers {workspace_id}")
    
    def _check_atem_status(self):
        """Vérifie périodiquement l'état de connexion ATEM et met à jour l'affichage."""
        if self.atem_controller:
            # Mettre à jour l'état dans la config
            was_connected = self.atem_config.get("connected", False)
            is_connected = self.atem_controller.is_connected()
            
            if was_connected != is_connected:
                self.atem_config["connected"] = is_connected
                # Mettre à jour l'affichage du dialog ATEM s'il est ouvert
                self.update_atem_status()
    
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
        
        # Mettre à jour les boutons de caméras dans le Workspace 3
        if hasattr(self, 'workspace_3_camera_buttons'):
            for i, btn in enumerate(self.workspace_3_camera_buttons, start=1):
                btn.blockSignals(True)
                btn.setChecked(i == camera_id)
                btn.blockSignals(False)
        
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
        
        # Mettre à jour l'indicateur de statut du slider pour cette caméra
        self.update_slider_status_indicator()
        
        # Mettre à jour le Workspace 3 si visible
        self.update_workspace_3_camera_display()
        
        # Mettre à jour le Workspace 4 si visible
        if self.active_workspace_id == 4:
            self.update_workspace_4_for_active_camera()
        
        # Changer la page Companion selon la caméra sélectionnée
        if hasattr(self, 'companion_controller') and self.companion_controller:
            companion_page = cam_data.companion_page
            self.companion_controller.switch_camera_page(camera_id, companion_page)
        
        # Activer/désactiver les contrôles selon l'état de connexion
        self.set_controls_enabled(cam_data.connected)
        
        # Synchroniser avec l'ATEM switcher (commuter HDMI 2 vers la caméra sélectionnée)
        if self.atem_controller and self.atem_controller.is_connected():
            try:
                # Mapping 1:1 : caméra 1 = input 1, caméra 2 = input 2, etc.
                if self.atem_controller.switch_to_camera(camera_id):
                    logger.info(f"ATEM: HDMI 2 commuté vers caméra {camera_id}")
                else:
                    logger.warning(f"ATEM: Échec de la commutation vers caméra {camera_id}")
            except Exception as e:
                logger.error(f"Erreur lors de la commutation ATEM: {e}")
        
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
        # Les valeurs iris_value_sent et iris_value_actual ont été supprimées, seul aperture_stop est affiché
        
        # Gain
        self.gain_sent_value = cam_data.gain_sent_value
        self.gain_actual_value = cam_data.gain_actual_value
        # TODO: Mettre à jour les widgets gain
        
        # Shutter
        self.shutter_sent_value = cam_data.shutter_sent_value
        self.shutter_actual_value = cam_data.shutter_actual_value
        # TODO: Mettre à jour les widgets shutter
        
        # White Balance
        self.whitebalance_sent_value = cam_data.whitebalance_sent_value
        self.whitebalance_actual_value = cam_data.whitebalance_actual_value
        if hasattr(self, 'whitebalance_value_actual'):
            self.whitebalance_value_actual.setText(f"{cam_data.whitebalance_actual_value}K")
        
        # Tint
        if hasattr(self, 'tint_value_actual'):
            self.tint_value_actual.setText(f"{cam_data.tint_actual_value}")
        
        # Zoom (focale caméra)
        self.zoom_sent_value = cam_data.zoom_sent_value
        self.zoom_actual_value = cam_data.zoom_actual_value
        # La focale sera mise à jour via on_zoom_changed quand les données sont chargées
        
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
        
        # Mettre à jour les champs distance des presets
        if hasattr(self, 'preset_distance_inputs') and len(self.preset_distance_inputs) > 0:
            self._update_preset_distance_inputs()
        
        # Mettre à jour les séquences
        if hasattr(self, 'sequences_table') and self.sequences_table:
            self.load_sequences_from_config()
    
    def _scale_value(self, value: float) -> int:
        """Helper pour obtenir une valeur scaled."""
        return self.ui_scaler.scale_value(value) if self.ui_scaler else int(value)
    
    def _scale_font(self, size: float) -> str:
        """Helper pour obtenir une taille de police scaled."""
        return self.ui_scaler.scale_font_size(size) if self.ui_scaler else f"{int(size)}px"
    
    def _scale_style(self, style: str) -> str:
        """Helper pour appliquer le scaling à un style CSS."""
        return self.ui_scaler.scale_style(style) if self.ui_scaler else style
    
    def _update_ui_scaling(self):
        """Met à jour tous les éléments de l'UI avec le nouveau scaling."""
        if not self.ui_scaler:
            return
        
        # Mettre à jour les largeurs des panneaux (réduites pour libérer de l'espace pour les sliders)
        panel_width = self._scale_value(200)  # Élargi
        panels = [
            self.focus_panel, self.iris_panel, self.gain_panel, 
            self.whitebalance_panel, self.shutter_panel,
            self.presets_panel, self.controls_panel
        ]
        for panel in panels:
            if panel:
                panel.setMinimumWidth(panel_width)
                panel.setMaximumWidth(panel_width)
                # Mettre à jour le style du panneau
                panel.setStyleSheet(self._scale_style("""
                    QWidget {
                        background-color: #1a1a1a;
                        border: 1px solid #444;
                        border-radius: 4px;
                    }
                """))
        
        # Mettre à jour les largeurs des panneaux de slider (utilisent tout l'espace disponible)
        # Les sliders prennent maintenant tout l'espace entre gain/shutter et presets grâce au stretch factor
        if hasattr(self, 'pan_tilt_panel') and self.pan_tilt_panel and hasattr(self, 'slider_container') and self.slider_container:
            # Obtenir la largeur réelle du conteneur slider (qui s'étire avec le stretch factor)
            slider_container_width = self.slider_container.width()
            if slider_container_width > 0:
                # Utiliser toute la largeur du conteneur moins une petite marge pour l'espacement interne
                slider_panel_width = max(self._scale_value(300), slider_container_width - self._scale_value(10))
            else:
                # Fallback si le conteneur n'a pas encore de largeur (calcul basé sur la fenêtre)
                base_width = self.width() if self.width() > 0 else 1920
                # Calculer la largeur disponible : largeur totale - marges - autres colonnes
                # Colonnes fixes : focus (170) + iris/wb (170) + gain/shutter (170) + presets (170) + controls (170) + spacing
                fixed_columns_width = self._scale_value(170) * 5  # 5 colonnes fixes
                spacing_width = self._scale_value(5) * 4  # 4 espacements entre 5 colonnes
                margins_width = self._scale_value(20) * 2  # marges gauche et droite
                available_width = base_width - fixed_columns_width - spacing_width - margins_width
                # Utiliser 95% de l'espace disponible pour maximiser l'utilisation
                slider_panel_width = max(self._scale_value(300), int(available_width * 0.95))
            
            slider_panels = [self.pan_tilt_panel, self.slide_panel, self.zoom_motor_panel]
            for slider_panel in slider_panels:
                if slider_panel:
                    slider_panel.setMinimumWidth(slider_panel_width)
                    slider_panel.setMaximumWidth(slider_panel_width)
        
        # Mettre à jour les boutons de caméra
        if hasattr(self, 'camera_buttons'):
            btn_width = self._scale_value(35)
            btn_height = self._scale_value(30)
            for btn in self.camera_buttons:
                btn.setMinimumSize(btn_width, btn_height)
                btn.setMaximumSize(btn_width, btn_height)
                btn.setStyleSheet(self._scale_style("""
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
                """))
        
        # Mettre à jour le bouton settings
        if hasattr(self, 'statusBar'):
            status_bar = self.statusBar()
            for widget in status_bar.children():
                if isinstance(widget, QPushButton) and widget.text() == "⚙️":
                    btn_size = self._scale_value(30)
                    widget.setMinimumSize(btn_size, btn_size)
                    widget.setMaximumSize(btn_size, btn_size)
                    widget.setStyleSheet(self._scale_style("""
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
                    """))
        
        # Mettre à jour tous les labels avec leurs styles
        self._update_labels_scaling()
        
        # Mettre à jour tous les boutons +/- et autres boutons
        self._update_buttons_scaling()
    
    def _update_labels_scaling(self):
        """Met à jour les styles de tous les labels."""
        if not self.ui_scaler:
            return
        
        # Trouver et mettre à jour tous les labels de titre dans les panneaux
        panels = [
            (self.focus_panel, "Focus Control"),
            (self.iris_panel, "Iris Control"),
            (self.gain_panel, "Gain Control"),
            (self.whitebalance_panel, "White Balance"),
            (self.shutter_panel, "⚡ Shutter Control"),
            (self.controls_panel, "Contrôles"),
        ]
        
        for panel, title_text in panels:
            if panel:
                for child in panel.findChildren(QLabel):
                    if child.text() == title_text or title_text in child.text():
                        if "font-weight: bold" in child.styleSheet():
                            child.setStyleSheet(f"font-size: {self._scale_font(20)}; font-weight: bold; color: #fff;")
                        else:
                            child.setStyleSheet(f"font-size: {self._scale_font(20)}; color: #fff;")
        
        # Label Presets
        if hasattr(self, 'presets_panel') and self.presets_panel:
            for child in self.presets_panel.findChildren(QLabel):
                if child.text() == "Presets":
                    child.setStyleSheet(f"font-size: {self._scale_font(20)}; font-weight: bold; color: #fff;")
                elif child.text() in ["Save", "Recall"]:
                    child.setStyleSheet(f"font-size: {self._scale_font(12)}; font-weight: bold; color: #aaa;")
                elif child.text() == "Recall Scope":
                    child.setStyleSheet(f"font-size: {self._scale_font(14)}; font-weight: bold; color: #fff; margin-top: {self._scale_value(10)}px;")
        
        # Labels de valeurs (envoyé, réel, etc.) - mettre à jour via leurs attributs
        if hasattr(self, 'focus_label') and self.focus_label:
            self.focus_label.setStyleSheet(f"font-size: {self._scale_font(10)}; color: #aaa; text-transform: uppercase;")
        
        # Labels de valeurs numériques
        value_labels = [
            (getattr(self, 'focus_value_sent', None), 12, "#ff0"),
            (getattr(self, 'focus_value_actual', None), 12, "#0ff"),
            # iris_value_sent et iris_value_actual supprimés, seul aperture_stop est affiché
            (getattr(self, 'gain_value_sent', None), 12, "#ff0"),
            (getattr(self, 'gain_value_actual', None), 12, "#0ff"),
            (getattr(self, 'whitebalance_value_sent', None), 12, "#ff0"),
            (getattr(self, 'whitebalance_value_actual', None), 12, "#0ff"),
            (getattr(self, 'shutter_value_sent', None), 12, "#ff0"),
            (getattr(self, 'shutter_value_actual', None), 12, "#0ff"),
        ]
        
        for label, size, color in value_labels:
            if label:
                label.setStyleSheet(f"font-size: {self._scale_font(size)}; font-weight: bold; color: {color}; font-family: 'Courier New';")
        
        # Labels "Envoyé" et "Réel (GET)" dans tous les panneaux
        for panel in [self.focus_panel, self.iris_panel, self.gain_panel, 
                     self.whitebalance_panel, self.shutter_panel]:
            if panel:
                for child in panel.findChildren(QLabel):
                    if child.text() in ["Envoyé", "Réel (GET)"]:
                        child.setStyleSheet(f"font-size: {self._scale_font(9)}; color: #888;")
    
    def _update_buttons_scaling(self):
        """Met à jour les tailles et styles de tous les boutons."""
        if not self.ui_scaler:
            return
        
        btn_size = self._scale_value(60)
        btn_style = self._scale_style("""
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
        
        # Boutons +/-
        plus_minus_buttons = [
            getattr(self, 'iris_plus_btn', None),
            getattr(self, 'iris_minus_btn', None),
            getattr(self, 'gain_plus_btn', None),
            getattr(self, 'gain_minus_btn', None),
            getattr(self, 'whitebalance_plus_btn', None),
            getattr(self, 'whitebalance_minus_btn', None),
            getattr(self, 'shutter_plus_btn', None),
            getattr(self, 'shutter_minus_btn', None),
        ]
        
        for btn in plus_minus_buttons:
            if btn:
                btn.setMinimumSize(btn_size, btn_size)
                btn.setMaximumSize(btn_size, btn_size)
                btn.setStyleSheet(btn_style)
        
        # Bouton Auto White Balance
        if hasattr(self, 'whitebalance_auto_btn') and self.whitebalance_auto_btn:
            auto_btn_width = self._scale_value(80)
            auto_btn_height = self._scale_value(40)
            self.whitebalance_auto_btn.setMinimumSize(auto_btn_width, auto_btn_height)
            self.whitebalance_auto_btn.setMaximumSize(auto_btn_width, auto_btn_height)
            self.whitebalance_auto_btn.setStyleSheet(self._scale_style("""
                QPushButton {
                    font-size: 14px;
                    font-weight: bold;
                    border: 2px solid #555;
                    background-color: #0a5;
                    color: #fff;
                    border-radius: 8px;
                }
                QPushButton:hover {
                    background-color: #0c7;
                    border-color: #777;
                }
                QPushButton:pressed {
                    background-color: #095;
                }
            """))
        
        # Bouton Autofocus
        if hasattr(self, 'autofocus_btn') and self.autofocus_btn:
            self.autofocus_btn.setStyleSheet(self._scale_style("""
                QPushButton {
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
            """))
        
        # Boutons toggle (Zebra, Focus Assist, etc.)
        toggle_style = self._scale_style("""
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
        
        toggle_buttons = [
            getattr(self, 'zebra_toggle', None),
            getattr(self, 'focusAssist_toggle', None),
            getattr(self, 'falseColor_toggle', None),
            getattr(self, 'cleanfeed_toggle', None),
        ]
        
        for btn in toggle_buttons:
            if btn:
                btn.setStyleSheet(toggle_style)
        
        # Boutons presets
        save_btn_style = self._scale_style("""
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
        
        recall_btn_style = self._scale_style("""
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
        
        if hasattr(self, 'preset_save_buttons'):
            for btn in self.preset_save_buttons:
                if btn:
                    btn.setStyleSheet(save_btn_style)
        
        if hasattr(self, 'preset_recall_buttons'):
            for btn in self.preset_recall_buttons:
                if btn:
                    btn.setStyleSheet(recall_btn_style)
        
        # Checkboxes Recall Scope
        recall_scope_style = self._scale_style("""
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
        
        if hasattr(self, 'recall_scope_checkboxes'):
            for checkbox in self.recall_scope_checkboxes.values():
                if checkbox:
                    checkbox.setStyleSheet(recall_scope_style)
    
    def _create_plus_minus_buttons(self, plus_callback, minus_callback, container_layout):
        """Crée deux boutons + et - alignés horizontalement avec un style uniforme."""
        btn_size = self._scale_value(50)
        btn_spacing = self._scale_value(10)
        
        # Container horizontal pour les boutons
        buttons_row = QWidget()
        buttons_row_layout = QHBoxLayout(buttons_row)
        buttons_row_layout.setContentsMargins(0, 0, 0, 0)
        buttons_row_layout.setSpacing(btn_spacing)
        buttons_row_layout.setAlignment(Qt.AlignCenter)
        
        # Bouton +
        plus_btn = QPushButton("+")
        plus_btn.setMinimumSize(btn_size, btn_size)
        plus_btn.setMaximumSize(btn_size, btn_size)
        plus_btn.setStyleSheet(self._scale_style("""
            QPushButton {
                font-size: 20px;
                font-weight: bold;
                border: 2px solid #666;
                background-color: #2a2a2a;
                color: #fff;
                border-radius: 6px;
            }
            QPushButton:hover {
                background-color: #3a3a3a;
                border-color: #888;
            }
            QPushButton:pressed {
                background-color: #4a4a4a;
                border-color: #aaa;
            }
        """))
        plus_btn.clicked.connect(plus_callback)
        buttons_row_layout.addWidget(plus_btn)
        
        # Bouton -
        minus_btn = QPushButton("−")
        minus_btn.setMinimumSize(btn_size, btn_size)
        minus_btn.setMaximumSize(btn_size, btn_size)
        minus_btn.setStyleSheet(self._scale_style("""
            QPushButton {
                font-size: 20px;
                font-weight: bold;
                border: 2px solid #666;
                background-color: #2a2a2a;
                color: #fff;
                border-radius: 6px;
            }
            QPushButton:hover {
                background-color: #3a3a3a;
                border-color: #888;
            }
            QPushButton:pressed {
                background-color: #4a4a4a;
                border-color: #aaa;
            }
        """))
        minus_btn.clicked.connect(minus_callback)
        buttons_row_layout.addWidget(minus_btn)
        
        container_layout.addWidget(buttons_row, alignment=Qt.AlignCenter)
        
        return plus_btn, minus_btn
    
    def create_focus_panel(self):
        """Crée le panneau de contrôle du focus."""
        panel = QWidget()
        panel_width = self._scale_value(200)  # Élargi
        panel.setMinimumWidth(panel_width)
        panel.setMaximumWidth(panel_width)
        # Permettre au panneau de s'étirer en hauteur
        panel.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        # Permettre au panneau de s'étirer en hauteur
        panel.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        panel.setStyleSheet(self._scale_style("""
            QWidget {
                background-color: #1a1a1a;
                border: 1px solid #444;
                border-radius: 4px;
            }
        """))
        layout = QVBoxLayout(panel)
        spacing = self._scale_value(15)
        margin = self._scale_value(30)
        layout.setSpacing(spacing)
        layout.setContentsMargins(margin, margin, margin, margin)
        
        # Titre
        title = QLabel("Focus Control")
        title.setAlignment(Qt.AlignCenter)
        font_size = self._scale_font(16)
        margin_bottom = self._scale_value(20)
        title.setStyleSheet(f"font-size: {font_size}; color: #fff; margin-bottom: {margin_bottom}px;")
        layout.addWidget(title, stretch=0)  # Pas de stretch pour le titre
        
        # Section d'affichage des valeurs
        focus_display = QWidget()
        focus_display_layout = QVBoxLayout(focus_display)
        focus_display_layout.setSpacing(10)
        
        self.focus_label = QLabel("Focus Normalisé")
        self.focus_label.setAlignment(Qt.AlignCenter)
        self.focus_label.setStyleSheet(f"font-size: {self._scale_font(10)}; color: #aaa; text-transform: uppercase;")
        focus_display_layout.addWidget(self.focus_label)
        
        # Container pour les valeurs (vertical : envoyé au-dessus de réel)
        value_container = QWidget()
        value_container_width = self._scale_value(90)
        value_container.setMinimumWidth(value_container_width)
        value_container.setMaximumWidth(value_container_width)
        value_layout = QVBoxLayout(value_container)
        value_layout.setSpacing(self._scale_value(5))
        value_layout.setContentsMargins(self._scale_value(5), 0, self._scale_value(5), 0)
        
        # Valeur envoyée
        sent_label = QLabel("Envoyé")
        sent_label.setAlignment(Qt.AlignCenter)
        sent_label.setStyleSheet(f"font-size: {self._scale_font(9)}; color: #888;")
        value_layout.addWidget(sent_label)
        self.focus_value_sent = QLabel("0.00")
        self.focus_value_sent.setAlignment(Qt.AlignCenter)
        self.focus_value_sent.setStyleSheet(f"font-size: {self._scale_font(12)}; font-weight: bold; color: #ff0; font-family: 'Courier New';")
        value_layout.addWidget(self.focus_value_sent)
        
        # Espacement
        value_layout.addSpacing(self._scale_value(5))
        
        # Valeur réelle
        actual_label = QLabel("Réel (GET)")
        actual_label.setAlignment(Qt.AlignCenter)
        actual_label.setStyleSheet(f"font-size: {self._scale_font(9)}; color: #888;")
        value_layout.addWidget(actual_label)
        self.focus_value_actual = QLabel("0.00")
        self.focus_value_actual.setAlignment(Qt.AlignCenter)
        self.focus_value_actual.setStyleSheet(f"font-size: {self._scale_font(12)}; font-weight: bold; color: #0ff; font-family: 'Courier New';")
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
        self.focus_slider.setStyleSheet(self._scale_style("""
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
        """))
        
        # Labels pour le slider (1.0, 0.5, 0.0)
        slider_labels_container = QWidget()
        slider_labels_layout = QVBoxLayout(slider_labels_container)
        slider_labels_layout.setContentsMargins(self._scale_value(10), 0, 0, 0)
        slider_labels_layout.setSpacing(0)
        
        label_1 = QLabel("1.0")
        label_1.setStyleSheet(f"font-size: {self._scale_font(9)}; color: #aaa;")
        slider_labels_layout.addWidget(label_1)
        
        slider_labels_layout.addStretch()
        
        label_05 = QLabel("0.5")
        label_05.setStyleSheet(f"font-size: {self._scale_font(9)}; color: #aaa;")
        slider_labels_layout.addWidget(label_05)
        
        slider_labels_layout.addStretch()
        
        label_0 = QLabel("0.0")
        label_0.setStyleSheet(f"font-size: {self._scale_font(9)}; color: #aaa;")
        slider_labels_layout.addWidget(label_0)
        
        # Le slider doit prendre toute la hauteur disponible dans le container
        slider_layout.addWidget(self.focus_slider, stretch=1)
        slider_layout.addWidget(slider_labels_container)
        slider_layout.addStretch()
        
        # Ajouter le slider container avec un stretch factor pour qu'il prenne tout l'espace disponible
        # Utiliser un stretch factor élevé pour garantir qu'il prend le maximum d'espace
        layout.addWidget(slider_container, stretch=1, alignment=Qt.AlignCenter)
        
        # Bouton Autofocus (juste en dessous du fader)
        self.autofocus_btn = QPushButton("🔍 Autofocus")
        self.autofocus_btn.setStyleSheet(self._scale_style("""
            QPushButton {
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
        """))
        self.autofocus_btn.clicked.connect(lambda: self.do_autofocus())
        layout.addWidget(self.autofocus_btn)
        
        # Label pour afficher la distance convertie en mètres (via LUT)
        self.focus_distance_label = QLabel("Distance: -- m")
        self.focus_distance_label.setAlignment(Qt.AlignCenter)
        self.focus_distance_label.setStyleSheet(self._scale_style("""
            QLabel {
                color: #00ff00;
                font-size: 12px;
                font-weight: bold;
                margin-top: 5px;
                padding: 5px;
            }
        """))
        layout.addWidget(self.focus_distance_label)
        
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
                autofocus_btn = self.autofocus_btn if hasattr(self, 'autofocus_btn') else None
                
                title_height = title.height() if title else 40
                display_height = focus_display.height() if focus_display else 80
                autofocus_height = autofocus_btn.height() if autofocus_btn else 50
                
                # Marges du layout (top + bottom)
                layout_margins = layout.contentsMargins()
                margins_height = layout_margins.top() + layout_margins.bottom()
                
                # Espacement entre les widgets (slider et autofocus, slider et display)
                spacing = layout.spacing() * 3  # Espacement avant slider, après slider, après autofocus
                
                # Calculer la hauteur disponible
                available_height = panel_height - title_height - display_height - autofocus_height - margins_height - spacing
                
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
        panel_width = self._scale_value(200)  # Élargi
        panel.setMinimumWidth(panel_width)
        panel.setMaximumWidth(panel_width)
        panel.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        panel.setStyleSheet(self._scale_style("""
            QWidget {
                background-color: #1a1a1a;
                border: 1px solid #444;
                border-radius: 4px;
            }
        """))
        layout = QVBoxLayout(panel)
        spacing = self._scale_value(15)
        margin = self._scale_value(30)
        layout.setSpacing(spacing)
        layout.setContentsMargins(margin, margin, margin, margin)
        
        title = QLabel("Iris Control")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(f"font-size: {self._scale_font(20)}; color: #fff;")
        layout.addWidget(title)
        
        # Section d'affichage - Aperture Stop uniquement
        iris_display = QWidget()
        iris_display_layout = QVBoxLayout(iris_display)
        iris_display_layout.setSpacing(self._scale_value(10))
        iris_display_layout.setContentsMargins(0, 0, 0, 0)
        
        # Aperture Stop
        aperture_label = QLabel("Aperture Stop")
        aperture_label.setAlignment(Qt.AlignCenter)
        aperture_label.setStyleSheet(f"font-size: {self._scale_font(11)}; color: #aaa; text-transform: uppercase;")
        iris_display_layout.addWidget(aperture_label)
        
        # Container pour la valeur Aperture Stop
        aperture_value_container = QWidget()
        aperture_value_container.setMinimumWidth(self._scale_value(150))
        aperture_value_layout = QVBoxLayout(aperture_value_container)
        aperture_value_layout.setSpacing(self._scale_value(2))
        aperture_value_layout.setContentsMargins(0, 0, 0, 0)
        
        self.iris_aperture_stop = QLabel("-")
        self.iris_aperture_stop.setAlignment(Qt.AlignCenter)
        self.iris_aperture_stop.setStyleSheet(f"font-size: {self._scale_font(18)}; font-weight: bold; color: #0ff; font-family: 'Courier New';")
        aperture_value_layout.addWidget(self.iris_aperture_stop)
        
        iris_display_layout.addWidget(aperture_value_container, alignment=Qt.AlignCenter)
        
        layout.addWidget(iris_display)
        
        # Espacement avant les boutons
        layout.addSpacing(self._scale_value(20))
        
        # Boutons + et - alignés horizontalement
        buttons_container = QWidget()
        buttons_container_layout = QVBoxLayout(buttons_container)
        buttons_container_layout.setContentsMargins(0, self._scale_value(15), 0, self._scale_value(15))
        buttons_container_layout.setSpacing(0)
        
        self.iris_plus_btn, self.iris_minus_btn = self._create_plus_minus_buttons(
            self.increment_iris,
            self.decrement_iris,
            buttons_container_layout
        )
        
        layout.addWidget(buttons_container, alignment=Qt.AlignCenter)
        
        layout.addStretch()
        
        return panel
    
    def increment_iris(self, camera_id: Optional[int] = None):
        """Incrémente l'iris d'un stop d'aperture pour la caméra spécifiée ou active."""
        # Le signal clicked de QPushButton émet un booléen, donc on doit ignorer False
        if camera_id is not None and camera_id is not False and isinstance(camera_id, int):
            if camera_id < 1 or camera_id > 8:
                logger.error(f"ID de caméra invalide: {camera_id}")
                return
            cam_data = self.cameras[camera_id]
        else:
            cam_data = self.get_active_camera_data()
        
        if not cam_data.connected or not cam_data.controller:
            return
        
        # Utiliser adjustmentStep pour incrémenter d'un stop
        try:
            success = cam_data.controller.set_iris(adjustment_step=1, silent=True)
            if success:
                # La valeur sera mise à jour via WebSocket, mais on peut aussi faire un GET pour avoir la nouvelle valeur immédiatement
                # Pour l'instant, on attend le WebSocket
                pass
            else:
                logger.error(f"Erreur lors de l'incrémentation de l'iris")
        except Exception as e:
            logger.error(f"Erreur lors de l'incrémentation de l'iris: {e}")
    
    def decrement_iris(self, camera_id: Optional[int] = None):
        """Décrémente l'iris d'un stop d'aperture pour la caméra spécifiée ou active."""
        # Le signal clicked de QPushButton émet un booléen, donc on doit ignorer False
        if camera_id is not None and camera_id is not False and isinstance(camera_id, int):
            if camera_id < 1 or camera_id > 8:
                logger.error(f"ID de caméra invalide: {camera_id}")
                return
            cam_data = self.cameras[camera_id]
        else:
            cam_data = self.get_active_camera_data()
        
        if not cam_data.connected or not cam_data.controller:
            return
        
        # Utiliser adjustmentStep pour décrémenter d'un stop
        try:
            success = cam_data.controller.set_iris(adjustment_step=-1, silent=True)
            if success:
                # La valeur sera mise à jour via WebSocket, mais on peut aussi faire un GET pour avoir la nouvelle valeur immédiatement
                # Pour l'instant, on attend le WebSocket
                pass
            else:
                logger.error(f"Erreur lors de la décrémentation de l'iris")
        except Exception as e:
            logger.error(f"Erreur lors de la décrémentation de l'iris: {e}")
    
    def update_iris_value(self, value: float, camera_id: Optional[int] = None):
        """Met à jour la valeur de l'iris pour la caméra spécifiée ou active."""
        # Le signal clicked de QPushButton émet un booléen, donc on doit ignorer False
        if camera_id is not None and camera_id is not False and isinstance(camera_id, int):
            if camera_id < 1 or camera_id > 8:
                logger.error(f"ID de caméra invalide: {camera_id}")
                return
            cam_data = self.cameras[camera_id]
        else:
            cam_data = self.get_active_camera_data()
        
        value = max(0.0, min(1.0, value))
        cam_data.iris_sent_value = value
        
        # Les valeurs iris_value_sent et iris_value_actual ont été supprimées, seul aperture_stop est affiché
        
        # Envoyer la valeur à la caméra
        actual_camera_id = camera_id if (camera_id is not None and camera_id is not False and isinstance(camera_id, int)) else None
        self.send_iris_value(value, camera_id=actual_camera_id)
    
    def send_iris_value(self, value: float, camera_id: Optional[int] = None):
        """Envoie la valeur de l'iris directement (utilisé par Companion)."""
        # Le signal clicked de QPushButton émet un booléen, donc on doit ignorer False
        if camera_id is not None and camera_id is not False and isinstance(camera_id, int):
            if camera_id < 1 or camera_id > 8:
                logger.error(f"ID de caméra invalide: {camera_id}")
                return
            cam_data = self.cameras[camera_id]
        else:
            cam_data = self.get_active_camera_data()
        
        if not cam_data.connected or not cam_data.controller:
            return
        
        try:
            success = cam_data.controller.set_iris(value, silent=True)
            if not success:
                logger.error(f"Erreur lors de l'envoi de l'iris")
        except Exception as e:
            logger.error(f"Erreur lors de l'envoi de l'iris: {e}")
    
    def create_gain_panel(self):
        """Crée le panneau de contrôle du gain."""
        panel = QWidget()
        panel_width = self._scale_value(200)  # Élargi
        panel.setMinimumWidth(panel_width)
        panel.setMaximumWidth(panel_width)
        panel.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        panel.setStyleSheet(self._scale_style("""
            QWidget {
                background-color: #1a1a1a;
                border: 1px solid #444;
                border-radius: 4px;
            }
        """))
        layout = QVBoxLayout(panel)
        spacing = self._scale_value(15)
        margin = self._scale_value(30)
        layout.setSpacing(spacing)
        layout.setContentsMargins(margin, margin, margin, margin)
        
        title = QLabel("Gain Control")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(f"font-size: {self._scale_font(20)}; color: #fff;")
        layout.addWidget(title)
        
        # Section d'affichage
        gain_display = QWidget()
        gain_display_layout = QVBoxLayout(gain_display)
        gain_display_layout.setSpacing(self._scale_value(10))
        
        gain_label = QLabel("Gain (dB)")
        gain_label.setAlignment(Qt.AlignCenter)
        gain_label.setStyleSheet(f"font-size: {self._scale_font(10)}; color: #aaa; text-transform: uppercase;")
        gain_display_layout.addWidget(gain_label)
        
        # Container pour les valeurs (vertical : envoyé au-dessus de réel)
        value_container = QWidget()
        value_container_width = self._scale_value(90)
        value_container.setMinimumWidth(value_container_width)
        value_container.setMaximumWidth(value_container_width)
        value_layout = QVBoxLayout(value_container)
        value_layout.setSpacing(self._scale_value(5))
        value_layout.setContentsMargins(self._scale_value(5), 0, self._scale_value(5), 0)
        
        # Valeur réelle uniquement (pas d'envoyé)
        actual_label = QLabel("Réel (GET)")
        actual_label.setAlignment(Qt.AlignCenter)
        actual_label.setStyleSheet(f"font-size: {self._scale_font(9)}; color: #888;")
        value_layout.addWidget(actual_label)
        self.gain_value_actual = QLabel("0")
        self.gain_value_actual.setAlignment(Qt.AlignCenter)
        self.gain_value_actual.setStyleSheet(f"font-size: {self._scale_font(12)}; font-weight: bold; color: #0ff; font-family: 'Courier New';")
        value_layout.addWidget(self.gain_value_actual)
        
        gain_display_layout.addWidget(value_container, alignment=Qt.AlignCenter)
        layout.addWidget(gain_display)
        
        # Espacement avant les boutons
        layout.addSpacing(self._scale_value(20))
        
        # Boutons + et - alignés horizontalement
        buttons_container = QWidget()
        buttons_container_layout = QVBoxLayout(buttons_container)
        buttons_container_layout.setContentsMargins(0, self._scale_value(15), 0, self._scale_value(15))
        buttons_container_layout.setSpacing(0)
        
        self.gain_plus_btn, self.gain_minus_btn = self._create_plus_minus_buttons(
            self.increment_gain,
            self.decrement_gain,
            buttons_container_layout
        )
        
        layout.addWidget(buttons_container, alignment=Qt.AlignCenter)
        
        layout.addStretch()
        return panel
    
    def create_whitebalance_panel(self):
        """Crée le panneau de contrôle du white balance."""
        panel = QWidget()
        panel_width = self._scale_value(200)  # Élargi
        panel.setMinimumWidth(panel_width)
        panel.setMaximumWidth(panel_width)
        panel.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        panel.setStyleSheet(self._scale_style("""
            QWidget {
                background-color: #1a1a1a;
                border: 1px solid #444;
                border-radius: 4px;
            }
        """))
        layout = QVBoxLayout(panel)
        spacing = self._scale_value(8)  # Espacement réduit pour une mise en page compacte
        margin = self._scale_value(15)  # Marges réduites pour une mise en page compacte
        layout.setSpacing(spacing)
        layout.setContentsMargins(margin, margin, margin, margin)
        
        title = QLabel("White Balance")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(f"font-size: {self._scale_font(20)}; color: #fff; font-weight: bold;")
        layout.addWidget(title)
        
        # Section Température (K)
        wb_display = QWidget()
        wb_display_layout = QVBoxLayout(wb_display)
        wb_display_layout.setSpacing(self._scale_value(4))  # Espacement réduit
        
        wb_label = QLabel("Température (K)")
        wb_label.setAlignment(Qt.AlignCenter)
        wb_label.setStyleSheet(f"font-size: {self._scale_font(11)}; color: #aaa; text-transform: uppercase;")
        wb_display_layout.addWidget(wb_label)
        
        # Container pour les valeurs (seulement réel, pas d'envoyé)
        value_container = QWidget()
        value_container.setMinimumWidth(self._scale_value(150))
        value_layout = QVBoxLayout(value_container)
        value_layout.setSpacing(self._scale_value(2))
        value_layout.setContentsMargins(0, 0, 0, 0)
        
        # Valeur réelle uniquement
        actual_label = QLabel("Réel")
        actual_label.setAlignment(Qt.AlignCenter)
        actual_label.setStyleSheet(f"font-size: {self._scale_font(10)}; color: #888;")
        value_layout.addWidget(actual_label)
        self.whitebalance_value_actual = QLabel("0K")
        self.whitebalance_value_actual.setAlignment(Qt.AlignCenter)
        self.whitebalance_value_actual.setStyleSheet(f"font-size: {self._scale_font(18)}; font-weight: bold; color: #0ff; font-family: 'Courier New';")
        value_layout.addWidget(self.whitebalance_value_actual)
        
        wb_display_layout.addWidget(value_container, alignment=Qt.AlignCenter)
        layout.addWidget(wb_display)
        
        # Espacement avant les boutons
        layout.addSpacing(self._scale_value(15))
        
        # Boutons de contrôle - Auto en premier, puis + et -
        buttons_container = QWidget()
        buttons_container_layout = QVBoxLayout(buttons_container)
        buttons_container_layout.setContentsMargins(0, self._scale_value(5), 0, self._scale_value(5))
        buttons_container_layout.setSpacing(self._scale_value(8))
        
        # Bouton Auto
        self.whitebalance_auto_btn = QPushButton("Auto")
        auto_btn_width = self._scale_value(100)
        auto_btn_height = self._scale_value(35)
        self.whitebalance_auto_btn.setMinimumSize(auto_btn_width, auto_btn_height)
        self.whitebalance_auto_btn.setMaximumSize(auto_btn_width, auto_btn_height)
        self.whitebalance_auto_btn.setStyleSheet(self._scale_style("""
            QPushButton {
                font-size: 14px;
                font-weight: bold;
                border: 2px solid #555;
                background-color: #0a5;
                color: #fff;
                border-radius: 8px;
            }
            QPushButton:hover {
                background-color: #0c7;
                border-color: #777;
            }
            QPushButton:pressed {
                background-color: #095;
            }
        """))
        self.whitebalance_auto_btn.clicked.connect(self.do_auto_whitebalance)
        buttons_container_layout.addWidget(self.whitebalance_auto_btn, alignment=Qt.AlignCenter)
        
        # Boutons + et - alignés horizontalement
        self.whitebalance_plus_btn, self.whitebalance_minus_btn = self._create_plus_minus_buttons(
            self.increment_whitebalance,
            self.decrement_whitebalance,
            buttons_container_layout
        )
        
        layout.addWidget(buttons_container, alignment=Qt.AlignCenter)
        
        # Séparateur entre température et tint
        layout.addSpacing(self._scale_value(8))
        
        # Section Tint
        tint_display = QWidget()
        tint_display_layout = QVBoxLayout(tint_display)
        tint_display_layout.setSpacing(self._scale_value(4))  # Espacement réduit
        
        tint_label = QLabel("Tint")
        tint_label.setAlignment(Qt.AlignCenter)
        tint_label.setStyleSheet(f"font-size: {self._scale_font(11)}; color: #aaa; text-transform: uppercase;")
        tint_display_layout.addWidget(tint_label)
        
        # Container pour les valeurs tint (seulement réel, pas d'envoyé)
        tint_value_container = QWidget()
        tint_value_container.setMinimumWidth(self._scale_value(150))
        tint_value_layout = QVBoxLayout(tint_value_container)
        tint_value_layout.setSpacing(self._scale_value(2))
        tint_value_layout.setContentsMargins(0, 0, 0, 0)
        
        # Valeur réelle uniquement
        tint_actual_label = QLabel("Réel")
        tint_actual_label.setAlignment(Qt.AlignCenter)
        tint_actual_label.setStyleSheet(f"font-size: {self._scale_font(10)}; color: #888;")
        tint_value_layout.addWidget(tint_actual_label)
        self.tint_value_actual = QLabel("0")
        self.tint_value_actual.setAlignment(Qt.AlignCenter)
        self.tint_value_actual.setStyleSheet(f"font-size: {self._scale_font(18)}; font-weight: bold; color: #0ff; font-family: 'Courier New';")
        tint_value_layout.addWidget(self.tint_value_actual)
        
        tint_display_layout.addWidget(tint_value_container, alignment=Qt.AlignCenter)
        layout.addWidget(tint_display)
        
        # Espacement avant les boutons
        layout.addSpacing(self._scale_value(15))
        
        # Boutons de contrôle tint alignés horizontalement
        tint_buttons_container = QWidget()
        tint_buttons_container_layout = QVBoxLayout(tint_buttons_container)
        tint_buttons_container_layout.setContentsMargins(0, self._scale_value(5), 0, self._scale_value(5))
        tint_buttons_container_layout.setSpacing(0)
        
        self.tint_plus_btn, self.tint_minus_btn = self._create_plus_minus_buttons(
            self.increment_tint,
            self.decrement_tint,
            tint_buttons_container_layout
        )
        
        layout.addWidget(tint_buttons_container, alignment=Qt.AlignCenter)
        
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
    
    def increment_gain(self, camera_id: Optional[int] = None):
        """Incrémente le gain vers la valeur suivante supportée pour la caméra spécifiée ou active."""
        # Le signal clicked de QPushButton émet un booléen, donc on doit ignorer False
        if camera_id is not None and camera_id is not False and isinstance(camera_id, int):
            if camera_id < 1 or camera_id > 8:
                logger.error(f"ID de caméra invalide: {camera_id}")
                return
            cam_data = self.cameras[camera_id]
        else:
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
                self.update_gain_value(new_value, camera_id=camera_id)
        except ValueError:
            # Valeur actuelle pas dans la liste, prendre la plus proche
            nearest = min(cam_data.supported_gains, key=lambda x: abs(x - current_value))
            nearest_index = cam_data.supported_gains.index(nearest)
            if nearest_index < len(cam_data.supported_gains) - 1:
                new_value = cam_data.supported_gains[nearest_index + 1]
                self.update_gain_value(new_value, camera_id=camera_id)
    
    def decrement_gain(self, camera_id: Optional[int] = None):
        """Décrémente le gain vers la valeur précédente supportée pour la caméra spécifiée ou active."""
        # Le signal clicked de QPushButton émet un booléen, donc on doit ignorer False
        if camera_id is not None and camera_id is not False and isinstance(camera_id, int):
            if camera_id < 1 or camera_id > 8:
                logger.error(f"ID de caméra invalide: {camera_id}")
                return
            cam_data = self.cameras[camera_id]
        else:
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
                self.update_gain_value(new_value, camera_id=camera_id)
        except ValueError:
            # Valeur actuelle pas dans la liste, prendre la plus proche
            nearest = min(cam_data.supported_gains, key=lambda x: abs(x - current_value))
            nearest_index = cam_data.supported_gains.index(nearest)
            if nearest_index > 0:
                new_value = cam_data.supported_gains[nearest_index - 1]
                self.update_gain_value(new_value, camera_id=camera_id)
    
    def update_gain_value(self, value: int, camera_id: Optional[int] = None):
        """Met à jour la valeur du gain pour la caméra spécifiée ou active."""
        # Le signal clicked de QPushButton émet un booléen, donc on doit ignorer False
        if camera_id is not None and camera_id is not False and isinstance(camera_id, int):
            if camera_id < 1 or camera_id > 8:
                logger.error(f"ID de caméra invalide: {camera_id}")
                return
            cam_data = self.cameras[camera_id]
        else:
            cam_data = self.get_active_camera_data()
        
        cam_data.gain_sent_value = value
        # Passer None au lieu de False pour send_gain_value
        actual_camera_id = camera_id if (camera_id is not None and camera_id is not False and isinstance(camera_id, int)) else None
        self.send_gain_value(value, camera_id=actual_camera_id)
    
    def send_gain_value(self, value: int, camera_id: Optional[int] = None):
        """Envoie la valeur du gain directement (sans throttling) pour la caméra active."""
        # Le signal clicked de QPushButton émet un booléen, donc on doit ignorer False
        if camera_id is not None and camera_id is not False and isinstance(camera_id, int):
            if camera_id < 1 or camera_id > 8:
                logger.error(f"ID de caméra invalide: {camera_id}")
                return
            cam_data = self.cameras[camera_id]
        else:
            cam_data = self.get_active_camera_data()
        
        if not cam_data.connected or not cam_data.controller:
            return
        
        try:
            success = cam_data.controller.set_gain(value, silent=True)
            if not success:
                logger.error(f"Erreur lors de l'envoi du gain")
        except Exception as e:
            logger.error(f"Erreur lors de l'envoi du gain: {e}")
    
    def load_whitebalance_description(self, camera_id: int):
        """Charge la plage min/max du white balance pour la caméra spécifiée."""
        if camera_id < 1 or camera_id > 8:
            return
        
        cam_data = self.cameras[camera_id]
        if not cam_data.controller:
            return
        try:
            desc = cam_data.controller.get_whitebalance_description()
            if desc:
                cam_data.whitebalance_min = desc.get('min', 0)
                cam_data.whitebalance_max = desc.get('max', 0)
                logger.info(f"Caméra {camera_id} - White balance range chargé: {cam_data.whitebalance_min}K - {cam_data.whitebalance_max}K")
        except Exception as e:
            logger.error(f"Caméra {camera_id} - Erreur lors du chargement de la description du white balance: {e}")
        
        # Charger la description du tint
        try:
            tint_desc = cam_data.controller.get_whitebalance_tint_description()
            if tint_desc:
                cam_data.tint_min = tint_desc.get('min', 0)
                cam_data.tint_max = tint_desc.get('max', 0)
                logger.info(f"Caméra {camera_id} - Tint range chargé: {cam_data.tint_min} - {cam_data.tint_max}")
        except Exception as e:
            logger.error(f"Caméra {camera_id} - Erreur lors du chargement de la description du tint: {e}")
    
    def increment_whitebalance(self, camera_id: Optional[int] = None):
        """Incrémente le white balance de 100K pour la caméra spécifiée ou active."""
        # Le signal clicked de QPushButton émet un booléen, donc on doit ignorer False
        if camera_id is not None and camera_id is not False and isinstance(camera_id, int):
            if camera_id < 1 or camera_id > 8:
                logger.error(f"ID de caméra invalide: {camera_id}")
                return
            cam_data = self.cameras[camera_id]
        else:
            cam_data = self.get_active_camera_data()
        
        if not cam_data.connected or not cam_data.controller:
            return
        
        current_value = cam_data.whitebalance_actual_value if cam_data.whitebalance_actual_value > 0 else cam_data.whitebalance_sent_value
        if current_value == 0:
            current_value = 3200  # Valeur par défaut si pas encore chargée
        
        increment = 100  # Incrément de 100K
        new_value = current_value + increment
        
        # Vérifier les limites
        if cam_data.whitebalance_max > 0 and new_value > cam_data.whitebalance_max:
            new_value = cam_data.whitebalance_max
        
        self.update_whitebalance_value(new_value, camera_id=camera_id)
    
    def decrement_whitebalance(self, camera_id: Optional[int] = None):
        """Décrémente le white balance de 100K pour la caméra spécifiée ou active."""
        # Le signal clicked de QPushButton émet un booléen, donc on doit ignorer False
        if camera_id is not None and camera_id is not False and isinstance(camera_id, int):
            if camera_id < 1 or camera_id > 8:
                logger.error(f"ID de caméra invalide: {camera_id}")
                return
            cam_data = self.cameras[camera_id]
        else:
            cam_data = self.get_active_camera_data()
        
        if not cam_data.connected or not cam_data.controller:
            return
        
        current_value = cam_data.whitebalance_actual_value if cam_data.whitebalance_actual_value > 0 else cam_data.whitebalance_sent_value
        if current_value == 0:
            current_value = 3200  # Valeur par défaut si pas encore chargée
        
        decrement = 100  # Décrément de 100K
        new_value = current_value - decrement
        
        # Vérifier les limites
        if cam_data.whitebalance_min > 0 and new_value < cam_data.whitebalance_min:
            new_value = cam_data.whitebalance_min
        
        self.update_whitebalance_value(new_value, camera_id=camera_id)
    
    def update_whitebalance_value(self, value: int, camera_id: Optional[int] = None):
        """Met à jour la valeur du white balance pour la caméra spécifiée ou active."""
        # Le signal clicked de QPushButton émet un booléen, donc on doit ignorer False
        if camera_id is not None and camera_id is not False and isinstance(camera_id, int):
            if camera_id < 1 or camera_id > 8:
                logger.error(f"ID de caméra invalide: {camera_id}")
                return
            cam_data = self.cameras[camera_id]
        else:
            cam_data = self.get_active_camera_data()
        
        cam_data.whitebalance_sent_value = value
        # Passer None au lieu de False pour send_whitebalance_value
        actual_camera_id = camera_id if (camera_id is not None and camera_id is not False and isinstance(camera_id, int)) else None
        self.send_whitebalance_value(value, camera_id=actual_camera_id)
    
    def send_whitebalance_value(self, value: int, camera_id: Optional[int] = None):
        """Envoie la valeur du white balance directement (utilisé par Companion)."""
        # Le signal clicked de QPushButton émet un booléen, donc on doit ignorer False
        if camera_id is not None and camera_id is not False and isinstance(camera_id, int):
            if camera_id < 1 or camera_id > 8:
                logger.error(f"ID de caméra invalide: {camera_id}")
                return
            cam_data = self.cameras[camera_id]
        else:
            cam_data = self.get_active_camera_data()
        
        if not cam_data.connected or not cam_data.controller:
            return
        
        # Vérifier si un envoi est déjà en cours
        if hasattr(self, 'whitebalance_sending') and self.whitebalance_sending:
            return
        
        self.whitebalance_sending = True
        
        try:
            success = cam_data.controller.set_whitebalance(value, silent=True)
            if not success:
                logger.error(f"Erreur lors de l'envoi du white balance")
        except Exception as e:
            logger.error(f"Erreur lors de l'envoi du white balance: {e}")
        finally:
            # Attendre 50ms après l'envoi avant de permettre le suivant
            QTimer.singleShot(50, self._on_whitebalance_send_complete)
    
    def _send_whitebalance_value_now(self, value: int):
        """Envoie la valeur du white balance avec gestion du lock."""
        cam_data = self.get_active_camera_data()
        if not cam_data.connected or not cam_data.controller:
            return
        
        # Vérifier si un envoi est déjà en cours
        if hasattr(self, 'whitebalance_sending') and self.whitebalance_sending:
            return
        
        self.whitebalance_sending = True
        
        try:
            success = cam_data.controller.set_whitebalance(value, silent=True)
            if not success:
                logger.error(f"Erreur lors de l'envoi du white balance")
        except Exception as e:
            logger.error(f"Erreur lors de l'envoi du white balance: {e}")
        finally:
            # Attendre 50ms après l'envoi avant de permettre le suivant
            QTimer.singleShot(50, self._on_whitebalance_send_complete)
    
    def _on_whitebalance_send_complete(self):
        """Callback après l'envoi du white balance."""
        self.whitebalance_sending = False
    
    def do_auto_whitebalance(self, camera_id: Optional[int] = None):
        """Déclenche l'auto white balance pour la caméra spécifiée ou la caméra active."""
        # Utiliser la caméra spécifiée ou la caméra active
        if camera_id is None or camera_id is False:
            camera_id = self.active_camera_id
        
        # Vérifier que camera_id est un entier valide
        if not isinstance(camera_id, int) or camera_id < 1 or camera_id > 8:
            logger.warning(f"ID de caméra invalide pour auto white balance: {camera_id}")
            return
        
        cam_data = self.cameras[camera_id]
        if not cam_data.connected or not cam_data.controller:
            logger.warning(f"Caméra {camera_id} non connectée pour auto white balance")
            return
        
        try:
            success = cam_data.controller.do_auto_whitebalance(silent=True)
            if not success:
                logger.error(f"Erreur lors du déclenchement de l'auto white balance")
        except Exception as e:
            logger.error(f"Erreur lors du déclenchement de l'auto white balance: {e}")
    
    def on_whitebalance_changed(self, value: int):
        """Callback appelé quand le white balance change via WebSocket."""
        cam_data = self.get_active_camera_data()
        cam_data.whitebalance_actual_value = value
        
        # Mettre à jour l'UI
        self.whitebalance_value_actual.setText(f"{value}K")
    
    def increment_tint(self, camera_id: Optional[int] = None):
        """Incrémente le tint de 1 pour la caméra spécifiée ou active."""
        if camera_id is not None and camera_id is not False and isinstance(camera_id, int):
            if camera_id < 1 or camera_id > 8:
                logger.error(f"ID de caméra invalide: {camera_id}")
                return
            cam_data = self.cameras[camera_id]
        else:
            cam_data = self.get_active_camera_data()
        
        if not cam_data.connected or not cam_data.controller:
            return
        
        # Utiliser la valeur la plus récente entre sent et actual (comme pour whitebalance)
        current_value = cam_data.tint_sent_value if cam_data.tint_sent_value != 0 else cam_data.tint_actual_value
        if current_value == 0:
            # Essayer de charger la valeur depuis la caméra
            tint_value = cam_data.controller.get_whitebalance_tint()
            if tint_value is not None:
                current_value = tint_value
                cam_data.tint_actual_value = tint_value
                cam_data.tint_sent_value = tint_value
        
        increment = 1  # Incrément de 1
        new_value = current_value + increment
        
        # Vérifier les limites
        if cam_data.tint_max > 0 and new_value > cam_data.tint_max:
            new_value = cam_data.tint_max
        
        self.update_tint_value(new_value, camera_id=camera_id)
    
    def decrement_tint(self, camera_id: Optional[int] = None):
        """Décrémente le tint de 1 pour la caméra spécifiée ou active."""
        if camera_id is not None and camera_id is not False and isinstance(camera_id, int):
            if camera_id < 1 or camera_id > 8:
                logger.error(f"ID de caméra invalide: {camera_id}")
                return
            cam_data = self.cameras[camera_id]
        else:
            cam_data = self.get_active_camera_data()
        
        if not cam_data.connected or not cam_data.controller:
            return
        
        # Utiliser la valeur la plus récente entre sent et actual (comme pour whitebalance)
        current_value = cam_data.tint_sent_value if cam_data.tint_sent_value != 0 else cam_data.tint_actual_value
        if current_value == 0:
            # Essayer de charger la valeur depuis la caméra
            tint_value = cam_data.controller.get_whitebalance_tint()
            if tint_value is not None:
                current_value = tint_value
                cam_data.tint_actual_value = tint_value
                cam_data.tint_sent_value = tint_value
        
        decrement = 1  # Décrément de 1
        new_value = current_value - decrement
        
        # Vérifier les limites
        if cam_data.tint_min > 0 and new_value < cam_data.tint_min:
            new_value = cam_data.tint_min
        
        self.update_tint_value(new_value, camera_id=camera_id)
    
    def update_tint_value(self, value: int, camera_id: Optional[int] = None):
        """Met à jour la valeur du tint pour la caméra spécifiée ou active."""
        if camera_id is not None and camera_id is not False and isinstance(camera_id, int):
            if camera_id < 1 or camera_id > 8:
                logger.error(f"ID de caméra invalide: {camera_id}")
                return
            cam_data = self.cameras[camera_id]
        else:
            cam_data = self.get_active_camera_data()
        
        cam_data.tint_sent_value = value
        # Passer None au lieu de False pour send_tint_value
        actual_camera_id = camera_id if (camera_id is not None and camera_id is not False and isinstance(camera_id, int)) else None
        self.send_tint_value(value, camera_id=actual_camera_id)
    
    def send_tint_value(self, value: int, camera_id: Optional[int] = None):
        """Envoie la valeur du tint directement (utilisé par Companion)."""
        if camera_id is not None and camera_id is not False and isinstance(camera_id, int):
            if camera_id < 1 or camera_id > 8:
                logger.error(f"ID de caméra invalide: {camera_id}")
                return
            cam_data = self.cameras[camera_id]
        else:
            cam_data = self.get_active_camera_data()
        
        if not cam_data.connected or not cam_data.controller:
            return
        
        # Vérifier si un envoi est déjà en cours
        if hasattr(self, 'tint_sending') and self.tint_sending:
            return
        
        self.tint_sending = True
        
        try:
            success = cam_data.controller.set_whitebalance_tint(value, silent=True)
            if not success:
                logger.error(f"Erreur lors de l'envoi du tint")
        except Exception as e:
            logger.error(f"Erreur lors de l'envoi du tint: {e}")
        finally:
            # Attendre 50ms après l'envoi avant de permettre le suivant
            QTimer.singleShot(50, self._on_tint_send_complete)
    
    def _on_tint_send_complete(self):
        """Callback après l'envoi du tint."""
        self.tint_sending = False
    
    def on_tint_changed(self, value: int):
        """Callback appelé quand le tint change via WebSocket."""
        # #region agent log
        try:
            import json
            import time
            with open('/Users/laurenteyen/Documents/cursor/FocusBMrestAPI1/.cursor/debug.log', 'a') as f:
                f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"A","location":"focus_ui_pyside6_standalone.py:3112","message":"on_tint_changed called","data":{"value":value},"timestamp":int(time.time()*1000)})+'\n')
        except: pass
        # #endregion
        cam_data = self.get_active_camera_data()
        cam_data.tint_actual_value = value
        # #region agent log
        try:
            import json
            import time
            with open('/Users/laurenteyen/Documents/cursor/FocusBMrestAPI1/.cursor/debug.log', 'a') as f:
                f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"A","location":"focus_ui_pyside6_standalone.py:3116","message":"tint_actual_value updated","data":{"tint_actual_value":cam_data.tint_actual_value,"active_camera_id":self.active_camera_id},"timestamp":int(time.time()*1000)})+'\n')
        except: pass
        # #endregion
        
        # Mettre à jour l'UI
        if cam_data == self.get_active_camera_data():
            # #region agent log
            try:
                import json
                import time
                with open('/Users/laurenteyen/Documents/cursor/FocusBMrestAPI1/.cursor/debug.log', 'a') as f:
                    f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"A","location":"focus_ui_pyside6_standalone.py:3120","message":"updating UI tint_value_actual","data":{"value":value},"timestamp":int(time.time()*1000)})+'\n')
            except: pass
            # #endregion
            self.tint_value_actual.setText(f"{value}")
    
    def create_shutter_panel(self):
        """Crée le panneau de contrôle du shutter."""
        panel = QWidget()
        panel_width = self._scale_value(200)  # Élargi
        panel.setMinimumWidth(panel_width)
        panel.setMaximumWidth(panel_width)
        panel.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        panel.setStyleSheet(self._scale_style("""
            QWidget {
                background-color: #1a1a1a;
                border: 1px solid #444;
                border-radius: 4px;
            }
        """))
        layout = QVBoxLayout(panel)
        spacing = self._scale_value(8)  # Espacement réduit pour correspondre à White Balance
        margin = self._scale_value(15)  # Marges réduites pour correspondre à White Balance
        layout.setSpacing(spacing)
        layout.setContentsMargins(margin, margin, margin, margin)
        
        title = QLabel("⚡ Shutter Control")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(f"font-size: {self._scale_font(20)}; color: #fff;")
        layout.addWidget(title)
        
        # Section d'affichage
        shutter_display = QWidget()
        shutter_display_layout = QVBoxLayout(shutter_display)
        shutter_display_layout.setSpacing(self._scale_value(10))
        
        shutter_label = QLabel("Shutter Speed (1/Xs)")
        shutter_label.setAlignment(Qt.AlignCenter)
        shutter_label.setStyleSheet(f"font-size: {self._scale_font(10)}; color: #aaa; text-transform: uppercase;")
        shutter_display_layout.addWidget(shutter_label)
        
        # Container pour les valeurs (vertical : envoyé au-dessus de réel)
        value_container = QWidget()
        value_container_width = self._scale_value(90)
        value_container.setMinimumWidth(value_container_width)
        value_container.setMaximumWidth(value_container_width)
        value_layout = QVBoxLayout(value_container)
        value_layout.setSpacing(self._scale_value(5))
        value_layout.setContentsMargins(self._scale_value(5), 0, self._scale_value(5), 0)
        
        # Valeur réelle uniquement (pas d'envoyé)
        actual_label = QLabel("Réel (GET)")
        actual_label.setAlignment(Qt.AlignCenter)
        actual_label.setStyleSheet(f"font-size: {self._scale_font(9)}; color: #888;")
        value_layout.addWidget(actual_label)
        self.shutter_value_actual = QLabel("-")
        self.shutter_value_actual.setAlignment(Qt.AlignCenter)
        self.shutter_value_actual.setStyleSheet(f"font-size: {self._scale_font(12)}; font-weight: bold; color: #0ff; font-family: 'Courier New';")
        value_layout.addWidget(self.shutter_value_actual)
        
        shutter_display_layout.addWidget(value_container, alignment=Qt.AlignCenter)
        layout.addWidget(shutter_display)
        
        # Espacement avant les boutons
        layout.addSpacing(self._scale_value(20))
        
        # Boutons + et - alignés horizontalement
        buttons_container = QWidget()
        buttons_container_layout = QVBoxLayout(buttons_container)
        buttons_container_layout.setContentsMargins(0, self._scale_value(15), 0, self._scale_value(15))
        buttons_container_layout.setSpacing(0)
        
        self.shutter_plus_btn, self.shutter_minus_btn = self._create_plus_minus_buttons(
            self.increment_shutter,
            self.decrement_shutter,
            buttons_container_layout
        )
        
        layout.addWidget(buttons_container, alignment=Qt.AlignCenter)
        
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
    
    def increment_shutter(self, camera_id: Optional[int] = None):
        """Incrémente le shutter vers la vitesse suivante supportée pour la caméra spécifiée ou active."""
        # Le signal clicked de QPushButton émet un booléen, donc on doit ignorer False
        if camera_id is not None and camera_id is not False and isinstance(camera_id, int):
            if camera_id < 1 or camera_id > 8:
                logger.error(f"ID de caméra invalide: {camera_id}")
                return
            cam_data = self.cameras[camera_id]
        else:
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
                self.update_shutter_value(new_value, camera_id=camera_id)
        except ValueError:
            # Valeur actuelle pas dans la liste, prendre la plus proche
            nearest = min(cam_data.supported_shutter_speeds, key=lambda x: abs(x - current_value))
            nearest_index = cam_data.supported_shutter_speeds.index(nearest)
            if nearest_index < len(cam_data.supported_shutter_speeds) - 1:
                new_value = cam_data.supported_shutter_speeds[nearest_index + 1]
                self.update_shutter_value(new_value, camera_id=camera_id)
    
    def decrement_shutter(self, camera_id: Optional[int] = None):
        """Décrémente le shutter vers la vitesse précédente supportée pour la caméra spécifiée ou active."""
        # Le signal clicked de QPushButton émet un booléen, donc on doit ignorer False
        if camera_id is not None and camera_id is not False and isinstance(camera_id, int):
            if camera_id < 1 or camera_id > 8:
                logger.error(f"ID de caméra invalide: {camera_id}")
                return
            cam_data = self.cameras[camera_id]
        else:
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
                self.update_shutter_value(new_value, camera_id=camera_id)
        except ValueError:
            # Valeur actuelle pas dans la liste, prendre la plus proche
            nearest = min(cam_data.supported_shutter_speeds, key=lambda x: abs(x - current_value))
            nearest_index = cam_data.supported_shutter_speeds.index(nearest)
            if nearest_index > 0:
                new_value = cam_data.supported_shutter_speeds[nearest_index - 1]
                self.update_shutter_value(new_value, camera_id=camera_id)
    
    def update_shutter_value(self, value: int, camera_id: Optional[int] = None):
        """Met à jour la valeur du shutter pour la caméra spécifiée ou active."""
        # Le signal clicked de QPushButton émet un booléen, donc on doit ignorer False
        if camera_id is not None and camera_id is not False and isinstance(camera_id, int):
            if camera_id < 1 or camera_id > 8:
                logger.error(f"ID de caméra invalide: {camera_id}")
                return
            cam_data = self.cameras[camera_id]
        else:
            cam_data = self.get_active_camera_data()
        
        cam_data.shutter_sent_value = value
        # Passer None au lieu de False pour send_shutter_value
        actual_camera_id = camera_id if (camera_id is not None and camera_id is not False and isinstance(camera_id, int)) else None
        self.send_shutter_value(value, camera_id=actual_camera_id)
    
    def send_shutter_value(self, value: int, camera_id: Optional[int] = None):
        """Envoie la valeur du shutter directement (sans throttling) pour la caméra active."""
        # Le signal clicked de QPushButton émet un booléen, donc on doit ignorer False
        if camera_id is not None and camera_id is not False and isinstance(camera_id, int):
            if camera_id < 1 or camera_id > 8:
                logger.error(f"ID de caméra invalide: {camera_id}")
                return
            cam_data = self.cameras[camera_id]
        else:
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
        panel_width = self._scale_value(170)  # Réduit pour optimiser l'espace pour les sliders (panneau non utilisé)
        panel.setMinimumWidth(panel_width)
        panel.setMaximumWidth(panel_width)
        panel.setStyleSheet(self._scale_style("""
            QWidget {
                background-color: #1a1a1a;
                border: 1px solid #444;
                border-radius: 4px;
            }
        """))
        layout = QVBoxLayout(panel)
        spacing = self._scale_value(15)
        margin = self._scale_value(30)
        layout.setSpacing(spacing)
        layout.setContentsMargins(margin, margin, margin, margin)
        
        title = QLabel("🔍 Zoom Control")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(f"font-size: {self._scale_font(20)}; color: #fff;")
        layout.addWidget(title)
        
        # Section d'affichage
        zoom_display = QWidget()
        zoom_display_layout = QVBoxLayout(zoom_display)
        zoom_display_layout.setSpacing(self._scale_value(10))
        
        zoom_label = QLabel("Focale (Zoom)")
        zoom_label.setAlignment(Qt.AlignCenter)
        zoom_label.setStyleSheet(f"font-size: {self._scale_font(10)}; color: #aaa; text-transform: uppercase;")
        zoom_display_layout.addWidget(zoom_label)
        
        # Row pour les valeurs
        value_row = QWidget()
        value_row_layout = QHBoxLayout(value_row)
        value_row_layout.setSpacing(self._scale_value(20))
        
        # Focale
        focal_container = QWidget()
        focal_container_width = self._scale_value(90)
        focal_container.setMinimumWidth(focal_container_width)
        focal_container.setMaximumWidth(focal_container_width)
        focal_layout = QVBoxLayout(focal_container)
        focal_layout.setSpacing(self._scale_value(3))
        focal_layout.setContentsMargins(self._scale_value(5), 0, self._scale_value(5), 0)
        focal_label = QLabel("Focale")
        focal_label.setAlignment(Qt.AlignCenter)
        focal_label.setStyleSheet(f"font-size: {self._scale_font(9)}; color: #888;")
        focal_layout.addWidget(focal_label)
        self.zoom_focal_length = QLabel("-")
        self.zoom_focal_length.setAlignment(Qt.AlignCenter)
        self.zoom_focal_length.setStyleSheet(f"font-size: {self._scale_font(12)}; font-weight: bold; color: #0ff; font-family: 'Courier New';")
        focal_layout.addWidget(self.zoom_focal_length)
        value_row_layout.addWidget(focal_container)
        
        # Normalisé
        norm_container = QWidget()
        norm_container.setMinimumWidth(focal_container_width)
        norm_container.setMaximumWidth(focal_container_width)
        norm_layout = QVBoxLayout(norm_container)
        norm_layout.setSpacing(self._scale_value(3))
        norm_layout.setContentsMargins(self._scale_value(5), 0, self._scale_value(5), 0)
        norm_label = QLabel("Normalisé")
        norm_label.setAlignment(Qt.AlignCenter)
        norm_label.setStyleSheet(f"font-size: {self._scale_font(9)}; color: #888;")
        norm_layout.addWidget(norm_label)
        self.zoom_normalised = QLabel("-")
        self.zoom_normalised.setAlignment(Qt.AlignCenter)
        self.zoom_normalised.setStyleSheet(f"font-size: {self._scale_font(12)}; font-weight: bold; color: #0ff; font-family: 'Courier New';")
        norm_layout.addWidget(self.zoom_normalised)
        value_row_layout.addWidget(norm_container)
        
        zoom_display_layout.addWidget(value_row)
        
        # Info supplémentaire
        zoom_info = QLabel("Focale en millimètres")
        zoom_info.setAlignment(Qt.AlignCenter)
        zoom_info.setStyleSheet(f"font-size: {self._scale_font(9)}; color: #888;")
        zoom_display_layout.addWidget(zoom_info)
        
        layout.addWidget(zoom_display)
        
        layout.addStretch()
        return panel
    
    def create_controls_panel(self):
        """Crée le panneau de contrôles."""
        panel = QWidget()
        panel_width = self._scale_value(170)  # Réduit pour optimiser l'espace pour les sliders
        panel.setMinimumWidth(panel_width)
        panel.setMaximumWidth(panel_width)
        panel.setStyleSheet(self._scale_style("""
            QWidget {
                background-color: #1a1a1a;
                border: 1px solid #444;
                border-radius: 4px;
            }
        """))
        layout = QVBoxLayout(panel)
        spacing = self._scale_value(15)
        margin = self._scale_value(30)
        layout.setSpacing(spacing)
        layout.setContentsMargins(margin, margin, margin, margin)
        
        title = QLabel("Contrôles")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(f"font-size: {self._scale_font(20)}; color: #fff;")
        layout.addWidget(title)
        
        # Variables pour les états des toggles
        self.zebra_enabled = False
        self.focusAssist_enabled = False
        self.falseColor_enabled = False
        self.cleanfeed_enabled = False
        
        # Boutons toggle
        toggle_style = self._scale_style("""
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
        
        self.zebra_toggle = QPushButton("Zebra\nOFF")
        self.zebra_toggle.setCheckable(True)
        self.zebra_toggle.setStyleSheet(toggle_style)
        self.zebra_toggle.clicked.connect(self.toggle_zebra)
        layout.addWidget(self.zebra_toggle)
        
        self.focusAssist_toggle = QPushButton("Focus Assist\nOFF")
        self.focusAssist_toggle.setCheckable(True)
        self.focusAssist_toggle.setStyleSheet(toggle_style)
        self.focusAssist_toggle.clicked.connect(self.toggle_focus_assist)
        layout.addWidget(self.focusAssist_toggle)
        
        self.falseColor_toggle = QPushButton("False Color\nOFF")
        self.falseColor_toggle.setCheckable(True)
        self.falseColor_toggle.setStyleSheet(toggle_style)
        self.falseColor_toggle.clicked.connect(self.toggle_false_color)
        layout.addWidget(self.falseColor_toggle)
        
        self.cleanfeed_toggle = QPushButton("Cleanfeed\nOFF")
        self.cleanfeed_toggle.setCheckable(True)
        self.cleanfeed_toggle.setStyleSheet(toggle_style)
        self.cleanfeed_toggle.clicked.connect(self.toggle_cleanfeed)
        layout.addWidget(self.cleanfeed_toggle)
        
        # Bouton pour activer/désactiver la transition progressive
        self.smooth_transition_toggle = QPushButton("Transition\nProgressive\nON")
        self.smooth_transition_toggle.setCheckable(True)
        self.smooth_transition_toggle.setChecked(True)  # Activé par défaut
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
        crossfade_label.setStyleSheet(f"font-size: {self._scale_font(12)}; font-weight: bold; color: #aaa; margin-top: {self._scale_value(10)}px;")
        layout.addWidget(crossfade_label)
        
        self.crossfade_duration_spinbox = QDoubleSpinBox()
        self.crossfade_duration_spinbox.setMinimum(0.0)
        self.crossfade_duration_spinbox.setMaximum(30.0)
        self.crossfade_duration_spinbox.setSingleStep(0.1)
        self.crossfade_duration_spinbox.setValue(2.0)
        self.crossfade_duration_spinbox.setDecimals(1)
        self.crossfade_duration_spinbox.setStyleSheet(self._scale_style("""
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
        """))
        self.crossfade_duration_spinbox.valueChanged.connect(self.on_crossfade_duration_changed)
        layout.addWidget(self.crossfade_duration_spinbox)
        
        layout.addStretch()
        return panel
    
    def create_slider_axis_panel(self, axis_name: str, display_name: str):
        """Crée un panneau de contrôle pour un axe du slider (pan, tilt, slide, zoom motor)."""
        panel = QWidget()
        # Utiliser un pourcentage de la largeur de la fenêtre (environ 20% de la largeur de référence)
        # Cela rend les sliders proportionnels à la taille de la fenêtre et optimisés pour maximum de largeur
        # La largeur sera mise à jour dans _update_ui_scaling lors du redimensionnement
        panel_width = self._scale_value(280)  # Largeur initiale optimisée, sera mise à jour lors du resize
        panel.setMinimumWidth(panel_width)
        panel.setMaximumWidth(panel_width)
        # Avec slider horizontal, on n'a plus besoin d'Expanding verticalement
        panel.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        panel.setStyleSheet(self._scale_style("""
            QWidget {
                background-color: #1a1a1a;
                border: 1px solid #444;
                border-radius: 4px;
            }
        """))
        layout = QVBoxLayout(panel)
        spacing = self._scale_value(10)  # Réduire l'espacement pour donner plus d'espace au slider
        margin = self._scale_value(20)  # Réduire les marges pour donner plus d'espace au slider
        layout.setSpacing(spacing)
        layout.setContentsMargins(margin, margin, margin, margin)
        
        # Titre
        title = QLabel(display_name)
        title.setAlignment(Qt.AlignCenter)
        font_size = self._scale_font(14)
        title.setStyleSheet(f"font-size: {font_size}; color: #fff;")
        layout.addWidget(title, stretch=0)
        
        # Affichage des valeurs (% et steps) au-dessus du slider
        values_display = QWidget()
        values_layout = QHBoxLayout(values_display)
        values_layout.setContentsMargins(0, 0, 0, 0)
        values_layout.setSpacing(10)
        
        # Label pour le pourcentage
        percent_label = QLabel("0.0%")
        percent_label.setAlignment(Qt.AlignLeft)
        percent_label.setStyleSheet(f"font-size: {self._scale_font(11)}; font-weight: bold; color: #0ff; font-family: 'Courier New';")
        values_layout.addWidget(percent_label)
        
        values_layout.addStretch()
        
        # Label pour les steps (juste la valeur numérique en jaune)
        steps_label = QLabel("0")
        steps_label.setAlignment(Qt.AlignRight)
        steps_label.setStyleSheet(f"font-size: {self._scale_font(11)}; font-weight: bold; color: #ff0; font-family: 'Courier New';")
        values_layout.addWidget(steps_label)
        
        # Initialiser les labels avec des valeurs par défaut
        percent_label.setText("0.0%")
        steps_label.setText("0")
        
        layout.addWidget(values_display, stretch=0)
        
        # Slider horizontal
        slider_container = QWidget()
        slider_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        slider_layout = QVBoxLayout(slider_container)
        slider_layout.setContentsMargins(0, 0, 0, 0)
        slider_layout.setSpacing(5)
        
        # Labels pour le slider (0.0 à gauche, 0.5 au centre, 1.0 à droite)
        labels_row = QWidget()
        labels_layout = QHBoxLayout(labels_row)
        labels_layout.setContentsMargins(0, 0, 0, 0)
        labels_layout.setSpacing(0)
        
        label_0 = QLabel("0.0")
        label_0.setStyleSheet(f"font-size: {self._scale_font(9)}; color: #aaa;")
        labels_layout.addWidget(label_0)
        labels_layout.addStretch()
        label_05 = QLabel("0.5")
        label_05.setAlignment(Qt.AlignCenter)
        label_05.setStyleSheet(f"font-size: {self._scale_font(9)}; color: #aaa;")
        labels_layout.addWidget(label_05)
        labels_layout.addStretch()
        label_1 = QLabel("1.0")
        label_1.setAlignment(Qt.AlignRight)
        label_1.setStyleSheet(f"font-size: {self._scale_font(9)}; color: #aaa;")
        labels_layout.addWidget(label_1)
        
        slider_layout.addWidget(labels_row)
        
        # Slider horizontal
        slider = QSlider(Qt.Horizontal)
        slider.setMinimum(0)
        slider.setMaximum(1000)  # 0.001 de précision
        slider.setValue(500)  # Position centrale par défaut (0.5)
        slider.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        slider.setStyleSheet(self._scale_style("""
            QSlider::groove:horizontal {
                background: #333;
                height: 8px;
                border: 1px solid #555;
                border-radius: 4px;
            }
            QSlider::handle:horizontal {
                background: #666;
                border: 1px solid #888;
                border-radius: 8px;
                width: 18px;
                height: 18px;
                margin: -6px 0;
            }
            QSlider::handle:horizontal:hover {
                background: #777;
            }
        """))
        
        slider_layout.addWidget(slider)
        
        layout.addWidget(slider_container, stretch=0)
        
        # Stocker les références dans le panel
        panel.slider = slider
        panel.axis_name = axis_name
        panel.percent_label = percent_label
        panel.steps_label = steps_label
        
        return panel
    
    def on_slider_position_update(self, data: Dict[str, Any], camera_id: Optional[int] = None):
        """
        Callback appelé quand les positions du slider sont mises à jour via WebSocket.
        
        Args:
            data: Dictionnaire avec les positions (format WebSocket)
                {
                    "pan": {"steps": 12345, "normalized": 0.5},
                    "tilt": {"steps": 6789, "normalized": 0.75},
                    "zoom": {"steps": 1000, "normalized": 0.3},
                    "slide": {"steps": 5000, "normalized": 0.6},
                    "timestamp": 1234567890
                }
            camera_id: ID de la caméra (optionnel, utilise active_camera_id si None)
        """
        # Utiliser camera_id si fourni, sinon utiliser la caméra active
        if camera_id is None:
            camera_id = self.active_camera_id
        
        if camera_id < 1 or camera_id > 8:
            return
        
        cam_data = self.cameras[camera_id]
        
        # Vérifier que c'est la caméra active avant de mettre à jour l'UI
        if camera_id != self.active_camera_id or not cam_data.connected:
            # Mettre à jour les données même si ce n'est pas la caméra active
            # mais ne pas mettre à jour l'UI
            try:
                pan_data = data.get('pan', {})
                tilt_data = data.get('tilt', {})
                zoom_data = data.get('zoom', {})
                slide_data = data.get('slide', {})
                
                cam_data.slider_pan_value = float(pan_data.get('normalized', 0.0))
                cam_data.slider_tilt_value = float(tilt_data.get('normalized', 0.0))
                cam_data.slider_zoom_value = float(zoom_data.get('normalized', 0.0))
                cam_data.slider_slide_value = float(slide_data.get('normalized', 0.0))
                
                cam_data.slider_pan_steps = int(pan_data.get('steps', 0))
                cam_data.slider_tilt_steps = int(tilt_data.get('steps', 0))
                cam_data.slider_zoom_steps = int(zoom_data.get('steps', 0))
                cam_data.slider_slide_steps = int(slide_data.get('steps', 0))
                
                # Extraire et stocker les offsets joystick
                joystick_offsets = data.get('joystick_offsets', {})
                cam_data.slider_joystick_pan_offset = float(joystick_offsets.get('pan', 0.0))
                cam_data.slider_joystick_tilt_offset = float(joystick_offsets.get('tilt', 0.0))
                cam_data.slider_joystick_zoom_offset = float(joystick_offsets.get('zoom', 0.0))
                cam_data.slider_joystick_slide_offset = float(joystick_offsets.get('slide', 0.0))
                
                # Mettre à jour le StateStore pour Companion (même si ce n'est pas la caméra active)
                self.state_store.update_cam(
                    camera_id,
                    slider_pan=cam_data.slider_pan_value,
                    slider_tilt=cam_data.slider_tilt_value,
                    slider_zoom=cam_data.slider_zoom_value,
                    slider_slide=cam_data.slider_slide_value
                )
            except Exception:
                pass
            return
        
        try:
            # Extraire les valeurs normalized et steps
            pan_data = data.get('pan', {})
            tilt_data = data.get('tilt', {})
            zoom_data = data.get('zoom', {})
            slide_data = data.get('slide', {})
            
            # Debug: vérifier si les steps sont présents dans les données
            logger.debug(f"WebSocket data reçue - pan steps: {pan_data.get('steps')}, tilt steps: {tilt_data.get('steps')}, zoom steps: {zoom_data.get('steps')}, slide steps: {slide_data.get('steps')}")
            
            # Mettre à jour CameraData avec les valeurs normalized
            cam_data.slider_pan_value = float(pan_data.get('normalized', 0.0))
            cam_data.slider_tilt_value = float(tilt_data.get('normalized', 0.0))
            cam_data.slider_zoom_value = float(zoom_data.get('normalized', 0.0))
            cam_data.slider_slide_value = float(slide_data.get('normalized', 0.0))
            
            # Mettre à jour CameraData avec les steps
            cam_data.slider_pan_steps = int(pan_data.get('steps', 0))
            cam_data.slider_tilt_steps = int(tilt_data.get('steps', 0))
            cam_data.slider_zoom_steps = int(zoom_data.get('steps', 0))
            cam_data.slider_slide_steps = int(slide_data.get('steps', 0))
            
            # Extraire et stocker les offsets joystick
            joystick_offsets = data.get('joystick_offsets', {})
            # #region agent log
            try:
                import json, time
                with open('/Users/laurenteyen/Documents/cursor/FocusBMrestAPI1/.cursor/debug.log', 'a') as f:
                    f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"F","location":"focus_ui_pyside6_standalone.py:3687","message":"on_slider_position_update: extraction joystick_offsets","data":{"has_joystick_offsets":"joystick_offsets" in data,"joystick_offsets_raw":joystick_offsets,"pan_offset":joystick_offsets.get('pan', 'missing')},"timestamp":int(time.time()*1000)})+'\n')
            except: pass
            # #endregion
            cam_data.slider_joystick_pan_offset = float(joystick_offsets.get('pan', 0.0))
            cam_data.slider_joystick_tilt_offset = float(joystick_offsets.get('tilt', 0.0))
            cam_data.slider_joystick_zoom_offset = float(joystick_offsets.get('zoom', 0.0))
            cam_data.slider_joystick_slide_offset = float(joystick_offsets.get('slide', 0.0))
            
            # Mettre à jour le StateStore pour Companion
            self.state_store.update_cam(
                camera_id,
                slider_pan=cam_data.slider_pan_value,
                slider_tilt=cam_data.slider_tilt_value,
                zoom_motor=cam_data.slider_zoom_value,  # Position moteur zoom du slider (0.0-1.0)
                slider_slide=cam_data.slider_slide_value
            )
            
            # Mettre à jour la matrice XY pan/tilt et les labels
            if hasattr(self, 'pan_tilt_panel') and hasattr(self.pan_tilt_panel, 'xy_matrix'):
                # Mettre à jour les labels (toujours, même si l'utilisateur touche la matrice)
                if hasattr(self.pan_tilt_panel, 'pan_percent_label'):
                    self.pan_tilt_panel.pan_percent_label.setText(f"{cam_data.slider_pan_value * 100:.1f}%")
                if hasattr(self.pan_tilt_panel, 'pan_steps_label'):
                    self.pan_tilt_panel.pan_steps_label.setText(f"{cam_data.slider_pan_steps}")
                if hasattr(self.pan_tilt_panel, 'tilt_percent_label'):
                    self.pan_tilt_panel.tilt_percent_label.setText(f"{cam_data.slider_tilt_value * 100:.1f}%")
                if hasattr(self.pan_tilt_panel, 'tilt_steps_label'):
                    self.pan_tilt_panel.tilt_steps_label.setText(f"{cam_data.slider_tilt_steps}")
                
                # Mettre à jour la position de la matrice seulement si l'utilisateur ne la touche pas
                if not self.slider_user_touching.get('pan', False) and not self.slider_user_touching.get('tilt', False):
                    self.pan_tilt_panel.xy_matrix.setPosition(cam_data.slider_pan_value, cam_data.slider_tilt_value)
                    self.pan_tilt_panel.xy_matrix.setSteps(cam_data.slider_pan_steps, cam_data.slider_tilt_steps)
            
            if hasattr(self, 'zoom_motor_panel') and hasattr(self.zoom_motor_panel, 'slider'):
                if not self.slider_user_touching.get('zoom', False):
                    zoom_value = int(cam_data.slider_zoom_value * 1000)
                    self.zoom_motor_panel.slider.blockSignals(True)
                    self.zoom_motor_panel.slider.setValue(zoom_value)
                    self.zoom_motor_panel.slider.blockSignals(False)
                # Mettre à jour les labels (toujours, même si l'utilisateur touche le slider)
                if hasattr(self.zoom_motor_panel, 'percent_label'):
                    self.zoom_motor_panel.percent_label.setText(f"{cam_data.slider_zoom_value * 100:.1f}%")
                if hasattr(self.zoom_motor_panel, 'steps_label'):
                    self.zoom_motor_panel.steps_label.setText(f"{cam_data.slider_zoom_steps}")
            
            if hasattr(self, 'slide_panel') and hasattr(self.slide_panel, 'slider'):
                if not self.slider_user_touching.get('slide', False):
                    slide_value = int(cam_data.slider_slide_value * 1000)
                    self.slide_panel.slider.blockSignals(True)
                    self.slide_panel.slider.setValue(slide_value)
                    self.slide_panel.slider.blockSignals(False)
                # Mettre à jour les labels (toujours, même si l'utilisateur touche le slider)
                if hasattr(self.slide_panel, 'percent_label'):
                    self.slide_panel.percent_label.setText(f"{cam_data.slider_slide_value * 100:.1f}%")
                if hasattr(self.slide_panel, 'steps_label'):
                    self.slide_panel.steps_label.setText(f"{cam_data.slider_slide_steps}")
            
        except Exception as e:
            logger.error(f"Erreur lors de la mise à jour des positions du slider via WebSocket: {e}")
    
    def update_slider_status_indicator(self):
        """Met à jour l'indicateur de statut du slider dans la barre de statut pour la caméra active."""
        cam_data = self.get_active_camera_data()
        slider_controller = self.slider_controllers.get(self.active_camera_id)
        
        # Vérifier si le slider est configuré
        slider_configured = slider_controller is not None and (
            slider_controller.is_configured() or 
            (hasattr(slider_controller, 'slider_ip') and slider_controller.slider_ip)
        )
        
        if not slider_configured or not cam_data.slider_ip:
            # Slider non configuré pour cette caméra
            self.slider_status_label.setText(f"● Slider Cam{self.active_camera_id}")
            self.slider_status_label.setStyleSheet("font-size: 12px; color: #666; margin-left: 10px;")
            return
        
        # Vérifier si le slider répond
        try:
            status = slider_controller.get_status(silent=True)
            if status is not None:
                # Slider répond correctement
                self.slider_status_label.setText(f"● Slider Cam{self.active_camera_id}")
                self.slider_status_label.setStyleSheet("font-size: 12px; color: #0f0; margin-left: 10px;")
            else:
                # Slider configuré mais ne répond pas
                self.slider_status_label.setText(f"● Slider Cam{self.active_camera_id}")
                self.slider_status_label.setStyleSheet("font-size: 12px; color: #f00; margin-left: 10px;")
        except Exception:
            # Erreur lors de la vérification
            self.slider_status_label.setText(f"● Slider Cam{self.active_camera_id}")
            self.slider_status_label.setStyleSheet("font-size: 12px; color: #f00; margin-left: 10px;")
    
    def sync_slider_positions_from_api(self, camera_id: Optional[int] = None):
        """Synchronise les positions des faders UI avec les positions réelles du slider via l'API HTTP (fallback)."""
        # Cette méthode est maintenant utilisée uniquement comme fallback si le WebSocket n'est pas disponible
        if camera_id is None:
            camera_id = self.active_camera_id
        cam_data = self.cameras[camera_id]
        slider_controller = self.slider_controllers.get(camera_id)
        
        if not slider_controller or not slider_controller.is_configured():
            return  # Slider non configuré
        
        try:
            # Lire les positions actuelles du slider
            slider_status = slider_controller.get_status(silent=True)
            if not slider_status:
                logger.debug("Impossible de lire les positions du slider")
                return
            
            # Simuler le format WebSocket pour utiliser la même méthode de mise à jour
            data = {
                'pan': {'steps': cam_data.slider_pan_steps, 'normalized': slider_status.get('pan', 0.0)},
                'tilt': {'steps': cam_data.slider_tilt_steps, 'normalized': slider_status.get('tilt', 0.0)},
                'zoom': {'steps': cam_data.slider_zoom_steps, 'normalized': slider_status.get('zoom', 0.0)},
                'slide': {'steps': cam_data.slider_slide_steps, 'normalized': slider_status.get('slide', 0.0)}
            }
            # Note: get_status() ne retourne pas les steps, donc on utilise les steps déjà stockés dans CameraData
            # Le WebSocket est la source principale pour les steps
            
            self.on_slider_position_update(data, camera_id=self.active_camera_id)
            
        except Exception as e:
            logger.error(f"Erreur lors de la synchronisation des positions du slider: {e}")
    
    def create_workspace_2_page(self):
        """Crée la page pour le Workspace 2 avec le panneau Joystick Control et LFO."""
        page = QWidget()
        page.setStyleSheet("""
            QWidget {
                background-color: #2a2a2a;
            }
        """)
        layout = QHBoxLayout(page)
        layout.setContentsMargins(self._scale_value(20), self._scale_value(20), 
                                 self._scale_value(20), self._scale_value(20))
        layout.setSpacing(self._scale_value(20))
        
        # Créer le panneau Joystick Control
        joystick_panel = self.create_joystick_control_panel()
        layout.addWidget(joystick_panel)
        
        # Créer le panneau LFO
        lfo_panel = self.create_lfo_panel()
        layout.addWidget(lfo_panel)
        
        # Créer le panneau Sequences
        sequences_panel = self.create_sequences_panel()
        layout.addWidget(sequences_panel)
        
        layout.addStretch()
        
        return page
    
    def create_workspace_3_page(self):
        """Crée la page pour le Workspace 3 - Vue caméras avec gestion musiciens et plans (style AUTOREAL)."""
        page = QWidget()
        page.setStyleSheet("""
            QWidget {
                background-color: #2a2a2a;
            }
        """)
        main_layout = QHBoxLayout(page)
        main_layout.setContentsMargins(self._scale_value(20), self._scale_value(20), 
                                      self._scale_value(20), self._scale_value(20))
        main_layout.setSpacing(self._scale_value(20))
        
        # Colonne gauche : Gestion des musiciens
        left_panel = self.create_workspace_3_musicians_panel()
        main_layout.addWidget(left_panel, stretch=0)
        
        # Colonne droite : Affichage d'un preset avec Save/Recall et assignation musiciens/plans
        right_panel = self.create_workspace_3_preset_view_panel()
        main_layout.addWidget(right_panel, stretch=1)
        
        return page
    
    def create_workspace_3_musicians_panel(self):
        """Crée le panneau de gestion des musiciens (colonne gauche)."""
        panel = QWidget()
        panel_width = self._scale_value(280)
        panel.setMinimumWidth(panel_width)
        panel.setMaximumWidth(panel_width)
        panel.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        panel.setStyleSheet(self._scale_style("""
            QWidget {
                background-color: #1a1a1a;
                border: 1px solid #444;
                border-radius: 8px;
            }
        """))
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(self._scale_value(25), self._scale_value(25), 
                                 self._scale_value(25), self._scale_value(25))
        layout.setSpacing(self._scale_value(15))
        
        # Titre
        title = QLabel("🎵 Musiciens")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(f"font-size: {self._scale_font(18)}; font-weight: bold; color: #fff;")
        layout.addWidget(title)
        
        # Séparateur
        separator = QWidget()
        separator.setFixedHeight(1)
        separator.setStyleSheet("background-color: #444;")
        layout.addWidget(separator)
        
        # Liste des musiciens
        musicians_scroll = QScrollArea()
        musicians_scroll.setWidgetResizable(True)
        musicians_scroll.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: transparent;
            }
        """)
        
        musicians_list_widget = QWidget()
        musicians_list_layout = QVBoxLayout(musicians_list_widget)
        musicians_list_layout.setContentsMargins(0, 0, 0, 0)
        musicians_list_layout.setSpacing(self._scale_value(8))
        
        self.workspace_3_musicians_list_layout = musicians_list_layout
        self.workspace_3_musician_widgets = []
        
        musicians_scroll.setWidget(musicians_list_widget)
        layout.addWidget(musicians_scroll, stretch=1)
        
        # Séparateur
        separator2 = QWidget()
        separator2.setFixedHeight(1)
        separator2.setStyleSheet("background-color: #444;")
        layout.addWidget(separator2)
        
        # Formulaire d'ajout
        add_label = QLabel("Ajouter un musicien:")
        add_label.setStyleSheet(f"font-size: {self._scale_font(12)}; font-weight: bold; color: #aaa;")
        layout.addWidget(add_label)
        
        add_container = QWidget()
        add_layout = QHBoxLayout(add_container)
        add_layout.setContentsMargins(0, 0, 0, 0)
        add_layout.setSpacing(self._scale_value(8))
        
        self.workspace_3_new_musician_input = QLineEdit()
        self.workspace_3_new_musician_input.setPlaceholderText("Nom du musicien")
        self.workspace_3_new_musician_input.setStyleSheet(self._scale_style("""
            QLineEdit {
                padding: 8px;
                background-color: #2a2a2a;
                border: 1px solid #555;
                border-radius: 4px;
                color: #fff;
                font-size: 12px;
            }
            QLineEdit:focus {
                border: 1px solid #0a5;
                background-color: #333;
            }
        """))
        
        add_btn = QPushButton("+")
        add_btn.setMinimumWidth(self._scale_value(45))
        add_btn.setMinimumHeight(self._scale_value(35))
        add_btn.setStyleSheet(self._scale_style("""
            QPushButton {
                padding: 8px;
                background-color: #0a5;
                border: 1px solid #0c7;
                border-radius: 4px;
                color: #fff;
                font-size: 18px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #0c7;
            }
            QPushButton:pressed {
                background-color: #084;
            }
        """))
        add_btn.clicked.connect(self.workspace_3_add_musician)
        self.workspace_3_new_musician_input.returnPressed.connect(self.workspace_3_add_musician)
        
        add_layout.addWidget(self.workspace_3_new_musician_input)
        add_layout.addWidget(add_btn)
        layout.addWidget(add_container)
        
        # Charger et afficher les musiciens existants
        QTimer.singleShot(100, self.workspace_3_refresh_musicians)
        
        return panel
    
    def create_workspace_3_preset_view_panel(self):
        """Crée le panneau d'affichage d'un preset avec Save/Recall et assignation musiciens/plans."""
        panel = QWidget()
        panel.setStyleSheet(self._scale_style("""
            QWidget {
                background-color: #1a1a1a;
                border: 1px solid #444;
                border-radius: 8px;
            }
        """))
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(self._scale_value(30), self._scale_value(30), 
                                 self._scale_value(30), self._scale_value(30))
        layout.setSpacing(self._scale_value(20))
        
        # Header avec nom de caméra et badges (ON AIR / PREVIEW)
        header_container = QWidget()
        header_layout = QHBoxLayout(header_container)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(self._scale_value(15))
        
        self.workspace_3_camera_name_label = QLabel("📹 Caméra 1")
        self.workspace_3_camera_name_label.setStyleSheet(f"font-size: {self._scale_font(20)}; font-weight: bold; color: #fff;")
        header_layout.addWidget(self.workspace_3_camera_name_label)
        
        # Badges ON AIR / PREVIEW (pour l'instant cachés, intégration ATEM future)
        self.workspace_3_on_air_badge = QLabel("🔴 ON AIR")
        self.workspace_3_on_air_badge.setStyleSheet(f"""
            font-size: {self._scale_font(12)};
            font-weight: bold;
            color: #fff;
            background-color: #f00;
            padding: 5px 10px;
            border-radius: 4px;
        """)
        self.workspace_3_on_air_badge.hide()
        
        self.workspace_3_preview_badge = QLabel("🟢 PREVIEW")
        self.workspace_3_preview_badge.setStyleSheet(f"""
            font-size: {self._scale_font(12)};
            font-weight: bold;
            color: #fff;
            background-color: #0a5;
            padding: 5px 10px;
            border-radius: 4px;
        """)
        self.workspace_3_preview_badge.hide()
        
        header_layout.addWidget(self.workspace_3_on_air_badge)
        header_layout.addWidget(self.workspace_3_preview_badge)
        header_layout.addStretch()
        
        layout.addWidget(header_container)
        
        # Séparateur
        separator = QWidget()
        separator.setFixedHeight(1)
        separator.setStyleSheet("background-color: #444;")
        layout.addWidget(separator)
        
        # Sélecteur de preset (boutons 1-10)
        preset_selector_label = QLabel("Sélectionner un preset:")
        preset_selector_label.setStyleSheet(f"font-size: {self._scale_font(14)}; font-weight: bold; color: #fff;")
        layout.addWidget(preset_selector_label)
        
        preset_buttons_container = QWidget()
        preset_buttons_layout = QGridLayout(preset_buttons_container)
        preset_buttons_layout.setContentsMargins(0, 0, 0, 0)
        preset_buttons_layout.setSpacing(self._scale_value(8))
        
        self.workspace_3_preset_selector_buttons = []
        self.workspace_3_selected_preset_id = 1
        
        for i in range(1, 11):
            row = (i - 1) // 5
            col = (i - 1) % 5
            
            btn = QPushButton(f"{i}")
            btn.setCheckable(True)
            btn.setMinimumHeight(self._scale_value(35))
            btn.setStyleSheet(self._scale_style("""
                QPushButton {
                    padding: 8px;
                    background-color: #333;
                    border: 2px solid #555;
                    border-radius: 4px;
                    color: #fff;
                    font-size: 13px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #444;
                    border-color: #777;
                }
                QPushButton:checked {
                    background-color: #0066cc;
                    border-color: #0088ff;
                }
            """))
            if i == 1:
                btn.setChecked(True)
            btn.clicked.connect(lambda checked, preset_id=i: self.workspace_3_select_preset(preset_id))
            self.workspace_3_preset_selector_buttons.append(btn)
            preset_buttons_layout.addWidget(btn, row, col)
        
        layout.addWidget(preset_buttons_container)
        
        # Séparateur
        separator2 = QWidget()
        separator2.setFixedHeight(1)
        separator2.setStyleSheet("background-color: #444;")
        layout.addWidget(separator2)
        
        # Section pour le preset sélectionné
        preset_title_label = QLabel("Preset 1")
        preset_title_label.setStyleSheet(f"font-size: {self._scale_font(18)}; font-weight: bold; color: #fff;")
        layout.addWidget(preset_title_label)
        self.workspace_3_preset_title_label = preset_title_label
        
        # Boutons Save et Recall pour ce preset (style identique au Workspace 1)
        buttons_container = QWidget()
        buttons_layout = QHBoxLayout(buttons_container)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.setSpacing(self._scale_value(15))
        
        # Bouton Save
        save_btn = QPushButton("Save")
        save_btn.setMinimumHeight(self._scale_value(35))
        save_btn.setStyleSheet(self._scale_style("""
            QPushButton {
                padding: 8px 20px;
                font-size: 12px;
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
        """))
        save_btn.clicked.connect(lambda: self.workspace_3_save_current_preset())
        self.workspace_3_save_btn = save_btn
        
        # Bouton Recall
        recall_btn = QPushButton("Recall")
        recall_btn.setMinimumHeight(self._scale_value(35))
        recall_btn.setStyleSheet(self._scale_style("""
            QPushButton {
                padding: 8px 20px;
                font-size: 12px;
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
        """))
        recall_btn.clicked.connect(lambda: self.workspace_3_recall_current_preset())
        self.workspace_3_recall_btn = recall_btn
        
        buttons_layout.addWidget(save_btn)
        buttons_layout.addWidget(recall_btn)
        buttons_layout.addStretch()
        
        layout.addWidget(buttons_container)
        
        # Séparateur
        separator3 = QWidget()
        separator3.setFixedHeight(1)
        separator3.setStyleSheet("background-color: #444;")
        layout.addWidget(separator3)
        
        # Section assignation musiciens/plans
        assignment_label = QLabel("Assignation musiciens / plans")
        assignment_label.setStyleSheet(f"font-size: {self._scale_font(16)}; font-weight: bold; color: #fff;")
        layout.addWidget(assignment_label)
        
        # Scroll area pour la grille de musiciens
        musicians_scroll = QScrollArea()
        musicians_scroll.setWidgetResizable(True)
        musicians_scroll.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: transparent;
            }
        """)
        
        musicians_grid_widget = QWidget()
        musicians_grid_layout = QVBoxLayout(musicians_grid_widget)
        musicians_grid_layout.setContentsMargins(0, 0, 0, 0)
        musicians_grid_layout.setSpacing(self._scale_value(12))
        
        self.workspace_3_musicians_grid_layout = musicians_grid_layout
        self.workspace_3_musician_plan_widgets = []
        
        musicians_scroll.setWidget(musicians_grid_widget)
        layout.addWidget(musicians_scroll, stretch=1)
        
        # Charger les assignations pour le preset sélectionné
        QTimer.singleShot(200, lambda: self.workspace_3_refresh_preset_assignment())
        
        return panel
    
    def create_joystick_control_panel(self):
        """Crée le panneau de contrôle Joystick."""
        panel = QWidget()
        panel_width = self._scale_value(340)  # 2x plus large que les autres panneaux pour voir tout le cercle
        panel.setMinimumWidth(panel_width)
        panel.setMaximumWidth(panel_width)
        panel.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        panel.setStyleSheet(self._scale_style("""
            QWidget {
                background-color: #1a1a1a;
                border: 1px solid #444;
                border-radius: 4px;
            }
        """))
        layout = QVBoxLayout(panel)
        spacing = self._scale_value(15)
        margin = self._scale_value(30)
        layout.setSpacing(spacing)
        layout.setContentsMargins(margin, margin, margin, margin)
        
        # Titre du panneau (style identique aux autres panneaux)
        title = QLabel("Joystick")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(f"font-size: {self._scale_font(20)}; color: #fff;")
        layout.addWidget(title)
        
        # Container principal pour le contenu (utilise toute la largeur)
        main_container = QWidget()
        main_container_layout = QVBoxLayout(main_container)
        main_container_layout.setContentsMargins(0, 0, 0, 0)
        main_container_layout.setSpacing(self._scale_value(20))
        
        # Joystick 2D pour Pan/Tilt (centré)
        joystick_2d = Joystick2DWidget()
        joystick_2d.setMinimumSize(self._scale_value(200), self._scale_value(200))
        joystick_2d.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        main_container_layout.addWidget(joystick_2d, alignment=Qt.AlignCenter)
        
        # Stocker la référence pour les connexions
        panel.joystick_2d = joystick_2d
        # Stocker la référence globale pour la mise à jour visuelle depuis le clavier
        self.workspace_2_joystick_2d = joystick_2d
        
        # Container pour les faders (vertical, utilise toute la largeur)
        fader_container = QWidget()
        fader_layout = QVBoxLayout(fader_container)
        fader_layout.setContentsMargins(0, 0, 0, 0)
        fader_layout.setSpacing(self._scale_value(15))
        
        # Fader Zoom
        zoom_container = QWidget()
        zoom_container_layout = QVBoxLayout(zoom_container)
        zoom_container_layout.setContentsMargins(0, 0, 0, 0)
        zoom_container_layout.setSpacing(self._scale_value(5))
        
        zoom_label = QLabel("Zoom")
        zoom_label.setAlignment(Qt.AlignCenter)
        zoom_label.setStyleSheet(f"font-size: {self._scale_font(10)}; color: #aaa;")
        zoom_container_layout.addWidget(zoom_label)
        
        # Fader horizontal pour zoom motor (slider) - utilise toute la largeur disponible
        zoom_fader = QSlider(Qt.Horizontal)
        zoom_fader.setMinimum(-1000)  # -1.0 * 1000 pour précision (joystick)
        zoom_fader.setMaximum(1000)  # +1.0 * 1000
        zoom_fader.setValue(0)  # Position centrale (0.0)
        zoom_fader.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        zoom_fader.setStyleSheet(self._scale_style("""
            QSlider::groove:horizontal {
                background: #333;
                height: 8px;
                border: 1px solid #555;
                border-radius: 4px;
            }
            QSlider::handle:horizontal {
                background: #666;
                border: 1px solid #888;
                border-radius: 8px;
                width: 18px;
                height: 18px;
                margin: -6px 0;
            }
            QSlider::handle:horizontal:hover {
                background: #777;
            }
            QSlider::handle:horizontal:pressed {
                background: #0ff;
            }
        """))
        zoom_container_layout.addWidget(zoom_fader)
        fader_layout.addWidget(zoom_container)
        panel.zoom_fader = zoom_fader
        
        # Fader Slide (en dessous de Zoom)
        slide_container = QWidget()
        slide_container_layout = QVBoxLayout(slide_container)
        slide_container_layout.setContentsMargins(0, 0, 0, 0)
        slide_container_layout.setSpacing(self._scale_value(5))
        
        slide_label = QLabel("Slide")
        slide_label.setAlignment(Qt.AlignCenter)
        slide_label.setStyleSheet(f"font-size: {self._scale_font(10)}; color: #aaa;")
        slide_container_layout.addWidget(slide_label)
        
        # Fader horizontal pour slide - utilise toute la largeur disponible
        slide_fader = QSlider(Qt.Horizontal)
        slide_fader.setMinimum(-1000)  # -1.0 * 1000 pour précision
        slide_fader.setMaximum(1000)  # +1.0 * 1000
        slide_fader.setValue(0)  # Position centrale (0.0)
        slide_fader.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        slide_fader.setStyleSheet(self._scale_style("""
            QSlider::groove:horizontal {
                background: #333;
                height: 8px;
                border: 1px solid #555;
                border-radius: 4px;
            }
            QSlider::handle:horizontal {
                background: #666;
                border: 1px solid #888;
                border-radius: 8px;
                width: 18px;
                height: 18px;
                margin: -6px 0;
            }
            QSlider::handle:horizontal:hover {
                background: #777;
            }
            QSlider::handle:horizontal:pressed {
                background: #0ff;
            }
        """))
        slide_container_layout.addWidget(slide_fader)
        fader_layout.addWidget(slide_container)
        panel.slide_fader = slide_fader
        
        # Slider Vitesse flèches (après Slide)
        speed_container = QWidget()
        speed_container_layout = QVBoxLayout(speed_container)
        speed_container_layout.setContentsMargins(0, 0, 0, 0)
        speed_container_layout.setSpacing(self._scale_value(5))
        
        speed_label = QLabel("Vitesse flèches")
        speed_label.setAlignment(Qt.AlignCenter)
        speed_label.setStyleSheet(f"font-size: {self._scale_font(10)}; color: #aaa;")
        speed_container_layout.addWidget(speed_label)
        
        # Slider horizontal pour la vitesse (0-1000 représente 0.0-1.0)
        speed_slider = QSlider(Qt.Horizontal)
        speed_slider.setMinimum(0)
        speed_slider.setMaximum(1000)
        speed_slider.setValue(500)  # Valeur par défaut 0.5 (500/1000)
        speed_slider.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        speed_slider.setStyleSheet(self._scale_style("""
            QSlider::groove:horizontal {
                background: #333;
                height: 8px;
                border: 1px solid #555;
                border-radius: 4px;
            }
            QSlider::handle:horizontal {
                background: #666;
                border: 1px solid #888;
                border-radius: 8px;
                width: 18px;
                height: 18px;
                margin: -6px 0;
            }
            QSlider::handle:horizontal:hover {
                background: #777;
            }
            QSlider::handle:horizontal:pressed {
                background: #0ff;
            }
        """))
        speed_container_layout.addWidget(speed_slider)
        
        # Label pour afficher la valeur actuelle
        speed_value_label = QLabel("0.50")
        speed_value_label.setAlignment(Qt.AlignCenter)
        speed_value_label.setStyleSheet(f"font-size: {self._scale_font(9)}; color: #888;")
        speed_container_layout.addWidget(speed_value_label)
        
        fader_layout.addWidget(speed_container)
        panel.speed_slider = speed_slider
        panel.speed_value_label = speed_value_label
        
        # Stocker la référence globale
        self.workspace_2_arrow_speed_slider = speed_slider
        self.workspace_2_arrow_speed_label = speed_value_label
        
        # Connecter le slider à la méthode de gestion
        speed_slider.valueChanged.connect(self.on_arrow_keys_speed_changed)
        
        # Ajouter les faders au container principal
        main_container_layout.addWidget(fader_container)
        
        layout.addWidget(main_container)
        layout.addStretch()
        
        return panel
    
    def on_joystick_pan_tilt_changed(self, pan: float, tilt: float):
        """Gère le changement de position du joystick pan/tilt."""
        # #region agent log
        try:
            import json, time
            with open('/Users/laurenteyen/Documents/cursor/FocusBMrestAPI1/.cursor/debug.log', 'a') as f:
                f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"M","location":"focus_ui_pyside6_standalone.py:4012","message":"on_joystick_pan_tilt_changed appelé","data":{"pan":pan,"tilt":tilt,"lfo_active":self.lfo_active},"timestamp":int(time.time()*1000)})+'\n')
        except: pass
        # #endregion
        camera_id = self.active_camera_id
        slider_controller = self.slider_controllers.get(camera_id)
        
        if slider_controller and slider_controller.is_configured():
            slider_controller.send_joy_command(pan=pan, tilt=tilt, silent=True)
            # #region agent log
            try:
                import json, time
                with open('/Users/laurenteyen/Documents/cursor/FocusBMrestAPI1/.cursor/debug.log', 'a') as f:
                    f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"M","location":"focus_ui_pyside6_standalone.py:4022","message":"send_joy_command appelé","data":{"pan":pan,"tilt":tilt,"lfo_active":self.lfo_active},"timestamp":int(time.time()*1000)})+'\n')
            except: pass
            # #endregion
            
            # Si le LFO est actif, mettre à jour l'offset pan du joystick pour adapter la compensation
            # Le pan du joystick est une position absolue (0.0 à 1.0), on calcule l'offset par rapport à la base
            if self.lfo_active and self.lfo_base_position:
                # Calculer l'offset pan du joystick par rapport à la position de base
                base_pan = self.lfo_base_position.get("pan", 0.5)
                pan_offset = pan - base_pan
                
                # Stocker l'offset actuel pour l'utiliser dans le calcul de compensation
                if not hasattr(self, 'lfo_current_joystick_pan_offset'):
                    self.lfo_current_joystick_pan_offset = 0.0
                self.lfo_current_joystick_pan_offset = pan_offset
                
                # Déclencher une mise à jour de la séquence LFO après debounce
                if self.lfo_debounce_timer is None:
                    self.lfo_debounce_timer = QTimer()
                    self.lfo_debounce_timer.setSingleShot(True)
                    self.lfo_debounce_timer.timeout.connect(self._trigger_lfo_update)
                
                self.lfo_debounce_timer.start(500)  # 500ms debounce
                
                # #region agent log
                try:
                    import json, time
                    with open('/Users/laurenteyen/Documents/cursor/FocusBMrestAPI1/.cursor/debug.log', 'a') as f:
                        f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"M","location":"focus_ui_pyside6_standalone.py:4037","message":"LFO: Joystick pan changé via UI","data":{"pan":pan,"base_pan":base_pan,"pan_offset":pan_offset,"lfo_current_joystick_pan_offset":self.lfo_current_joystick_pan_offset},"timestamp":int(time.time()*1000)})+'\n')
                except: pass
                # #endregion
    
    def on_joystick_zoom_fader_changed(self, value: int):
        """Gère le changement de valeur du fader zoom motor (slider)."""
        # Convertir de -1000..1000 à -1.0..+1.0 (joystick zoom motor)
        normalized_value = value / 1000.0
        camera_id = self.active_camera_id
        slider_controller = self.slider_controllers.get(camera_id)
        
        # Contrôler le zoom motor du slider (pas la focale de la caméra)
        if slider_controller and slider_controller.is_configured():
            slider_controller.send_joy_command(zoom=normalized_value, silent=True)
    
    def on_joystick_zoom_fader_released(self):
        """Gère le relâchement du fader zoom motor - remet à 0."""
        if self.workspace_2_zoom_fader:
            self.workspace_2_zoom_fader.setValue(0)
            # Envoyer la commande joystick à 0.0
            camera_id = self.active_camera_id
            slider_controller = self.slider_controllers.get(camera_id)
            if slider_controller and slider_controller.is_configured():
                slider_controller.send_joy_command(zoom=0.0, silent=True)
    
    def on_joystick_slide_fader_changed(self, value: int):
        """Gère le changement de valeur du fader slide."""
        # Convertir de -1000..1000 à -1.0..+1.0
        normalized_value = value / 1000.0
        camera_id = self.active_camera_id
        slider_controller = self.slider_controllers.get(camera_id)
        
        if slider_controller and slider_controller.is_configured():
            slider_controller.send_joy_command(slide=normalized_value, silent=True)
    
    def on_joystick_slide_fader_released(self):
        """Gère le relâchement du fader slide - remet à 0."""
        if self.workspace_2_slide_fader:
            self.workspace_2_slide_fader.setValue(0)
            # Envoyer la commande joystick à 0.0
            camera_id = self.active_camera_id
            slider_controller = self.slider_controllers.get(camera_id)
            if slider_controller and slider_controller.is_configured():
                slider_controller.send_joy_command(slide=0.0, silent=True)
    
    def on_arrow_keys_speed_changed(self, value: int):
        """Gère le changement de vitesse des flèches."""
        # Convertir de 0-1000 à 0.0-1.0
        speed = value / 1000.0
        self.arrow_keys_speed = speed
        # Mettre à jour le label d'affichage
        if self.workspace_2_arrow_speed_label:
            self.workspace_2_arrow_speed_label.setText(f"{speed:.2f}")
    
    def update_joystick_visual_position(self, pan: float, tilt: float):
        """Met à jour visuellement la position du joystick 2D sans émettre de signal."""
        if self.workspace_2_joystick_2d:
            self.workspace_2_joystick_2d.setPosition(pan, tilt)
    
    def _calculate_lfo_sequence(self, base_slide: float, base_pan: float, base_tilt: float = None, base_zoom: float = None, pan_offset: float = 0.0) -> tuple:
        """
        Calcule la séquence LFO à partir d'une position de base.
        
        Args:
            base_slide: Position slide de base (0.0-1.0)
            base_pan: Position pan de base (0.0-1.0) - pan de départ
            pan_offset: Offset pan du joystick (-1.0 à +1.0) - commande utilisateur
            base_tilt: Position tilt de base (0.0-1.0), optionnel
            base_zoom: Position zoom de base (0.0-1.0), optionnel
        
        Returns:
            tuple: (sequence_points, lfo_base_position, lfo_position_plus, lfo_position_minus)
        """
        # Calculer le pan réel (hors compensation) = pan de départ + pan offset
        # Le pan offset est en -1.0 à +1.0, on doit le convertir en position absolue
        # Pour simplifier, on considère que l'offset est une commande de vitesse qui modifie progressivement le pan
        # On utilise donc directement base_pan + pan_offset comme pan réel
        # Mais attention : pan_offset est en -1.0 à +1.0, donc on doit le convertir en delta de position
        # Pour l'instant, on utilise base_pan directement et on ajustera avec pan_offset dans monitor_lfo_changes
        
        # Calculer les positions + et - de manière symétrique
        # L'amplitude est répartie : moitié en positif, moitié en négatif
        half_amplitude = self.lfo_amplitude / 2.0
        
        # Calculer les positions idéales
        slide_plus_ideal = base_slide + half_amplitude
        slide_minus_ideal = base_slide - half_amplitude
        
        # Vérifier les limites et reporter le manque de l'autre côté si nécessaire
        slide_plus = max(0.0, min(1.0, slide_plus_ideal))
        slide_minus = max(0.0, min(1.0, slide_minus_ideal))
        
        # Si une limite est atteinte, reporter le manque de l'autre côté
        if slide_plus_ideal > 1.0:
            # On a atteint la limite supérieure, reporter le manque vers le bas
            excess = slide_plus_ideal - 1.0
            slide_minus = max(0.0, slide_minus_ideal - excess)
        elif slide_minus_ideal < 0.0:
            # On a atteint la limite inférieure, reporter le manque vers le haut
            excess = abs(slide_minus_ideal)
            slide_plus = min(1.0, slide_plus_ideal + excess)
        
        # S'assurer que les valeurs finales sont dans les limites
        slide_plus = max(0.0, min(1.0, slide_plus))
        slide_minus = max(0.0, min(1.0, slide_minus))
        
        # Calculer les décalages en mètres
        # Le slider fait 147 cm = 1.47 mètres
        slider_length = 1.47  # mètres
        delta_slide_plus_meters = (slide_plus - base_slide) * slider_length
        delta_slide_minus_meters = (slide_minus - base_slide) * slider_length
        
        # Calculer le pan réel (hors compensation) = pan de départ + pan offset
        # Le pan offset est en -1.0 à +1.0 (commande joystick), on doit le convertir en position absolue
        # Le pan offset est une commande de vitesse, donc on l'ajoute directement à base_pan
        # Mais attention : pan_offset est en -1.0 à +1.0, donc on doit le convertir en delta de position
        # Pour simplifier, on considère que pan_offset modifie directement la position pan
        # Pan réel = pan de départ + pan offset (converti en position absolue)
        # Le pan offset est en -1.0 à +1.0, donc on le convertit en delta de position (0.0 à 1.0)
        # Pour l'instant, on utilise directement base_pan + pan_offset comme approximation
        # TODO: Convertir correctement pan_offset (-1.0 à +1.0) en delta de position
        real_pan = base_pan + pan_offset  # Pan réel (hors compensation)
        real_pan = max(0.0, min(1.0, real_pan))  # Clamper entre 0.0 et 1.0
        
        # #region agent log
        try:
            import json, time
            with open('/Users/laurenteyen/Documents/cursor/FocusBMrestAPI1/.cursor/debug.log', 'a') as f:
                f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"A","location":"focus_ui_pyside6_standalone.py:4179","message":"_calculate_lfo_sequence: calcul real_pan","data":{"base_pan":base_pan,"pan_offset":pan_offset,"real_pan":real_pan,"real_pan_equals_base_pan":abs(real_pan - base_pan) < 0.0001},"timestamp":int(time.time()*1000)})+'\n')
        except: pass
        # #endregion
        
        # Calculer les compensations pan (triangulation de la parallaxe)
        # La compensation doit être multipliée par un facteur qui dépend de l'angle réel
        # Si pan = 0.5 (90° perpendiculaire), compensation maximale
        # Si pan = 0.0 (+90°) ou pan = 1.0 (-90°), compensation nulle (caméra dans le sens du rail)
        # Le facteur cos(angle) gère naturellement la triangulation :
        # - cos(90°) = 0 (pan = 0.0 ou 1.0) : pas de compensation
        # - cos(0°) = 1 (pan = 0.5) : compensation maximale
        
        # Convertir real_pan en angle en degrés
        # pan 50% = 90° (perpendiculaire), pan 100% = -90°, pan 0% = +90°
        base_pan_angle_deg = (real_pan - 0.5) * 180.0  # -90° à +90°
        
        # Calculer le facteur de compensation basé sur l'angle réel (triangulation)
        # Le facteur est maximum à 90° (pan = 0.5) et nul à 0° ou 180° (pan = 0.0 ou 1.0)
        # On utilise cos(angle) pour avoir 1.0 à 90° et 0.0 à 0°/180°
        base_pan_angle_rad = math.radians(base_pan_angle_deg)
        compensation_factor = abs(math.cos(base_pan_angle_rad))
        
        # Calculer les angles de compensation bruts
        # Formule: angle_pan_rad = -atan(delta_slide_meters / distance)
        # Le signe est inversé car le slide a été inversé (erreur corrigée)
        if abs(delta_slide_plus_meters) > 0.001 and self.lfo_distance > 0.1:
            pan_angle_plus_rad_raw = -math.atan(delta_slide_plus_meters / self.lfo_distance)
        else:
            pan_angle_plus_rad_raw = 0.0
        
        if abs(delta_slide_minus_meters) > 0.001 and self.lfo_distance > 0.1:
            pan_angle_minus_rad_raw = -math.atan(delta_slide_minus_meters / self.lfo_distance)
        else:
            pan_angle_minus_rad_raw = 0.0
        
        # Appliquer le facteur de compensation
        pan_angle_plus_rad = pan_angle_plus_rad_raw * compensation_factor
        pan_angle_minus_rad = pan_angle_minus_rad_raw * compensation_factor
        
        # Convertir les angles en valeurs normalisées pan
        # pan 50% = 90° (perpendiculaire), pan 100% = -90°, pan 0% = +90°
        # Formule: angle_deg = (pan_value - 0.5) * 180
        # Donc pour convertir un angle en pan: pan_value = (angle_deg / 180.0) + 0.5
        pan_angle_plus_deg = math.degrees(pan_angle_plus_rad)
        pan_angle_minus_deg = math.degrees(pan_angle_minus_rad)
        
        # Calculer les valeurs pan compensées (ajoutées à la position réelle, pas la base)
        # La compensation est un delta d'angle, donc on l'ajoute à real_pan (pan de départ + offset)
        pan_plus_before_clamp = real_pan + (pan_angle_plus_deg / 180.0)
        pan_minus_before_clamp = real_pan + (pan_angle_minus_deg / 180.0)
        
        # Clamper les valeurs pan entre 0.0 et 1.0
        pan_plus = max(0.0, min(1.0, pan_plus_before_clamp))
        pan_minus = max(0.0, min(1.0, pan_minus_before_clamp))
        
        # #region agent log
        try:
            import json, time
            with open('/Users/laurenteyen/Documents/cursor/FocusBMrestAPI1/.cursor/debug.log', 'a') as f:
                f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"I","location":"focus_ui_pyside6_standalone.py:4163","message":"Calcul pan compensation LFO","data":{"base_pan":base_pan,"pan_offset":pan_offset,"real_pan":real_pan,"base_pan_angle_deg":base_pan_angle_deg,"compensation_factor":compensation_factor,"pan_angle_plus_deg":pan_angle_plus_deg,"pan_angle_minus_deg":pan_angle_minus_deg,"pan_plus_before_clamp":pan_plus_before_clamp,"pan_minus_before_clamp":pan_minus_before_clamp,"pan_plus":pan_plus,"pan_minus":pan_minus,"delta_slide_plus_meters":delta_slide_plus_meters,"delta_slide_minus_meters":delta_slide_minus_meters,"lfo_distance":self.lfo_distance,"lfo_amplitude":self.lfo_amplitude},"timestamp":int(time.time()*1000)})+'\n')
        except: pass
        # #endregion
        
        # Créer la séquence d'interpolation avec 4 points selon les spécifications :
        # 0% : position de départ (actuelle) - DOIT être exactement la position actuelle
        # 25% : position actuelle + amplitude/2 sur slide avec pan compensé
        # 75% : position de départ - amplitude/2 sur slide avec pan compensé dans l'autre sens
        # 100% : position de départ
        # Utiliser les valeurs de tilt et zoom passées en paramètres (ou valeurs par défaut)
        if base_tilt is None:
            base_tilt = 0.5  # Valeur par défaut
        if base_zoom is None:
            base_zoom = 0.0  # Valeur par défaut
        
        # HYPOTHÈSE J: L'API du slider nécessite tilt/zoom dans la séquence avec valeurs constantes
        # Si tilt/zoom ne sont pas dans la séquence, l'API peut utiliser des valeurs par défaut ou les réinitialiser
        # Solution: Inclure tilt et zoom dans la séquence avec des valeurs CONSTANTES (même valeur pour tous les points)
        # CORRECTION: Le point 0% doit utiliser base_pan (position actuelle exacte) et non real_pan
        # car real_pan = base_pan + pan_offset, et même si pan_offset=0.0, il peut y avoir des erreurs d'arrondi
        # Pour le point 0%, on veut la position actuelle exacte, donc on utilise base_pan directement
        sequence_points = [
            {"pan": base_pan, "tilt": base_tilt, "zoom": base_zoom, "slide": base_slide, "fraction": 0.0},    # Position de départ (0%) - tilt/zoom constants
            {"pan": pan_plus, "tilt": base_tilt, "zoom": base_zoom, "slide": slide_plus, "fraction": 0.25},   # Position +amplitude/2 (25%) - tilt/zoom constants
            {"pan": pan_minus, "tilt": base_tilt, "zoom": base_zoom, "slide": slide_minus, "fraction": 0.75}, # Position -amplitude/2 (75%) - tilt/zoom constants
            {"pan": base_pan, "tilt": base_tilt, "zoom": base_zoom, "slide": base_slide, "fraction": 1.0}    # Position de départ (100%) - tilt/zoom constants
        ]
        
        # #region agent log
        try:
            import json, time
            with open('/Users/laurenteyen/Documents/cursor/FocusBMrestAPI1/.cursor/debug.log', 'a') as f:
                f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"A,B,C,D,E","location":"focus_ui_pyside6_standalone.py:4252","message":"_calculate_lfo_sequence: séquence créée","data":{"base_pan":base_pan,"real_pan":real_pan,"pan_offset":pan_offset,"point_0_pan":sequence_points[0]["pan"],"point_0_tilt":sequence_points[0]["tilt"],"point_0_zoom":sequence_points[0]["zoom"],"point_0_slide":sequence_points[0]["slide"],"base_tilt":base_tilt,"base_zoom":base_zoom,"sequence_points":sequence_points},"timestamp":int(time.time()*1000)})+'\n')
        except: pass
        # #endregion
        
        base_position = {"slide": base_slide, "pan": base_pan}
        position_plus = {"slide": slide_plus, "pan": pan_plus}
        position_minus = {"slide": slide_minus, "pan": pan_minus}
        
        return sequence_points, base_position, position_plus, position_minus
    
    def start_lfo(self):
        """Démarre l'oscillation LFO basée sur la position actuelle du slider."""
        # #region agent log
        try:
            import json, time
            with open('/Users/laurenteyen/Documents/cursor/FocusBMrestAPI1/.cursor/debug.log', 'a') as f:
                f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"H","location":"focus_ui_pyside6_standalone.py:4190","message":"start_lfo appelé","data":{"lfo_active":self.lfo_active,"active_camera_id":self.active_camera_id,"lfo_amplitude":self.lfo_amplitude,"lfo_distance":self.lfo_distance,"lfo_speed":self.lfo_speed},"timestamp":int(time.time()*1000)})+'\n')
        except: pass
        # #endregion
        
        if self.lfo_active:
            # #region agent log
            try:
                with open('/Users/laurenteyen/Documents/cursor/FocusBMrestAPI1/.cursor/debug.log', 'a') as f:
                    f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"H","location":"focus_ui_pyside6_standalone.py:4193","message":"LFO déjà actif, retour","data":{},"timestamp":int(time.time()*1000)})+'\n')
            except: pass
            # #endregion
            return
        
        camera_id = self.active_camera_id
        cam_data = self.cameras.get(camera_id)
        if not cam_data or not cam_data.connected:
            logger.warning("Impossible de démarrer le LFO : caméra non connectée")
            # #region agent log
            try:
                with open('/Users/laurenteyen/Documents/cursor/FocusBMrestAPI1/.cursor/debug.log', 'a') as f:
                    f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"H","location":"focus_ui_pyside6_standalone.py:4197","message":"Caméra non connectée","data":{"cam_data_exists":cam_data is not None,"cam_data_connected":cam_data.connected if cam_data else None},"timestamp":int(time.time()*1000)})+'\n')
            except: pass
            # #endregion
            return
        
        # Récupérer le slider controller
        slider_controller = self.slider_controllers.get(camera_id)
        if not slider_controller or not slider_controller.is_configured():
            logger.warning("Impossible de démarrer le LFO : slider non configuré")
            # #region agent log
            try:
                with open('/Users/laurenteyen/Documents/cursor/FocusBMrestAPI1/.cursor/debug.log', 'a') as f:
                    f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"H","location":"focus_ui_pyside6_standalone.py:4202","message":"Slider non configuré","data":{"slider_controller_exists":slider_controller is not None,"slider_configured":slider_controller.is_configured() if slider_controller else None},"timestamp":int(time.time()*1000)})+'\n')
            except: pass
            # #endregion
            if self.lfo_panel:
                self.lfo_panel.state_label.setText("État: Slider non configuré")
                self.lfo_panel.state_label.setStyleSheet(f"font-size: {self._scale_font(10)}; color: #f00;")
            return
        
        # Récupérer la position actuelle du slider
        current_status = slider_controller.get_status(silent=True)
        if current_status is None:
            logger.warning("Impossible de démarrer le LFO : impossible de récupérer la position du slider")
            # #region agent log
            try:
                with open('/Users/laurenteyen/Documents/cursor/FocusBMrestAPI1/.cursor/debug.log', 'a') as f:
                    f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"H","location":"focus_ui_pyside6_standalone.py:4211","message":"Position slider inconnue","data":{},"timestamp":int(time.time()*1000)})+'\n')
            except: pass
            # #endregion
            if self.lfo_panel:
                self.lfo_panel.state_label.setText("État: Position inconnue")
                self.lfo_panel.state_label.setStyleSheet(f"font-size: {self._scale_font(10)}; color: #f00;")
            return
        
        # Utiliser la position actuelle comme position de base
        base_slide = current_status.get('slide', 0.0)
        base_pan = current_status.get('pan', 0.5)  # 0.5 = 90° (perpendiculaire à l'axe du slide)
        base_tilt = current_status.get('tilt', 0.5)  # Récupérer aussi le tilt actuel
        base_zoom = current_status.get('zoom', 0.0)  # Récupérer aussi le zoom actuel
        
        # #region agent log
        try:
            import json, time
            with open('/Users/laurenteyen/Documents/cursor/FocusBMrestAPI1/.cursor/debug.log', 'a') as f:
                f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"A,B,C,D,E","location":"focus_ui_pyside6_standalone.py:4327","message":"start_lfo: positions de base récupérées depuis current_status","data":{"base_slide":base_slide,"base_pan":base_pan,"base_tilt":base_tilt,"base_zoom":base_zoom,"current_status":current_status,"current_status_keys":list(current_status.keys()),"tilt_in_status":"tilt" in current_status,"zoom_in_status":"zoom" in current_status},"timestamp":int(time.time()*1000)})+'\n')
        except: pass
        # #endregion
        
        # Calculer la séquence LFO (passer tilt et zoom en paramètres)
        # Au démarrage, pan_offset = 0.0 car on utilise la position actuelle comme base
        sequence_points, base_position, position_plus, position_minus = self._calculate_lfo_sequence(base_slide, base_pan, base_tilt, base_zoom, pan_offset=0.0)
        
        # Récupérer la position actuelle juste avant l'envoi pour garantir que le point 0% est exactement la position actuelle
        current_status = slider_controller.get_status(silent=True)
        if current_status:
            # Mettre à jour le point 0% avec la position actuelle exacte
            sequence_points[0]["pan"] = current_status.get('pan', base_pan)
            sequence_points[0]["tilt"] = current_status.get('tilt', base_tilt)
            sequence_points[0]["zoom"] = current_status.get('zoom', base_zoom)
            sequence_points[0]["slide"] = current_status.get('slide', base_slide)
        
        # Stocker les positions calculées (inclure tilt et zoom initiaux)
        self.lfo_base_position = {
            "slide": base_slide,
            "pan": base_pan,
            "tilt": base_tilt,  # Stocker le tilt initial
            "zoom": base_zoom   # Stocker le zoom initial
        }
        self.lfo_position_plus = position_plus
        self.lfo_position_minus = position_minus
        
        # BAKER: Intégrer les offsets actuels dans la position de base avant d'envoyer la séquence
        # Cela évite que le joystick continue à modifier la position à chaque variation
        if slider_controller.bake_offsets(silent=True):
            logger.debug("LFO: Offsets 'bakeés' avec succès avant envoi séquence")
        else:
            logger.warning("LFO: Échec du bake des offsets (continuation quand même)")
        
        # Envoyer la séquence d'interpolation
        if not slider_controller.send_interpolation_sequence(sequence_points, self.lfo_speed, silent=True):
            logger.warning("Impossible d'envoyer la séquence d'interpolation")
            if self.lfo_panel:
                self.lfo_panel.state_label.setText("État: Erreur séquence")
                self.lfo_panel.state_label.setStyleSheet(f"font-size: {self._scale_font(10)}; color: #f00;")
            return
        
        # Activer l'interpolation automatique
        # Le firmware démarre maintenant toujours depuis u0 = 0.0, donc pas besoin de repositionnement explicite
        if not slider_controller.set_auto_interpolation(enable=True, duration=self.lfo_speed, silent=True):
            logger.warning("Impossible d'activer l'interpolation automatique")
            if self.lfo_panel:
                self.lfo_panel.state_label.setText("État: Erreur activation")
                self.lfo_panel.state_label.setStyleSheet(f"font-size: {self._scale_font(10)}; color: #f00;")
            return
        
        self.lfo_active = True
        self.lfo_sequence_initialized = True  # La séquence a été initialisée avec POST
        
        # #region agent log
        try:
            import json, time
            with open('/Users/laurenteyen/Documents/cursor/FocusBMrestAPI1/.cursor/debug.log', 'a') as f:
                f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"H","location":"focus_ui_pyside6_standalone.py:4286","message":"LFO activé avec succès","data":{"lfo_active":self.lfo_active,"initial_joystick_pan_offset":self.lfo_initial_joystick_pan_offset},"timestamp":int(time.time()*1000)})+'\n')
        except: pass
        # #endregion
        
        # Initialiser les valeurs de référence pour la surveillance
        self.lfo_last_pan_base = base_pan
        self.lfo_last_amplitude = self.lfo_amplitude
        self.lfo_last_distance = self.lfo_distance
        self.lfo_last_speed = self.lfo_speed
        
        # Capturer l'offset joystick initial pour éviter les fausses détections
        # au démarrage (l'offset peut être non-nul si le joystick a été utilisé avant)
        cam_data = self.cameras.get(camera_id)
        if cam_data:
            self.lfo_initial_joystick_pan_offset = cam_data.slider_joystick_pan_offset
        else:
            self.lfo_initial_joystick_pan_offset = 0.0
        
        # Plus besoin du timer car l'interpolation automatique gère la boucle
        if self.lfo_timer:
            self.lfo_timer.stop()
        
        # Créer et démarrer le timer de surveillance (200ms)
        if self.lfo_monitor_timer is None:
            self.lfo_monitor_timer = QTimer()
            self.lfo_monitor_timer.timeout.connect(self.monitor_lfo_changes)
        self.lfo_monitor_timer.start(200)  # 200ms
        logger.info("LFO: Timer de surveillance démarré (200ms)")
        
        # Mettre à jour l'UI
        if self.lfo_panel:
            self.lfo_panel.lfo_toggle_btn.setText("ON")
            self.lfo_panel.lfo_toggle_btn.setStyleSheet(self._scale_style("""
                QPushButton {
                    padding: 10px;
                    font-size: 14px;
                    font-weight: bold;
                    border: 2px solid #0a5;
                    border-radius: 8px;
                    background-color: #0a5;
                    color: #fff;
                    margin-top: 10px;
                }
                QPushButton:hover {
                    background-color: #0c7;
                }
                QPushButton:pressed {
                    background-color: #0e9;
                }
            """))
            self.lfo_panel.state_label.setText("État: Actif")
            self.lfo_panel.state_label.setStyleSheet(f"font-size: {self._scale_font(10)}; color: #0f0;")
            # Afficher la position de base
            self.lfo_panel.preset_label.setText(f"Base: slide={base_slide:.3f}, pan={base_pan:.3f}")
            # Afficher la compensation pan max (pour l'affichage)
            pan_compensation_max = max(abs(position_plus["pan"] - base_pan), abs(position_minus["pan"] - base_pan))
            self.lfo_panel.compensation_label.setText(f"Compensation: ±{pan_compensation_max:.3f}")
        
        logger.info(f"LFO démarré depuis position actuelle (slide={base_slide:.3f}, pan={base_pan:.3f}), amplitude {self.lfo_amplitude:.3f}, durée {self.lfo_speed}s")
    
    def stop_lfo(self):
        """Arrête l'oscillation LFO en désactivant l'interpolation automatique."""
        if not self.lfo_active:
            return
        
        self.lfo_active = False
        
        # Arrêter le timer si encore actif
        if self.lfo_timer:
            self.lfo_timer.stop()
        
        # Arrêter le timer de surveillance
        if self.lfo_monitor_timer:
            self.lfo_monitor_timer.stop()
        
        # Arrêter le debounce timer si actif
        if self.lfo_debounce_timer:
            self.lfo_debounce_timer.stop()
        
        # Désactiver l'interpolation automatique
        camera_id = self.active_camera_id
        slider_controller = self.slider_controllers.get(camera_id)
        if slider_controller and slider_controller.is_configured():
            slider_controller.set_auto_interpolation(enable=False, silent=True)
        
        # Réinitialiser les références
        self.lfo_base_position = None
        self.lfo_position_plus = None
        self.lfo_position_minus = None
        self.lfo_last_pan_base = None
        self.lfo_update_pending = False
        self.lfo_sequence_initialized = False
        self.lfo_initial_joystick_pan_offset = 0.0
        
        # Mettre à jour l'UI
        if self.lfo_panel:
            self.lfo_panel.lfo_toggle_btn.setText("OFF")
            self.lfo_panel.lfo_toggle_btn.setStyleSheet(self._scale_style("""
                QPushButton {
                    padding: 10px;
                    font-size: 14px;
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
            """))
            self.lfo_panel.state_label.setText("État: Inactif")
            self.lfo_panel.state_label.setStyleSheet(f"font-size: {self._scale_font(10)}; color: #aaa;")
            self.lfo_panel.compensation_label.setText("Compensation: 0.00")
            # Réinitialiser le label de position
            self.lfo_panel.preset_label.setText("Base: -")
        
        logger.info("LFO arrêté")
    
    def update_lfo_sequence(self):
        """Met à jour la séquence LFO en temps réel sans interrompre le mouvement."""
        if not self.lfo_active:
            logger.debug("LFO: update_lfo_sequence appelé mais LFO inactif")
            return
        
        if self.lfo_update_pending:
            logger.debug("LFO: update_lfo_sequence appelé mais mise à jour déjà en cours")
            return
        
        if not self.lfo_base_position:
            logger.warning("LFO: position de base non définie, impossible de mettre à jour")
            return
        
        logger.info(f"LFO: Mise à jour de la séquence (amplitude={self.lfo_amplitude:.3f}, distance={self.lfo_distance:.1f}m, speed={self.lfo_speed:.1f}s)")
        
        camera_id = self.active_camera_id
        slider_controller = self.slider_controllers.get(camera_id)
        if not slider_controller or not slider_controller.is_configured():
            return
        
        # Recalculer la séquence avec les paramètres actuels
        # NOTE: PATCH conserve les offsets joystick, donc pas besoin de bake avant PATCH
        # Le bake n'est nécessaire que pour POST (initialisation), qui réinitialise les offsets
        # IMPORTANT: Utiliser la position de base stockée, PAS la position actuelle du slider
        # car la position actuelle inclut déjà la compensation LFO
        base_slide = self.lfo_base_position["slide"]
        base_pan = self.lfo_base_position["pan"]  # Position de base originale (sans compensation)
        
        # Utiliser les valeurs initiales de tilt et zoom stockées dans lfo_base_position
        # Ne PAS récupérer les valeurs actuelles depuis le slider car elles peuvent avoir changé
        # via le joystick pendant que le LFO est actif
        base_tilt = self.lfo_base_position.get("tilt", 0.5)  # Valeur initiale stockée
        base_zoom = self.lfo_base_position.get("zoom", 0.0)   # Valeur initiale stockée
        
        # Calculer la séquence LFO (utiliser les valeurs initiales de tilt et zoom)
        # Récupérer le pan offset actuel depuis le joystick UI pour adapter la compensation en temps réel
        pan_offset = getattr(self, 'lfo_current_joystick_pan_offset', 0.0)
        sequence_points, base_position, position_plus, position_minus = self._calculate_lfo_sequence(base_slide, base_pan, base_tilt, base_zoom, pan_offset=pan_offset)
        
        # Mettre à jour les positions stockées
        self.lfo_position_plus = position_plus
        self.lfo_position_minus = position_minus
        
        # Mettre à jour la séquence via PATCH (sans interruption)
        if self.lfo_sequence_initialized:
            # Utiliser PATCH pour mettre à jour sans interruption
            logger.debug(f"LFO: Envoi PATCH avec {len(sequence_points)} points, durée={self.lfo_speed:.1f}s")
            success = slider_controller.update_interpolation_sequence(
                sequence_points,
                recalculate_duration=True,
                duration=self.lfo_speed,
                silent=False  # Activer les logs pour déboguer
            )
            
            if success:
                logger.info(f"LFO: PATCH réussi, séquence mise à jour")
            else:
                # Si PATCH échoue (interpolation non active), utiliser POST et redémarrer
                logger.warning("LFO: PATCH échoué, utilisation de POST pour réinitialiser")
                if slider_controller.send_interpolation_sequence(sequence_points, self.lfo_speed, silent=False):
                    slider_controller.set_auto_interpolation(enable=True, duration=self.lfo_speed, silent=False)
                    self.lfo_sequence_initialized = True
                    logger.info("LFO: POST réussi, interpolation réinitialisée")
        else:
            # Première fois : utiliser POST
            logger.debug(f"LFO: Première initialisation avec POST, {len(sequence_points)} points, durée={self.lfo_speed:.1f}s")
            if slider_controller.send_interpolation_sequence(sequence_points, self.lfo_speed, silent=False):
                slider_controller.set_auto_interpolation(enable=True, duration=self.lfo_speed, silent=False)
                self.lfo_sequence_initialized = True
                logger.info("LFO: POST réussi, interpolation initialisée")
        
        # Mettre à jour les valeurs de référence
        self.lfo_last_amplitude = self.lfo_amplitude
        self.lfo_last_distance = self.lfo_distance
        self.lfo_last_speed = self.lfo_speed
        self.lfo_last_pan_base = base_pan
        
        # Mettre à jour l'UI
        if self.lfo_panel:
            pan_compensation_max = max(abs(position_plus["pan"] - base_pan), abs(position_minus["pan"] - base_pan))
            self.lfo_panel.compensation_label.setText(f"Compensation: ±{pan_compensation_max:.3f}")
        
        self.lfo_update_pending = False
        logger.debug(f"LFO séquence mise à jour: amplitude={self.lfo_amplitude:.3f}, distance={self.lfo_distance:.1f}m, speed={self.lfo_speed:.1f}s")
    
    def _trigger_lfo_update(self):
        """Déclenche la mise à jour de la séquence LFO après le debounce."""
        if self.lfo_active:
            # Réinitialiser le flag avant d'appeler update_lfo_sequence
            self.lfo_update_pending = False
            self.update_lfo_sequence()
    
    def monitor_lfo_changes(self):
        """Surveille les changements de pan (joystick) et des paramètres LFO toutes les 200ms."""
        # #region agent log
        import json, time
        try:
            with open('/Users/laurenteyen/Documents/cursor/FocusBMrestAPI1/.cursor/debug.log', 'a') as f:
                f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"G","location":"focus_ui_pyside6_standalone.py:4449","message":"monitor_lfo_changes appelé","data":{"lfo_active":self.lfo_active},"timestamp":int(time.time()*1000)})+'\n')
        except: pass
        # #endregion
        
        if not self.lfo_active:
            return
        
        camera_id = self.active_camera_id
        slider_controller = self.slider_controllers.get(camera_id)
        if not slider_controller or not slider_controller.is_configured():
            return
        
        if not self.lfo_base_position:
            logger.debug("LFO: monitor_lfo_changes appelé mais lfo_base_position est None")
            return
        
        # Vérifier que les valeurs de référence sont initialisées
        if self.lfo_last_pan_base is None:
            self.lfo_last_pan_base = self.lfo_base_position["pan"]
            logger.debug(f"LFO: Initialisation lfo_last_pan_base = {self.lfo_last_pan_base:.3f}")
        
        if self.lfo_last_amplitude == 0.0 and self.lfo_amplitude > 0.0:
            self.lfo_last_amplitude = self.lfo_amplitude
            logger.debug(f"LFO: Initialisation lfo_last_amplitude = {self.lfo_last_amplitude:.3f}")
        
        if self.lfo_last_distance == 1.0 and self.lfo_distance != 1.0:
            self.lfo_last_distance = self.lfo_distance
            logger.debug(f"LFO: Initialisation lfo_last_distance = {self.lfo_last_distance:.1f}")
        
        if self.lfo_last_speed == 1.0 and self.lfo_speed != 1.0:
            self.lfo_last_speed = self.lfo_speed
            logger.debug(f"LFO: Initialisation lfo_last_speed = {self.lfo_last_speed:.1f}")
        
        # Récupérer la position actuelle depuis les données stockées (au lieu de get_status)
        # pour avoir accès aux offsets joystick en temps réel
        cam_data = self.cameras.get(camera_id)
        if not cam_data:
            return
        
        current_pan = cam_data.slider_pan_value
        current_tilt = cam_data.slider_tilt_value
        current_slide = cam_data.slider_slide_value
        joystick_pan_offset = cam_data.slider_joystick_pan_offset
        
        # #region agent log
        try:
            import json, time
            base_tilt = self.lfo_base_position.get("tilt", 0.5)
            base_zoom = self.lfo_base_position.get("zoom", 0.0)
            current_zoom = getattr(cam_data, 'slider_zoom_value', 0.0)
            tilt_drift = abs(current_tilt - base_tilt)
            zoom_drift = abs(current_zoom - base_zoom)
            with open('/Users/laurenteyen/Documents/cursor/FocusBMrestAPI1/.cursor/debug.log', 'a') as f:
                f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"Q,R,S,T","location":"focus_ui_pyside6_standalone.py:4850","message":"monitor_lfo_changes: observation dérive tilt/zoom (correction désactivée)","data":{"current_tilt":current_tilt,"base_tilt":base_tilt,"tilt_drift":tilt_drift,"current_zoom":current_zoom,"base_zoom":base_zoom,"zoom_drift":zoom_drift},"timestamp":int(time.time()*1000)})+'\n')
        except: pass
        # #endregion
        
        # #region agent log
        try:
            import json, time
            with open('/Users/laurenteyen/Documents/cursor/FocusBMrestAPI1/.cursor/debug.log', 'a') as f:
                f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"W","location":"focus_ui_pyside6_standalone.py:4654","message":"monitor_lfo_changes: positions actuelles","data":{"current_pan":current_pan,"current_tilt":current_tilt,"current_slide":current_slide,"lfo_base_position":self.lfo_base_position,"tilt_drift":tilt_drift,"zoom_drift":zoom_drift},"timestamp":int(time.time()*1000)})+'\n')
        except: pass
        # #endregion
        
        # Détecter les changements de paramètres LFO
        param_changed = False
        amplitude_changed = abs(self.lfo_amplitude - self.lfo_last_amplitude) > 0.001
        distance_changed = abs(self.lfo_distance - self.lfo_last_distance) > 0.01
        speed_changed = abs(self.lfo_speed - self.lfo_last_speed) > 0.1
        
        if amplitude_changed:
            param_changed = True
            logger.info(f"LFO: Changement amplitude détecté: {self.lfo_last_amplitude:.3f} -> {self.lfo_amplitude:.3f}")
        if distance_changed:
            param_changed = True
            logger.info(f"LFO: Changement distance détecté: {self.lfo_last_distance:.1f} -> {self.lfo_distance:.1f}")
        if speed_changed:
            param_changed = True
            logger.info(f"LFO: Changement vitesse détecté: {self.lfo_last_speed:.1f} -> {self.lfo_speed:.1f}")
        
        # Détecter les changements de pan (joystick) en utilisant les offsets joystick
        # Les offsets joystick permettent de distinguer les mouvements utilisateur
        # (joystick actif) des mouvements automatiques (interpolation LFO)
        # Si les offsets ne sont pas disponibles (toujours à 0), utiliser une détection
        # basée sur la vitesse de changement de pan
        pan_changed = False
        JOYSTICK_THRESHOLD = 0.01  # Seuil de détection : 1% de mouvement
        PAN_VELOCITY_THRESHOLD = 0.05  # Seuil de vitesse : 5% par cycle (200ms) = 25%/s
        
        # #region agent log
        import json, time
        try:
            with open('/Users/laurenteyen/Documents/cursor/FocusBMrestAPI1/.cursor/debug.log', 'a') as f:
                f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"A,B,C,D,E","location":"focus_ui_pyside6_standalone.py:4513","message":"monitor_lfo_changes: vérification joystick","data":{"joystick_pan_offset":joystick_pan_offset,"abs_offset":abs(joystick_pan_offset),"threshold":JOYSTICK_THRESHOLD,"current_pan":current_pan,"lfo_last_pan_base":self.lfo_last_pan_base,"debounce_active":self.lfo_debounce_timer.isActive() if self.lfo_debounce_timer else False},"timestamp":int(time.time()*1000)})+'\n')
        except: pass
        # #endregion
        
        # Vérifier si le joystick pan est actif (mouvement utilisateur)
        # Méthode 1 : Utiliser les offsets joystick si disponibles
        # Comparer avec l'offset initial capturé au démarrage du LFO
        # pour éviter les fausses détections si l'offset était non-nul au démarrage
        initial_offset = getattr(self, 'lfo_initial_joystick_pan_offset', 0.0)
        offset_delta = abs(joystick_pan_offset - initial_offset)
        # Utiliser un seuil plus strict pour éviter les fausses détections dues au bruit
        # Le seuil de 0.01 (1%) est trop sensible, utiliser 0.05 (5%) pour plus de stabilité
        STRICT_JOYSTICK_THRESHOLD = 0.05  # Seuil strict : 5% de mouvement
        joystick_active_by_offset = offset_delta > STRICT_JOYSTICK_THRESHOLD
        
        # Méthode 2 : DÉSACTIVÉE - Ne pas utiliser current_pan car il change à cause de la compensation LFO
        # Cela créerait une boucle de rétroaction (serpent qui se mord la queue)
        # On se fie uniquement aux offsets joystick pour détecter les mouvements utilisateur
        
        # Le joystick est actif uniquement si les offsets joystick indiquent un mouvement
        joystick_active = joystick_active_by_offset
        
        # #region agent log
        try:
            with open('/Users/laurenteyen/Documents/cursor/FocusBMrestAPI1/.cursor/debug.log', 'a') as f:
                f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"G","location":"focus_ui_pyside6_standalone.py:4540","message":"Détection joystick","data":{"joystick_pan_offset":joystick_pan_offset,"initial_offset":initial_offset,"offset_delta":offset_delta,"abs_offset":abs(joystick_pan_offset),"threshold":JOYSTICK_THRESHOLD,"joystick_active_by_offset":joystick_active_by_offset,"joystick_active":joystick_active,"current_pan":current_pan,"lfo_last_pan_base":self.lfo_last_pan_base},"timestamp":int(time.time()*1000)})+'\n')
        except: pass
        # #endregion
        
        if joystick_active:
            # #region agent log
            try:
                with open('/Users/laurenteyen/Documents/cursor/FocusBMrestAPI1/.cursor/debug.log', 'a') as f:
                    f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"A,D","location":"focus_ui_pyside6_standalone.py:4580","message":"Joystick actif détecté","data":{"joystick_pan_offset":joystick_pan_offset,"initial_offset":initial_offset,"offset_delta":offset_delta,"current_pan":current_pan,"lfo_last_pan_base":self.lfo_last_pan_base,"pan_delta":abs(current_pan - self.lfo_last_pan_base) if self.lfo_last_pan_base else None},"timestamp":int(time.time()*1000)})+'\n')
            except: pass
            # #endregion
            # Le joystick est actif, c'est un mouvement utilisateur
            # Vérifier que le changement de pan est significatif pour éviter les mises à jour continues
            # dues au bruit ou aux petites variations
            MIN_PAN_CHANGE = 0.02  # Seuil minimum de changement de pan (2%) pour déclencher une mise à jour
            old_pan = self.lfo_base_position["pan"] if self.lfo_base_position else None
            pan_change = abs(current_pan - old_pan) if old_pan is not None else 1.0  # Si pas de base, considérer comme changement significatif
            
            if pan_change < MIN_PAN_CHANGE:
                # Le changement de pan est trop petit, ignorer pour éviter les mises à jour continues
                # #region agent log
                try:
                    with open('/Users/laurenteyen/Documents/cursor/FocusBMrestAPI1/.cursor/debug.log', 'a') as f:
                        f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"I","location":"focus_ui_pyside6_standalone.py:4643","message":"Changement pan trop petit, ignoré","data":{"pan_change":pan_change,"min_pan_change":MIN_PAN_CHANGE,"current_pan":current_pan,"old_pan":old_pan},"timestamp":int(time.time()*1000)})+'\n')
                except: pass
                # #endregion
                return  # Ne pas mettre à jour si le changement est trop petit
            
            # Mouvement utilisateur détecté - mise à jour immédiate
            pan_changed = True
            pan_delta = pan_change
            
            # SOLUTION A: Ne pas modifier lfo_base_position["pan"] pour éviter l'accumulation
            # La base reste fixe, l'offset joystick est appliqué uniquement dans _calculate_lfo_sequence()
            base_pan_original = self.lfo_base_position["pan"]  # Base fixe, ne pas modifier
            pan_offset_ui = getattr(self, 'lfo_current_joystick_pan_offset', 0.0)
            
            # #region agent log
            try:
                with open('/Users/laurenteyen/Documents/cursor/FocusBMrestAPI1/.cursor/debug.log', 'a') as f:
                    f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"A,D","location":"focus_ui_pyside6_standalone.py:4625","message":"Mouvement utilisateur détecté, mise à jour pan (base fixe)","data":{"joystick_pan_offset":joystick_pan_offset,"base_pan_original":base_pan_original,"pan_offset_ui":pan_offset_ui,"current_pan":current_pan},"timestamp":int(time.time()*1000)})+'\n')
            except: pass
            # #endregion
            
            # Recalculer les positions attendues (plus/minus) avec la base fixe + offset
            # L'offset sera appliqué dans _calculate_lfo_sequence() via le paramètre pan_offset
            if self.lfo_base_position:
                base_slide = self.lfo_base_position["slide"]
                base_tilt = self.lfo_base_position.get("tilt", 0.5)
                base_zoom = self.lfo_base_position.get("zoom", 0.0)
                # Utiliser le pan offset actuel depuis le joystick UI pour adapter la compensation
                pan_offset = getattr(self, 'lfo_current_joystick_pan_offset', 0.0)
                _, _, position_plus, position_minus = self._calculate_lfo_sequence(
                    base_slide, base_pan_original, base_tilt, base_zoom, pan_offset=pan_offset
                )
                self.lfo_position_plus = position_plus
                self.lfo_position_minus = position_minus
            
            logger.info(f"LFO: Changement pan utilisateur détecté (joystick offset: {joystick_pan_offset:.3f}, base pan fixe: {base_pan_original:.3f})")
        
        # Si un changement est détecté, déclencher le debounce
        if param_changed or pan_changed:
            logger.info(f"LFO: Changement détecté (param={param_changed}, pan={pan_changed}), déclenchement debounce...")
            
            # Si un debounce est déjà en cours, ne pas le réinitialiser
            # Cela évite que le debounce soit réinitialisé en continu si les changements sont détectés à chaque cycle
            if self.lfo_debounce_timer and self.lfo_debounce_timer.isActive():
                # Le debounce est déjà en cours, ne pas le réinitialiser
                logger.debug("LFO: Debounce déjà en cours, pas de réinitialisation")
                return
            
            # Arrêter le debounce timer précédent s'il existe (ne devrait pas arriver ici)
            if self.lfo_debounce_timer:
                self.lfo_debounce_timer.stop()
            
            # Créer un nouveau debounce timer (150ms, réduit pour plus de réactivité)
            if self.lfo_debounce_timer is None:
                self.lfo_debounce_timer = QTimer()
                self.lfo_debounce_timer.setSingleShot(True)
                self.lfo_debounce_timer.timeout.connect(self._trigger_lfo_update)
            
            self.lfo_update_pending = True
            self.lfo_debounce_timer.start(150)  # 150ms debounce (réduit de 300ms pour plus de réactivité)
            logger.debug(f"LFO: Debounce démarré (150ms)")
    
    def update_lfo_oscillation(self):
        """
        Ancienne fonction de mise à jour de l'oscillation LFO.
        Plus utilisée car l'interpolation automatique gère maintenant la boucle.
        Conservée pour compatibilité mais ne fait rien.
        """
        # L'interpolation automatique gère maintenant la boucle
        # Cette fonction n'est plus nécessaire mais conservée pour compatibilité
        pass
    
    def on_lfo_sync_toggle_changed(self, checked: bool):
        """Gère le changement du toggle de synchronisation automatique D ↔ Focus."""
        self.lfo_auto_sync_distance = checked
        
        # Mettre à jour le texte du bouton
        if hasattr(self, 'lfo_panel') and self.lfo_panel and hasattr(self.lfo_panel, 'sync_toggle_btn'):
            self.lfo_panel.sync_toggle_btn.setText(f"Sync D↔Focus: {'ON' if checked else 'OFF'}")
        
        logger.info(f"LFO: Synchronisation automatique D ↔ Focus {'activée' if checked else 'désactivée'}")
    
    def on_lfo_amplitude_changed(self, value: int):
        """Gère le changement de l'amplitude LFO."""
        # Convertir de 0-1000 à 0.0-1.0
        self.lfo_amplitude = value / 1000.0
        if self.lfo_panel:
            self.lfo_panel.amplitude_value_label.setText(f"{self.lfo_amplitude:.3f}")
        
        # La surveillance détectera automatiquement le changement et mettra à jour la séquence
    
    def on_lfo_speed_changed(self, value: int):
        """Gère le changement de la vitesse LFO."""
        # Convertir de 10-600 (0.1s steps) à 1.0-60.0 secondes
        self.lfo_speed = value / 10.0
        if self.lfo_panel:
            self.lfo_panel.speed_value_label.setText(f"{self.lfo_speed:.1f} s/cycle")
        
        # La surveillance détectera automatiquement le changement et mettra à jour la séquence
    
    def on_lfo_distance_changed(self, value: int):
        """Gère le changement de la distance LFO."""
        # Convertir de 5-200 (0.1m steps) à 0.5-20.0 mètres
        self.lfo_distance = value / 10.0
        if self.lfo_panel:
            self.lfo_panel.distance_value_label.setText(f"{self.lfo_distance:.1f} m")
        
        # La surveillance détectera automatiquement le changement et mettra à jour la séquence
    
    def sync_lfo_distance_from_focus(self, focus_normalised: float):
        """
        Synchronise automatiquement le D du LFO avec le focus.
        
        Args:
            focus_normalised: Valeur normalisée du focus (0.0-1.0)
        """
        if not self.lfo_auto_sync_distance:
            return
        
        # Éviter les mises à jour continues si la valeur n'a pas changé significativement (seuil 0.001 = 0.1%)
        if self.last_synced_focus_value is not None:
            if abs(focus_normalised - self.last_synced_focus_value) < 0.001:
                return
        
        # Obtenir le zoom actuel pour la conversion
        # IMPORTANT: La LUT 3D utilise les valeurs normalisées du SLIDER (slider_zoom_value),
        # pas celles de l'API caméra. slider_zoom_value est mis à jour via on_slider_position_update
        zoom_normalised = None
        cam_data = self.get_active_camera_data()
        if cam_data and hasattr(cam_data, 'slider_zoom_value') and cam_data.slider_zoom_value is not None:
            zoom_normalised = cam_data.slider_zoom_value  # Valeur normalisée du slider (0.0-1.0)
        
        # Convertir normalised → distance en mètres via la LUT (avec zoom si disponible)
        # La LUT 3D utilise les valeurs normalisées du slider
        distance_meters = self.focus_lut.normalised_to_distance_with_zoom(focus_normalised, zoom_normalised)
        if distance_meters is None:
            logger.debug("LFO: Impossible de convertir focus en distance (LUT non disponible)")
            # Mettre à jour le label même si la conversion échoue
            if hasattr(self, 'focus_distance_label') and self.focus_distance_label:
                self.focus_distance_label.setText("Distance: -- m")
            return
        
        # Mettre à jour le label d'affichage de la distance
        if hasattr(self, 'focus_distance_label') and self.focus_distance_label:
            self.focus_distance_label.setText(f"Distance: {distance_meters:.2f} m")
        
        # Clamper la distance entre 0.5 et 20.0 mètres (plage du LFO)
        new_distance = max(0.5, min(20.0, distance_meters))
        
        # Mettre à jour seulement si le changement est significatif (> 0.01m)
        if abs(new_distance - self.lfo_distance) > 0.01:
            self.lfo_distance = new_distance
            self.last_synced_focus_value = focus_normalised
            
            # Mettre à jour le slider UI (valeur slider = distance * 10, plage 5-200)
            if self.lfo_panel:
                distance_slider_value = int(self.lfo_distance * 10)
                distance_slider_value = max(5, min(200, distance_slider_value))
                self.lfo_panel.distance_slider.blockSignals(True)
                self.lfo_panel.distance_slider.setValue(distance_slider_value)
                self.lfo_panel.distance_slider.blockSignals(False)
                self.lfo_panel.distance_value_label.setText(f"{self.lfo_distance:.1f} m")
            
            logger.info(f"LFO: Distance synchronisée avec focus: {self.lfo_distance:.1f}m (focus={focus_normalised:.3f})")
            
            # Si LFO actif, mettre à jour la séquence
            if self.lfo_active:
                self.update_lfo_sequence()
    
    def toggle_lfo(self):
        """Bascule l'état du LFO (ON/OFF)."""
        # #region agent log
        try:
            import json, time
            with open('/Users/laurenteyen/Documents/cursor/FocusBMrestAPI1/.cursor/debug.log', 'a') as f:
                f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"H","location":"focus_ui_pyside6_standalone.py:4732","message":"toggle_lfo appelé","data":{"lfo_active":self.lfo_active,"lfo_panel_exists":self.lfo_panel is not None},"timestamp":int(time.time()*1000)})+'\n')
        except: pass
        # #endregion
        
        if self.lfo_active:
            self.stop_lfo()
        else:
            self.start_lfo()
    
    def create_lfo_panel(self):
        """Crée le panneau de contrôle LFO (Low Frequency Oscillator)."""
        panel = QWidget()
        panel_width = self._scale_value(300)  # Élargi pour workspace 2
        panel.setMinimumWidth(panel_width)
        panel.setMaximumWidth(panel_width)
        panel.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        panel.setStyleSheet(self._scale_style("""
            QWidget {
                background-color: #1a1a1a;
                border: 1px solid #444;
                border-radius: 4px;
            }
        """))
        layout = QVBoxLayout(panel)
        spacing = self._scale_value(15)
        margin = self._scale_value(30)
        layout.setSpacing(spacing)
        layout.setContentsMargins(margin, margin, margin, margin)
        
        # Titre du panneau
        title = QLabel("L.F.O.")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(f"font-size: {self._scale_font(20)}; color: #fff;")
        layout.addWidget(title)
        
        # Afficher le preset de base utilisé
        preset_label = QLabel("Base: -")
        preset_label.setAlignment(Qt.AlignCenter)
        preset_label.setStyleSheet(f"font-size: {self._scale_font(10)}; color: #aaa;")
        layout.addWidget(preset_label)
        panel.preset_label = preset_label
        
        # Container pour les contrôles
        controls_container = QWidget()
        controls_layout = QVBoxLayout(controls_container)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(self._scale_value(20))
        
        # Contrôle Amplitude
        amplitude_container = QWidget()
        amplitude_layout = QVBoxLayout(amplitude_container)
        amplitude_layout.setContentsMargins(0, 0, 0, 0)
        amplitude_layout.setSpacing(self._scale_value(5))
        
        amplitude_label = QLabel("Amplitude")
        amplitude_label.setAlignment(Qt.AlignCenter)
        amplitude_label.setStyleSheet(f"font-size: {self._scale_font(10)}; color: #aaa;")
        amplitude_layout.addWidget(amplitude_label)
        
        amplitude_value_label = QLabel("0.000")
        amplitude_value_label.setAlignment(Qt.AlignCenter)
        amplitude_value_label.setStyleSheet(f"font-size: {self._scale_font(11)}; font-weight: bold; color: #ff0; font-family: 'Courier New';")
        amplitude_layout.addWidget(amplitude_value_label)
        
        amplitude_slider = QSlider(Qt.Horizontal)
        amplitude_slider.setMinimum(0)
        amplitude_slider.setMaximum(1000)  # 0-1000 pour avoir 0.000-1.000 avec 3 décimales
        # Initialiser avec une valeur par défaut raisonnable (40% = 0.4)
        default_amplitude_value = int(self.lfo_amplitude * 1000) if self.lfo_amplitude > 0 else 400
        amplitude_slider.setValue(default_amplitude_value)
        # Mettre à jour lfo_amplitude avec la valeur initiale
        self.lfo_amplitude = default_amplitude_value / 1000.0
        # Mettre à jour le label avec la valeur initiale
        amplitude_value_label.setText(f"{self.lfo_amplitude:.3f}")
        amplitude_slider.setStyleSheet(self._scale_style("""
            QSlider::groove:horizontal {
                background: #333;
                height: 8px;
                border: 1px solid #555;
                border-radius: 4px;
            }
            QSlider::handle:horizontal {
                background: #666;
                border: 1px solid #888;
                border-radius: 8px;
                width: 18px;
                height: 18px;
                margin: -6px 0;
            }
            QSlider::handle:horizontal:hover {
                background: #777;
            }
        """))
        amplitude_layout.addWidget(amplitude_slider)
        controls_layout.addWidget(amplitude_container)
        panel.amplitude_slider = amplitude_slider
        panel.amplitude_value_label = amplitude_value_label
        
        # Contrôle Vitesse
        speed_container = QWidget()
        speed_layout = QVBoxLayout(speed_container)
        speed_layout.setContentsMargins(0, 0, 0, 0)
        speed_layout.setSpacing(self._scale_value(5))
        
        speed_label = QLabel("Vitesse")
        speed_label.setAlignment(Qt.AlignCenter)
        speed_label.setStyleSheet(f"font-size: {self._scale_font(10)}; color: #aaa;")
        speed_layout.addWidget(speed_label)
        
        speed_value_label = QLabel("15.0 s/cycle")
        speed_value_label.setAlignment(Qt.AlignCenter)
        speed_value_label.setStyleSheet(f"font-size: {self._scale_font(11)}; font-weight: bold; color: #ff0; font-family: 'Courier New';")
        speed_layout.addWidget(speed_value_label)
        
        speed_slider = QSlider(Qt.Horizontal)
        speed_slider.setMinimum(10)  # 1.0 secondes (10 * 0.1)
        speed_slider.setMaximum(600)  # 60.0 secondes (600 * 0.1)
        speed_slider.setValue(150)  # 15.0 secondes par défaut
        speed_slider.setStyleSheet(self._scale_style("""
            QSlider::groove:horizontal {
                background: #333;
                height: 8px;
                border: 1px solid #555;
                border-radius: 4px;
            }
            QSlider::handle:horizontal {
                background: #666;
                border: 1px solid #888;
                border-radius: 8px;
                width: 18px;
                height: 18px;
                margin: -6px 0;
            }
            QSlider::handle:horizontal:hover {
                background: #777;
            }
        """))
        speed_layout.addWidget(speed_slider)
        controls_layout.addWidget(speed_container)
        panel.speed_slider = speed_slider
        panel.speed_value_label = speed_value_label
        
        # Contrôle Distance
        distance_container = QWidget()
        distance_layout = QVBoxLayout(distance_container)
        distance_layout.setContentsMargins(0, 0, 0, 0)
        distance_layout.setSpacing(self._scale_value(5))
        
        distance_label = QLabel("Distance")
        distance_label.setAlignment(Qt.AlignCenter)
        distance_label.setStyleSheet(f"font-size: {self._scale_font(10)}; color: #aaa;")
        distance_layout.addWidget(distance_label)
        
        distance_value_label = QLabel("1.0 m")
        distance_value_label.setAlignment(Qt.AlignCenter)
        distance_value_label.setStyleSheet(f"font-size: {self._scale_font(11)}; font-weight: bold; color: #ff0; font-family: 'Courier New';")
        distance_layout.addWidget(distance_value_label)
        
        distance_slider = QSlider(Qt.Horizontal)
        distance_slider.setMinimum(5)  # 0.5 mètres (5 * 0.1)
        distance_slider.setMaximum(200)  # 20.0 mètres (200 * 0.1)
        distance_slider.setValue(10)  # 1.0 mètre par défaut
        distance_slider.setStyleSheet(self._scale_style("""
            QSlider::groove:horizontal {
                background: #333;
                height: 8px;
                border: 1px solid #555;
                border-radius: 4px;
            }
            QSlider::handle:horizontal {
                background: #666;
                border: 1px solid #888;
                border-radius: 8px;
                width: 18px;
                height: 18px;
                margin: -6px 0;
            }
            QSlider::handle:horizontal:hover {
                background: #777;
            }
        """))
        distance_layout.addWidget(distance_slider)
        controls_layout.addWidget(distance_container)
        panel.distance_slider = distance_slider
        panel.distance_value_label = distance_value_label
        
        # Bouton toggle pour activer/désactiver la synchronisation automatique D ↔ Focus
        sync_toggle_btn = QPushButton("Sync D↔Focus: ON")
        sync_toggle_btn.setCheckable(True)
        sync_toggle_btn.setChecked(self.lfo_auto_sync_distance)
        sync_toggle_btn.setStyleSheet(self._scale_style("""
            QPushButton {
                padding: 8px;
                font-size: 11px;
                font-weight: bold;
                border: 2px solid #555;
                border-radius: 6px;
                background-color: #2a5a2a;
                color: #fff;
            }
            QPushButton:checked {
                background-color: #2a5a2a;
                border-color: #4a8a4a;
            }
            QPushButton:!checked {
                background-color: #5a2a2a;
                border-color: #8a4a4a;
            }
            QPushButton:hover {
                border-color: #777;
            }
            QPushButton:pressed {
                background-color: #3a3a3a;
            }
        """))
        sync_toggle_btn.toggled.connect(self.on_lfo_sync_toggle_changed)
        controls_layout.addWidget(sync_toggle_btn)
        panel.sync_toggle_btn = sync_toggle_btn
        
        # Bouton ON/OFF
        self.lfo_toggle_btn = QPushButton("OFF")
        self.lfo_toggle_btn.setStyleSheet(self._scale_style("""
            QPushButton {
                padding: 10px;
                font-size: 14px;
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
        """))
        controls_layout.addWidget(self.lfo_toggle_btn)
        panel.lfo_toggle_btn = self.lfo_toggle_btn
        
        # Affichage de l'état
        state_label = QLabel("État: Inactif")
        state_label.setAlignment(Qt.AlignCenter)
        state_label.setStyleSheet(f"font-size: {self._scale_font(10)}; color: #aaa;")
        controls_layout.addWidget(state_label)
        panel.state_label = state_label
        
        # Affichage de la compensation
        compensation_label = QLabel("Compensation: 0.00")
        compensation_label.setAlignment(Qt.AlignCenter)
        compensation_label.setStyleSheet(f"font-size: {self._scale_font(10)}; color: #0ff;")
        controls_layout.addWidget(compensation_label)
        panel.compensation_label = compensation_label
        
        layout.addWidget(controls_container)
        layout.addStretch()
        
        return panel
    
    def create_sequences_panel(self):
        """Crée le panneau Sequences avec un tableau de 20 séquences."""
        panel = QWidget()
        # Doubler la largeur du panneau
        panel_width = self._scale_value(600)  # Doublé (était ~300)
        panel.setMinimumWidth(panel_width)
        panel.setMaximumWidth(panel_width)
        panel.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        panel.setStyleSheet(self._scale_style("""
            QWidget {
                background-color: #1a1a1a;
                border: 1px solid #444;
                border-radius: 4px;
            }
        """))
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(self._scale_value(15), self._scale_value(15), 
                                 self._scale_value(15), self._scale_value(15))
        layout.setSpacing(self._scale_value(10))
        
        # Titre
        title = QLabel("Sequences")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(f"font-size: {self._scale_font(20)}; font-weight: bold; color: #fff;")
        layout.addWidget(title)
        
        # Tableau
        table = QTableWidget(20, 9)
        table.setHorizontalHeaderLabels(["Name", "0%", "25%", "50%", "75%", "100%", "Duration", "Save", "Erase"])
        table.horizontalHeader().setStretchLastSection(False)
        table.verticalHeader().setVisible(True)
        table.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
        # Rendre l'en-tête vertical cliquable
        table.verticalHeader().setSectionsClickable(True)
        table.setAlternatingRowColors(True)
        # Activer le menu contextuel
        table.setContextMenuPolicy(Qt.CustomContextMenu)
        table.customContextMenuRequested.connect(self.on_sequence_context_menu)
        table.setStyleSheet(self._scale_style("""
            QTableWidget {
                background-color: #2a2a2a;
                border: 1px solid #555;
                gridline-color: #444;
                color: #fff;
            }
            QTableWidget::item {
                padding: 4px;
            }
            QTableWidget::item:selected {
                background-color: #4a4a4a;
            }
            QHeaderView::section {
                background-color: #333;
                color: #fff;
                padding: 6px;
                border: 1px solid #555;
                font-weight: bold;
            }
        """))
        # Permettre la coloration des lignes
        table.setShowGrid(True)
        
        # Configurer les colonnes (charger depuis la config ou utiliser les valeurs par défaut)
        # Note: load_sequences_column_widths() sera appelé après avoir assigné self.sequences_table
        
        # Connecter le signal de redimensionnement pour capturer les changements manuels
        table.horizontalHeader().sectionResized.connect(self.on_sequence_column_resized)
        
        # Connecter le clic sur l'en-tête vertical (numéro de ligne)
        table.verticalHeader().sectionClicked.connect(self.on_sequence_row_clicked)
        
        # Connecter le double-clic sur la colonne Name
        table.cellDoubleClicked.connect(self.on_sequence_cell_double_clicked)
        
        # Créer les widgets pour chaque cellule
        for row in range(20):
            # Colonne Name - rendre cliquable pour envoyer
            name_edit = QLineEdit()
            name_edit.setPlaceholderText(f"Seq {row + 1}")
            name_edit.setStyleSheet(self._scale_style("""
                QLineEdit {
                    background-color: #2a2a2a;
                    border: 1px solid #555;
                    color: #fff;
                    padding: 4px;
                }
                QLineEdit:hover {
                    border: 1px solid #0a5;
                    background-color: #3a3a3a;
                }
            """))
            table.setCellWidget(row, 0, name_edit)
            name_edit.textChanged.connect(lambda text, r=row: self.on_sequence_name_changed(r, text))
            
            # Colonnes 0%, 25%, 50%, 75%, 100%
            fractions = [0.0, 0.25, 0.5, 0.75, 1.0]
            for col_idx, fraction in enumerate(fractions, start=1):
                preset_edit = QLineEdit()
                preset_edit.setPlaceholderText("Preset")
                preset_edit.setStyleSheet(self._scale_style("""
                    QLineEdit {
                        background-color: #2a2a2a;
                        border: 1px solid #555;
                        color: #fff;
                        padding: 4px;
                        text-align: center;
                    }
                    QLineEdit:focus {
                        border: 1px solid #0a5;
                    }
                """))
                table.setCellWidget(row, col_idx, preset_edit)
                preset_edit.editingFinished.connect(lambda r=row, f=fraction: self.on_sequence_preset_changed(r, f))
            
            # Colonne Duration
            duration_edit = QLineEdit()
            duration_edit.setPlaceholderText("5.0")
            duration_edit.setText("5.0")
            validator = QDoubleValidator(0.1, 600.0, 1)
            validator.setNotation(QDoubleValidator.StandardNotation)
            duration_edit.setValidator(validator)
            duration_edit.setStyleSheet(self._scale_style("""
                QLineEdit {
                    background-color: #2a2a2a;
                    border: 1px solid #555;
                    color: #fff;
                    padding: 4px;
                    text-align: center;
                }
                QLineEdit:focus {
                    border: 1px solid #0a5;
                }
            """))
            table.setCellWidget(row, 6, duration_edit)
            duration_edit.editingFinished.connect(lambda r=row: self.on_sequence_duration_changed(r))
            
            # Colonne Save - bouton qui devient rouge quand bakeé
            save_btn = QPushButton("Save")
            save_btn.setStyleSheet(self._scale_style("""
                QPushButton {
                    padding: 6px;
                    font-size: 10px;
                    font-weight: bold;
                    border: 1px solid #555;
                    border-radius: 4px;
                    background-color: #5a2a2a;
                    color: #fff;
                }
                QPushButton:hover {
                    background-color: #7a4a4a;
                }
                QPushButton:pressed {
                    background-color: #4a2a2a;
                }
            """))
            save_btn.clicked.connect(lambda checked, r=row: self.bake_sequence(r))
            table.setCellWidget(row, 7, save_btn)
            # Stocker la référence au bouton pour pouvoir changer sa couleur
            save_btn.setProperty("row_index", row)
            
            # Colonne Erase - bouton pour effacer la séquence
            erase_btn = QPushButton("Erase")
            erase_btn.setStyleSheet(self._scale_style("""
                QPushButton {
                    padding: 6px;
                    font-size: 10px;
                    font-weight: bold;
                    border: 1px solid #555;
                    border-radius: 4px;
                    background-color: #5a2a2a;
                    color: #fff;
                }
                QPushButton:hover {
                    background-color: #7a4a4a;
                }
                QPushButton:pressed {
                    background-color: #4a2a2a;
                }
            """))
            erase_btn.clicked.connect(lambda checked, r=row: self.erase_sequence(r))
            table.setCellWidget(row, 8, erase_btn)
        
        layout.addWidget(table)
        self.sequences_table = table
        
        # Charger les largeurs de colonnes sauvegardées (doit être fait après avoir assigné self.sequences_table)
        self.load_sequences_column_widths()
        
        # Bouton Stop global
        stop_btn = QPushButton("STOP")
        stop_btn.setStyleSheet(self._scale_style("""
            QPushButton {
                padding: 12px;
                font-size: 14px;
                font-weight: bold;
                border: 2px solid #f00;
                border-radius: 6px;
                background-color: #f00;
                color: #fff;
            }
            QPushButton:hover {
                background-color: #f22;
                border-color: #f22;
            }
            QPushButton:pressed {
                background-color: #d00;
                border-color: #d00;
            }
        """))
        stop_btn.clicked.connect(self.stop_sequence)
        layout.addWidget(stop_btn)
        
        # Charger les séquences depuis la config
        self.load_sequences_from_config()
        
        return panel
    
    def on_sequence_row_clicked(self, row: int):
        """Appelé quand on clique sur le numéro de ligne (en-tête vertical)."""
        if 0 <= row < 20:
            self.send_sequence(row)
    
    def on_sequence_cell_double_clicked(self, row: int, col: int):
        """Appelé quand on double-clique sur une cellule."""
        # Si c'est la colonne Name (col 0), envoyer la séquence
        if col == 0 and 0 <= row < 20:
            self.send_sequence(row)
    
    def on_sequence_context_menu(self, position):
        """Affiche le menu contextuel pour les séquences."""
        if not self.sequences_table:
            return
        
        item = self.sequences_table.itemAt(position)
        if item is None:
            # Si on clique dans une zone sans item, utiliser la ligne de l'en-tête vertical
            row = self.sequences_table.rowAt(position.y())
        else:
            row = item.row()
        
        if row < 0 or row >= 20:
            return
        
        menu = QMenu(self)
        bake_action = menu.addAction("Save")
        bake_action.triggered.connect(lambda checked, r=row: self.bake_sequence(r))
        
        menu.exec_(self.sequences_table.viewport().mapToGlobal(position))
    
    def on_sequence_name_changed(self, row: int, text: str):
        """Appelé quand le nom d'une séquence change."""
        if 0 <= row < len(self.sequences_data):
            self.sequences_data[row]["name"] = text
            self.save_sequences_to_config()
    
    def on_sequence_preset_changed(self, row: int, fraction: float):
        """Appelé quand un preset d'une séquence change."""
        if not self.sequences_table or row < 0 or row >= 20:
            return
        
        # Trouver la colonne correspondant à la fraction
        fraction_to_col = {0.0: 1, 0.25: 2, 0.5: 3, 0.75: 4, 1.0: 5}
        col = fraction_to_col.get(fraction)
        if col is None:
            return
        
        widget = self.sequences_table.cellWidget(row, col)
        if not isinstance(widget, QLineEdit):
            return
        
        text = widget.text().strip()
        
        if 0 <= row < len(self.sequences_data):
            if text:
                # Vérifier si c'est un numéro de preset (1-10)
                try:
                    preset_num = int(text)
                    if 1 <= preset_num <= 10:
                        self.sequences_data[row]["points"][fraction] = {"type": "preset", "value": preset_num}
                        # Mettre à jour l'affichage
                        widget.setStyleSheet(self._scale_style("""
                            QLineEdit {
                                background-color: #2a2a2a;
                                border: 1px solid #555;
                                color: #fff;
                                padding: 4px;
                                text-align: center;
                            }
                            QLineEdit:focus {
                                border: 1px solid #0a5;
                            }
                        """))
                    else:
                        # Valeur invalide
                        widget.clear()
                        self.sequences_data[row]["points"][fraction] = None
                except ValueError:
                    # Ce n'est pas un nombre, peut-être une valeur bakeée (✗)
                    if text == "✗" or text == "B":
                        # C'est déjà bakeé, ne rien faire
                        pass
                    else:
                        widget.clear()
                        self.sequences_data[row]["points"][fraction] = None
            else:
                self.sequences_data[row]["points"][fraction] = None
            
            self.save_sequences_to_config()
    
    def on_sequence_duration_changed(self, row: int):
        """Appelé quand la durée d'une séquence change."""
        if not self.sequences_table or row < 0 or row >= 20:
            return
        
        widget = self.sequences_table.cellWidget(row, 6)
        if not isinstance(widget, QLineEdit):
            return
        
        text = widget.text().strip()
        
        if 0 <= row < len(self.sequences_data):
            try:
                duration = float(text.replace(',', '.'))
                if 0.1 <= duration <= 600.0:
                    self.sequences_data[row]["duration"] = duration
                else:
                    # Valeur invalide, remettre la valeur précédente
                    widget.setText(f"{self.sequences_data[row]['duration']:.1f}")
            except ValueError:
                # Valeur invalide, remettre la valeur précédente
                widget.setText(f"{self.sequences_data[row]['duration']:.1f}")
            
            self.save_sequences_to_config()
    
    def send_sequence(self, row_index: int):
        """Envoie une séquence au slider."""
        if row_index < 0 or row_index >= len(self.sequences_data):
            return
        
        cam_data = self.get_active_camera_data()
        if not cam_data.connected:
            logger.warning("Impossible d'envoyer la séquence : caméra non connectée")
            return
        
        slider_controller = self.slider_controllers.get(self.active_camera_id)
        if not slider_controller or not slider_controller.is_configured():
            logger.warning("Impossible d'envoyer la séquence : slider non configuré")
            return
        
        sequence = self.sequences_data[row_index]
        points = []
        
        # Construire les points de la séquence
        for fraction in [0.0, 0.25, 0.5, 0.75, 1.0]:
            point_data = sequence["points"].get(fraction)
            # Debug: vérifier les clés disponibles si point_data est None
            if point_data is None:
                available_keys = list(sequence["points"].keys())
                logger.debug(f"Séquence {row_index + 1}, fraction {fraction}: point_data=None, clés disponibles: {available_keys}")
            if point_data is None:
                continue  # Case vide, on ignore
            
            if point_data["type"] == "preset":
                # Récupérer les valeurs du preset
                preset_num = point_data["value"]
                preset_key = f"preset_{preset_num}"
                if preset_key not in cam_data.presets:
                    logger.warning(f"Preset {preset_num} introuvable pour la séquence {row_index + 1}")
                    continue
                
                preset_data = cam_data.presets[preset_key]
                point = {
                    "fraction": fraction,
                    "pan": preset_data.get("pan", 0.5),
                    "tilt": preset_data.get("tilt", 0.5),
                    "zoom": preset_data.get("zoom_motor", 0.0),
                    "slide": preset_data.get("slide", 0.5)
                }
            elif point_data["type"] == "baked":
                # Utiliser directement les valeurs bakeées
                baked_values = point_data["value"]
                point = {
                    "fraction": fraction,
                    "pan": baked_values.get("pan", 0.5),
                    "tilt": baked_values.get("tilt", 0.5),
                    "zoom": baked_values.get("zoom", 0.0),
                    "slide": baked_values.get("slide", 0.5)
                }
            else:
                continue
            
            points.append(point)
        
        if not points:
            logger.warning(f"Séquence {row_index + 1} vide, rien à envoyer")
            return
        
        # Trier les points par fraction
        points.sort(key=lambda p: p["fraction"])
        
        # Appliquer le focus du premier point (fraction 0.0)
        first_point_focus = None
        first_point_data = sequence["points"].get(0.0)
        if first_point_data is not None:
            if first_point_data["type"] == "preset":
                # Récupérer le focus du preset
                preset_num = first_point_data["value"]
                preset_key = f"preset_{preset_num}"
                if preset_key in cam_data.presets:
                    preset_data = cam_data.presets[preset_key]
                    if "focus" in preset_data:
                        first_point_focus = float(preset_data["focus"])
            elif first_point_data["type"] == "baked":
                # Récupérer le focus bakeé
                baked_values = first_point_data["value"]
                if "focus" in baked_values:
                    first_point_focus = float(baked_values["focus"])
        
        # Appliquer le focus à la caméra avec transition de 3 secondes
        if first_point_focus is not None and cam_data.controller:
            # Arrêter toute transition en cours
            if self.focus_transition_timer and self.focus_transition_timer.isActive():
                self.focus_transition_timer.stop()
            
            # Récupérer le focus actuel
            current_focus_data = cam_data.controller.get_focus()
            current_focus = current_focus_data.get("normalised") if current_focus_data else cam_data.focus_sent_value
            
            if current_focus is None:
                current_focus = 0.5  # Valeur par défaut
            
            # Si le focus actuel est très proche du nouveau, pas besoin de transition
            if abs(current_focus - first_point_focus) < 0.001:
                cam_data.controller.set_focus(first_point_focus, silent=True)
                cam_data.focus_sent_value = first_point_focus
                self._update_focus_ui(first_point_focus)
                logger.info(f"Séquence {row_index + 1} : Focus appliqué directement ({first_point_focus:.3f})")
            elif self.smooth_preset_transition:
                # Démarrer la transition si activée
                self._start_focus_transition(current_focus, first_point_focus, cam_data)
                logger.info(f"Séquence {row_index + 1} : Transition de focus de {current_focus:.3f} à {first_point_focus:.3f} sur 3 secondes")
            else:
                # Transition désactivée, appliquer directement
                cam_data.controller.set_focus(first_point_focus, silent=True)
                cam_data.focus_sent_value = first_point_focus
                self._update_focus_ui(first_point_focus)
                logger.info(f"Séquence {row_index + 1} : Focus appliqué directement (transition désactivée) ({first_point_focus:.3f})")
        
        # Réinitialiser la surbrillance de l'ancienne séquence active
        if self.active_sequence_row is not None and self.sequences_table:
            self._update_sequence_row_style(self.active_sequence_row, active=False)
        
        # Envoyer la séquence
        duration = sequence.get("duration", 5.0)
        if slider_controller.send_interpolation_sequence(points, duration, silent=False):
            # Activer l'interpolation automatique
            slider_controller.set_auto_interpolation(enable=True, duration=duration, silent=False)
            # Mettre en surbrillance la séquence active
            self.active_sequence_row = row_index
            if self.sequences_table:
                self._update_sequence_row_style(row_index, active=True)
            logger.info(f"Séquence {row_index + 1} ({sequence.get('name', 'Sans nom')}) envoyée avec {len(points)} points, durée {duration}s")
        else:
            logger.error(f"Échec de l'envoi de la séquence {row_index + 1}")
    
    def bake_sequence(self, row_index: int):
        """Bake une séquence en remplaçant les références aux presets par les valeurs réelles."""
        if row_index < 0 or row_index >= len(self.sequences_data):
            return
        
        cam_data = self.get_active_camera_data()
        sequence = self.sequences_data[row_index]
        baked_count = 0
        
        # Pour chaque point de la séquence
        for fraction in [0.0, 0.25, 0.5, 0.75, 1.0]:
            point_data = sequence["points"].get(fraction)
            if point_data is None:
                continue
            
            if point_data["type"] == "preset":
                # Récupérer les valeurs du preset
                preset_num = point_data["value"]
                preset_key = f"preset_{preset_num}"
                if preset_key not in cam_data.presets:
                    logger.warning(f"Preset {preset_num} introuvable pour le bake de la séquence {row_index + 1}")
                    continue
                
                preset_data = cam_data.presets[preset_key]
                # Remplacer par une valeur bakeée (inclure le focus)
                baked_value = {
                    "pan": preset_data.get("pan", 0.5),
                    "tilt": preset_data.get("tilt", 0.5),
                    "zoom": preset_data.get("zoom_motor", 0.0),
                    "slide": preset_data.get("slide", 0.5)
                }
                # Ajouter le focus si présent dans le preset
                if "focus" in preset_data:
                    baked_value["focus"] = preset_data["focus"]
                
                sequence["points"][fraction] = {
                    "type": "baked",
                    "value": baked_value
                }
                baked_count += 1
                
                # Mettre à jour l'affichage dans le tableau
                fraction_to_col = {0.0: 1, 0.25: 2, 0.5: 3, 0.75: 4, 1.0: 5}
                col = fraction_to_col.get(fraction)
                if col is not None and self.sequences_table:
                    widget = self.sequences_table.cellWidget(row_index, col)
                    if isinstance(widget, QLineEdit):
                        widget.setText("✗")
                        widget.setStyleSheet(self._scale_style("""
                            QLineEdit {
                                background-color: #3a2a2a;
                                border: 1px solid #8a4a4a;
                                color: #faa;
                                padding: 4px;
                                text-align: center;
                            }
                            QLineEdit:focus {
                                border: 1px solid #faa;
                            }
                        """))
        
        if baked_count > 0:
            # Vérifier si tous les points sont bakeés
            all_baked = all(
                p is None or (isinstance(p, dict) and p.get("type") == "baked")
                for p in sequence["points"].values()
            )
            sequence["baked"] = all_baked
            
            # Mettre à jour la couleur du bouton Save (rouge si bakeé)
            if self.sequences_table:
                save_btn = self.sequences_table.cellWidget(row_index, 7)
                if isinstance(save_btn, QPushButton):
                    if sequence["baked"]:
                        # Bouton rouge quand bakeé
                        save_btn.setStyleSheet(self._scale_style("""
                            QPushButton {
                                padding: 6px;
                                font-size: 10px;
                                font-weight: bold;
                                border: 1px solid #f00;
                                border-radius: 4px;
                                background-color: #f00;
                                color: #fff;
                            }
                            QPushButton:hover {
                                background-color: #f22;
                            }
                            QPushButton:pressed {
                                background-color: #d00;
                            }
                        """))
                    else:
                        # Bouton normal quand pas complètement bakeé
                        save_btn.setStyleSheet(self._scale_style("""
                            QPushButton {
                                padding: 6px;
                                font-size: 10px;
                                font-weight: bold;
                                border: 1px solid #555;
                                border-radius: 4px;
                                background-color: #5a2a2a;
                                color: #fff;
                            }
                            QPushButton:hover {
                                background-color: #7a4a4a;
                            }
                            QPushButton:pressed {
                                background-color: #4a2a2a;
                            }
                        """))
            
            self.save_sequences_to_config()
            logger.info(f"Séquence {row_index + 1} bakeée : {baked_count} point(s) converti(s)")
        else:
            logger.info(f"Séquence {row_index + 1} : aucun preset à baker")
    
    def erase_sequence(self, row_index: int):
        """Efface une séquence en réinitialisant tous ses champs."""
        if row_index < 0 or row_index >= len(self.sequences_data):
            return
        
        sequence = self.sequences_data[row_index]
        
        # Réinitialiser la séquence
        sequence["name"] = ""
        sequence["points"] = {0.0: None, 0.25: None, 0.5: None, 0.75: None, 1.0: None}
        sequence["duration"] = 5.0
        sequence["baked"] = False
        
        # Mettre à jour l'UI
        if self.sequences_table:
            # Nom
            name_widget = self.sequences_table.cellWidget(row_index, 0)
            if isinstance(name_widget, QLineEdit):
                name_widget.setText("")
            
            # Points (0%, 25%, 50%, 75%, 100%)
            fractions = [0.0, 0.25, 0.5, 0.75, 1.0]
            for col_idx, fraction in enumerate(fractions, start=1):
                preset_widget = self.sequences_table.cellWidget(row_index, col_idx)
                if isinstance(preset_widget, QLineEdit):
                    preset_widget.setText("")
                    preset_widget.setStyleSheet(self._scale_style("""
                        QLineEdit {
                            background-color: #2a2a2a;
                            border: 1px solid #555;
                            color: #fff;
                            padding: 4px;
                            text-align: center;
                        }
                        QLineEdit:focus {
                            border: 1px solid #0a5;
                        }
                    """))
            
            # Durée
            duration_widget = self.sequences_table.cellWidget(row_index, 6)
            if isinstance(duration_widget, QLineEdit):
                duration_widget.setText("5.0")
            
            # Bouton Save - réinitialiser à l'état normal
            save_btn = self.sequences_table.cellWidget(row_index, 7)
            if isinstance(save_btn, QPushButton):
                save_btn.setStyleSheet(self._scale_style("""
                    QPushButton {
                        padding: 6px;
                        font-size: 10px;
                        font-weight: bold;
                        border: 1px solid #555;
                        border-radius: 4px;
                        background-color: #5a2a2a;
                        color: #fff;
                    }
                    QPushButton:hover {
                        background-color: #7a4a4a;
                    }
                    QPushButton:pressed {
                        background-color: #4a2a2a;
                    }
                """))
        
        # Si cette séquence était active, la désactiver
        if self.active_sequence_row == row_index:
            self._update_sequence_row_style(row_index, active=False)
            self.active_sequence_row = None
        
        logger.info(f"Séquence {row_index + 1} effacée")
        
        # Sauvegarder
        self.save_sequences_to_config()
    
    def load_sequences_from_config(self):
        """Charge les séquences depuis la config et met à jour le tableau."""
        cam_data = self.get_active_camera_data()
        if not self.sequences_table:
            return
        
        # Charger depuis cam_data.sequences si disponible
        if hasattr(cam_data, 'sequences') and cam_data.sequences:
            # S'assurer qu'on a 20 séquences
            while len(cam_data.sequences) < 20:
                cam_data.sequences.append({
                    "name": "",
                    "points": {0.0: None, 0.25: None, 0.5: None, 0.75: None, 1.0: None},
                    "duration": 5.0,
                    "baked": False
                })
            
            # Copier les séquences (on prend les 20 premières)
            self.sequences_data = []
            for i in range(20):
                if i < len(cam_data.sequences):
                    # Faire une copie profonde pour éviter les références partagées
                    seq = cam_data.sequences[i].copy()
                    # Normaliser les clés des points : convertir les strings en float
                    points_normalized = {}
                    for key, value in seq["points"].items():
                        # Convertir la clé string en float si nécessaire
                        if isinstance(key, str):
                            try:
                                float_key = float(key)
                                points_normalized[float_key] = value
                            except ValueError:
                                # Si la conversion échoue, garder la clé originale
                                points_normalized[key] = value
                        else:
                            points_normalized[key] = value
                    seq["points"] = points_normalized
                    self.sequences_data.append(seq)
                else:
                    self.sequences_data.append({
                        "name": "",
                        "points": {0.0: None, 0.25: None, 0.5: None, 0.75: None, 1.0: None},
                        "duration": 5.0,
                        "baked": False
                    })
        else:
            # Initialiser avec des séquences vides si pas de données
            if not hasattr(cam_data, 'sequences'):
                cam_data.sequences = []
            while len(cam_data.sequences) < 20:
                cam_data.sequences.append({
                    "name": "",
                    "points": {0.0: None, 0.25: None, 0.5: None, 0.75: None, 1.0: None},
                    "duration": 5.0,
                    "baked": False
                })
            # Copier dans self.sequences_data
            self.sequences_data = []
            for seq in cam_data.sequences[:20]:
                seq_copy = seq.copy()
                # Normaliser les clés des points : convertir les strings en float
                points_normalized = {}
                for key, value in seq["points"].items():
                    # Convertir la clé string en float si nécessaire
                    if isinstance(key, str):
                        try:
                            float_key = float(key)
                            points_normalized[float_key] = value
                        except ValueError:
                            # Si la conversion échoue, garder la clé originale
                            points_normalized[key] = value
                    else:
                        points_normalized[key] = value
                seq_copy["points"] = points_normalized
                self.sequences_data.append(seq_copy)
        
        # Mettre à jour le tableau
        for row in range(20):
            if row >= len(self.sequences_data):
                break
            
            sequence = self.sequences_data[row]
            
            # Nom
            name_widget = self.sequences_table.cellWidget(row, 0)
            if isinstance(name_widget, QLineEdit):
                name_widget.setText(sequence.get("name", ""))
            
            # Points (0%, 25%, 50%, 75%, 100%)
            fraction_to_col = {0.0: 1, 0.25: 2, 0.5: 3, 0.75: 4, 1.0: 5}
            for fraction, col in fraction_to_col.items():
                widget = self.sequences_table.cellWidget(row, col)
                if isinstance(widget, QLineEdit):
                    point_data = sequence["points"].get(fraction)
                    if point_data is None:
                        widget.clear()
                    elif point_data["type"] == "preset":
                        widget.setText(str(point_data["value"]))
                        widget.setStyleSheet(self._scale_style("""
                            QLineEdit {
                                background-color: #2a2a2a;
                                border: 1px solid #555;
                                color: #fff;
                                padding: 4px;
                                text-align: center;
                            }
                            QLineEdit:focus {
                                border: 1px solid #0a5;
                            }
                        """))
                    elif point_data["type"] == "baked":
                        widget.setText("✗")
                        widget.setStyleSheet(self._scale_style("""
                            QLineEdit {
                                background-color: #3a2a2a;
                                border: 1px solid #8a4a4a;
                                color: #faa;
                                padding: 4px;
                                text-align: center;
                            }
                            QLineEdit:focus {
                                border: 1px solid #faa;
                            }
                        """))
            
            # Durée
            duration_widget = self.sequences_table.cellWidget(row, 6)
            if isinstance(duration_widget, QLineEdit):
                duration_widget.setText(f"{sequence.get('duration', 5.0):.1f}")
            
            # Bouton Save - mettre à jour la couleur selon l'état
            save_btn = self.sequences_table.cellWidget(row, 7)
            if isinstance(save_btn, QPushButton):
                if sequence.get("baked", False):
                    # Bouton rouge quand bakeé
                    save_btn.setStyleSheet(self._scale_style("""
                        QPushButton {
                            padding: 6px;
                            font-size: 10px;
                            font-weight: bold;
                            border: 1px solid #f00;
                            border-radius: 4px;
                            background-color: #f00;
                            color: #fff;
                        }
                        QPushButton:hover {
                            background-color: #f22;
                        }
                        QPushButton:pressed {
                            background-color: #d00;
                        }
                    """))
                else:
                    # Bouton normal quand pas bakeé
                    save_btn.setStyleSheet(self._scale_style("""
                        QPushButton {
                            padding: 6px;
                            font-size: 10px;
                            font-weight: bold;
                            border: 1px solid #555;
                            border-radius: 4px;
                            background-color: #5a2a2a;
                            color: #fff;
                        }
                        QPushButton:hover {
                            background-color: #7a4a4a;
                        }
                        QPushButton:pressed {
                            background-color: #4a2a2a;
                        }
                    """))
    
    def save_sequences_to_config(self):
        """Sauvegarde les séquences dans la config."""
        cam_data = self.get_active_camera_data()
        cam_data.sequences = self.sequences_data.copy()
        self.save_cameras_config()
    
    def stop_sequence(self):
        """Arrête l'interpolation automatique du slider."""
        slider_controller = self.slider_controllers.get(self.active_camera_id)
        if slider_controller and slider_controller.is_configured():
            if slider_controller.set_auto_interpolation(enable=False, silent=False):
                logger.info("Interpolation automatique arrêtée")
                # Réinitialiser la surbrillance de la séquence active
                if self.active_sequence_row is not None and self.sequences_table:
                    self._update_sequence_row_style(self.active_sequence_row, active=False)
                    self.active_sequence_row = None
            else:
                logger.warning("Échec de l'arrêt de l'interpolation automatique")
        else:
            logger.warning("Impossible d'arrêter la séquence : slider non configuré")
    
    def save_sequences_column_widths(self):
        """Sauvegarde les largeurs actuelles des colonnes du tableau Sequences."""
        if not self.sequences_table:
            return
        
        column_widths = {}
        scale_factor = self.ui_scaler.scale if self.ui_scaler else 1.0
        for i in range(9):
            width = self.sequences_table.columnWidth(i)
            # Convertir en valeur non-scalée pour la sauvegarde
            unscaled_width = width / scale_factor
            column_widths[str(i)] = unscaled_width
        
        # Sauvegarder dans la configuration globale (pas par caméra)
        self.sequences_column_widths = column_widths
        self.save_cameras_config()
        logger.debug(f"Largeurs de colonnes sauvegardées (global): {column_widths}")

    def load_sequences_column_widths(self):
        """Charge les largeurs sauvegardées des colonnes du tableau Sequences (global)."""
        if not self.sequences_table:
            logger.debug("load_sequences_column_widths: sequences_table n'existe pas encore")
            return
        
        logger.debug(f"load_sequences_column_widths: self.sequences_column_widths = {self.sequences_column_widths}")
        
        if self.sequences_column_widths:
            column_widths = self.sequences_column_widths
            logger.info(f"Chargement des largeurs de colonnes sauvegardées (global): {column_widths}")
            for i in range(9):
                if str(i) in column_widths:
                    unscaled_width = column_widths[str(i)]
                    scaled_width = self._scale_value(unscaled_width)
                    self.sequences_table.setColumnWidth(i, scaled_width)
                    logger.debug(f"  Colonne {i}: {unscaled_width} (non-scalé) -> {scaled_width} (scalé)")
            logger.debug(f"Largeurs de colonnes chargées: {column_widths}")
        else:
            # Valeurs par défaut si aucune sauvegarde
            logger.debug("Aucune largeur sauvegardée, utilisation des valeurs par défaut")
            self.sequences_table.setColumnWidth(0, self._scale_value(200))  # Name
            for i in range(1, 6):  # 0%, 25%, 50%, 75%, 100%
                self.sequences_table.setColumnWidth(i, self._scale_value(120))
            self.sequences_table.setColumnWidth(6, self._scale_value(160))  # Duration
            self.sequences_table.setColumnWidth(7, self._scale_value(100))  # Save
            self.sequences_table.setColumnWidth(8, self._scale_value(100))  # Erase

    def on_sequence_column_resized(self, logical_index: int, old_size: int, new_size: int):
        """Appelé quand une colonne du tableau Sequences est redimensionnée."""
        # Sauvegarder avec un petit délai pour éviter trop de sauvegardes
        if not hasattr(self, '_sequences_column_widths_save_timer'):
            self._sequences_column_widths_save_timer = QTimer()
            self._sequences_column_widths_save_timer.setSingleShot(True)
            self._sequences_column_widths_save_timer.timeout.connect(self.save_sequences_column_widths)
        
        # Réinitialiser le timer à chaque redimensionnement
        self._sequences_column_widths_save_timer.stop()
        self._sequences_column_widths_save_timer.start(500)  # Sauvegarder après 500ms d'inactivité
    
    def _update_sequence_row_style(self, row: int, active: bool):
        """Met à jour le style d'une ligne de séquence (surbrillance jaune si active)."""
        if not self.sequences_table or row < 0 or row >= 20:
            return
        
        # Couleur de fond pour la ligne
        bg_color = "#ffaa00" if active else "#2a2a2a"
        text_color = "#000" if active else "#fff"
        
        for col in range(9):  # 9 colonnes
            # Mettre à jour le style des widgets dans les cellules
            widget = self.sequences_table.cellWidget(row, col)
            if widget:
                if active:
                    # Style actif : fond jaune
                    if isinstance(widget, QLineEdit):
                        widget.setStyleSheet(self._scale_style(f"""
                            QLineEdit {{
                                background-color: {bg_color};
                                color: {text_color};
                                border: 1px solid #ff8800;
                                padding: 4px;
                            }}
                        """))
                    elif isinstance(widget, QPushButton):
                        # Le bouton Save garde son style mais avec fond jaune
                        widget.setStyleSheet(self._scale_style(f"""
                            QPushButton {{
                                padding: 6px;
                                font-size: 10px;
                                font-weight: bold;
                                border: 1px solid #ff8800;
                                border-radius: 4px;
                                background-color: {bg_color};
                                color: {text_color};
                            }}
                            QPushButton:hover {{
                                background-color: #ffcc00;
                            }}
                            QPushButton:pressed {{
                                background-color: #ff9900;
                            }}
                        """))
                else:
                    # Restaurer le style original selon le type de widget
                    if isinstance(widget, QLineEdit):
                        if col == 0:  # Name
                            widget.setStyleSheet(self._scale_style("""
                                QLineEdit {
                                    background-color: #2a2a2a;
                                    border: 1px solid #555;
                                    color: #fff;
                                    padding: 4px;
                                }
                                QLineEdit:hover {
                                    border: 1px solid #0a5;
                                    background-color: #3a3a3a;
                                }
                            """))
                        elif col in range(1, 6):  # 0%, 25%, 50%, 75%, 100%
                            widget.setStyleSheet(self._scale_style("""
                                QLineEdit {
                                    background-color: #2a2a2a;
                                    border: 1px solid #555;
                                    color: #fff;
                                    padding: 4px;
                                    text-align: center;
                                }
                                QLineEdit:focus {
                                    border: 1px solid #0a5;
                                }
                            """))
                        elif col == 6:  # Duration
                            widget.setStyleSheet(self._scale_style("""
                                QLineEdit {
                                    background-color: #2a2a2a;
                                    border: 1px solid #555;
                                    color: #fff;
                                    padding: 4px;
                                    text-align: center;
                                }
                                QLineEdit:focus {
                                    border: 1px solid #0a5;
                                }
                            """))
                    elif isinstance(widget, QPushButton):
                        # Restaurer le style original du bouton Save (sera géré par bake_sequence)
                        pass
    
    def _start_focus_transition(self, start_value: float, end_value: float, cam_data: 'CameraData'):
        """Démarre une transition progressive du focus sur 3 secondes."""
        self.focus_transition_start = start_value
        self.focus_transition_end = end_value
        self.focus_transition_start_time = time.time()
        
        # Créer le timer s'il n'existe pas
        if self.focus_transition_timer is None:
            self.focus_transition_timer = QTimer()
            self.focus_transition_timer.timeout.connect(self._update_focus_transition)
        
        # Mettre à jour toutes les 50ms pour une transition fluide
        self.focus_transition_timer.start(50)
    
    def _update_focus_transition(self):
        """Met à jour le focus pendant la transition."""
        if (self.focus_transition_start is None or 
            self.focus_transition_end is None or 
            self.focus_transition_start_time is None):
            if self.focus_transition_timer:
                self.focus_transition_timer.stop()
            return
        
        # Récupérer la caméra active
        cam_data = self.get_active_camera_data()
        if not cam_data or not cam_data.controller:
            if self.focus_transition_timer:
                self.focus_transition_timer.stop()
            return
        
        elapsed = time.time() - self.focus_transition_start_time
        progress = min(elapsed / self.focus_transition_duration, 1.0)
        
        # Interpolation linéaire
        current_focus = self.focus_transition_start + (self.focus_transition_end - self.focus_transition_start) * progress
        
        # Appliquer le focus
        cam_data.controller.set_focus(current_focus, silent=True)
        cam_data.focus_sent_value = current_focus
        self._update_focus_ui(current_focus)
        
        # Arrêter la transition si terminée
        if progress >= 1.0:
            if self.focus_transition_timer:
                self.focus_transition_timer.stop()
            logger.info(f"Transition de focus terminée : {self.focus_transition_end:.3f}")
    
    def _update_focus_ui(self, focus_value: float):
        """Met à jour l'UI du focus."""
        if hasattr(self, 'focus_value_sent'):
            self.focus_value_sent.setText(f"{focus_value:.3f}")
        if hasattr(self, 'focus_slider'):
            slider_value = int(focus_value * 1000)
            self.focus_slider.blockSignals(True)
            self.focus_slider.setValue(slider_value)
            self.focus_slider.blockSignals(False)
    
    def create_pan_tilt_matrix_panel(self):
        """Crée le panneau de contrôle Pan/Tilt avec une matrice XY."""
        panel = QWidget()
        # La largeur sera mise à jour dans _update_ui_scaling
        panel_width = self._scale_value(280)
        panel.setMinimumWidth(panel_width)
        panel.setMaximumWidth(panel_width)
        panel.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        panel.setStyleSheet(self._scale_style("""
            QWidget {
                background-color: #1a1a1a;
                border: 1px solid #444;
                border-radius: 4px;
            }
        """))
        layout = QVBoxLayout(panel)
        spacing = self._scale_value(10)
        margin = self._scale_value(20)
        layout.setSpacing(spacing)
        layout.setContentsMargins(margin, margin, margin, margin)
        
        # Titre
        title = QLabel("Pan/Tilt Control")
        title.setAlignment(Qt.AlignCenter)
        font_size = self._scale_font(14)
        title.setStyleSheet(f"font-size: {font_size}; color: #fff;")
        layout.addWidget(title, stretch=0)
        
        # Affichage des valeurs normalisées et steps
        values_display = QWidget()
        values_layout = QVBoxLayout(values_display)
        values_layout.setContentsMargins(0, 0, 0, 0)
        values_layout.setSpacing(5)
        
        # Ligne pour Pan
        pan_row = QWidget()
        pan_layout = QHBoxLayout(pan_row)
        pan_layout.setContentsMargins(0, 0, 0, 0)
        pan_layout.setSpacing(10)
        
        pan_label = QLabel("Pan:")
        pan_label.setStyleSheet(f"font-size: {self._scale_font(10)}; color: #aaa;")
        pan_layout.addWidget(pan_label)
        
        pan_percent_label = QLabel("0.0%")
        pan_percent_label.setStyleSheet(f"font-size: {self._scale_font(11)}; font-weight: bold; color: #0ff; font-family: 'Courier New';")
        pan_layout.addWidget(pan_percent_label)
        
        pan_layout.addStretch()
        
        pan_steps_label = QLabel("0")
        pan_steps_label.setStyleSheet(f"font-size: {self._scale_font(11)}; font-weight: bold; color: #ff0; font-family: 'Courier New';")
        pan_layout.addWidget(pan_steps_label)
        
        values_layout.addWidget(pan_row)
        
        # Ligne pour Tilt
        tilt_row = QWidget()
        tilt_layout = QHBoxLayout(tilt_row)
        tilt_layout.setContentsMargins(0, 0, 0, 0)
        tilt_layout.setSpacing(10)
        
        tilt_label = QLabel("Tilt:")
        tilt_label.setStyleSheet(f"font-size: {self._scale_font(10)}; color: #aaa;")
        tilt_layout.addWidget(tilt_label)
        
        tilt_percent_label = QLabel("0.0%")
        tilt_percent_label.setStyleSheet(f"font-size: {self._scale_font(11)}; font-weight: bold; color: #0ff; font-family: 'Courier New';")
        tilt_layout.addWidget(tilt_percent_label)
        
        tilt_layout.addStretch()
        
        tilt_steps_label = QLabel("0")
        tilt_steps_label.setStyleSheet(f"font-size: {self._scale_font(11)}; font-weight: bold; color: #ff0; font-family: 'Courier New';")
        tilt_layout.addWidget(tilt_steps_label)
        
        values_layout.addWidget(tilt_row)
        
        layout.addWidget(values_display, stretch=0)
        
        # Matrice XY
        xy_matrix = XYMatrixWidget()
        xy_matrix.setMinimumHeight(self._scale_value(200))
        xy_matrix.setMaximumHeight(self._scale_value(300))
        layout.addWidget(xy_matrix, stretch=1)
        
        # Stocker les références
        panel.xy_matrix = xy_matrix
        panel.pan_percent_label = pan_percent_label
        panel.pan_steps_label = pan_steps_label
        panel.tilt_percent_label = tilt_percent_label
        panel.tilt_steps_label = tilt_steps_label
        
        return panel
    
    def create_slide_panel(self):
        """Crée le panneau de contrôle Slide."""
        return self.create_slider_axis_panel("slide", "Slide Control")
    
    def create_zoom_motor_panel(self):
        """Crée le panneau de contrôle Zoom Motor avec affichage de la focale caméra."""
        # Créer le panneau de base
        panel = self.create_slider_axis_panel("zoom", "Zoom Motor Control")
        
        # Ajouter un label pour afficher la focale caméra en rouge sous le titre
        focal_length_label = QLabel("- mm")
        focal_length_label.setAlignment(Qt.AlignCenter)
        focal_length_label.setStyleSheet(f"font-size: {self._scale_font(11)}; font-weight: bold; color: #f00; font-family: 'Courier New';")
        
        # Insérer le label après le titre (index 0) dans le layout
        panel.layout().insertWidget(1, focal_length_label)
        
        # Stocker la référence pour pouvoir la mettre à jour
        panel.focal_length_label = focal_length_label
        
        return panel
    
    def create_presets_panel(self):
        """Crée le panneau de presets."""
        panel = QWidget()
        panel_width = self._scale_value(250)  # Augmenté pour accommoder la colonne distance
        panel.setMinimumWidth(panel_width)
        panel.setMaximumWidth(panel_width)
        panel.setStyleSheet(self._scale_style("""
            QWidget {
                background-color: #1a1a1a;
                border: 1px solid #444;
                border-radius: 4px;
            }
        """))
        layout = QVBoxLayout(panel)
        spacing = self._scale_value(15)
        margin = self._scale_value(30)
        layout.setSpacing(spacing)
        layout.setContentsMargins(margin, margin, margin, margin)
        
        presets_label = QLabel("Presets")
        presets_label.setAlignment(Qt.AlignCenter)
        presets_label.setStyleSheet(f"font-size: {self._scale_font(20)}; font-weight: bold; color: #fff;")
        layout.addWidget(presets_label)
        
        # Conteneur pour les trois colonnes (Save, Recall, Distance)
        presets_container = QHBoxLayout()
        presets_container.setSpacing(self._scale_value(10))
        
        # Colonne Save
        save_column = QVBoxLayout()
        save_column.setSpacing(self._scale_value(3))  # Réduire l'espacement pour éviter le décalage
        save_column.setContentsMargins(0, 0, 0, 0)  # Pas de marges pour un alignement parfait
        save_label = QLabel("Save")
        save_label.setAlignment(Qt.AlignCenter)
        save_label.setFixedHeight(self._scale_value(20))  # Hauteur fixe pour alignement
        save_label.setStyleSheet(f"font-size: {self._scale_font(12)}; font-weight: bold; color: #aaa;")
        save_column.addWidget(save_label)
        
        self.preset_save_buttons = []
        save_btn_style = self._scale_style("""
            QPushButton {
                padding: 6px;
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
        for i in range(1, 11):
            save_btn = QPushButton(f"{i}")
            save_btn.setStyleSheet(save_btn_style)
            save_btn.setFixedHeight(self._scale_value(28))  # Hauteur fixe pour alignement
            save_btn.clicked.connect(lambda checked, n=i: self.save_preset(n))
            save_column.addWidget(save_btn)
            self.preset_save_buttons.append(save_btn)
        
        # Colonne Recall
        recall_column = QVBoxLayout()
        recall_column.setSpacing(self._scale_value(3))  # Réduire l'espacement pour éviter le décalage
        recall_column.setContentsMargins(0, 0, 0, 0)  # Pas de marges pour un alignement parfait
        recall_label = QLabel("Recall")
        recall_label.setAlignment(Qt.AlignCenter)
        recall_label.setFixedHeight(self._scale_value(20))  # Hauteur fixe identique à Save pour alignement
        recall_label.setStyleSheet(f"font-size: {self._scale_font(12)}; font-weight: bold; color: #aaa;")
        recall_column.addWidget(recall_label)
        
        self.preset_recall_buttons = []
        recall_btn_style = self._scale_style("""
            QPushButton {
                padding: 6px;
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
        for i in range(1, 11):
            recall_btn = QPushButton(f"{i}")
            recall_btn.setStyleSheet(recall_btn_style)
            recall_btn.setFixedHeight(self._scale_value(28))  # Hauteur fixe identique à Save pour alignement
            recall_btn.clicked.connect(lambda checked, n=i: self.recall_preset(n))
            recall_column.addWidget(recall_btn)
            self.preset_recall_buttons.append(recall_btn)
        
        # Colonne Distance (D)
        distance_column = QVBoxLayout()
        distance_column.setSpacing(self._scale_value(3))
        distance_column.setContentsMargins(0, 0, 0, 0)
        distance_label = QLabel("D")
        distance_label.setAlignment(Qt.AlignCenter)
        distance_label.setFixedHeight(self._scale_value(20))
        distance_label.setStyleSheet(f"font-size: {self._scale_font(12)}; font-weight: bold; color: #aaa;")
        distance_column.addWidget(distance_label)
        
        self.preset_distance_inputs = []
        distance_input_style = self._scale_style("""
            QLineEdit {
                padding: 4px;
                font-size: 10px;
                border: 1px solid #555;
                border-radius: 4px;
                background-color: #2a2a2a;
                color: #fff;
                text-align: center;
            }
            QLineEdit:focus {
                border: 1px solid #0a5;
                background-color: #333;
            }
        """)
        for i in range(1, 11):
            distance_input = QLineEdit()
            distance_input.setStyleSheet(distance_input_style)
            distance_input.setFixedHeight(self._scale_value(28))
            distance_input.setPlaceholderText("m")
            # Pas de validator strict - on gère la validation manuellement pour accepter . et ,
            # Connecter le signal pour sauvegarder la valeur
            distance_input.editingFinished.connect(lambda n=i: self.on_preset_distance_changed(n))
            distance_column.addWidget(distance_input)
            self.preset_distance_inputs.append(distance_input)
        
        # Ajouter les trois colonnes au conteneur
        presets_container.addLayout(save_column)
        presets_container.addLayout(recall_column)
        presets_container.addLayout(distance_column)
        
        layout.addLayout(presets_container)
        
        # Section Recall Scope
        layout.addSpacing(self._scale_value(20))
        recall_scope_label = QLabel("Recall Scope")
        recall_scope_label.setAlignment(Qt.AlignCenter)
        recall_scope_label.setStyleSheet(f"font-size: {self._scale_font(14)}; font-weight: bold; color: #fff; margin-top: {self._scale_value(10)}px;")
        layout.addWidget(recall_scope_label)
        
        # Conteneur pour les checkboxes
        recall_scope_container = QVBoxLayout()
        recall_scope_container.setSpacing(self._scale_value(8))
        
        # Dictionnaire pour stocker les références aux checkboxes
        self.recall_scope_checkboxes = {}
        
        # Style partagé pour tous les checkboxes de recall scope
        recall_scope_checkbox_style = self._scale_style("""
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
        
        # Checkbox Focus
        focus_checkbox = QPushButton("☐ Focus")
        focus_checkbox.setCheckable(True)
        focus_checkbox.setStyleSheet(recall_scope_checkbox_style)
        focus_checkbox.clicked.connect(lambda checked: self.on_recall_scope_changed('focus', checked))
        recall_scope_container.addWidget(focus_checkbox)
        self.recall_scope_checkboxes['focus'] = focus_checkbox
        
        # Checkbox Iris
        iris_checkbox = QPushButton("☐ Iris")
        iris_checkbox.setCheckable(True)
        iris_checkbox.setStyleSheet(recall_scope_checkbox_style)
        iris_checkbox.clicked.connect(lambda checked: self.on_recall_scope_changed('iris', checked))
        recall_scope_container.addWidget(iris_checkbox)
        self.recall_scope_checkboxes['iris'] = iris_checkbox
        
        # Checkbox Gain
        gain_checkbox = QPushButton("☐ Gain")
        gain_checkbox.setCheckable(True)
        gain_checkbox.setStyleSheet(recall_scope_checkbox_style)
        gain_checkbox.clicked.connect(lambda checked: self.on_recall_scope_changed('gain', checked))
        recall_scope_container.addWidget(gain_checkbox)
        self.recall_scope_checkboxes['gain'] = gain_checkbox
        
        # Checkbox Shutter
        shutter_checkbox = QPushButton("☐ Shutter")
        shutter_checkbox.setCheckable(True)
        shutter_checkbox.setStyleSheet(recall_scope_checkbox_style)
        shutter_checkbox.clicked.connect(lambda checked: self.on_recall_scope_changed('shutter', checked))
        recall_scope_container.addWidget(shutter_checkbox)
        self.recall_scope_checkboxes['shutter'] = shutter_checkbox
        
        # Checkbox White Balance
        whitebalance_checkbox = QPushButton("☐ White Balance")
        whitebalance_checkbox.setCheckable(True)
        whitebalance_checkbox.setStyleSheet(recall_scope_checkbox_style)
        whitebalance_checkbox.clicked.connect(lambda checked: self.on_recall_scope_changed('whitebalance', checked))
        recall_scope_container.addWidget(whitebalance_checkbox)
        self.recall_scope_checkboxes['whitebalance'] = whitebalance_checkbox
        
        # Checkbox Slider
        slider_checkbox = QPushButton("☐ Slider")
        slider_checkbox.setCheckable(True)
        slider_checkbox.setStyleSheet(recall_scope_checkbox_style)
        slider_checkbox.clicked.connect(lambda checked: self.on_recall_scope_changed('slider', checked))
        recall_scope_container.addWidget(slider_checkbox)
        self.recall_scope_checkboxes['slider'] = slider_checkbox
        
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
                        
                        # Synchroniser automatiquement le D du LFO avec le focus
                        self.sync_lfo_distance_from_focus(focus_value)
                        
                        # Mettre à jour l'affichage de la distance même si la synchronisation LFO est désactivée
                        if hasattr(self, 'focus_distance_label') and self.focus_distance_label:
                            # Obtenir le zoom actuel pour la conversion (valeur du slider pour la LUT 3D)
                            zoom_normalised = None
                            if cam_data and hasattr(cam_data, 'slider_zoom_value') and cam_data.slider_zoom_value is not None:
                                zoom_normalised = cam_data.slider_zoom_value  # Valeur normalisée du slider
                            
                            distance_meters = self.focus_lut.normalised_to_distance_with_zoom(focus_value, zoom_normalised)
                            if distance_meters is not None:
                                self.focus_distance_label.setText(f"Distance: {distance_meters:.2f} m")
                            else:
                                self.focus_distance_label.setText("Distance: -- m")
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
        self.signals.whitebalance_changed.connect(self.on_whitebalance_changed)
        self.signals.tint_changed.connect(self.on_tint_changed)
        self.signals.focusAssist_changed.connect(self.on_focusAssist_changed)
        self.signals.falseColor_changed.connect(self.on_falseColor_changed)
        self.signals.cleanfeed_changed.connect(self.on_cleanfeed_changed)
        # Note: websocket_status n'est plus utilisé car on utilise maintenant _handle_websocket_change avec camera_id
        
        # Connecter les signaux des sliders (pan, tilt, slide, zoom motor)
        # Connecter la matrice XY pan/tilt
        if hasattr(self, 'pan_tilt_panel') and hasattr(self.pan_tilt_panel, 'xy_matrix'):
            self.pan_tilt_panel.xy_matrix.positionChanged.connect(self.on_pan_tilt_matrix_changed)
        
        self.slide_panel.slider.sliderPressed.connect(lambda: self.on_slider_pressed('slide'))
        self.slide_panel.slider.sliderReleased.connect(lambda: self.on_slider_released('slide'))
        self.slide_panel.slider.valueChanged.connect(lambda v: self.on_slider_value_changed('slide', v))
        
        self.zoom_motor_panel.slider.sliderPressed.connect(lambda: self.on_slider_pressed('zoom'))
        self.zoom_motor_panel.slider.sliderReleased.connect(lambda: self.on_slider_released('zoom'))
        self.zoom_motor_panel.slider.valueChanged.connect(lambda v: self.on_slider_value_changed('zoom', v))
    
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
        """Ouvre le dialog de configuration ATEM."""
        dialog = ConnectionDialog(self, atem_config=self.atem_config)
        # Mettre à jour le statut après création pour afficher l'état initial
        dialog.update_atem_status()
        # Garder une référence au dialog pour mettre à jour le statut
        self.atem_dialog = dialog
        dialog.exec()
        # Nettoyer la référence après fermeture
        self.atem_dialog = None
    
    def _try_auto_connect_all_cameras(self):
        """Tente une connexion automatique pour toutes les caméras configurées."""
        logger.info("Démarrage de la connexion automatique pour toutes les caméras configurées...")
        camera_count = 0
        # Credentials par défaut si vides
        default_username = "roo"
        default_password = "koko"
        
        for camera_id in range(1, 9):
            cam_data = self.cameras[camera_id]
            # Vérifier que l'URL existe (requis)
            if not cam_data.url:
                continue
            
            # Utiliser les credentials par défaut si vides
            username = cam_data.username if cam_data.username else default_username
            password = cam_data.password if cam_data.password else default_password
            
            # Ne pas vérifier cam_data.connected ici car cela peut être False même si la connexion est en cours
            # Échelonner les tentatives de connexion (2 secondes entre chaque caméra)
            # pour éviter de surcharger le réseau et donner plus de temps à chaque caméra
            delay_ms = 2000 * camera_count  # 0ms pour première caméra, 2000ms pour suivante, etc.
            camera_count += 1
            # Utiliser functools.partial ou une fonction wrapper pour capturer correctement camera_id
            def make_connect_func(cam_id, user, pwd):
                return lambda: self._try_auto_connect(cam_id, attempt=0, max_attempts=5, username=user, password=pwd)
            QTimer.singleShot(delay_ms, make_connect_func(camera_id, username, password))
            logger.info(f"Connexion automatique programmée pour caméra {camera_id} dans {delay_ms/1000:.1f}s (user: {username})")
    
    def _try_auto_connect(self, camera_id: int = None, attempt: int = 0, max_attempts: int = 5, username: str = None, password: str = None):
        """Tente une connexion automatique sans bloquer l'UI avec plusieurs tentatives."""
        try:
            # Utiliser la caméra active si camera_id n'est pas spécifié (rétrocompatibilité)
            if camera_id is None:
                camera_id = self.active_camera_id
            
            cam_data = self.cameras[camera_id]
            if not cam_data.url:
                logger.debug(f"Caméra {camera_id} - URL manquante, connexion automatique ignorée")
                return
            
            # Vérifier si la reconnexion automatique est activée
            if not getattr(cam_data, 'auto_reconnect_enabled', True):
                logger.info(f"Caméra {camera_id} - Reconnexion automatique désactivée, connexion automatique ignorée")
                return
            
            # Utiliser les credentials fournis en paramètre, ou ceux de cam_data, ou les valeurs par défaut
            default_username = "roo"
            default_password = "koko"
            effective_username = username if username is not None else (cam_data.username if cam_data.username else default_username)
            effective_password = password if password is not None else (cam_data.password if cam_data.password else default_password)
            
            # Si déjà connecté, ne pas réessayer
            if cam_data.connected:
                logger.info(f"Caméra {camera_id} - Déjà connectée, connexion automatique ignorée")
                return
            
            # Si un contrôleur existe déjà (connexion en cours), ne pas réessayer immédiatement
            if cam_data.controller is not None:
                logger.debug(f"Caméra {camera_id} - Contrôleur existe déjà, connexion peut être en cours")
                # Attendre un peu et vérifier à nouveau
                if attempt == 0:
                    QTimer.singleShot(3000, partial(self._try_auto_connect, camera_id, 1, max_attempts))
                return
            
                import requests
                from requests.auth import HTTPBasicAuth
            import socket
            from urllib.parse import urlparse
            
            # Résoudre le hostname .local en IP si nécessaire (pour améliorer la stabilité)
            test_url = cam_data.url
            try:
                parsed = urlparse(cam_data.url)
                hostname = parsed.hostname
                if hostname and hostname.endswith('.local'):
                    # Essayer de résoudre le .local en IP
                    try:
                        addr_info = socket.getaddrinfo(hostname, None, socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP)
                        if addr_info:
                            ip_address = addr_info[0][4][0]
                            logger.info(f"Résolution DNS pour connexion auto: {hostname} -> {ip_address}")
                            test_url = cam_data.url.replace(hostname, ip_address)
                    except (socket.gaierror, OSError) as e:
                        logger.debug(f"Résolution DNS échouée pour {hostname}, utilisation du nom original: {e}")
            except Exception as e:
                logger.debug(f"Erreur lors de la résolution DNS: {e}, utilisation de l'URL originale")
            
            # Timeout progressif : 5s pour la première tentative, 8s pour les suivantes
            timeout = 5.0 if attempt == 0 else 8.0
            
            try:
                test_endpoint = f"{test_url}/control/api/v1/lens/focus"
                logger.info(f"Caméra {camera_id} - Tentative {attempt + 1}/{max_attempts} de connexion automatique à {test_endpoint} (timeout: {timeout}s, user: {effective_username})")
                
                response = requests.get(
                    test_endpoint,
                    auth=HTTPBasicAuth(effective_username, effective_password),
                    timeout=timeout,
                    verify=False  # Désactiver la vérification SSL pour les certificats auto-signés
                )
                
                # Si la caméra répond, on peut lancer la connexion complète
                if response.status_code == 200:
                    logger.info(f"✓ Caméra {camera_id} accessible, connexion en cours...")
                    self.connect_to_camera(camera_id, cam_data.url, effective_username, effective_password)
                else:
                    logger.info(f"Caméra {camera_id} - Réponse HTTP {response.status_code}, réessai dans 2s...")
                    if attempt < max_attempts - 1:
                        QTimer.singleShot(2000, partial(self._try_auto_connect, camera_id, attempt + 1, max_attempts))
                        
            except requests.exceptions.Timeout:
                logger.info(f"Caméra {camera_id} - Timeout après {timeout}s (tentative {attempt + 1}/{max_attempts})")
                if attempt < max_attempts - 1:
                    # Attendre 3 secondes avant la prochaine tentative (augmenté de 2s à 3s)
                    QTimer.singleShot(3000, partial(self._try_auto_connect, camera_id, attempt + 1, max_attempts))
                else:
                    logger.warning(f"Caméra {camera_id} - Connexion automatique abandonnée après {max_attempts} tentatives (timeout)")
                    
            except (requests.exceptions.ConnectionError, requests.exceptions.RequestException) as e:
                error_str = str(e).lower()
                # Si c'est une erreur de résolution DNS, réessayer avec plus de patience
                if 'nodename' in error_str or 'servname' in error_str or 'name resolution' in error_str:
                    logger.info(f"Caméra {camera_id} - Résolution DNS en cours... (tentative {attempt + 1}/{max_attempts})")
                    if attempt < max_attempts - 1:
                        # Attendre plus longtemps pour la résolution DNS (6 secondes, augmenté de 5s)
                        QTimer.singleShot(6000, partial(self._try_auto_connect, camera_id, attempt + 1, max_attempts))
                    else:
                        logger.warning(f"Caméra {camera_id} - Résolution DNS échouée après {max_attempts} tentatives")
                else:
                    logger.info(f"Caméra {camera_id} - Erreur de connexion (tentative {attempt + 1}/{max_attempts}): {e}")
                    if attempt < max_attempts - 1:
                        QTimer.singleShot(3000, partial(self._try_auto_connect, camera_id, attempt + 1, max_attempts))
                    else:
                        logger.warning(f"Caméra {camera_id} - Connexion automatique abandonnée après {max_attempts} tentatives")
                        
        except Exception as e:
            logger.warning(f"Connexion automatique échouée pour caméra {camera_id} (non bloquant): {e}")
            # Réessayer une fois de plus si on n'a pas atteint le maximum
            if attempt < max_attempts - 1:
                QTimer.singleShot(4000, partial(self._try_auto_connect, camera_id, attempt + 1, max_attempts))
    
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
            
            # Marquer comme "connecting" si ce n'est pas déjà fait
            if not getattr(cam_data, 'connecting', False):
                cam_data.connecting = True
            
            # Créer le contrôleur (non bloquant, juste initialise les endpoints)
            try:
                cam_data.controller = BlackmagicFocusController(cam_data.url, cam_data.username, cam_data.password)
            except Exception as e:
                logger.error(f"Erreur lors de la création du contrôleur pour la caméra {camera_id}: {e}")
                cam_data.connected = False
                cam_data.connecting = False
                if camera_id == self.active_camera_id:
                    self.status_label.setText(f"✗ Caméra {camera_id} - Erreur: {e}")
                    self.status_label.setStyleSheet("color: #f00;")
                    self.set_controls_enabled(False)
                # Mettre à jour le Workspace 4 si c'est la caméra active
                if camera_id == self.active_camera_id and hasattr(self, 'workspace_4_camera_status_label'):
                    QTimer.singleShot(100, lambda: self.update_workspace_4_camera_status(camera_id))
                    QTimer.singleShot(100, lambda: self.update_workspace_4_slider_status(camera_id))
                return
            
            # Réinitialiser le flag pour cette nouvelle connexion
            cam_data.initial_values_received = False
            
            # Se connecter au WebSocket de manière asynchrone pour ne pas bloquer l'UI
            QTimer.singleShot(50, lambda: self.connect_websocket(camera_id))
            
            # Charger les gains et shutters supportés de manière asynchrone pour ne pas bloquer l'UI
            # Ces appels sont différés pour éviter de bloquer si la caméra n'est pas accessible
            QTimer.singleShot(100, lambda: self.load_supported_gains(camera_id))
            QTimer.singleShot(200, lambda: self.load_supported_shutters(camera_id))
            QTimer.singleShot(300, lambda: self.load_whitebalance_description(camera_id))
            
            # TEMPORAIRE: Charger aussi les valeurs initiales via GET pour s'assurer qu'on a les bonnes valeurs
            # TODO: Retirer cette ligne une fois que le WebSocket fournit correctement les valeurs initiales
            # Différer aussi load_initial_values pour ne pas bloquer
            QTimer.singleShot(400, lambda: self.load_initial_values(camera_id))
            
            # Mettre à jour l'UI après le chargement des valeurs initiales si c'est la caméra active
            if camera_id == self.active_camera_id:
                QTimer.singleShot(100, lambda: self._update_ui_from_camera_data(cam_data))
            
            # Garder load_initial_values comme fallback après un délai (si WebSocket ne répond pas)
            QTimer.singleShot(2000, lambda: self._fallback_load_initial_values(camera_id))
            
            # Mettre à jour l'état
            cam_data.connected = True
            
            # Mettre à jour le StateStore avec l'état de connexion
            self.state_store.update_cam(camera_id, connected=True)
            
            # Synchroniser les positions du slider via API (fallback si WebSocket n'est pas encore connecté)
            # Cela garantit que les valeurs initiales sont chargées même si le WebSocket n'est pas encore prêt
            slider_controller = self.slider_controllers.get(camera_id)
            if slider_controller and slider_controller.is_configured():
                # Synchroniser les positions du slider après un court délai pour laisser le temps à la connexion de s'établir
                # Envoyer un snapshot mis à jour après la synchronisation pour inclure les valeurs du slider
                def sync_and_broadcast():
                    # Utiliser sync_slider_positions_from_api mais pour la bonne caméra
                    cam_data = self.cameras[camera_id]
                    if slider_controller and slider_controller.is_configured():
                        try:
                            slider_status = slider_controller.get_status(silent=True)
                            if slider_status:
                                data = {
                                    'pan': {'steps': cam_data.slider_pan_steps, 'normalized': slider_status.get('pan', 0.0)},
                                    'tilt': {'steps': cam_data.slider_tilt_steps, 'normalized': slider_status.get('tilt', 0.0)},
                                    'zoom': {'steps': cam_data.slider_zoom_steps, 'normalized': slider_status.get('zoom', 0.0)},
                                    'slide': {'steps': cam_data.slider_slide_steps, 'normalized': slider_status.get('slide', 0.0)}
                                }
                                self.on_slider_position_update(data, camera_id=camera_id)
                        except Exception as e:
                            logger.error(f"Erreur lors de la synchronisation des positions du slider: {e}")
                    # Envoyer un snapshot mis à jour après un court délai
                    QTimer.singleShot(200, lambda: self.companion_server.broadcast_snapshot())
                QTimer.singleShot(500, sync_and_broadcast)
            
            # Démarrer le WebSocket du slider si configuré
            if cam_data.slider_ip:
                try:
                    # Créer un callback qui passe le camera_id
                    def position_update_callback(data):
                        self.on_slider_position_update(data, camera_id=camera_id)
                    
                    def connection_status_callback(connected: bool, message: str):
                        """Callback pour le statut de connexion du slider."""
                        cam_data.slider_connecting = False
                        if cam_data.slider_websocket_client:
                            cam_data.slider_websocket_client.connected = connected
                        # Mettre à jour l'affichage du Workspace 4 si nécessaire
                        if camera_id == self.active_camera_id and hasattr(self, 'workspace_4_slider_status_label'):
                            QTimer.singleShot(100, lambda: self.update_workspace_4_slider_status(camera_id))
                    
                    slider_ws_client = SliderWebSocketClient(
                        slider_ip=cam_data.slider_ip,
                        on_position_update_callback=position_update_callback,
                        on_connection_status_callback=connection_status_callback,
                        auto_reconnect_enabled=getattr(cam_data, 'slider_auto_reconnect_enabled', True)
                    )
                    cam_data.slider_connecting = True
                    slider_ws_client.start()
                    cam_data.slider_websocket_client = slider_ws_client
                    logger.info(f"WebSocket slider démarré pour caméra {camera_id}")
                    
                    # Envoyer un snapshot mis à jour après un court délai pour inclure les valeurs du slider
                    # Cela garantit que Companion reçoit les valeurs même si le WebSocket n'a pas encore envoyé de données
                    QTimer.singleShot(1000, lambda: self.companion_server.broadcast_snapshot())
                except Exception as e:
                    logger.error(f"Erreur lors du démarrage du WebSocket slider: {e}")
                    cam_data.slider_connecting = False
            
            # Mettre à jour l'UI seulement si c'est la caméra active
            if camera_id == self.active_camera_id:
                self.status_label.setText(f"✓ Caméra {camera_id} - Connectée à {cam_data.url}")
                self.status_label.setStyleSheet("color: #0f0;")
                # Activer tous les contrôles
                self.set_controls_enabled(True)
                # Synchronisation initiale via HTTP (fallback si WebSocket pas encore connecté)
                # Envoyer un snapshot mis à jour après la synchronisation pour inclure les valeurs du slider
                def sync_and_broadcast():
                    self.sync_slider_positions_from_api(self.active_camera_id)
                    # Envoyer un snapshot mis à jour après un court délai pour inclure les valeurs synchronisées
                    QTimer.singleShot(200, lambda: self.companion_server.broadcast_snapshot())
                QTimer.singleShot(500, sync_and_broadcast)
            
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
            # Si c'est la caméra active, arrêter le LFO
            if camera_id == self.active_camera_id:
                self.stop_lfo()
            
            # Arrêter le WebSocket de la caméra
            if cam_data.websocket_client:
                cam_data.websocket_client.stop()
                cam_data.websocket_client = None
            
            # Arrêter le WebSocket du slider
            if cam_data.slider_websocket_client:
                cam_data.slider_websocket_client.stop()
                cam_data.slider_websocket_client = None
            
            # Détruire le contrôleur
            cam_data.controller = None
            
            # Mettre à jour l'état
            cam_data.connected = False
            cam_data.connecting = False  # Arrêter les tentatives de connexion
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
        """Gère les événements clavier pour contrôler pan/tilt, focus, zoom et slide."""
        cam_data = self.get_active_camera_data()
        camera_id = self.active_camera_id
        slider_controller = self.slider_controllers.get(camera_id)
        
        # Préparer les variables pour les raccourcis presets (compatible AZERTY/QWERTY)
        text = event.text()
        has_shift = bool(event.modifiers() & Qt.ShiftModifier)
        
        # Flèches pour pan/tilt - traiter en premier
        if event.key() == Qt.Key_Up:
            # Tilt positif (haut)
            self.active_arrow_keys.add('up')
            event.accept()
            # Envoyer immédiatement les commandes et démarrer la répétition
            self._send_joystick_keyboard_commands()
            self._start_joystick_key_repeat()
            return
        elif event.key() == Qt.Key_Down:
            # Tilt négatif (bas)
            self.active_arrow_keys.add('down')
            event.accept()
            # Envoyer immédiatement les commandes et démarrer la répétition
            self._send_joystick_keyboard_commands()
            self._start_joystick_key_repeat()
            return
        elif event.key() == Qt.Key_Right:
            # Pan positif (droite)
            self.active_arrow_keys.add('right')
            event.accept()
            # Envoyer immédiatement les commandes et démarrer la répétition
            self._send_joystick_keyboard_commands()
            self._start_joystick_key_repeat()
            return
        elif event.key() == Qt.Key_Left:
            # Pan négatif (gauche)
            self.active_arrow_keys.add('left')
            event.accept()
            # Envoyer immédiatement les commandes et démarrer la répétition
            self._send_joystick_keyboard_commands()
            self._start_joystick_key_repeat()
            return
        # R et T pour focus
        elif event.key() == Qt.Key_R:
            # Focus diminuer
            if cam_data.connected and cam_data.controller:
                self._stop_key_repeat()
                self._adjust_focus_precise_increment(-0.001)
                self._start_key_repeat('down')
            event.accept()
        elif event.key() == Qt.Key_T:
            # Focus augmenter
            if cam_data.connected and cam_data.controller:
                self._stop_key_repeat()
                self._adjust_focus_precise_increment(0.001)
                self._start_key_repeat('up')
            event.accept()
        # M et P pour zoom
        elif event.key() == Qt.Key_M:
            # Zoom augmenter
            self.active_arrow_keys.add('m')
            event.accept()
            # Envoyer immédiatement les commandes et démarrer la répétition
            self._send_joystick_keyboard_commands()
            self._start_joystick_key_repeat()
            return
        elif event.key() == Qt.Key_P:
            # Zoom diminuer
            self.active_arrow_keys.add('p')
            event.accept()
            # Envoyer immédiatement les commandes et démarrer la répétition
            self._send_joystick_keyboard_commands()
            self._start_joystick_key_repeat()
            return
        # B et N pour slide
        elif event.key() == Qt.Key_B:
            # Slide augmenter
            self.active_arrow_keys.add('b')
            event.accept()
            # Envoyer immédiatement les commandes et démarrer la répétition
            self._send_joystick_keyboard_commands()
            self._start_joystick_key_repeat()
            return
        elif event.key() == Qt.Key_N:
            # Slide diminuer
            self.active_arrow_keys.add('n')
            event.accept()
            # Envoyer immédiatement les commandes et démarrer la répétition
            self._send_joystick_keyboard_commands()
            self._start_joystick_key_repeat()
            return
        # Préparer les variables pour les raccourcis
        has_command = bool(event.modifiers() & (Qt.MetaModifier | Qt.ControlModifier))
        
        # Raccourcis pour les séquences (Command + &é"'(§è!çà) - PRIORITÉ 1
        if has_command:
            if text == '&':
                self.send_sequence(0)  # Séquence 1 (index 0)
                event.accept()
            elif text == 'é':
                self.send_sequence(1)  # Séquence 2 (index 1)
                event.accept()
            elif text == '"':
                self.send_sequence(2)  # Séquence 3 (index 2)
                event.accept()
            elif text == "'":
                self.send_sequence(3)  # Séquence 4 (index 3)
                event.accept()
            elif text == '(':
                self.send_sequence(4)  # Séquence 5 (index 4)
                event.accept()
            elif text == '§':
                self.send_sequence(5)  # Séquence 6 (index 5)
                event.accept()
            elif text == 'è':
                self.send_sequence(6)  # Séquence 7 (index 6)
                event.accept()
            elif text == '!':
                self.send_sequence(7)  # Séquence 8 (index 7)
                event.accept()
            elif text == 'ç':
                self.send_sequence(8)  # Séquence 9 (index 8)
                event.accept()
            elif text == 'à':
                self.send_sequence(9)  # Séquence 10 (index 9)
                event.accept()
            else:
                # Command pressé mais pas une touche de séquence, on ne fait rien
                event.accept()
        # Raccourcis pour les presets
        # Sur AZERTY : &é"'(§è!çà sont SANS Shift, 1234567890 sont AVEC Shift
        # Avec Shift : &é"'(§è!çà pour sauvegarder les presets 1-10
        elif has_shift:
            if text == '&':
                self.save_preset(1)
                event.accept()
            elif text == 'é':
                self.save_preset(2)
                event.accept()
            elif text == '"':
                self.save_preset(3)
                event.accept()
            elif text == "'":
                self.save_preset(4)
                event.accept()
            elif text == '(':
                self.save_preset(5)
                event.accept()
            elif text == '§':
                self.save_preset(6)
                event.accept()
            elif text == 'è':
                self.save_preset(7)
                event.accept()
            elif text == '!':
                self.save_preset(8)
                event.accept()
            elif text == 'ç':
                self.save_preset(9)
                event.accept()
            elif text == 'à':
                self.save_preset(10)
                event.accept()
            # Avec Shift : 1234567890 pour sauvegarder les presets 1-10 (alternative)
            elif text == '1':
                self.save_preset(1)
                event.accept()
            elif text == '2':
                self.save_preset(2)
                event.accept()
            elif text == '3':
                self.save_preset(3)
                event.accept()
            elif text == '4':
                self.save_preset(4)
                event.accept()
            elif text == '5':
                self.save_preset(5)
                event.accept()
            elif text == '6':
                self.save_preset(6)
                event.accept()
            elif text == '7':
                self.save_preset(7)
                event.accept()
            elif text == '8':
                self.save_preset(8)
                event.accept()
            elif text == '9':
                self.save_preset(9)
                event.accept()
            elif text == '0':
                self.save_preset(10)
                event.accept()
        # Sans Shift : &é"'(§è!çà pour rappeler les presets 1-10
        elif text == '&':
            self.recall_preset(1)
            event.accept()
        elif text == 'é':
            self.recall_preset(2)
            event.accept()
        elif text == '"':
            self.recall_preset(3)
            event.accept()
        elif text == "'":
            self.recall_preset(4)
            event.accept()
        elif text == '(':
            self.recall_preset(5)
            event.accept()
        elif text == '§':
            self.recall_preset(6)
            event.accept()
        elif text == 'è':
            self.recall_preset(7)
            event.accept()
        elif text == '!':
            self.recall_preset(8)
            event.accept()
        elif text == 'ç':
            self.recall_preset(9)
            event.accept()
        elif text == 'à':
            self.recall_preset(10)
            event.accept()
        # Touche S pour arrêter la séquence
        elif event.key() == Qt.Key_S:
            self.stop_sequence()
            event.accept()
            return
        else:
            self._stop_key_repeat()
            super().keyPressEvent(event)
            return
    
    def keyReleaseEvent(self, event: QKeyEvent):
        """Arrête la répétition quand la touche est relâchée."""
        # Gérer le relâchement des flèches pan/tilt
        if event.key() == Qt.Key_Up:
            self.active_arrow_keys.discard('up')
            event.accept()
        elif event.key() == Qt.Key_Down:
            self.active_arrow_keys.discard('down')
            event.accept()
        elif event.key() == Qt.Key_Right:
            self.active_arrow_keys.discard('right')
            event.accept()
        elif event.key() == Qt.Key_Left:
            self.active_arrow_keys.discard('left')
            event.accept()
        # Gérer le relâchement de R et T (focus)
        elif event.key() == Qt.Key_R or event.key() == Qt.Key_T:
            self._stop_key_repeat()
            event.accept()
        # Gérer le relâchement de M et P (zoom)
        elif event.key() == Qt.Key_M:
            self.active_arrow_keys.discard('m')
            event.accept()
        elif event.key() == Qt.Key_P:
            self.active_arrow_keys.discard('p')
            event.accept()
        # Gérer le relâchement de B et N (slide)
        elif event.key() == Qt.Key_B:
            self.active_arrow_keys.discard('b')
            event.accept()
        elif event.key() == Qt.Key_N:
            self.active_arrow_keys.discard('n')
            event.accept()
        else:
            super().keyReleaseEvent(event)
            return
        
        # Recalculer et envoyer les commandes après relâchement
        self._send_joystick_keyboard_commands()
        
        # Arrêter la répétition si toutes les touches sont relâchées
        if not self.active_arrow_keys:
            self._stop_joystick_key_repeat()
        else:
            # Continuer la répétition avec les nouvelles valeurs
            self._start_joystick_key_repeat()
    
    def _send_joystick_keyboard_commands(self):
        """Calcule et envoie les commandes joystick basées sur les touches actuellement pressées."""
        camera_id = self.active_camera_id
        slider_controller = self.slider_controllers.get(camera_id)
        
        if not slider_controller or not slider_controller.is_configured():
            return
        
        # Calculer les valeurs pan/tilt
        if 'up' in self.active_arrow_keys:
            tilt_value = self.arrow_keys_speed
        elif 'down' in self.active_arrow_keys:
            tilt_value = -self.arrow_keys_speed
        else:
            tilt_value = 0.0
        
        if 'right' in self.active_arrow_keys:
            pan_value = self.arrow_keys_speed
        elif 'left' in self.active_arrow_keys:
            pan_value = -self.arrow_keys_speed
        else:
            pan_value = 0.0
        
        # Calculer les valeurs zoom/slide
        if 'm' in self.active_arrow_keys:
            zoom_value = -self.arrow_keys_speed  # M = zoom diminuer
        elif 'p' in self.active_arrow_keys:
            zoom_value = self.arrow_keys_speed  # P = zoom augmenter
        else:
            zoom_value = 0.0
        
        if 'b' in self.active_arrow_keys:
            slide_value = -self.arrow_keys_speed  # B = slide diminuer
        elif 'n' in self.active_arrow_keys:
            slide_value = self.arrow_keys_speed  # N = slide augmenter
        else:
            slide_value = 0.0
        
        # Mettre à jour les axes récemment utilisés
        if 'left' in self.active_arrow_keys or 'right' in self.active_arrow_keys or pan_value != 0.0:
            self.recently_used_axes.add('pan')
        if 'up' in self.active_arrow_keys or 'down' in self.active_arrow_keys or tilt_value != 0.0:
            self.recently_used_axes.add('tilt')
        if 'm' in self.active_arrow_keys or 'p' in self.active_arrow_keys or zoom_value != 0.0:
            self.recently_used_axes.add('zoom')
        if 'b' in self.active_arrow_keys or 'n' in self.active_arrow_keys or slide_value != 0.0:
            self.recently_used_axes.add('slide')
        
        # Envoyer les commandes joystick
        # Toujours envoyer 0.0 pour les axes récemment utilisés, même si toutes les touches sont relâchées
        pan_to_send = pan_value if ('left' in self.active_arrow_keys or 'right' in self.active_arrow_keys or 'pan' in self.recently_used_axes) else None
        tilt_to_send = tilt_value if ('up' in self.active_arrow_keys or 'down' in self.active_arrow_keys or 'tilt' in self.recently_used_axes) else None
        zoom_to_send = zoom_value if ('m' in self.active_arrow_keys or 'p' in self.active_arrow_keys or 'zoom' in self.recently_used_axes) else None
        slide_to_send = slide_value if ('b' in self.active_arrow_keys or 'n' in self.active_arrow_keys or 'slide' in self.recently_used_axes) else None
        
        # Retirer les axes de recently_used_axes si toutes les touches correspondantes sont relâchées ET la valeur est 0.0
        # (pour éviter d'envoyer 0.0 indéfiniment)
        if pan_to_send == 0.0 and 'left' not in self.active_arrow_keys and 'right' not in self.active_arrow_keys:
            self.recently_used_axes.discard('pan')
        if tilt_to_send == 0.0 and 'up' not in self.active_arrow_keys and 'down' not in self.active_arrow_keys:
            self.recently_used_axes.discard('tilt')
        if zoom_to_send == 0.0 and 'm' not in self.active_arrow_keys and 'p' not in self.active_arrow_keys:
            self.recently_used_axes.discard('zoom')
        if slide_to_send == 0.0 and 'b' not in self.active_arrow_keys and 'n' not in self.active_arrow_keys:
            self.recently_used_axes.discard('slide')
        
        slider_controller.send_joy_command(
            pan=pan_to_send,
            tilt=tilt_to_send,
            zoom=zoom_to_send,
            slide=slide_to_send,
            silent=True
        )
        
        # Mettre à jour visuellement le joystick pour pan/tilt
        self.update_joystick_visual_position(pan_value, tilt_value)
    
    def _start_joystick_key_repeat(self):
        """Démarre la répétition automatique des commandes joystick."""
        # Arrêter toute répétition en cours
        self._stop_joystick_key_repeat()
        
        # Délai initial de 300ms, puis répétition toutes les 50ms
        def repeat_action():
            if self.active_arrow_keys:  # Vérifier qu'il y a encore des touches pressées
                self._send_joystick_keyboard_commands()
        
        # Premier délai plus long (300ms), puis répétition rapide (50ms)
        QTimer.singleShot(300, lambda: self._continue_joystick_key_repeat(repeat_action))
    
    def _continue_joystick_key_repeat(self, action):
        """Continue la répétition avec un timer récurrent."""
        if not self.active_arrow_keys:
            return
        
        # Exécuter l'action immédiatement
        action()
        
        # Créer le timer s'il n'existe pas
        if not hasattr(self, 'joystick_key_repeat_timer') or self.joystick_key_repeat_timer is None:
            self.joystick_key_repeat_timer = QTimer()
            self.joystick_key_repeat_timer.setSingleShot(False)  # Timer récurrent
            self.joystick_key_repeat_timer.timeout.connect(action)
        
        # Démarrer ou redémarrer le timer
        if not self.joystick_key_repeat_timer.isActive():
            self.joystick_key_repeat_timer.start(50)  # Répéter toutes les 50ms
    
    def _stop_joystick_key_repeat(self):
        """Arrête la répétition automatique des commandes joystick."""
        if hasattr(self, 'joystick_key_repeat_timer') and self.joystick_key_repeat_timer:
            self.joystick_key_repeat_timer.stop()
            self.joystick_key_repeat_timer = None
    
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
        
        # White Balance
        self.whitebalance_plus_btn.setEnabled(enabled)
        self.whitebalance_minus_btn.setEnabled(enabled)
        self.whitebalance_auto_btn.setEnabled(enabled)
        
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
            on_connection_status_callback=on_websocket_status,
            auto_reconnect_enabled=getattr(cam_data, 'auto_reconnect_enabled', True)
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
            # Stocker l'aperture stop pour Companion (au lieu de la valeur normalisée)
            if 'apertureStop' in data:
                cam_data.iris_aperture_stop = float(data['apertureStop'])
                update_kwargs['iris'] = cam_data.iris_aperture_stop
            elif cam_data.iris_aperture_stop is not None:
                # Si pas d'aperture stop dans les données mais qu'on en a déjà une, la garder
                update_kwargs['iris'] = cam_data.iris_aperture_stop
            # Stocker l'aperture number pour les ajustements relatifs
            if 'apertureNumber' in data:
                cam_data.iris_aperture_number = int(data['apertureNumber'])
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
        elif param_name == 'whiteBalance':
            if 'whiteBalance' in data:
                value = int(data['whiteBalance'])
                cam_data.whitebalance_actual_value = value
                update_kwargs['whiteBalance'] = value
                if camera_id == self.active_camera_id:
                    self.signals.whitebalance_changed.emit(value)
        elif param_name == 'whiteBalanceTint':
            # #region agent log
            try:
                import json
                import time
                with open('/Users/laurenteyen/Documents/cursor/FocusBMrestAPI1/.cursor/debug.log', 'a') as f:
                    f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"B","location":"focus_ui_pyside6_standalone.py:6244","message":"whiteBalanceTint param received","data":{"data":data,"camera_id":camera_id,"active_camera_id":self.active_camera_id},"timestamp":int(time.time()*1000)})+'\n')
            except: pass
            # #endregion
            if 'whiteBalanceTint' in data:
                value = int(data['whiteBalanceTint'])
                # #region agent log
                try:
                    import json
                    import time
                    with open('/Users/laurenteyen/Documents/cursor/FocusBMrestAPI1/.cursor/debug.log', 'a') as f:
                        f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"B","location":"focus_ui_pyside6_standalone.py:6250","message":"whiteBalanceTint value extracted","data":{"value":value},"timestamp":int(time.time()*1000)})+'\n')
                except: pass
                # #endregion
                cam_data.tint_actual_value = value
                update_kwargs['tint'] = value
                if camera_id == self.active_camera_id:
                    # #region agent log
                    try:
                        import json
                        import time
                        with open('/Users/laurenteyen/Documents/cursor/FocusBMrestAPI1/.cursor/debug.log', 'a') as f:
                            f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"B","location":"focus_ui_pyside6_standalone.py:6255","message":"emitting tint_changed signal","data":{"value":value},"timestamp":int(time.time()*1000)})+'\n')
                    except: pass
                    # #endregion
                    self.signals.tint_changed.emit(value)
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
            # zoom = focale en mm (lue depuis l'API)
            if 'focalLength' in data:
                focal_length = data.get('focalLength')
                if focal_length is not None:
                    update_kwargs['zoom'] = float(focal_length)
            # zoom_motor = position normalisée du moteur zoom du slider (0.0-1.0)
            # Note: zoom_motor est mis à jour via on_slider_position_update pour slider_zoom
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
                        
                        # Mettre à jour l'affichage de la distance
                        if hasattr(self, 'focus_distance_label') and self.focus_distance_label:
                            # Obtenir le zoom actuel pour la conversion (valeur du slider pour la LUT 3D)
                            zoom_normalised = None
                            cam_data = self.get_active_camera_data()
                            if cam_data and hasattr(cam_data, 'slider_zoom_value') and cam_data.slider_zoom_value is not None:
                                zoom_normalised = cam_data.slider_zoom_value  # Valeur normalisée du slider
                            
                            distance_meters = self.focus_lut.normalised_to_distance_with_zoom(value, zoom_normalised)
                            if distance_meters is not None:
                                self.focus_distance_label.setText(f"Distance: {distance_meters:.2f} m")
                            else:
                                self.focus_distance_label.setText("Distance: -- m")
            
            # Iris
            iris_data = cam_data.controller.get_iris()
            if iris_data:
                if 'normalised' in iris_data:
                    value = float(iris_data['normalised'])
                    cam_data.iris_actual_value = value
                    cam_data.iris_sent_value = value
                # Stocker l'aperture stop pour Companion
                if 'apertureStop' in iris_data:
                    cam_data.iris_aperture_stop = float(iris_data['apertureStop'])
                # Stocker l'aperture number pour les ajustements relatifs
                if 'apertureNumber' in iris_data:
                    cam_data.iris_aperture_number = int(iris_data['apertureNumber'])
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
            
            # White Balance
            whitebalance_value = cam_data.controller.get_whitebalance()
            if whitebalance_value is not None:
                cam_data.whitebalance_actual_value = whitebalance_value
                cam_data.whitebalance_sent_value = whitebalance_value
                if camera_id == self.active_camera_id:
                    self.on_whitebalance_changed(whitebalance_value)
            
            # Tint
            tint_value = cam_data.controller.get_whitebalance_tint()
            # #region agent log
            try:
                import json
                import time
                with open('/Users/laurenteyen/Documents/cursor/FocusBMrestAPI1/.cursor/debug.log', 'a') as f:
                    f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"C","location":"focus_ui_pyside6_standalone.py:6437","message":"load_initial_values tint","data":{"tint_value":tint_value,"camera_id":camera_id,"active_camera_id":self.active_camera_id},"timestamp":int(time.time()*1000)})+'\n')
            except: pass
            # #endregion
            if tint_value is not None:
                cam_data.tint_actual_value = tint_value
                cam_data.tint_sent_value = tint_value
                if camera_id == self.active_camera_id:
                    self.on_tint_changed(tint_value)
            
            # Zoom
            # IMPORTANT: get_zoom() lit depuis l'API caméra (GET /lens/zoom), pas depuis le slider
            zoom_data = cam_data.controller.get_zoom()
            if zoom_data:
                # Stocker la valeur normalisée depuis l'API caméra dans CameraData
                # Cette valeur sera utilisée pour la conversion focus->distance via la LUT 3D
                if 'normalised' in zoom_data:
                    cam_data.zoom_actual_value = float(zoom_data['normalised'])  # Valeur normalisée API caméra
                    cam_data.zoom_sent_value = float(zoom_data['normalised'])
                # Mettre à jour le StateStore avec la focale en mm
                if 'focalLength' in zoom_data:
                    focal_length = zoom_data.get('focalLength')
                    if focal_length is not None:
                        self.state_store.update_cam(camera_id, zoom=float(focal_length))
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
            # Envoyer l'aperture stop au lieu de la valeur normalisée pour Companion
            if cam_data.iris_aperture_stop is not None:
                update_kwargs['iris'] = cam_data.iris_aperture_stop
            elif cam_data.iris_actual_value is not None:
                # Fallback si pas d'aperture stop disponible (ne devrait pas arriver)
                update_kwargs['iris'] = cam_data.iris_actual_value
            if cam_data.gain_actual_value is not None:
                update_kwargs['gain'] = cam_data.gain_actual_value
            if cam_data.shutter_actual_value is not None:
                update_kwargs['shutter'] = cam_data.shutter_actual_value
            if cam_data.whitebalance_actual_value is not None:
                update_kwargs['whiteBalance'] = cam_data.whitebalance_actual_value
            if cam_data.tint_actual_value is not None:
                update_kwargs['tint'] = cam_data.tint_actual_value
            # Ajouter les valeurs des sliders (elles sont initialisées à 0.0, donc toujours présentes)
            # Les valeurs seront mises à jour via WebSocket ou sync_slider_positions_from_api
            update_kwargs['slider_pan'] = cam_data.slider_pan_value
            update_kwargs['slider_tilt'] = cam_data.slider_tilt_value
            update_kwargs['zoom_motor'] = cam_data.slider_zoom_value  # Position moteur zoom du slider (0.0-1.0)
            update_kwargs['slider_slide'] = cam_data.slider_slide_value
            if update_kwargs:
                self.state_store.update_cam(camera_id, **update_kwargs)
            
            # Marquer que les valeurs initiales ont été chargées via GET
            cam_data.initial_values_received = True
            logger.info(f"Valeurs initiales chargées pour la caméra {camera_id}: focus={cam_data.focus_actual_value}, iris={cam_data.iris_actual_value}, gain={cam_data.gain_actual_value}, shutter={cam_data.shutter_actual_value}, whitebalance={cam_data.whitebalance_actual_value}")
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
        
        # Synchroniser automatiquement le D du LFO avec le focus
        self.sync_lfo_distance_from_focus(value_rounded)
        
        # Mettre à jour l'affichage de la distance même si la synchronisation LFO est désactivée
        if hasattr(self, 'focus_distance_label') and self.focus_distance_label:
            # Obtenir le zoom actuel pour la conversion (valeur du slider pour la LUT 3D)
            zoom_normalised = None
            cam_data = self.get_active_camera_data()
            if cam_data and hasattr(cam_data, 'slider_zoom_value') and cam_data.slider_zoom_value is not None:
                zoom_normalised = cam_data.slider_zoom_value  # Valeur normalisée du slider
            
            distance_meters = self.focus_lut.normalised_to_distance_with_zoom(value_rounded, zoom_normalised)
            if distance_meters is not None:
                self.focus_distance_label.setText(f"Distance: {distance_meters:.2f} m")
            else:
                self.focus_distance_label.setText("Distance: -- m")
    
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
    
    def on_pan_tilt_matrix_changed(self, pan: float, tilt: float):
        """Appelé quand la position de la matrice XY pan/tilt change."""
        # Marquer que l'utilisateur touche les contrôles pan/tilt
        self.slider_user_touching['pan'] = True
        self.slider_user_touching['tilt'] = True
        self.slider_command_sent['pan'] = False
        self.slider_command_sent['tilt'] = False
        
        # Mettre à jour les valeurs dans CameraData
        cam_data = self.get_active_camera_data()
        cam_data.slider_pan_value = pan
        cam_data.slider_tilt_value = tilt
        
        # Mettre à jour le StateStore pour Companion
        self.state_store.update_cam(self.active_camera_id, slider_pan=pan, slider_tilt=tilt)
        
        # Envoyer les commandes au slider (pan et tilt simultanément)
        self._send_slider_command('pan', pan)
        self._send_slider_command('tilt', tilt)
        
        # Marquer que les commandes ont été envoyées
        self.slider_command_sent['pan'] = True
        self.slider_command_sent['tilt'] = True
        
        # Réinitialiser les flags après un court délai pour permettre les mises à jour continues
        QTimer.singleShot(100, lambda: self._reset_pan_tilt_touching_flags())
    
    def _reset_pan_tilt_touching_flags(self):
        """Réinitialise les flags de toucher pour pan/tilt après un délai."""
        # Ne réinitialiser que si l'utilisateur ne touche plus (vérifier via le widget)
        if hasattr(self, 'pan_tilt_panel') and hasattr(self.pan_tilt_panel, 'xy_matrix'):
            if not self.pan_tilt_panel.xy_matrix.dragging:
                self.slider_user_touching['pan'] = False
                self.slider_user_touching['tilt'] = False
                self.slider_command_sent['pan'] = False
                self.slider_command_sent['tilt'] = False
    
    def on_slider_pressed(self, axis_name: str):
        """Appelé quand on appuie sur un slider (pan, tilt, slide, zoom)."""
        self.slider_user_touching[axis_name] = True
        self.slider_command_sent[axis_name] = False  # Réinitialiser le flag pour cette interaction
    
    def on_slider_released(self, axis_name: str):
        """Appelé quand on relâche un slider (pan, tilt, slide, zoom)."""
        # Si aucune commande n'a été envoyée pendant l'interaction (clic court/jump),
        # envoyer la valeur actuelle du slider
        if not self.slider_command_sent.get(axis_name, False):
            # Récupérer la valeur actuelle du slider
            if axis_name == 'pan' and hasattr(self, 'pan_tilt_panel') and hasattr(self.pan_tilt_panel, 'xy_matrix'):
                current_value = int(self.pan_tilt_panel.xy_matrix.pan_value * 1000)
            elif axis_name == 'tilt' and hasattr(self, 'pan_tilt_panel') and hasattr(self.pan_tilt_panel, 'xy_matrix'):
                current_value = int(self.pan_tilt_panel.xy_matrix.tilt_value * 1000)
            elif axis_name == 'zoom' and hasattr(self, 'zoom_motor_panel') and hasattr(self.zoom_motor_panel, 'slider'):
                current_value = self.zoom_motor_panel.slider.value()
            elif axis_name == 'slide' and hasattr(self, 'slide_panel') and hasattr(self.slide_panel, 'slider'):
                current_value = self.slide_panel.slider.value()
            else:
                current_value = None
            
            if current_value is not None:
                normalized_value = current_value / 1000.0
                # Mettre à jour la valeur dans CameraData
                cam_data = self.get_active_camera_data()
                if axis_name == 'pan':
                    cam_data.slider_pan_value = normalized_value
                elif axis_name == 'tilt':
                    cam_data.slider_tilt_value = normalized_value
                elif axis_name == 'zoom':
                    cam_data.slider_zoom_value = normalized_value
                elif axis_name == 'slide':
                    cam_data.slider_slide_value = normalized_value
                
                # Envoyer la commande
                self._send_slider_command(axis_name, normalized_value)
        
        self.slider_user_touching[axis_name] = False
        self.slider_command_sent[axis_name] = False  # Réinitialiser pour la prochaine interaction
    
    def on_slider_value_changed(self, axis_name: str, value: int):
        """Appelé quand la valeur d'un slider change (pan, tilt, slide, zoom)."""
        # Envoyer SEULEMENT si l'utilisateur touche physiquement le slider
        if not self.slider_user_touching[axis_name]:
            return
        
        # Convertir la valeur du slider (0-1000) en valeur normalisée (0.0-1.0)
        normalized_value = value / 1000.0
        
        # Mettre à jour la valeur dans CameraData
        cam_data = self.get_active_camera_data()
        if axis_name == 'pan':
            cam_data.slider_pan_value = normalized_value
        elif axis_name == 'tilt':
            cam_data.slider_tilt_value = normalized_value
        elif axis_name == 'zoom':
            cam_data.slider_zoom_value = normalized_value
        elif axis_name == 'slide':
            cam_data.slider_slide_value = normalized_value
        
        # Mettre à jour le StateStore pour Companion
        update_kwargs = {}
        if axis_name == 'pan':
            update_kwargs['slider_pan'] = normalized_value
        elif axis_name == 'tilt':
            update_kwargs['slider_tilt'] = normalized_value
        elif axis_name == 'zoom':
            update_kwargs['zoom_motor'] = normalized_value
        elif axis_name == 'slide':
            update_kwargs['slider_slide'] = normalized_value
        if update_kwargs:
            self.state_store.update_cam(self.active_camera_id, **update_kwargs)
        
        # Envoyer la commande au slider (pas besoin de mettre à jour l'affichage, on a supprimé les labels)
        self._send_slider_command(axis_name, normalized_value)
        # Marquer qu'une commande a été envoyée pendant cette interaction
        self.slider_command_sent[axis_name] = True
    
    def _send_slider_command(self, axis_name: str, value: float):
        """Envoie une commande au slider pour déplacer un axe."""
        cam_data = self.get_active_camera_data()
        slider_controller = self.slider_controllers.get(self.active_camera_id)
        
        if not slider_controller or not slider_controller.is_configured():
            return  # Slider non configuré
        
        # Mapper les noms d'axes aux méthodes du SliderController
        axis_map = {
            'pan': 'move_pan',
            'tilt': 'move_tilt',
            'slide': 'move_slide',
            'zoom': 'move_zoom'
        }
        
        if axis_name in axis_map:
            method = getattr(slider_controller, axis_map[axis_name])
            method(value, silent=True)
    
    def increment_slider_pan(self, camera_id: Optional[int] = None):
        """Incrémente le pan du slider de 1% (0.01) pour la caméra spécifiée ou active."""
        if camera_id is not None and camera_id is not False and isinstance(camera_id, int):
            if camera_id < 1 or camera_id > 8:
                logger.error(f"ID de caméra invalide: {camera_id}")
                return
            cam_data = self.cameras[camera_id]
            actual_camera_id = camera_id
        else:
            cam_data = self.get_active_camera_data()
            actual_camera_id = self.active_camera_id
        
        if not cam_data.connected:
            return
        
        # Vérifier que le slider est configuré
        slider_controller = self.slider_controllers.get(actual_camera_id)
        if not slider_controller or not slider_controller.is_configured():
            return
        
        # Incrémenter de 1% (0.01) et clamper entre 0.0 et 1.0
        current_value = cam_data.slider_pan_value
        new_value = min(1.0, current_value + 0.01)
        cam_data.slider_pan_value = new_value
        
        # Mettre à jour le StateStore
        self.state_store.update_cam(actual_camera_id, slider_pan=new_value)
        
        # Envoyer la commande directement au slider
        slider_controller.move_pan(new_value, silent=True)
    
    def decrement_slider_pan(self, camera_id: Optional[int] = None):
        """Décrémente le pan du slider de 1% (0.01) pour la caméra spécifiée ou active."""
        if camera_id is not None and camera_id is not False and isinstance(camera_id, int):
            if camera_id < 1 or camera_id > 8:
                logger.error(f"ID de caméra invalide: {camera_id}")
                return
            cam_data = self.cameras[camera_id]
            actual_camera_id = camera_id
        else:
            cam_data = self.get_active_camera_data()
            actual_camera_id = self.active_camera_id
        
        if not cam_data.connected:
            return
        
        slider_controller = self.slider_controllers.get(actual_camera_id)
        if not slider_controller or not slider_controller.is_configured():
            return
        
        current_value = cam_data.slider_pan_value
        new_value = max(0.0, current_value - 0.01)
        cam_data.slider_pan_value = new_value
        
        self.state_store.update_cam(actual_camera_id, slider_pan=new_value)
        slider_controller.move_pan(new_value, silent=True)
    
    def increment_slider_tilt(self, camera_id: Optional[int] = None):
        """Incrémente le tilt du slider de 1% (0.01) pour la caméra spécifiée ou active."""
        if camera_id is not None and camera_id is not False and isinstance(camera_id, int):
            if camera_id < 1 or camera_id > 8:
                logger.error(f"ID de caméra invalide: {camera_id}")
                return
            cam_data = self.cameras[camera_id]
            actual_camera_id = camera_id
        else:
            cam_data = self.get_active_camera_data()
            actual_camera_id = self.active_camera_id
        
        if not cam_data.connected:
            return
        
        slider_controller = self.slider_controllers.get(actual_camera_id)
        if not slider_controller or not slider_controller.is_configured():
            return
        
        current_value = cam_data.slider_tilt_value
        new_value = min(1.0, current_value + 0.01)
        cam_data.slider_tilt_value = new_value
        
        self.state_store.update_cam(actual_camera_id, slider_tilt=new_value)
        slider_controller.move_tilt(new_value, silent=True)
    
    def decrement_slider_tilt(self, camera_id: Optional[int] = None):
        """Décrémente le tilt du slider de 1% (0.01) pour la caméra spécifiée ou active."""
        if camera_id is not None and camera_id is not False and isinstance(camera_id, int):
            if camera_id < 1 or camera_id > 8:
                logger.error(f"ID de caméra invalide: {camera_id}")
                return
            cam_data = self.cameras[camera_id]
            actual_camera_id = camera_id
        else:
            cam_data = self.get_active_camera_data()
            actual_camera_id = self.active_camera_id
        
        if not cam_data.connected:
            return
        
        slider_controller = self.slider_controllers.get(actual_camera_id)
        if not slider_controller or not slider_controller.is_configured():
            return
        
        current_value = cam_data.slider_tilt_value
        new_value = max(0.0, current_value - 0.01)
        cam_data.slider_tilt_value = new_value
        
        self.state_store.update_cam(actual_camera_id, slider_tilt=new_value)
        slider_controller.move_tilt(new_value, silent=True)
    
    def increment_slider_zoom(self, camera_id: Optional[int] = None):
        """Incrémente le zoom du slider de 1% (0.01) pour la caméra spécifiée ou active."""
        if camera_id is not None and camera_id is not False and isinstance(camera_id, int):
            if camera_id < 1 or camera_id > 8:
                logger.error(f"ID de caméra invalide: {camera_id}")
                return
            cam_data = self.cameras[camera_id]
            actual_camera_id = camera_id
        else:
            cam_data = self.get_active_camera_data()
            actual_camera_id = self.active_camera_id
        
        if not cam_data.connected:
            return
        
        slider_controller = self.slider_controllers.get(actual_camera_id)
        if not slider_controller or not slider_controller.is_configured():
            return
        
        current_value = cam_data.slider_zoom_value
        new_value = min(1.0, current_value + 0.01)
        cam_data.slider_zoom_value = new_value
        
        self.state_store.update_cam(actual_camera_id, zoom_motor=new_value)
        slider_controller.move_zoom(new_value, silent=True)
    
    def decrement_slider_zoom(self, camera_id: Optional[int] = None):
        """Décrémente le zoom du slider de 1% (0.01) pour la caméra spécifiée ou active."""
        if camera_id is not None and camera_id is not False and isinstance(camera_id, int):
            if camera_id < 1 or camera_id > 8:
                logger.error(f"ID de caméra invalide: {camera_id}")
                return
            cam_data = self.cameras[camera_id]
            actual_camera_id = camera_id
        else:
            cam_data = self.get_active_camera_data()
            actual_camera_id = self.active_camera_id
        
        if not cam_data.connected:
            return
        
        slider_controller = self.slider_controllers.get(actual_camera_id)
        if not slider_controller or not slider_controller.is_configured():
            return
        
        current_value = cam_data.slider_zoom_value
        new_value = max(0.0, current_value - 0.01)
        cam_data.slider_zoom_value = new_value
        
        self.state_store.update_cam(actual_camera_id, zoom_motor=new_value)
        slider_controller.move_zoom(new_value, silent=True)
    
    def increment_slider_slide(self, camera_id: Optional[int] = None):
        """Incrémente le slide du slider de 1% (0.01) pour la caméra spécifiée ou active."""
        if camera_id is not None and camera_id is not False and isinstance(camera_id, int):
            if camera_id < 1 or camera_id > 8:
                logger.error(f"ID de caméra invalide: {camera_id}")
                return
            cam_data = self.cameras[camera_id]
            actual_camera_id = camera_id
        else:
            cam_data = self.get_active_camera_data()
            actual_camera_id = self.active_camera_id
        
        if not cam_data.connected:
            return
        
        slider_controller = self.slider_controllers.get(actual_camera_id)
        if not slider_controller or not slider_controller.is_configured():
            return
        
        current_value = cam_data.slider_slide_value
        new_value = min(1.0, current_value + 0.01)
        cam_data.slider_slide_value = new_value
        
        self.state_store.update_cam(actual_camera_id, slider_slide=new_value)
        slider_controller.move_slide(new_value, silent=True)
    
    def decrement_slider_slide(self, camera_id: Optional[int] = None):
        """Décrémente le slide du slider de 1% (0.01) pour la caméra spécifiée ou active."""
        if camera_id is not None and camera_id is not False and isinstance(camera_id, int):
            if camera_id < 1 or camera_id > 8:
                logger.error(f"ID de caméra invalide: {camera_id}")
                return
            cam_data = self.cameras[camera_id]
            actual_camera_id = camera_id
        else:
            cam_data = self.get_active_camera_data()
            actual_camera_id = self.active_camera_id
        
        if not cam_data.connected:
            return
        
        slider_controller = self.slider_controllers.get(actual_camera_id)
        if not slider_controller or not slider_controller.is_configured():
            return
        
        current_value = cam_data.slider_slide_value
        new_value = max(0.0, current_value - 0.01)
        cam_data.slider_slide_value = new_value
        
        self.state_store.update_cam(actual_camera_id, slider_slide=new_value)
        slider_controller.move_slide(new_value, silent=True)
    
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
            # Les valeurs iris_value_sent et iris_value_actual ont été supprimées, seul aperture_stop est affiché
        
        # Toujours mettre à jour l'aperture stop si présent
        if 'apertureStop' in data:
            cam_data.iris_aperture_stop = float(data['apertureStop'])
            self.iris_aperture_stop.setText(f"{data['apertureStop']:.2f}")
            # Mettre à jour le StateStore avec l'aperture stop pour Companion
            self.state_store.update_cam(self.active_camera_id, iris=cam_data.iris_aperture_stop)
        
        # Toujours mettre à jour l'aperture number si présent
        if 'apertureNumber' in data:
            cam_data.iris_aperture_number = int(data['apertureNumber'])
    
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
        cam_data = self.get_active_camera_data()
        
        # Mettre à jour la focale dans le panneau zoom motor (en rouge)
        if 'focalLength' in data:
            if hasattr(self, 'zoom_motor_panel') and hasattr(self.zoom_motor_panel, 'focal_length_label'):
                self.zoom_motor_panel.focal_length_label.setText(f"{data['focalLength']} mm")
        
        if 'normalised' in data:
            zoom_value = float(data['normalised'])
            # Mettre à jour la valeur dans CameraData
            # IMPORTANT: Cette valeur vient de l'API caméra (WebSocket ou GET /lens/zoom), pas du slider
            cam_data.zoom_actual_value = zoom_value  # Valeur normalisée API caméra
            cam_data.zoom_sent_value = zoom_value
            
            # Synchroniser automatiquement le D du LFO avec le zoom
            self.sync_lfo_distance_from_zoom(zoom_value)
    
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
        # Réinitialiser le flag connecting quand la connexion est établie ou échouée
        if connected:
            cam_data.connecting = False
        
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
        
        # Mettre à jour le Workspace 4 si c'est la caméra active et que le workspace 4 est visible
        if camera_id == self.active_camera_id and hasattr(self, 'workspace_4_camera_status_label'):
            QTimer.singleShot(100, lambda: self.update_workspace_4_camera_status(camera_id))
            QTimer.singleShot(100, lambda: self.update_workspace_4_slider_status(camera_id))
        
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
                "whitebalance": cam_data.whitebalance_actual_value,
                "zoom": 0.0  # Valeur par défaut si non disponible
            }
            
            # Récupérer la valeur de zoom normalisée si disponible
            try:
                zoom_data = cam_data.controller.get_zoom()
                if zoom_data and 'normalised' in zoom_data:
                    preset_data["zoom"] = zoom_data['normalised']
            except:
                pass
            
            # Récupérer les valeurs du slider
            slider_controller = self.slider_controllers.get(self.active_camera_id)
            # Vérifier si le slider est configuré (IP non vide) même si is_configured() retourne False
            slider_configured = slider_controller is not None and (
                slider_controller.is_configured() or 
                (hasattr(slider_controller, 'slider_ip') and slider_controller.slider_ip)
            )
            
            if slider_configured:
                try:
                    slider_status = slider_controller.get_status(silent=True)
                    if slider_status:
                        preset_data["pan"] = slider_status.get('pan', 0.0)
                        preset_data["tilt"] = slider_status.get('tilt', 0.0)
                        preset_data["zoom_motor"] = slider_status.get('zoom', 0.0)
                        preset_data["slide"] = slider_status.get('slide', 0.0)
                    else:
                        # Si le slider n'est pas accessible, utiliser les valeurs actuelles des sliders UI
                        preset_data["pan"] = cam_data.slider_pan_value
                        preset_data["tilt"] = cam_data.slider_tilt_value
                        preset_data["zoom_motor"] = cam_data.slider_zoom_value
                        preset_data["slide"] = cam_data.slider_slide_value
                        logger.debug("Slider configuré mais get_status() retourne None, utilisation des valeurs UI")
                except Exception as e:
                    logger.debug(f"Erreur lors de la lecture du statut du slider: {e}")
                    # Utiliser les valeurs actuelles des sliders UI en cas d'erreur
                    preset_data["pan"] = cam_data.slider_pan_value
                    preset_data["tilt"] = cam_data.slider_tilt_value
                    preset_data["zoom_motor"] = cam_data.slider_zoom_value
                    preset_data["slide"] = cam_data.slider_slide_value
            else:
                # Slider non configuré, utiliser les valeurs actuelles des sliders UI ou 0.0
                preset_data["pan"] = cam_data.slider_pan_value
                preset_data["tilt"] = cam_data.slider_tilt_value
                preset_data["zoom_motor"] = cam_data.slider_zoom_value
                preset_data["slide"] = cam_data.slider_slide_value
            
            # Sauvegarder le preset dans la caméra active
            cam_data.presets[f"preset_{preset_number}"] = preset_data
            
            # Mettre à jour le StateStore
            self.state_store.set_preset(self.active_camera_id, f"preset_{preset_number}", preset_data)
            
            # Sauvegarder dans le fichier
            self.save_cameras_config()
            
            logger.info(f"Caméra {self.active_camera_id} - Preset {preset_number} sauvegardé: {preset_data}")
            
            # Faire clignoter le bouton en rouge pour confirmer la sauvegarde
            self._flash_preset_save_button(preset_number)
        except Exception as e:
            logger.error(f"Erreur lors de la sauvegarde du preset {preset_number}: {e}")
    
    def _flash_preset_save_button(self, preset_number: int):
        """Fait clignoter le bouton de sauvegarde du preset en rouge pour confirmer l'action."""
        if preset_number < 1 or preset_number > 10:
            return
        
        if not hasattr(self, 'preset_save_buttons') or len(self.preset_save_buttons) < preset_number:
            return
        
        save_btn = self.preset_save_buttons[preset_number - 1]
        if not save_btn:
            return
        
        # Sauvegarder le style original
        original_style = save_btn.styleSheet()
        
        # Style rouge pour le clignotement
        red_style = self._scale_style("""
            QPushButton {
                padding: 6px;
                font-size: 10px;
                font-weight: bold;
                border: 1px solid #f00;
                border-radius: 4px;
                background-color: #f00;
                color: #fff;
            }
        """)
        
        # Appliquer le style rouge
        save_btn.setStyleSheet(red_style)
        
        # Restaurer le style original après 200ms
        QTimer.singleShot(200, lambda: save_btn.setStyleSheet(original_style))
    
    def on_preset_distance_changed(self, preset_number: int):
        """Appelé quand la distance d'un preset est modifiée."""
        cam_data = self.get_active_camera_data()
        preset_key = f"preset_{preset_number}"
        
        # Récupérer la valeur du champ
        distance_input = self.preset_distance_inputs[preset_number - 1]
        text = distance_input.text().strip()
        
        if text:
            try:
                # Remplacer la virgule par un point pour la conversion
                text_normalized = text.replace(',', '.')
                distance_value = float(text_normalized)
                if 0.1 <= distance_value <= 100.0:
                    # Initialiser le preset s'il n'existe pas
                    if preset_key not in cam_data.presets:
                        cam_data.presets[preset_key] = {}
                    
                    # Sauvegarder la distance dans le preset
                    cam_data.presets[preset_key]["lfo_distance"] = distance_value
                    
                    # Sauvegarder dans le fichier
                    self.save_cameras_config()
                    
                    logger.debug(f"Preset {preset_number} - Distance mise à jour: {distance_value}m")
                else:
                    logger.warning(f"Distance invalide pour preset {preset_number}: {distance_value} (doit être entre 0.1 et 100.0)")
                    # Réinitialiser le champ avec la valeur précédente
                    if preset_key in cam_data.presets and "lfo_distance" in cam_data.presets[preset_key]:
                        distance_input.setText(f"{cam_data.presets[preset_key]['lfo_distance']:.2f}")
                    else:
                        distance_input.clear()
            except ValueError:
                logger.warning(f"Valeur non numérique pour preset {preset_number}: {text}")
                # Réinitialiser le champ
                if preset_key in cam_data.presets and "lfo_distance" in cam_data.presets[preset_key]:
                    distance_input.setText(f"{cam_data.presets[preset_key]['lfo_distance']:.2f}")
                else:
                    distance_input.clear()
        else:
            # Champ vide, supprimer la distance du preset
            if preset_key in cam_data.presets and "lfo_distance" in cam_data.presets[preset_key]:
                del cam_data.presets[preset_key]["lfo_distance"]
                self.save_cameras_config()
                logger.debug(f"Preset {preset_number} - Distance supprimée")
    
    def _update_preset_distance_inputs(self):
        """Met à jour les champs distance avec les valeurs des presets."""
        cam_data = self.get_active_camera_data()
        for i in range(1, 11):
            preset_key = f"preset_{i}"
            distance_input = self.preset_distance_inputs[i - 1]
            
            if preset_key in cam_data.presets and "lfo_distance" in cam_data.presets[preset_key]:
                distance_value = cam_data.presets[preset_key]["lfo_distance"]
                distance_input.setText(f"{distance_value:.2f}")
            else:
                distance_input.clear()
    
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
            
            # Séparer les valeurs slider des autres valeurs
            slider_values = {}
            camera_values = {}
            
            for param, value in preset_data.items():
                if param in ['pan', 'tilt', 'zoom_motor', 'slide']:
                    slider_values[param] = value
                else:
                    camera_values[param] = value
            
            # Filtrer les paramètres caméra selon le recall scope (exclure ceux où recall_scope[param] == True)
            filtered_camera_data = {
                param: value for param, value in camera_values.items()
                if param not in cam_data.recall_scope or not cam_data.recall_scope[param]
            }
            
            # Filtrer les valeurs slider selon le recall scope
            # Si recall_scope['slider'] == True, on n'envoie pas les valeurs slider
            should_send_slider = (
                slider_values and 
                'slider' in cam_data.recall_scope and 
                not cam_data.recall_scope['slider']
            )
            
            # NOUVEAU: Si LFO actif et preset contient des valeurs slider, recalculer la séquence LFO
            if self.lfo_active and should_send_slider and slider_values:
                slider_controller = self.slider_controllers.get(self.active_camera_id)
                if slider_controller and slider_controller.is_configured():
                    # 1. BAKER: Intégrer les offsets actuels dans la position de base
                    if slider_controller.bake_offsets(silent=True):
                        logger.debug(f"LFO: Offsets 'bakeés' avant activation preset {preset_number}")
                    
                    # 2. Extraire les valeurs slider du preset (déjà en 0.0-1.0)
                    preset_pan = slider_values.get('pan')
                    preset_tilt = slider_values.get('tilt')
                    preset_zoom = slider_values.get('zoom_motor')  # zoom_motor dans preset -> zoom dans API
                    preset_slide = slider_values.get('slide')
                    
                    # 3. Utiliser les valeurs du preset si présentes, sinon garder les valeurs actuelles
                    if preset_pan is not None:
                        base_pan = max(0.0, min(1.0, preset_pan))  # Clamp pour sécurité
                    else:
                        base_pan = self.lfo_base_position.get("pan", 0.5)
                    
                    if preset_tilt is not None:
                        base_tilt = max(0.0, min(1.0, preset_tilt))
                    else:
                        base_tilt = self.lfo_base_position.get("tilt", 0.5)
                    
                    if preset_zoom is not None:
                        base_zoom = max(0.0, min(1.0, preset_zoom))
                    else:
                        base_zoom = self.lfo_base_position.get("zoom", 0.0)
                    
                    if preset_slide is not None:
                        base_slide = max(0.0, min(1.0, preset_slide))
                    else:
                        base_slide = self.lfo_base_position.get("slide", 0.5)
                    
                    # 4. Mettre à jour la position de base LFO avec les valeurs du preset
                    self.lfo_base_position["pan"] = base_pan
                    self.lfo_base_position["tilt"] = base_tilt
                    self.lfo_base_position["zoom"] = base_zoom
                    self.lfo_base_position["slide"] = base_slide
                    
                    # 5. Réinitialiser l'offset joystick car la position est maintenant "bakeée"
                    self.lfo_current_joystick_pan_offset = 0.0
                    
                    # 6. Recalculer la séquence LFO avec la nouvelle base (preset)
                    pan_offset = 0.0  # Pas d'offset car la position est "bakeée"
                    
                    # NOUVEAU: Utiliser la distance du preset si sync D focus est off
                    distance_to_use = self.lfo_distance  # Par défaut, utiliser la distance actuelle
                    original_distance = self.lfo_distance  # Sauvegarder pour restauration
                    
                    if not self.lfo_auto_sync_distance and "lfo_distance" in preset_data:
                        # Utiliser la distance du preset
                        distance_to_use = preset_data["lfo_distance"]
                        # Mettre à jour self.lfo_distance pour le calcul
                        self.lfo_distance = distance_to_use
                        # Mettre à jour le slider distance dans l'UI LFO si nécessaire
                        if hasattr(self, 'lfo_panel') and hasattr(self.lfo_panel, 'distance_slider'):
                            # Convertir la distance en valeur slider (0.5-20 mètres -> 0-1000)
                            slider_value = int((distance_to_use - 0.5) / 19.5 * 1000)
                            slider_value = max(0, min(1000, slider_value))
                            self.lfo_panel.distance_slider.setValue(slider_value)
                            # Mettre à jour le label de distance
                            if hasattr(self.lfo_panel, 'distance_value_label'):
                                self.lfo_panel.distance_value_label.setText(f"{distance_to_use:.1f} m")
                        logger.info(f"LFO: Utilisation de la distance du preset {preset_number}: {distance_to_use:.1f}m")
                    
                    sequence_points, base_position, position_plus, position_minus = self._calculate_lfo_sequence(
                        base_slide, base_pan, base_tilt, base_zoom, pan_offset=pan_offset
                    )
                    
                    # Restaurer la distance originale si sync est activé (pour ne pas perturber l'affichage)
                    if self.lfo_auto_sync_distance:
                        self.lfo_distance = original_distance
                    
                    # 7. Mettre à jour les positions stockées
                    self.lfo_position_plus = position_plus
                    self.lfo_position_minus = position_minus
                    
                    # 8. Envoyer la nouvelle séquence
                    if self.lfo_sequence_initialized:
                        # Utiliser PATCH pour mettre à jour sans interruption
                        success = slider_controller.update_interpolation_sequence(
                            sequence_points,
                            recalculate_duration=True,
                            duration=self.lfo_speed,
                            silent=True
                        )
                        if not success:
                            # Si PATCH échoue, utiliser POST et redémarrer
                            if slider_controller.send_interpolation_sequence(sequence_points, self.lfo_speed, silent=True):
                                slider_controller.set_auto_interpolation(enable=True, duration=self.lfo_speed, silent=True)
                                self.lfo_sequence_initialized = True
                    else:
                        # Première fois : utiliser POST
                        if slider_controller.send_interpolation_sequence(sequence_points, self.lfo_speed, silent=True):
                            slider_controller.set_auto_interpolation(enable=True, duration=self.lfo_speed, silent=True)
                            self.lfo_sequence_initialized = True
                    
                    logger.info(f"LFO: Séquence recalculée avec preset {preset_number} comme nouvelle base")
                    # 9. Empêcher l'envoi normal de move_axes() car la séquence LFO gère déjà le mouvement
                    should_send_slider = False
            
            # Arrêter toute transition en cours
            if self.preset_transition_timer:
                self.preset_transition_timer.stop()
                self.preset_transition_timer = None
            
            # Si transition progressive activée, faire une transition
            if self.smooth_preset_transition:
                try:
                    self._start_smooth_preset_transition(filtered_camera_data, preset_number)
                except Exception as e:
                    logger.error(f"Erreur dans _start_smooth_preset_transition: {e}")
                    raise
            else:
                # Appliquer les valeurs instantanément
                self._apply_preset_values_instant(filtered_camera_data, preset_number)
            
            # Envoyer les valeurs slider si nécessaire
            if should_send_slider:
                slider_controller = self.slider_controllers.get(self.active_camera_id)
                # Vérifier si le slider est configuré (IP non vide) même si is_configured() retourne False
                slider_configured = slider_controller is not None and (
                    slider_controller.is_configured() or 
                    (hasattr(slider_controller, 'slider_ip') and slider_controller.slider_ip)
                )
                
                if slider_configured:
                    # Les valeurs pan/tilt dans les presets sont déjà en 0.0-1.0
                    pan = slider_values.get('pan')
                    tilt = slider_values.get('tilt')
                    zoom = slider_values.get('zoom_motor')  # zoom_motor dans preset -> zoom dans API
                    slide = slider_values.get('slide')
                    
                    # Envoyer avec la durée de crossfade pour synchronisation
                    try:
                        slider_controller.move_axes(
                            pan=pan,
                            tilt=tilt,
                            zoom=zoom,
                            slide=slide,
                            duration=cam_data.crossfade_duration,
                            silent=True
                        )
                        logger.info(f"Preset {preset_number} - Valeurs slider envoyées: pan={pan}, tilt={tilt}, zoom={zoom}, slide={slide}")
                    except Exception as e:
                        logger.error(f"Erreur lors de l'envoi des valeurs slider du preset {preset_number}: {e}")
                else:
                    logger.warning(f"Preset {preset_number} - Slider non configuré, valeurs slider ignorées")
            
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
        
        # White Balance - toujours instantané
        if 'whitebalance' in preset_data:
            whitebalance_value = int(preset_data['whitebalance'])
            self.update_whitebalance_value(whitebalance_value)
        
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
        
        # Mettre à jour le label du preset dans le panneau LFO si présent
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
        
        # Mettre à jour le label du preset dans le panneau LFO si présent
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
    
    def _get_param_display_name(self, param: str) -> str:
        """Retourne le nom d'affichage d'un paramètre pour les checkboxes."""
        display_names = {
            'focus': 'Focus',
            'iris': 'Iris',
            'gain': 'Gain',
            'shutter': 'Shutter',
            'whitebalance': 'White Balance',
            'slider': 'Slider'
        }
        return display_names.get(param, param.capitalize())
    
    def on_recall_scope_changed(self, param: str, excluded: bool):
        """Appelé quand une checkbox de recall scope change."""
        cam_data = self.get_active_camera_data()
        cam_data.recall_scope[param] = excluded
        
        # Mettre à jour le texte de la checkbox
        checkbox = self.recall_scope_checkboxes.get(param)
        if checkbox:
            display_name = self._get_param_display_name(param)
            checkbox.setText(f"{'☑' if excluded else '☐'} {display_name}")
        
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
                display_name = self._get_param_display_name(param)
                checkbox.setText(f"{'☑' if excluded else '☐'} {display_name}")
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
    
    def update_workspace_3_camera_display(self):
        """Met à jour l'affichage de la caméra dans le Workspace 3."""
        cam_data = self.get_active_camera_data()
        
        # Mettre à jour le nom de la caméra
        if hasattr(self, 'workspace_3_camera_name_label'):
            self.workspace_3_camera_name_label.setText(f"📹 Caméra {self.active_camera_id}")
        
        # S'assurer que la caméra existe dans preset_description.json
        ensure_camera_exists(self.active_camera_id)
        
        # Réinitialiser le preset sélectionné à 1 quand on change de caméra
        if hasattr(self, 'workspace_3_selected_preset_id'):
            self.workspace_3_selected_preset_id = 1
            if hasattr(self, 'workspace_3_preset_title_label'):
                self.workspace_3_preset_title_label.setText("Preset 1")
            # Mettre à jour les boutons de sélection
            if hasattr(self, 'workspace_3_preset_selector_buttons'):
                for i, btn in enumerate(self.workspace_3_preset_selector_buttons, start=1):
                    btn.setChecked(i == 1)
        
        # Rafraîchir l'assignation musiciens/plans pour le preset sélectionné
        if hasattr(self, 'workspace_3_selected_preset_id'):
            self.workspace_3_refresh_preset_assignment()
    
    def update_preset_highlight(self):
        """Met à jour l'encadré coloré autour du preset actif."""
        cam_data = self.get_active_camera_data()
        active_preset_num = cam_data.active_preset
        
        # Mettre à jour les presets du Workspace 1
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
        
        # Mettre à jour le bouton Recall du Workspace 3 (si visible)
        if hasattr(self, 'workspace_3_recall_btn'):
            # Le bouton Recall du Workspace 3 n'a pas besoin de mise à jour visuelle
            # car il est toujours disponible pour le preset sélectionné
            pass
    
    # ========== Workspace 3 - Gestion musiciens et plans ==========
    
    def workspace_3_add_musician(self):
        """Ajoute un musicien à la liste."""
        name = self.workspace_3_new_musician_input.text().strip()
        if not name:
            return
        
        if add_musician(name):
            self.workspace_3_new_musician_input.clear()
            self.workspace_3_refresh_musicians()
            self.workspace_3_refresh_preset_assignment()
            logger.info(f"Musicien ajouté: {name}")
        else:
            logger.warning(f"Impossible d'ajouter le musicien: {name} (déjà existant?)")
    
    def workspace_3_remove_musician(self, name: str):
        """Supprime un musicien de la liste."""
        if remove_musician(name):
            self.workspace_3_refresh_musicians()
            self.workspace_3_refresh_preset_assignment()
            logger.info(f"Musicien supprimé: {name}")
        else:
            logger.warning(f"Impossible de supprimer le musicien: {name}")
    
    def workspace_3_refresh_musicians(self):
        """Rafraîchit l'affichage de la liste des musiciens."""
        if not hasattr(self, 'workspace_3_musicians_list_layout'):
            return
        
        # Supprimer les widgets existants
        for widget in self.workspace_3_musician_widgets:
            widget.setParent(None)
        self.workspace_3_musician_widgets.clear()
        
        # Charger les musiciens
        musicians = get_musicians()
        
        # Créer un widget pour chaque musicien
        for musician in musicians:
            musician_row = QWidget()
            musician_row.setStyleSheet(self._scale_style("""
                QWidget {
                    background-color: #2a2a2a;
                    border: 1px solid #444;
                    border-radius: 4px;
                    padding: 2px;
                }
            """))
            musician_layout = QHBoxLayout(musician_row)
            musician_layout.setContentsMargins(self._scale_value(10), self._scale_value(8), 
                                              self._scale_value(10), self._scale_value(8))
            musician_layout.setSpacing(self._scale_value(10))
            
            label = QLabel(musician)
            label.setStyleSheet(f"font-size: {self._scale_font(13)}; font-weight: bold; color: #fff;")
            label.setMinimumWidth(self._scale_value(150))
            
            remove_btn = QPushButton("×")
            remove_btn.setFixedSize(self._scale_value(30), self._scale_value(30))
            remove_btn.setStyleSheet(self._scale_style("""
                QPushButton {
                    background-color: #a50;
                    border: 1px solid #c70;
                    border-radius: 4px;
                    color: #fff;
                    font-size: 16px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #c70;
                }
                QPushButton:pressed {
                    background-color: #840;
                }
            """))
            remove_btn.clicked.connect(lambda checked, m=musician: self.workspace_3_remove_musician(m))
            
            musician_layout.addWidget(label)
            musician_layout.addWidget(remove_btn)
            musician_layout.addStretch()
            
            self.workspace_3_musicians_list_layout.addWidget(musician_row)
            self.workspace_3_musician_widgets.append(musician_row)
        
        if not musicians:
            empty_label = QLabel("Aucun musicien.\nAjoutez-en un ci-dessous.")
            empty_label.setAlignment(Qt.AlignCenter)
            empty_label.setStyleSheet(f"font-size: {self._scale_font(11)}; color: #666; font-style: italic; padding: 20px;")
            empty_label.setWordWrap(True)
            self.workspace_3_musicians_list_layout.addWidget(empty_label)
    
    def workspace_3_select_preset(self, preset_id: int):
        """Sélectionne un preset dans le Workspace 3."""
        self.workspace_3_selected_preset_id = preset_id
        
        # Mettre à jour le titre du preset
        if hasattr(self, 'workspace_3_preset_title_label'):
            self.workspace_3_preset_title_label.setText(f"Preset {preset_id}")
        
        # Mettre à jour les boutons de sélection
        for i, btn in enumerate(self.workspace_3_preset_selector_buttons, start=1):
            btn.setChecked(i == preset_id)
        
        # Rafraîchir l'assignation musiciens/plans
        self.workspace_3_refresh_preset_assignment()
    
    def workspace_3_refresh_preset_assignment(self):
        """Rafraîchit l'affichage de l'assignation musiciens/plans pour le preset sélectionné."""
        if not hasattr(self, 'workspace_3_musicians_grid_layout'):
            return
        
        # Supprimer les widgets existants
        for widget in self.workspace_3_musician_plan_widgets:
            widget.setParent(None)
        self.workspace_3_musician_plan_widgets.clear()
        
        # S'assurer que la caméra existe dans preset_description.json
        ensure_camera_exists(self.active_camera_id)
        
        # Charger les musiciens
        musicians = get_musicians()
        
        if not musicians:
            empty_label = QLabel("Aucun musicien.\nAjoutez-en dans le panneau de gauche\npour les assigner aux presets.")
            empty_label.setAlignment(Qt.AlignCenter)
            empty_label.setStyleSheet(f"font-size: {self._scale_font(12)}; color: #666; font-style: italic; padding: 40px;")
            empty_label.setWordWrap(True)
            self.workspace_3_musicians_grid_layout.addWidget(empty_label)
            return
        
        # Plans disponibles
        shot_types = [
            ("absent", "absent – Non cadré"),
            ("ecu", "ECU – Détail (main/pédale)"),
            ("cu", "CU – Gros plan (visage/instrument serré)"),
            ("mcu", "MCU – Plan rapproché (buste)"),
            ("ms", "MS – Plan moyen (taille)"),
            ("ws", "WS – Plan large (ensemble)")
        ]
        
        # Créer une ligne pour chaque musicien
        for musician in musicians:
            row = QWidget()
            row.setStyleSheet(self._scale_style("""
                QWidget {
                    background-color: #2a2a2a;
                    border: 1px solid #444;
                    border-radius: 6px;
                    padding: 2px;
                }
            """))
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(self._scale_value(12), self._scale_value(10), 
                                         self._scale_value(12), self._scale_value(10))
            row_layout.setSpacing(self._scale_value(15))
            
            # Label du musicien
            label = QLabel(musician)
            label.setMinimumWidth(self._scale_value(140))
            label.setStyleSheet(f"font-size: {self._scale_font(13)}; font-weight: bold; color: #fff;")
            row_layout.addWidget(label)
            
            # Menu déroulant pour le plan
            combo = QComboBox()
            combo.setMinimumWidth(self._scale_value(280))
            combo.setMinimumHeight(self._scale_value(32))
            current_plan = get_preset_musician_plan(
                self.active_camera_id,
                self.workspace_3_selected_preset_id,
                musician
            )
            
            combo.setStyleSheet(self._scale_style("""
                QComboBox {
                    padding: 6px 8px;
                    background-color: #333;
                    border: 1px solid #555;
                    border-radius: 4px;
                    color: #fff;
                    font-size: 12px;
                }
                QComboBox:hover {
                    border: 1px solid #777;
                    background-color: #3a3a3a;
                }
                QComboBox::drop-down {
                    border: none;
                    width: 20px;
                }
                QComboBox::down-arrow {
                    image: none;
                    border-left: 4px solid transparent;
                    border-right: 4px solid transparent;
                    border-top: 6px solid #aaa;
                    margin-right: 5px;
                }
                QComboBox QAbstractItemView {
                    background-color: #333;
                    border: 1px solid #555;
                    selection-background-color: #0a5;
                    selection-color: #fff;
                    color: #fff;
                }
            """))
            
            current_index = 0
            for idx, (plan_value, plan_label) in enumerate(shot_types):
                combo.addItem(plan_label)
                combo.setItemData(idx, plan_value)
                if plan_value == current_plan:
                    current_index = idx
            combo.setCurrentIndex(current_index)
            
            # Appliquer un style selon le plan
            self.workspace_3_apply_plan_style(row, current_plan)
            
            # Stocker les références pour le callback
            def create_plan_changed_callback(m, c, r):
                def callback(idx):
                    plan_value = c.itemData(idx)
                    if plan_value:
                        self.workspace_3_on_plan_changed(m, plan_value, r)
                return callback
            
            combo.currentIndexChanged.connect(create_plan_changed_callback(musician, combo, row))
            
            row_layout.addWidget(combo)
            row_layout.addStretch()
            
            self.workspace_3_musicians_grid_layout.addWidget(row)
            self.workspace_3_musician_plan_widgets.append(row)
    
    def workspace_3_apply_plan_style(self, widget: QWidget, plan: str):
        """Applique un style de couleur selon le plan."""
        colors = {
            "absent": "#666",
            "ecu": "#8b5cf6",
            "cu": "#a78bfa",
            "mcu": "#c4b5fd",
            "ms": "#ddd6fe",
            "ws": "#ede9fe"
        }
        color = colors.get(plan, "#666")
        widget.setStyleSheet(self._scale_style(f"""
            QWidget {{
                background-color: {color}30;
                border-left: 4px solid {color};
                border-radius: 6px;
            }}
        """))
    
    def workspace_3_on_plan_changed(self, musician: str, plan: str, row_widget: QWidget):
        """Appelé quand le plan d'un musicien change."""
        if set_preset_musician_plan(
            self.active_camera_id,
            self.workspace_3_selected_preset_id,
            musician,
            plan
        ):
            self.workspace_3_apply_plan_style(row_widget, plan)
            logger.info(f"Plan assigné: Cam{self.active_camera_id} Preset{self.workspace_3_selected_preset_id} - {musician} → {plan}")
        else:
            logger.error(f"Erreur lors de l'assignation du plan")
    
    def workspace_3_recall_current_preset(self):
        """Rappelle le preset actuellement sélectionné dans le Workspace 3."""
        self.recall_preset(self.workspace_3_selected_preset_id)
    
    def workspace_3_save_current_preset(self):
        """Sauvegarde le preset actuellement sélectionné dans le Workspace 3."""
        self.save_preset(self.workspace_3_selected_preset_id)
    
    def create_workspace_4_page(self):
        """Crée la page pour le Workspace 4 avec la configuration des caméras."""
        page = QWidget()
        page.setStyleSheet("""
            QWidget {
                background-color: #2a2a2a;
            }
        """)
        
        main_layout = QVBoxLayout(page)
        main_layout.setContentsMargins(self._scale_value(40), self._scale_value(40), 
                                     self._scale_value(40), self._scale_value(40))
        main_layout.setSpacing(self._scale_value(30))
        
        # Titre avec indication de la caméra active
        self.workspace_4_camera_label = QLabel(f"Configuration de la Caméra {self.active_camera_id}")
        self.workspace_4_camera_label.setStyleSheet(f"""
            font-size: {self._scale_font(24)}px;
            font-weight: bold;
            color: #fff;
            padding-bottom: {self._scale_value(10)}px;
        """)
        main_layout.addWidget(self.workspace_4_camera_label)
        
        # Section Configuration
        config_group = QGroupBox("Configuration")
        config_group.setStyleSheet(self._scale_style("""
            QGroupBox {
                font-size: 16px;
                font-weight: bold;
                color: #fff;
                border: 2px solid #555;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
        """))
        config_layout = QVBoxLayout(config_group)
        config_layout.setSpacing(self._scale_value(15))
        
        # URL de la caméra
        url_layout = QHBoxLayout()
        url_label = QLabel("URL de la caméra:")
        url_label.setMinimumWidth(self._scale_value(150))
        url_label.setStyleSheet(f"font-size: {self._scale_font(14)}px; color: #aaa;")
        url_layout.addWidget(url_label)
        self.workspace_4_url_input = QLineEdit()
        self.workspace_4_url_input.setPlaceholderText("http://Micro-Studio-Camera-4K-G2.local")
        self.workspace_4_url_input.setStyleSheet(self._scale_style("""
            QLineEdit {
                padding: 8px;
                background-color: #333;
                border: 1px solid #555;
                border-radius: 4px;
                color: #fff;
                font-size: 14px;
            }
            QLineEdit:focus {
                border: 2px solid #0a5;
            }
        """))
        url_layout.addWidget(self.workspace_4_url_input)
        config_layout.addLayout(url_layout)
        
        # Nom d'utilisateur
        username_layout = QHBoxLayout()
        username_label = QLabel("Nom d'utilisateur:")
        username_label.setMinimumWidth(self._scale_value(150))
        username_label.setStyleSheet(f"font-size: {self._scale_font(14)}px; color: #aaa;")
        username_layout.addWidget(username_label)
        self.workspace_4_username_input = QLineEdit()
        self.workspace_4_username_input.setPlaceholderText("roo")
        self.workspace_4_username_input.setStyleSheet(self._scale_style("""
            QLineEdit {
                padding: 8px;
                background-color: #333;
                border: 1px solid #555;
                border-radius: 4px;
                color: #fff;
                font-size: 14px;
            }
            QLineEdit:focus {
                border: 2px solid #0a5;
            }
        """))
        username_layout.addWidget(self.workspace_4_username_input)
        config_layout.addLayout(username_layout)
        
        # Mot de passe
        password_layout = QHBoxLayout()
        password_label = QLabel("Mot de passe:")
        password_label.setMinimumWidth(self._scale_value(150))
        password_label.setStyleSheet(f"font-size: {self._scale_font(14)}px; color: #aaa;")
        password_layout.addWidget(password_label)
        self.workspace_4_password_input = QLineEdit()
        self.workspace_4_password_input.setEchoMode(QLineEdit.Password)
        self.workspace_4_password_input.setPlaceholderText("koko")
        self.workspace_4_password_input.setStyleSheet(self._scale_style("""
            QLineEdit {
                padding: 8px;
                background-color: #333;
                border: 1px solid #555;
                border-radius: 4px;
                color: #fff;
                font-size: 14px;
            }
            QLineEdit:focus {
                border: 2px solid #0a5;
            }
        """))
        password_layout.addWidget(self.workspace_4_password_input)
        config_layout.addLayout(password_layout)
        
        # IP du slider
        slider_layout = QHBoxLayout()
        slider_label = QLabel("IP ou hostname du slider:")
        slider_label.setMinimumWidth(self._scale_value(150))
        slider_label.setStyleSheet(f"font-size: {self._scale_font(14)}px; color: #aaa;")
        slider_layout.addWidget(slider_label)
        self.workspace_4_slider_ip_input = QLineEdit()
        self.workspace_4_slider_ip_input.setPlaceholderText("192.168.1.100 ou slider1.local")
        self.workspace_4_slider_ip_input.setStyleSheet(self._scale_style("""
            QLineEdit {
                padding: 8px;
                background-color: #333;
                border: 1px solid #555;
                border-radius: 4px;
                color: #fff;
                font-size: 14px;
            }
            QLineEdit:focus {
                border: 2px solid #0a5;
            }
        """))
        slider_layout.addWidget(self.workspace_4_slider_ip_input)
        config_layout.addLayout(slider_layout)
        
        # Page Companion
        companion_layout = QHBoxLayout()
        companion_label = QLabel("Page Companion:")
        companion_label.setMinimumWidth(self._scale_value(150))
        companion_label.setStyleSheet(f"font-size: {self._scale_font(14)}px; color: #aaa;")
        companion_layout.addWidget(companion_label)
        self.workspace_4_companion_input = QLineEdit()
        self.workspace_4_companion_input.setPlaceholderText("1")
        self.workspace_4_companion_input.setStyleSheet(self._scale_style("""
            QLineEdit {
                padding: 8px;
                background-color: #333;
                border: 1px solid #555;
                border-radius: 4px;
                color: #fff;
                font-size: 14px;
            }
            QLineEdit:focus {
                border: 2px solid #0a5;
            }
        """))
        companion_layout.addWidget(self.workspace_4_companion_input)
        config_layout.addLayout(companion_layout)
        
        # Bouton Sauvegarder
        save_btn = QPushButton("Sauvegarder")
        save_btn.clicked.connect(self.on_workspace_4_save_camera_config)
        save_btn.setStyleSheet(self._scale_style("""
            QPushButton {
                padding: 10px 20px;
                background-color: #0a5;
                border: none;
                border-radius: 6px;
                color: #fff;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #0b6;
            }
            QPushButton:pressed {
                background-color: #094;
            }
        """))
        config_layout.addWidget(save_btn)
        config_layout.addStretch()
        main_layout.addWidget(config_group)
        
        # Section État de connexion - Caméra
        camera_status_group = QGroupBox("État de connexion - Caméra")
        camera_status_group.setStyleSheet(self._scale_style("""
            QGroupBox {
                font-size: 16px;
                font-weight: bold;
                color: #fff;
                border: 2px solid #555;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
        """))
        camera_status_layout = QVBoxLayout(camera_status_group)
        camera_status_layout.setSpacing(self._scale_value(15))
        
        # Indicateur LED et label d'état caméra
        camera_status_indicator_layout = QHBoxLayout()
        self.workspace_4_camera_status_led = QLabel("●")
        self.workspace_4_camera_status_led.setStyleSheet("font-size: 24px; color: #f00;")
        camera_status_indicator_layout.addWidget(self.workspace_4_camera_status_led)
        self.workspace_4_camera_status_label = QLabel("Déconnecté")
        self.workspace_4_camera_status_label.setStyleSheet(f"font-size: {self._scale_font(14)}px; color: #f00; font-weight: bold;")
        camera_status_indicator_layout.addWidget(self.workspace_4_camera_status_label)
        camera_status_indicator_layout.addStretch()
        camera_status_layout.addLayout(camera_status_indicator_layout)
        
        # Boutons Connect/Disconnect caméra
        camera_buttons_layout = QHBoxLayout()
        camera_buttons_layout.setSpacing(self._scale_value(10))
        self.workspace_4_camera_connect_btn = QPushButton("Connecter")
        self.workspace_4_camera_connect_btn.clicked.connect(self.on_workspace_4_camera_connect)
        self.workspace_4_camera_connect_btn.setStyleSheet(self._scale_style("""
            QPushButton {
                padding: 10px 20px;
                background-color: #0a5;
                border: none;
                border-radius: 6px;
                color: #fff;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #0b6;
            }
            QPushButton:pressed {
                background-color: #094;
            }
            QPushButton:disabled {
                background-color: #444;
                color: #888;
            }
        """))
        camera_buttons_layout.addWidget(self.workspace_4_camera_connect_btn)
        
        self.workspace_4_camera_disconnect_btn = QPushButton("Déconnecter")
        self.workspace_4_camera_disconnect_btn.clicked.connect(self.on_workspace_4_camera_disconnect)
        self.workspace_4_camera_disconnect_btn.setStyleSheet(self._scale_style("""
            QPushButton {
                padding: 10px 20px;
                background-color: #a50;
                border: none;
                border-radius: 6px;
                color: #fff;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #b60;
            }
            QPushButton:pressed {
                background-color: #940;
            }
            QPushButton:disabled {
                background-color: #444;
                color: #888;
            }
        """))
        self.workspace_4_camera_disconnect_btn.setEnabled(False)
        camera_buttons_layout.addWidget(self.workspace_4_camera_disconnect_btn)
        camera_status_layout.addLayout(camera_buttons_layout)
        camera_status_layout.addStretch()
        main_layout.addWidget(camera_status_group)
        
        # Section État de connexion - Slider
        slider_status_group = QGroupBox("État de connexion - Slider")
        slider_status_group.setStyleSheet(self._scale_style("""
            QGroupBox {
                font-size: 16px;
                font-weight: bold;
                color: #fff;
                border: 2px solid #555;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
        """))
        slider_status_layout = QVBoxLayout(slider_status_group)
        slider_status_layout.setSpacing(self._scale_value(15))
        
        # Indicateur LED et label d'état slider
        slider_status_indicator_layout = QHBoxLayout()
        self.workspace_4_slider_status_led = QLabel("●")
        self.workspace_4_slider_status_led.setStyleSheet("font-size: 24px; color: #f00;")
        slider_status_indicator_layout.addWidget(self.workspace_4_slider_status_led)
        self.workspace_4_slider_status_label = QLabel("Déconnecté")
        self.workspace_4_slider_status_label.setStyleSheet(f"font-size: {self._scale_font(14)}px; color: #f00; font-weight: bold;")
        slider_status_indicator_layout.addWidget(self.workspace_4_slider_status_label)
        slider_status_indicator_layout.addStretch()
        slider_status_layout.addLayout(slider_status_indicator_layout)
        
        # Boutons Connect/Disconnect slider
        slider_buttons_layout = QHBoxLayout()
        slider_buttons_layout.setSpacing(self._scale_value(10))
        self.workspace_4_slider_connect_btn = QPushButton("Connecter")
        self.workspace_4_slider_connect_btn.clicked.connect(self.on_workspace_4_slider_connect)
        self.workspace_4_slider_connect_btn.setStyleSheet(self._scale_style("""
            QPushButton {
                padding: 10px 20px;
                background-color: #0a5;
                border: none;
                border-radius: 6px;
                color: #fff;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #0b6;
            }
            QPushButton:pressed {
                background-color: #094;
            }
            QPushButton:disabled {
                background-color: #444;
                color: #888;
            }
        """))
        slider_buttons_layout.addWidget(self.workspace_4_slider_connect_btn)
        
        self.workspace_4_slider_disconnect_btn = QPushButton("Déconnecter")
        self.workspace_4_slider_disconnect_btn.clicked.connect(self.on_workspace_4_slider_disconnect)
        self.workspace_4_slider_disconnect_btn.setStyleSheet(self._scale_style("""
            QPushButton {
                padding: 10px 20px;
                background-color: #a50;
                border: none;
                border-radius: 6px;
                color: #fff;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #b60;
            }
            QPushButton:pressed {
                background-color: #940;
            }
            QPushButton:disabled {
                background-color: #444;
                color: #888;
            }
        """))
        self.workspace_4_slider_disconnect_btn.setEnabled(False)
        slider_buttons_layout.addWidget(self.workspace_4_slider_disconnect_btn)
        slider_status_layout.addLayout(slider_buttons_layout)
        slider_status_layout.addStretch()
        main_layout.addWidget(slider_status_group)
        
        main_layout.addStretch()
        
        # Initialiser avec la caméra active
        self.update_workspace_4_for_active_camera()
        
        return page
    
    def update_workspace_4_for_active_camera(self):
        """Met à jour le Workspace 4 avec les paramètres de la caméra active."""
        if not hasattr(self, 'workspace_4_url_input'):
            return  # Workspace 4 pas encore créé
        
        camera_id = self.active_camera_id
        cam_data = self.cameras[camera_id]
        
        # Mettre à jour le titre
        if hasattr(self, 'workspace_4_camera_label'):
            self.workspace_4_camera_label.setText(f"Configuration de la Caméra {camera_id}")
        
        # Mettre à jour les champs avec les valeurs de la caméra
        self.workspace_4_url_input.setText(cam_data.url or "")
        self.workspace_4_username_input.setText(cam_data.username or "")
        self.workspace_4_password_input.setText(cam_data.password or "")
        self.workspace_4_slider_ip_input.setText(cam_data.slider_ip or "")
        self.workspace_4_companion_input.setText(str(cam_data.companion_page) if cam_data.companion_page else str(camera_id))
        
        # Mettre à jour l'affichage du statut de connexion
        self.update_workspace_4_camera_status(camera_id)
        self.update_workspace_4_slider_status(camera_id)
    
    def on_workspace_4_camera_selected(self, index: int):
        """Méthode dépréciée - utilise maintenant update_workspace_4_for_active_camera()."""
        # Cette méthode est conservée pour compatibilité mais ne fait plus rien
        # Le Workspace 4 suit maintenant automatiquement la caméra active
        pass
    
    def update_workspace_4_camera_status(self, camera_id: int):
        """Met à jour l'affichage du statut de connexion de la caméra."""
        if not hasattr(self, 'workspace_4_camera_status_label'):
            return  # Workspace 4 pas encore créé
        
        cam_data = self.cameras[camera_id]
        connected = cam_data.connected
        connecting = getattr(cam_data, 'connecting', False)
        auto_reconnect = getattr(cam_data, 'auto_reconnect_enabled', True)
        
        if connecting:
            # État "Connecting" (tâche de fond en cours)
            self.workspace_4_camera_status_led.setStyleSheet("font-size: 24px; color: #ffa500;")  # Orange
            self.workspace_4_camera_status_label.setText("Connexion en cours...")
            self.workspace_4_camera_status_label.setStyleSheet(f"font-size: {self._scale_font(14)}px; color: #ffa500; font-weight: bold;")
            self.workspace_4_camera_connect_btn.setEnabled(False)
            self.workspace_4_camera_disconnect_btn.setText("Arrêter les tentatives")
            self.workspace_4_camera_disconnect_btn.setEnabled(True)
            self.workspace_4_camera_disconnect_btn.setStyleSheet(self._scale_style("""
                QPushButton {
                    padding: 10px 20px;
                    background-color: #ff8c00;
                    border: none;
                    border-radius: 6px;
                    color: #fff;
                    font-size: 14px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #ff9f33;
                }
                QPushButton:pressed {
                    background-color: #e67e00;
                }
            """))
        elif connected:
            # État "Connected"
            self.workspace_4_camera_status_led.setStyleSheet("font-size: 24px; color: #0f0;")  # Vert
            self.workspace_4_camera_status_label.setText("Connecté")
            self.workspace_4_camera_status_label.setStyleSheet(f"font-size: {self._scale_font(14)}px; color: #0f0; font-weight: bold;")
            self.workspace_4_camera_connect_btn.setEnabled(False)
            self.workspace_4_camera_disconnect_btn.setText("Déconnecter")
            self.workspace_4_camera_disconnect_btn.setEnabled(True)
            self.workspace_4_camera_disconnect_btn.setStyleSheet(self._scale_style("""
                QPushButton {
                    padding: 10px 20px;
                    background-color: #a50;
                    border: none;
                    border-radius: 6px;
                    color: #fff;
                    font-size: 14px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #b60;
                }
                QPushButton:pressed {
                    background-color: #940;
                }
            """))
        else:
            # État "Disconnected"
            if auto_reconnect:
                # Des tentatives automatiques sont en cours
                self.workspace_4_camera_status_led.setStyleSheet("font-size: 24px; color: #ffa500;")  # Orange
                self.workspace_4_camera_status_label.setText("Déconnecté (reconnexion auto...)")
                self.workspace_4_camera_status_label.setStyleSheet(f"font-size: {self._scale_font(14)}px; color: #ffa500; font-weight: bold;")
                self.workspace_4_camera_connect_btn.setEnabled(True)
                self.workspace_4_camera_disconnect_btn.setText("Arrêter les tentatives")
                self.workspace_4_camera_disconnect_btn.setEnabled(True)
                self.workspace_4_camera_disconnect_btn.setStyleSheet(self._scale_style("""
                    QPushButton {
                        padding: 10px 20px;
                        background-color: #ff8c00;
                        border: none;
                        border-radius: 6px;
                        color: #fff;
                        font-size: 14px;
                        font-weight: bold;
                    }
                    QPushButton:hover {
                        background-color: #ff9f33;
                    }
                    QPushButton:pressed {
                        background-color: #e67e00;
                    }
                """))
            else:
                # Aucune tentative automatique
                self.workspace_4_camera_status_led.setStyleSheet("font-size: 24px; color: #f00;")  # Rouge
                self.workspace_4_camera_status_label.setText("Déconnecté")
                self.workspace_4_camera_status_label.setStyleSheet(f"font-size: {self._scale_font(14)}px; color: #f00; font-weight: bold;")
                self.workspace_4_camera_connect_btn.setEnabled(True)
                self.workspace_4_camera_disconnect_btn.setText("Arrêter les tentatives")
                self.workspace_4_camera_disconnect_btn.setEnabled(False)  # Pas de tentative à arrêter
                self.workspace_4_camera_disconnect_btn.setStyleSheet(self._scale_style("""
                    QPushButton {
                        padding: 10px 20px;
                        background-color: #444;
                        border: none;
                        border-radius: 6px;
                        color: #888;
                        font-size: 14px;
                        font-weight: bold;
                    }
                    QPushButton:disabled {
                        background-color: #444;
                        color: #888;
                    }
                """))
    
    def update_workspace_4_slider_status(self, camera_id: int):
        """Met à jour l'affichage du statut de connexion du slider."""
        if not hasattr(self, 'workspace_4_slider_status_label'):
            return  # Workspace 4 pas encore créé
        
        cam_data = self.cameras[camera_id]
        slider_connected = False
        if cam_data.slider_websocket_client:
            slider_connected = getattr(cam_data.slider_websocket_client, 'connected', False)
        slider_connecting = getattr(cam_data, 'slider_connecting', False)
        slider_auto_reconnect = getattr(cam_data, 'slider_auto_reconnect_enabled', True)
        
        if slider_connecting:
            # État "Connecting" (tâche de fond en cours)
            self.workspace_4_slider_status_led.setStyleSheet("font-size: 24px; color: #ffa500;")  # Orange
            self.workspace_4_slider_status_label.setText("Connexion en cours...")
            self.workspace_4_slider_status_label.setStyleSheet(f"font-size: {self._scale_font(14)}px; color: #ffa500; font-weight: bold;")
            self.workspace_4_slider_connect_btn.setEnabled(False)
            self.workspace_4_slider_disconnect_btn.setText("Arrêter les tentatives")
            self.workspace_4_slider_disconnect_btn.setEnabled(True)
            self.workspace_4_slider_disconnect_btn.setStyleSheet(self._scale_style("""
                QPushButton {
                    padding: 10px 20px;
                    background-color: #ff8c00;
                    border: none;
                    border-radius: 6px;
                    color: #fff;
                    font-size: 14px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #ff9f33;
                }
                QPushButton:pressed {
                    background-color: #e67e00;
                }
            """))
        elif slider_connected:
            # État "Connected"
            self.workspace_4_slider_status_led.setStyleSheet("font-size: 24px; color: #0f0;")  # Vert
            self.workspace_4_slider_status_label.setText("Connecté")
            self.workspace_4_slider_status_label.setStyleSheet(f"font-size: {self._scale_font(14)}px; color: #0f0; font-weight: bold;")
            self.workspace_4_slider_connect_btn.setEnabled(False)
            self.workspace_4_slider_disconnect_btn.setText("Déconnecter")
            self.workspace_4_slider_disconnect_btn.setEnabled(True)
            self.workspace_4_slider_disconnect_btn.setStyleSheet(self._scale_style("""
                QPushButton {
                    padding: 10px 20px;
                    background-color: #a50;
                    border: none;
                    border-radius: 6px;
                    color: #fff;
                    font-size: 14px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #b60;
                }
                QPushButton:pressed {
                    background-color: #940;
                }
            """))
        else:
            # État "Disconnected"
            if slider_auto_reconnect and cam_data.slider_websocket_client and cam_data.slider_websocket_client.running:
                # Des tentatives automatiques sont en cours
                self.workspace_4_slider_status_led.setStyleSheet("font-size: 24px; color: #ffa500;")  # Orange
                self.workspace_4_slider_status_label.setText("Déconnecté (reconnexion auto...)")
                self.workspace_4_slider_status_label.setStyleSheet(f"font-size: {self._scale_font(14)}px; color: #ffa500; font-weight: bold;")
                self.workspace_4_slider_connect_btn.setEnabled(True)
                self.workspace_4_slider_disconnect_btn.setText("Arrêter les tentatives")
                self.workspace_4_slider_disconnect_btn.setEnabled(True)
                self.workspace_4_slider_disconnect_btn.setStyleSheet(self._scale_style("""
                    QPushButton {
                        padding: 10px 20px;
                        background-color: #ff8c00;
                        border: none;
                        border-radius: 6px;
                        color: #fff;
                        font-size: 14px;
                        font-weight: bold;
                    }
                    QPushButton:hover {
                        background-color: #ff9f33;
                    }
                    QPushButton:pressed {
                        background-color: #e67e00;
                    }
                """))
            else:
                # Aucune tentative automatique
                self.workspace_4_slider_status_led.setStyleSheet("font-size: 24px; color: #f00;")  # Rouge
                self.workspace_4_slider_status_label.setText("Déconnecté")
                self.workspace_4_slider_status_label.setStyleSheet(f"font-size: {self._scale_font(14)}px; color: #f00; font-weight: bold;")
                self.workspace_4_slider_connect_btn.setEnabled(True)
                self.workspace_4_slider_disconnect_btn.setText("Arrêter les tentatives")
                self.workspace_4_slider_disconnect_btn.setEnabled(False)  # Pas de tentative à arrêter
                self.workspace_4_slider_disconnect_btn.setStyleSheet(self._scale_style("""
                    QPushButton {
                        padding: 10px 20px;
                        background-color: #444;
                        border: none;
                        border-radius: 6px;
                        color: #888;
                        font-size: 14px;
                        font-weight: bold;
                    }
                    QPushButton:disabled {
                        background-color: #444;
                        color: #888;
                    }
                """))
    
    def on_workspace_4_save_camera_config(self):
        """Sauvegarde la configuration de la caméra active."""
        camera_id = self.active_camera_id
        cam_data = self.cameras[camera_id]
        
        # Récupérer les valeurs des champs
        new_url = self.workspace_4_url_input.text().strip()
        new_username = self.workspace_4_username_input.text().strip()
        new_password = self.workspace_4_password_input.text().strip()
        new_slider_ip = self.workspace_4_slider_ip_input.text().strip()
        try:
            new_companion_page = int(self.workspace_4_companion_input.text().strip() or str(camera_id))
        except ValueError:
            new_companion_page = camera_id
        
        # Sauvegarder l'ancien slider_ip pour vérifier s'il a changé
        old_slider_ip = cam_data.slider_ip
        
        # Mettre à jour les valeurs
        cam_data.url = new_url.rstrip('/')
        cam_data.username = new_username
        cam_data.password = new_password
        cam_data.slider_ip = new_slider_ip
        cam_data.companion_page = new_companion_page
        
        # Arrêter l'ancien WebSocket slider si existant
        if cam_data.slider_websocket_client:
            cam_data.slider_websocket_client.stop()
            cam_data.slider_websocket_client = None
        
        # Mettre à jour le SliderController si l'IP a changé
        if old_slider_ip != new_slider_ip:
            if new_slider_ip:
                slider_controller = SliderController(new_slider_ip)
                self.slider_controllers[camera_id] = slider_controller
                # Vérifier que le slider répond
                try:
                    status = slider_controller.get_status(silent=True)
                    if status is not None:
                        logger.info(f"Slider {new_slider_ip} répond correctement")
                    else:
                        logger.warning(f"Slider {new_slider_ip} configuré mais ne répond pas")
                except Exception as e:
                    logger.warning(f"Erreur lors de la vérification du slider {new_slider_ip}: {e}")
            else:
                self.slider_controllers[camera_id] = None
        
        # Sauvegarder dans le fichier
        self.save_cameras_config()
        
        # Mettre à jour l'indicateur de statut du slider
        QTimer.singleShot(100, self.update_slider_status_indicator)
        
        # Si la caméra était déjà connectée et qu'on a changé le slider_ip, démarrer le nouveau WebSocket slider
        if cam_data.connected and new_slider_ip:
            try:
                def position_update_callback(data):
                    self.on_slider_position_update(data, camera_id=camera_id)
                
                slider_ws_client = SliderWebSocketClient(
                    slider_ip=new_slider_ip,
                    on_position_update_callback=position_update_callback,
                    on_connection_status_callback=None,
                    auto_reconnect_enabled=getattr(cam_data, 'slider_auto_reconnect_enabled', True)
                )
                slider_ws_client.start()
                cam_data.slider_websocket_client = slider_ws_client
                logger.info(f"WebSocket slider démarré pour caméra {camera_id}")
            except Exception as e:
                logger.error(f"Erreur lors du démarrage du WebSocket slider: {e}")
        
        logger.info(f"Configuration caméra {camera_id} sauvegardée")
    
    def on_workspace_4_camera_connect(self):
        """Lance la connexion de la caméra active."""
        camera_id = self.active_camera_id
        cam_data = self.cameras[camera_id]
        
        # Vérifier que la caméra n'est pas déjà connectée ou en cours de connexion
        if cam_data.connected or getattr(cam_data, 'connecting', False):
            return
        
        url = self.workspace_4_url_input.text().strip()
        username = self.workspace_4_username_input.text().strip()
        password = self.workspace_4_password_input.text().strip()
        
        if not url:
            logger.warning(f"URL manquante pour caméra {camera_id}")
            return
        
        # Réactiver la reconnexion automatique (car l'utilisateur demande explicitement la connexion)
        cam_data.auto_reconnect_enabled = True
        
        # Marquer comme "connecting"
        cam_data.connecting = True
        self.update_workspace_4_camera_status(camera_id)
        
        # Lancer la connexion (qui est asynchrone)
        self.connect_to_camera(camera_id, url, username, password)
        
        # Le statut sera mis à jour automatiquement via on_websocket_status
    
    def on_workspace_4_camera_disconnect(self):
        """Arrête la connexion de la caméra active et interrompt les tentatives en cours."""
        camera_id = self.active_camera_id
        cam_data = self.cameras[camera_id]
        
        # Arrêter les tentatives de connexion automatique si en cours
        cam_data.connecting = False
        
        # Désactiver la reconnexion automatique
        cam_data.auto_reconnect_enabled = False
        
        # Arrêter le WebSocket client s'il existe et qu'il tente de se reconnecter
        if cam_data.websocket_client:
            cam_data.websocket_client.stop()  # Cela arrête aussi les tentatives de reconnexion
        
        # Déconnecter la caméra
        if cam_data.connected:
            self.disconnect_from_camera(camera_id)
        
        # Mettre à jour l'affichage
        self.update_workspace_4_camera_status(camera_id)
    
    def on_workspace_4_slider_connect(self):
        """Lance la connexion du slider pour la caméra active."""
        camera_id = self.active_camera_id
        cam_data = self.cameras[camera_id]
        
        # Vérifier que le slider n'est pas déjà connecté ou en cours de connexion
        slider_connected = False
        if cam_data.slider_websocket_client:
            slider_connected = getattr(cam_data.slider_websocket_client, 'connected', False)
        
        if slider_connected or getattr(cam_data, 'slider_connecting', False):
            return
        
        slider_ip = self.workspace_4_slider_ip_input.text().strip()
        if not slider_ip:
            logger.warning(f"IP slider manquante pour caméra {camera_id}")
            return
        
        # Réactiver la reconnexion automatique (car l'utilisateur demande explicitement la connexion)
        cam_data.slider_auto_reconnect_enabled = True
        
        # Arrêter l'ancien WebSocket slider si existant
        if cam_data.slider_websocket_client:
            try:
                cam_data.slider_websocket_client.stop()
            except Exception as e:
                logger.error(f"Erreur lors de l'arrêt de l'ancien WebSocket slider: {e}")
            cam_data.slider_websocket_client = None
        
        # Marquer comme "connecting"
        cam_data.slider_connecting = True
        self.update_workspace_4_slider_status(camera_id)
        
        # Créer et démarrer le WebSocket slider
        try:
            def position_update_callback(data):
                self.on_slider_position_update(data, camera_id=camera_id)
            
            def connection_status_callback(connected: bool, message: str):
                """Callback pour le statut de connexion du slider."""
                cam_data.slider_connecting = False
                if cam_data.slider_websocket_client:
                    cam_data.slider_websocket_client.connected = connected
                # Mettre à jour l'affichage
                QTimer.singleShot(100, lambda: self.update_workspace_4_slider_status(camera_id))
            
            slider_ws_client = SliderWebSocketClient(
                slider_ip=slider_ip,
                on_position_update_callback=position_update_callback,
                on_connection_status_callback=connection_status_callback,
                auto_reconnect_enabled=getattr(cam_data, 'slider_auto_reconnect_enabled', True)
            )
            slider_ws_client.start()
            cam_data.slider_websocket_client = slider_ws_client
            logger.info(f"Connexion slider WebSocket démarrée pour caméra {camera_id}")
        except Exception as e:
            logger.error(f"Erreur lors du démarrage du WebSocket slider: {e}")
            cam_data.slider_connecting = False
            self.update_workspace_4_slider_status(camera_id)
    
    def on_workspace_4_slider_disconnect(self):
        """Arrête la connexion du slider et interrompt les tentatives en cours."""
        camera_id = self.active_camera_id
        cam_data = self.cameras[camera_id]
        
        # Arrêter les tentatives de connexion si en cours
        cam_data.slider_connecting = False
        
        # Désactiver la reconnexion automatique
        cam_data.slider_auto_reconnect_enabled = False
        
        # Arrêter le WebSocket slider si existant
        if cam_data.slider_websocket_client:
            try:
                # Désactiver la reconnexion automatique dans le WebSocket client
                cam_data.slider_websocket_client.auto_reconnect_enabled = False
                cam_data.slider_websocket_client.stop()
            except Exception as e:
                logger.error(f"Erreur lors de l'arrêt du WebSocket slider: {e}")
            cam_data.slider_websocket_client = None
        
        # Mettre à jour l'affichage
        self.update_workspace_4_slider_status(camera_id)
    
    def update_atem_status(self):
        """Met à jour l'affichage de l'état ATEM dans le dialog si ouvert."""
        # Si le dialog ATEM est ouvert, mettre à jour son affichage
        if hasattr(self, 'atem_dialog') and self.atem_dialog:
            self.atem_dialog.update_atem_status()
    
    def on_atem_connect_clicked(self):
        """Gère le clic sur le bouton Connecter/Déconnecter/Arrêter les tentatives ATEM."""
        connected = self.atem_config.get("connected", False)
        auto_reconnect = self.atem_config.get("auto_reconnect_enabled", True)
        controller_running = False
        if self.atem_controller:
            controller_running = getattr(self.atem_controller, 'running', False)
        
        if connected:
            # Si connecté, déconnecter
            self.disconnect_atem()
        elif auto_reconnect and controller_running:
            # Si pas connecté mais des tentatives sont en cours, arrêter les tentatives
            logger.info("Arrêt des tentatives de reconnexion ATEM demandé par l'utilisateur")
            self.atem_config["auto_reconnect_enabled"] = False
            if self.atem_controller:
                # Désactiver auto_retry dans le controller
                self.atem_controller.auto_retry = False
                # Arrêter le thread de reconnexion si en cours
                self.atem_controller.running = False
                # Déconnecter proprement
                self.atem_controller.disconnect()
        else:
            # Si pas connecté et pas de tentatives en cours, connecter
            # Réactiver la reconnexion automatique (car l'utilisateur demande explicitement la connexion)
            self.atem_config["auto_reconnect_enabled"] = True
            # Réinitialiser le controller avec le nouveau flag si nécessaire
            if self.atem_controller:
                # Si le controller existe mais auto_reconnect a changé, le réinitialiser
                old_auto_retry = getattr(self.atem_controller, 'auto_retry', True)
                if old_auto_retry != self.atem_config["auto_reconnect_enabled"]:
                    self.init_atem_controller()
                else:
                    self.connect_atem()
            else:
                self.connect_atem()
        
        # Mettre à jour l'affichage du dialog si ouvert
        QTimer.singleShot(100, self.update_atem_status)


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

