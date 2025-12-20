#!/usr/bin/env python3
"""
Interface web pour contrôler le focus de la caméra Blackmagic.
Fournit un slider vertical et l'affichage en temps réel de la valeur du focus.
"""

from flask import Flask, render_template_string, jsonify, request
from flask_socketio import SocketIO, emit
import threading
import time
import queue
from blackmagic_focus_control import BlackmagicFocusController, BlackmagicWebSocketClient
import argparse
import logging

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading', ping_timeout=60, ping_interval=25)
controller = None
websocket_client = None
event_queue = queue.Queue()
logging.basicConfig(level=logging.INFO)

# Template HTML avec slider vertical
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Contrôle Focus Blackmagic</title>
    <script src="https://cdn.socket.io/4.5.4/socket.io.min.js"></script>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: Arial, sans-serif;
            background: #2a2a2a;
            min-height: 100vh;
            padding: 20px;
            color: #fff;
            margin: 0;
            position: relative;
        }
        
        .global-status {
            position: fixed;
            top: 20px;
            right: 20px;
            padding: 10px 20px;
            font-size: 12px;
            border-radius: 4px;
            background: #1a1a1a;
            border: 1px solid #444;
            z-index: 1000;
        }
        
        .global-status.connected {
            color: #0f0;
            border-color: #0f0;
        }
        
        .global-status.disconnected {
            color: #f00;
            border-color: #f00;
        }
        
        .container {
            background: #1a1a1a;
            border: 1px solid #444;
            padding: 30px;
            max-width: 200px;
            width: 100%;
            box-shadow: 0 4px 8px rgba(0, 0, 0, 0.5);
            min-height: 600px;
            display: flex;
            flex-direction: column;
        }
        
        .iris-display {
            text-align: center;
            margin-bottom: 30px;
            min-height: 120px;
            display: flex;
            flex-direction: column;
            justify-content: flex-start;
        }
        
        .iris-value-sent {
            font-size: 24px;
            font-weight: bold;
            color: #ff0;
            margin-bottom: 3px;
            font-family: 'Courier New', monospace;
        }
        
        .iris-value-actual {
            font-size: 24px;
            font-weight: bold;
            color: #0ff;
            margin-bottom: 5px;
            font-family: 'Courier New', monospace;
        }
        
        .iris-label {
            font-size: 12px;
            color: #aaa;
            text-transform: uppercase;
            margin-bottom: 10px;
        }
        
        .iris-additional {
            font-size: 11px;
            color: #888;
            margin-top: 5px;
        }
        
        h1 {
            text-align: center;
            color: #fff;
            margin-bottom: 20px;
            font-size: 20px;
            font-weight: normal;
        }
        
        .focus-display {
            text-align: center;
            margin-bottom: 30px;
            min-height: 120px;
            display: flex;
            flex-direction: column;
            justify-content: flex-start;
        }
        
        .focus-value {
            font-size: 36px;
            font-weight: bold;
            color: #0f0;
            margin-bottom: 5px;
            font-family: 'Courier New', monospace;
        }
        
        .focus-value-sent {
            font-size: 24px;
            font-weight: bold;
            color: #ff0;
            margin-bottom: 3px;
            font-family: 'Courier New', monospace;
        }
        
        .focus-value-actual {
            font-size: 24px;
            font-weight: bold;
            color: #0ff;
            margin-bottom: 5px;
            font-family: 'Courier New', monospace;
        }
        
        .focus-label {
            font-size: 12px;
            color: #aaa;
            text-transform: uppercase;
            margin-bottom: 10px;
        }
        
        .value-row {
            display: flex;
            justify-content: space-around;
            margin-top: 10px;
        }
        
        .value-item {
            text-align: center;
        }
        
        .value-item-label {
            font-size: 10px;
            color: #888;
            margin-bottom: 3px;
        }
        
        .slider-container {
            display: flex;
            justify-content: center;
            align-items: stretch;
            height: 320px;
            margin: 20px 0;
            flex-shrink: 0;
        }
        
        .slider-row {
            display: flex;
            align-items: center;
            gap: 20px;
            height: 100%;
        }
        
        .slider-wrapper {
            position: relative;
            height: 100%;
            width: 60px;
        }
        
        input[type="range"] {
            -webkit-appearance: none;
            appearance: none;
            width: 300px;
            height: 60px;
            transform: rotate(-90deg);
            transform-origin: center;
            background: transparent;
            outline: none;
            position: absolute;
            left: -120px;
            top: 120px;
        }
        
        input[type="range"]::-webkit-slider-track {
            width: 300px;
            height: 8px;
            background: #333;
            border: 1px solid #555;
            border-radius: 4px;
        }
        
        input[type="range"]::-webkit-slider-thumb {
            -webkit-appearance: none;
            appearance: none;
            width: 20px;
            height: 50px;
            background: #666;
            border: 1px solid #888;
            border-radius: 3px;
            cursor: pointer;
            margin-top: -21px;
        }
        
        input[type="range"]::-webkit-slider-thumb:hover {
            background: #777;
        }
        
        input[type="range"]::-moz-range-track {
            width: 300px;
            height: 8px;
            background: #333;
            border: 1px solid #555;
            border-radius: 4px;
        }
        
        input[type="range"]::-moz-range-thumb {
            width: 20px;
            height: 50px;
            background: #666;
            border: 1px solid #888;
            border-radius: 3px;
            cursor: pointer;
        }
        
        .slider-labels {
            display: flex;
            flex-direction: column;
            align-items: center;
            margin-top: 10px;
            font-size: 11px;
            color: #aaa;
            height: 300px;
            justify-content: space-between;
            position: absolute;
            left: 70px;
            top: 0;
        }
        
        .status {
            text-align: center;
            margin-top: 15px;
            padding: 8px;
            font-size: 11px;
            color: #aaa;
        }
        
        .status.connected {
            color: #0f0;
        }
        
        .status.disconnected {
            color: #f00;
        }
        
        .button-group {
            display: flex;
            gap: 8px;
            margin-top: 15px;
        }
        
        button {
            flex: 1;
            padding: 8px;
            border: 1px solid #555;
            background: #333;
            color: #fff;
            font-size: 12px;
            cursor: pointer;
        }
        
        button:hover {
            background: #444;
        }
        
        .mode-selector {
            display: flex;
            gap: 5px;
            margin-bottom: 15px;
            justify-content: center;
        }
        
        .mode-button {
            padding: 6px 12px;
            font-size: 11px;
            border: 1px solid #555;
            background: #333;
            color: #aaa;
            cursor: pointer;
        }
        
        .mode-button.active {
            background: #555;
            color: #fff;
            border-color: #777;
        }
        
        .mode-button:hover {
            background: #444;
        }
        
        .control-buttons {
            display: flex;
            flex-direction: column;
            gap: 15px;
            align-items: center;
            margin: 30px 0;
        }
        
        .control-button {
            width: 60px;
            height: 60px;
            font-size: 24px;
            font-weight: bold;
            border: 2px solid #555;
            background: #333;
            color: #fff;
            cursor: pointer;
            border-radius: 8px;
            display: flex;
            align-items: center;
            justify-content: center;
            transition: all 0.2s;
        }
        
        .control-button:hover {
            background: #444;
            border-color: #777;
        }
        
        .control-button:active {
            background: #555;
            transform: scale(0.95);
        }
        
        .control-button:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }
        
        .toggle-button {
            width: 100%;
            padding: 20px;
            font-size: 16px;
            font-weight: bold;
            border: 2px solid #555;
            border-radius: 8px;
            cursor: pointer;
            transition: all 0.3s ease;
            text-align: center;
            background: #2a2a2a;
            color: #aaa;
        }
        
        .toggle-button.enabled {
            background: #0a5;
            color: #fff;
            border-color: #0f0;
        }
        
        .toggle-button.disabled {
            background: #2a2a2a;
            color: #aaa;
            border-color: #555;
        }
        
        .toggle-button:hover {
            opacity: 0.8;
        }
        
        .toggle-button:active {
            transform: scale(0.98);
        }
        
        .main-container {
            display: flex;
            gap: 20px;
            flex-wrap: wrap;
            justify-content: center;
            align-items: flex-start;
            min-height: calc(100vh - 40px);
            padding-top: 20px;
        }
        
        .spacer {
            flex: 1;
            min-height: 320px;
        }
    </style>
</head>
<body>
    <div class="global-status" id="globalStatus">Chargement...</div>
    <div class="main-container">
    <div class="container">
        <h1>Focus Control</h1>
        
        <div class="focus-display">
            <div class="focus-label">Focus Normalisé</div>
            <div class="value-row">
                <div class="value-item">
                    <div class="value-item-label">Envoyé</div>
                    <div class="focus-value-sent" id="focusValueSent">0.000</div>
                </div>
                <div class="value-item">
                    <div class="value-item-label">Réel (GET)</div>
                    <div class="focus-value-actual" id="focusValueActual">0.000</div>
                </div>
            </div>
        </div>
        
        <div class="slider-container">
            <div class="slider-row">
                <div class="slider-wrapper">
                <input 
                    type="range" 
                    id="focusSlider" 
                    min="0" 
                    max="1" 
                    step="0.001" 
                    value="0"
                    oninput="updateFocus(this.value)"
                    onmousedown="onSliderTouch()"
                    onmouseup="onSliderRelease()"
                    ontouchstart="onSliderTouch()"
                    ontouchend="onSliderRelease()"
                >
                <div class="slider-labels">
                    <span>1.0</span>
                    <span>0.5</span>
                    <span>0.0</span>
                </div>
                </div>
            </div>
        </div>
        
    </div>
    
    <div class="container">
        <h1>Iris Control</h1>
        
        <div class="iris-display">
            <div class="iris-label">Iris Normalisé</div>
            <div class="value-row">
                <div class="value-item">
                    <div class="value-item-label">Envoyé</div>
                    <div class="iris-value-sent" id="irisValueSent">0.000</div>
                </div>
                <div class="value-item">
                    <div class="value-item-label">Réel (GET)</div>
                    <div class="iris-value-actual" id="irisValueActual">0.000</div>
                </div>
            </div>
            <div class="iris-additional">
                <div>Aperture Stop: <span id="irisApertureStop">-</span></div>
            </div>
        </div>
        
        <div class="control-buttons">
            <button class="control-button" id="irisPlusBtn" onclick="incrementIris()">+</button>
            <button class="control-button" id="irisMinusBtn" onclick="decrementIris()">-</button>
        </div>
        
    </div>
    
    <div class="container">
        <h1>Gain Control</h1>
        
        <div class="iris-display">
            <div class="iris-label">Gain (dB)</div>
            <div class="value-row">
                <div class="value-item">
                    <div class="value-item-label">Envoyé</div>
                    <div class="iris-value-sent" id="gainValueSent">0</div>
                </div>
                <div class="value-item">
                    <div class="value-item-label">Réel (GET)</div>
                    <div class="iris-value-actual" id="gainValueActual">0</div>
                </div>
            </div>
        </div>
        
        <div class="control-buttons">
            <button class="control-button" id="gainPlusBtn" onclick="incrementGain()">+</button>
            <button class="control-button" id="gainMinusBtn" onclick="decrementGain()">-</button>
        </div>
        
    </div>
    
    <div class="container">
        <h1>⚡ Shutter Control</h1>
        
        <div class="iris-display">
            <div class="iris-label">Shutter Speed (1/Xs)</div>
            <div class="value-row">
                <div class="value-item">
                    <div class="value-item-label">Envoyé</div>
                    <div class="iris-value-sent" id="shutterValueSent">-</div>
                </div>
                <div class="value-item">
                    <div class="value-item-label">Réel (GET)</div>
                    <div class="iris-value-actual" id="shutterValueActual">-</div>
                </div>
            </div>
        </div>
        
        <div class="control-buttons">
            <button class="control-button" id="shutterPlusBtn" onclick="incrementShutter()">+</button>
            <button class="control-button" id="shutterMinusBtn" onclick="decrementShutter()">-</button>
        </div>
        
    </div>
    
    <div class="container">
        <h1>🔍 Zoom Control</h1>
        
        <div class="iris-display">
            <div class="iris-label">Focale (Zoom)</div>
            <div class="value-row">
                <div class="value-item">
                    <div class="value-item-label">Focale</div>
                    <div class="iris-value-actual" id="zoomFocalLength">-</div>
                </div>
                <div class="value-item">
                    <div class="value-item-label">Normalisé</div>
                    <div class="iris-value-actual" id="zoomNormalised">-</div>
                </div>
            </div>
            <div class="iris-additional">
                <div>Focale en millimètres</div>
            </div>
        </div>
        
        <div class="spacer"></div>
    </div>
    
    <div class="container">
        <h1>Contrôles</h1>
        
        <div class="control-buttons" style="flex-direction: column; gap: 15px; align-items: stretch; margin: 20px 0;">
            <button class="toggle-button disabled" id="zebraToggle" onclick="toggleZebra()">
                Zebra: OFF
            </button>
            
            <button class="toggle-button disabled" id="focusAssistToggle" onclick="toggleFocusAssist()">
                Focus Assist: OFF
            </button>
            
            <button class="toggle-button disabled" id="falseColorToggle" onclick="toggleFalseColor()">
                False Color: OFF
            </button>
            
            <button class="toggle-button disabled" id="cleanfeedToggle" onclick="toggleCleanfeed()">
                Cleanfeed: OFF
            </button>
            
            <button class="control-button" id="autofocusBtn" onclick="doAutoFocus()" style="width: 100%; margin-top: 10px;">
                🔍 Autofocus
            </button>
        </div>
        
        <div class="spacer"></div>
    </div>
    </div>
    
    <script>
        // Fonction pour mettre à jour le statut global (définie en premier)
        function updateGlobalStatus(status, message) {
            
            const statusEl = document.getElementById('globalStatus');
            if (statusEl) {
                statusEl.className = 'global-status ' + status;
                statusEl.textContent = message;
                
            } else {
                
            }
        }
        
        // Variables globales
        let socket = null;
        let websocketEventsReceived = false;
        
        let isUpdating = false;
        let sentValue = 0;
        let actualValue = 0;
        let sliderLocked = false;
        let sliderLockTimeout = null;
        
        // Throttling pour limiter la fréquence d'envoi
        let lastFocusSendTime = 0;
        let lastIrisSendTime = 0;
        let lastGainSendTime = 0;
        let lastShutterSendTime = 0;
        const FOCUS_MIN_INTERVAL = 100; // 10 fois/seconde max (100ms)
        const OTHER_MIN_INTERVAL = 500; // 2 fois/seconde max (500ms)
        let pendingFocusValue = null;
        let pendingIrisValue = null;
        let pendingGainValue = null;
        let pendingShutterValue = null;
        
        // Quand on touche le slider
        
        window.onSliderTouch = function() {
            
            sliderLocked = true;
            // Annuler le timeout précédent s'il existe
            if (sliderLockTimeout) {
                clearTimeout(sliderLockTimeout);
            }
        };
        
        // Quand on relâche le slider
        
        window.onSliderRelease = function() {
            
            // Verrouiller pendant 2 secondes après le relâchement
            if (sliderLockTimeout) {
                clearTimeout(sliderLockTimeout);
            }
            sliderLockTimeout = setTimeout(() => {
                sliderLocked = false;
                // Remettre le slider à la valeur réelle après 2 secondes
                const slider = document.getElementById('focusSlider');
                if (slider && actualValue !== null && actualValue !== undefined) {
                    slider.value = actualValue;
                }
            }, 2000); // 2 secondes
        };
        
        // Fonction pour envoyer le focus avec throttling
        function sendFocusValue(value) {
            const now = Date.now();
            const timeSinceLastSend = now - lastFocusSendTime;
            
            if (timeSinceLastSend < FOCUS_MIN_INTERVAL) {
                // Trop tôt, stocker la valeur pour l'envoyer plus tard
                pendingFocusValue = value;
                setTimeout(() => {
                    if (pendingFocusValue !== null) {
                        const val = pendingFocusValue;
                        pendingFocusValue = null;
                        sendFocusValue(val);
                    }
                }, FOCUS_MIN_INTERVAL - timeSinceLastSend);
                return;
            }
            
            lastFocusSendTime = now;
            
            fetch('/set_focus', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ value: value })
            })
            .then(response => {
                
                return response.json();
            })
            .then(data => {
                
                if (data.success) {
                    // Ne pas mettre à jour le statut ici, on attend les événements WebSocket
                    // La valeur réelle sera mise à jour via WebSocket
                } else {
                    updateGlobalStatus('disconnected', 'Erreur: ' + (data.error || 'Inconnue'));
                }
            })
            .catch(error => {
                
                updateGlobalStatus('disconnected', 'Erreur de connexion');
                console.error('Error:', error);
            });
        }
        
        // Mettre à jour le focus quand le slider change
        
        window.updateFocus = function(value) {
            
            if (isUpdating) return;
            
            const numValue = parseFloat(value);
            sentValue = numValue;
            
            // Mettre à jour le slider avec la valeur envoyée
            const slider = document.getElementById('focusSlider');
            if (slider) {
                slider.value = numValue;
            }
            
            document.getElementById('focusValueSent').textContent = numValue.toFixed(3);
            
            // Verrouiller le slider pendant la manipulation
            sliderLocked = true;
            if (sliderLockTimeout) {
                clearTimeout(sliderLockTimeout);
            }
            
            // Envoyer avec throttling
            sendFocusValue(numValue);
        };
        
        // Handler WebSocket pour les changements de focus
        if (socket) {
        socket.on('focus_changed', (data) => {
                if (!websocketEventsReceived) {
                    // Premier événement reçu, arrêter le polling de secours
                    websocketEventsReceived = true;
                    stopPollingFallback();
                    console.log('WebSocket actif, arrêt du polling de secours');
                }
            const value = data.normalised !== undefined ? data.normalised : data.value;
            if (value !== null && value !== undefined) {
                actualValue = value;
                document.getElementById('focusValueActual').textContent = value.toFixed(3);
                
                // Mettre à jour le slider seulement si on n'est pas en train de le manipuler
                if (!sliderLocked) {
                    const slider = document.getElementById('focusSlider');
                    if (slider) {
                        slider.value = value;
                    }
                }
                
                    // Si on reçoit des événements, le WebSocket fonctionne
                    updateGlobalStatus('connected', 'WebSocket caméra: Actif ✓');
            } else {
                console.warn('focus_changed: value is null or undefined', data);
            }
        });
        }
        
        // Réinitialiser le focus à 0.5
        function resetFocus() {
            updateFocus(0.5);
        }
        
        // Variables pour l'iris
        let isUpdatingIris = false;
        let sentIrisValue = 0;
        let actualIrisValue = 0;
        let irisLocked = false;
        let irisLockTimeout = null;
        
        // Incrémenter l'iris
        function incrementIris() {
            if (isUpdatingIris) return;
            const currentValue = actualIrisValue !== null && actualIrisValue !== undefined ? actualIrisValue : sentIrisValue;
            const newValue = Math.min(1.0, currentValue + 0.05);
            updateIrisValue(newValue);
        }
        
        // Décrémenter l'iris
        function decrementIris() {
            if (isUpdatingIris) return;
            const currentValue = actualIrisValue !== null && actualIrisValue !== undefined ? actualIrisValue : sentIrisValue;
            const newValue = Math.max(0.0, currentValue - 0.05);
            updateIrisValue(newValue);
        }
        
        // Mettre à jour la valeur de l'iris
        function updateIrisValue(value) {
            if (isUpdatingIris) return;
            
            const numValue = Math.max(0.0, Math.min(1.0, parseFloat(value)));
            sentIrisValue = numValue;
            document.getElementById('irisValueSent').textContent = numValue.toFixed(3);
            
            // Envoyer avec throttling
            sendIrisValue(numValue);
        }
        
        // Fonction pour envoyer l'iris avec throttling
        function sendIrisValue(value) {
            const now = Date.now();
            const timeSinceLastSend = now - lastIrisSendTime;
            
            if (timeSinceLastSend < OTHER_MIN_INTERVAL) {
                // Trop tôt, stocker la valeur pour l'envoyer plus tard
                pendingIrisValue = value;
                setTimeout(() => {
                    if (pendingIrisValue !== null) {
                        const val = pendingIrisValue;
                        pendingIrisValue = null;
                        sendIrisValue(val);
                    }
                }, OTHER_MIN_INTERVAL - timeSinceLastSend);
                return;
            }
            
            lastIrisSendTime = now;
            
            fetch('/set_iris', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ value: value })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    // Ne pas mettre à jour le statut ici, on attend les événements WebSocket
                    // La valeur réelle sera mise à jour via WebSocket
                } else {
                    updateGlobalStatus('disconnected', 'Erreur: ' + (data.error || 'Inconnue'));
                }
            })
            .catch(error => {
                updateGlobalStatus('disconnected', 'Erreur de connexion');
                console.error('Error:', error);
            });
        }
        
        // Handler WebSocket pour les changements d'iris
        if (socket) {
        socket.on('iris_changed', (data) => {
            if (!websocketEventsReceived) {
                websocketEventsReceived = true;
                stopPollingFallback();
                console.log('WebSocket actif, arrêt du polling de secours');
            }
            const normalised = data.normalised;
            const apertureStop = data.apertureStop;
            
            if (normalised !== null && normalised !== undefined) {
                actualIrisValue = normalised;
                document.getElementById('irisValueActual').textContent = normalised.toFixed(3);
            }
            
            if (apertureStop !== null && apertureStop !== undefined) {
                document.getElementById('irisApertureStop').textContent = apertureStop.toFixed(2);
            } else {
                document.getElementById('irisApertureStop').textContent = '-';
            }
            
            // Si on reçoit des événements, le WebSocket fonctionne
            updateGlobalStatus('connected', 'WebSocket caméra: Actif ✓');
            console.log('Iris mis à jour via WebSocket:', normalised);
        });
        }
        
        // Réinitialiser l'iris à 0.5
        function resetIris() {
            updateIrisValue(0.5);
        }
        
        // Handlers WebSocket pour les changements de paramètres
        
        // Handler pour les changements de zoom
        if (socket) {
        socket.on('zoom_changed', (data) => {
            if (!websocketEventsReceived) {
                websocketEventsReceived = true;
                stopPollingFallback();
                console.log('WebSocket actif, arrêt du polling de secours');
            }
            const focal = data.focalLength;
            const norm = data.normalised;
            
            if (focal !== null && focal !== undefined) {
                document.getElementById('zoomFocalLength').textContent = focal + ' mm';
            } else {
                document.getElementById('zoomFocalLength').textContent = '-';
            }
            
            if (norm !== null && norm !== undefined) {
                document.getElementById('zoomNormalised').textContent = norm.toFixed(3);
            } else {
                document.getElementById('zoomNormalised').textContent = '-';
            }
            
            // Si on reçoit des événements, le WebSocket fonctionne
            updateGlobalStatus('connected', 'WebSocket caméra: Actif ✓');
            console.log('Zoom mis à jour via WebSocket:', focal, norm);
        });
        }
        
        // Variables pour le gain
        let isUpdatingGain = false;
        let sentGainValue = 0;
        let actualGainValue = 0;
        let gainLocked = false;
        let gainLockTimeout = null;
        let supportedGains = [];
        
        // Charger les gains supportés
        function loadSupportedGains() {
            fetch('/get_supported_gains')
                .then(response => response.json())
                .then(data => {
                    if (data.success && data.supportedGains && data.supportedGains.length > 0) {
                        supportedGains = data.supportedGains.sort((a, b) => a - b);
                    }
                })
                .catch(error => {
                    console.error('Error loading supported gains:', error);
                });
        }
        
        // Trouver la valeur de gain la plus proche dans la liste supportée
        function findNearestGain(value) {
            if (supportedGains.length === 0) return value;
            return supportedGains.reduce((prev, curr) => {
                return Math.abs(curr - value) < Math.abs(prev - value) ? curr : prev;
            });
        }
        
        // Incrémenter le gain
        function incrementGain() {
            if (isUpdatingGain || supportedGains.length === 0) return;
            const currentValue = actualGainValue !== null && actualGainValue !== undefined ? actualGainValue : sentGainValue;
            const currentIndex = supportedGains.indexOf(currentValue);
            if (currentIndex < supportedGains.length - 1) {
                updateGainValue(supportedGains[currentIndex + 1]);
            }
        }
        
        // Décrémenter le gain
        function decrementGain() {
            if (isUpdatingGain || supportedGains.length === 0) return;
            const currentValue = actualGainValue !== null && actualGainValue !== undefined ? actualGainValue : sentGainValue;
            const currentIndex = supportedGains.indexOf(currentValue);
            if (currentIndex > 0) {
                updateGainValue(supportedGains[currentIndex - 1]);
            }
        }
        
        // Mettre à jour la valeur du gain
        function updateGainValue(value) {
            if (isUpdatingGain) return;
            
            sentGainValue = value;
            document.getElementById('gainValueSent').textContent = value + ' dB';
            
            // Envoyer avec throttling
            sendGainValue(value);
        }
        
        // Fonction pour envoyer le gain avec throttling
        function sendGainValue(value) {
            const now = Date.now();
            const timeSinceLastSend = now - lastGainSendTime;
            
            if (timeSinceLastSend < OTHER_MIN_INTERVAL) {
                // Trop tôt, stocker la valeur pour l'envoyer plus tard
                pendingGainValue = value;
                setTimeout(() => {
                    if (pendingGainValue !== null) {
                        const val = pendingGainValue;
                        pendingGainValue = null;
                        sendGainValue(val);
                    }
                }, OTHER_MIN_INTERVAL - timeSinceLastSend);
                return;
            }
            
            lastGainSendTime = now;
            
            fetch('/set_gain', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ value: value })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    // Ne pas mettre à jour le statut ici, on attend les événements WebSocket
                    // La valeur réelle sera mise à jour via WebSocket
                } else {
                    updateGlobalStatus('disconnected', 'Erreur: ' + (data.error || 'Inconnue'));
                }
            })
            .catch(error => {
                updateGlobalStatus('disconnected', 'Erreur de connexion');
                console.error('Error:', error);
            });
        }
        
        // Récupérer la valeur actuelle du gain (GET)
        // Handler WebSocket pour les changements de gain
        if (socket) {
        socket.on('gain_changed', (data) => {
            if (!websocketEventsReceived) {
                websocketEventsReceived = true;
                stopPollingFallback();
                console.log('WebSocket actif, arrêt du polling de secours');
            }
            const value = data.gain !== undefined ? data.gain : data.value;
            if (value !== null && value !== undefined) {
                actualGainValue = value;
                document.getElementById('gainValueActual').textContent = value + ' dB';
                // Si on reçoit des événements, le WebSocket fonctionne
                updateGlobalStatus('connected', 'WebSocket caméra: Actif ✓');
                console.log('Gain mis à jour via WebSocket:', value);
            } else {
                console.warn('gain_changed: value is null or undefined', data);
            }
        });
        }
        
        // Réinitialiser le gain à 0
        function resetGain() {
            if (supportedGains.length > 0) {
                updateGainValue(supportedGains[0]);
            } else {
                updateGainValue(0);
            }
        }
        
        // Variables pour le shutter
        let isUpdatingShutter = false;
        let sentShutterValue = 0;
        let actualShutterValue = 0;
        let supportedShutterSpeeds = [];
        
        // Charger les shutters supportés (seulement ShutterSpeed)
        function loadSupportedShutters() {
            fetch('/get_supported_shutters')
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        supportedShutterSpeeds = (data.shutterSpeeds || []).sort((a, b) => a - b);
                    }
                })
                .catch(error => {
                    console.error('Error loading supported shutters:', error);
                });
        }
        
        // Incrémenter le shutter
        function incrementShutter() {
            if (isUpdatingShutter || supportedShutterSpeeds.length === 0) return;
            const currentValue = actualShutterValue !== null && actualShutterValue !== undefined ? actualShutterValue : sentShutterValue;
            const currentIndex = supportedShutterSpeeds.indexOf(currentValue);
            if (currentIndex < supportedShutterSpeeds.length - 1) {
                updateShutterValue(supportedShutterSpeeds[currentIndex + 1]);
            }
        }
        
        // Décrémenter le shutter
        function decrementShutter() {
            if (isUpdatingShutter || supportedShutterSpeeds.length === 0) return;
            const currentValue = actualShutterValue !== null && actualShutterValue !== undefined ? actualShutterValue : sentShutterValue;
            const currentIndex = supportedShutterSpeeds.indexOf(currentValue);
            if (currentIndex > 0) {
                updateShutterValue(supportedShutterSpeeds[currentIndex - 1]);
            }
        }
        
        // Mettre à jour la valeur du shutter
        function updateShutterValue(value) {
            if (isUpdatingShutter) return;
            
            sentShutterValue = value;
            document.getElementById('shutterValueSent').textContent = `1/${value}s`;
            
            // Envoyer avec throttling
            sendShutterValue(value, 'ShutterSpeed');
        }
        
        // Fonction pour envoyer le shutter avec throttling
        function sendShutterValue(value, mode) {
            const now = Date.now();
            const timeSinceLastSend = now - lastShutterSendTime;
            
            if (timeSinceLastSend < OTHER_MIN_INTERVAL) {
                // Trop tôt, stocker la valeur pour l'envoyer plus tard
                pendingShutterValue = { value: value, mode: mode };
                setTimeout(() => {
                    if (pendingShutterValue !== null) {
                        const val = pendingShutterValue.value;
                        const m = pendingShutterValue.mode;
                        pendingShutterValue = null;
                        sendShutterValue(val, m);
                    }
                }, OTHER_MIN_INTERVAL - timeSinceLastSend);
                return;
            }
            
            lastShutterSendTime = now;
            
            fetch('/set_shutter', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ value: value, mode: mode })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    // Ne pas mettre à jour le statut ici, on attend les événements WebSocket
                    // La valeur réelle sera mise à jour via WebSocket
                } else {
                    updateGlobalStatus('disconnected', 'Erreur: ' + (data.error || 'Inconnue'));
                }
            })
            .catch(error => {
                updateGlobalStatus('disconnected', 'Erreur de connexion');
                console.error('Error:', error);
            });
        }
        
        // Récupérer la valeur actuelle du shutter (GET)
        // Handler WebSocket pour les changements de shutter
        if (socket) {
        socket.on('shutter_changed', (data) => {
            if (!websocketEventsReceived) {
                websocketEventsReceived = true;
                stopPollingFallback();
                console.log('WebSocket actif, arrêt du polling de secours');
            }
            const value = data.shutterSpeed;
            if (value !== null && value !== undefined) {
                actualShutterValue = value;
                document.getElementById('shutterValueActual').textContent = `1/${value}s`;
                // Si on reçoit des événements, le WebSocket fonctionne
                updateGlobalStatus('connected', 'WebSocket caméra: Actif ✓');
                console.log('Shutter mis à jour via WebSocket:', value);
            } else {
                console.warn('shutter_changed: value is null or undefined', data);
            }
        });
        }
        
        // Variables pour les toggles
        let zebraEnabled = false;
        let focusAssistEnabled = false;
        let falseColorEnabled = false;
        let cleanfeedEnabled = false;
        
        // Fonction pour mettre à jour l'apparence d'un bouton toggle
        function updateToggleButton(buttonId, enabled, label) {
            const button = document.getElementById(buttonId);
            if (button) {
                button.className = enabled ? 'toggle-button enabled' : 'toggle-button disabled';
                button.textContent = label + ': ' + (enabled ? 'ON' : 'OFF');
            }
        }
        
        // Toggle Zebra - rendre accessible globalement
        window.toggleZebra = function() {
            const newState = !zebraEnabled;
            zebraEnabled = newState;
            updateToggleButton('zebraToggle', newState, 'Zebra');
            
            fetch('/set_zebra', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ enabled: newState })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    updateGlobalStatus('connected', 'Connecté');
                } else {
                    // Revert on error
                    zebraEnabled = !newState;
                    updateToggleButton('zebraToggle', !newState, 'Zebra');
                    updateGlobalStatus('disconnected', 'Erreur: ' + (data.error || 'Inconnue'));
                }
            })
            .catch(error => {
                // Revert on error
                zebraEnabled = !newState;
                updateToggleButton('zebraToggle', !newState, 'Zebra');
                updateGlobalStatus('disconnected', 'Erreur de connexion');
                console.error('Error:', error);
            });
        };
        
        // Toggle Focus Assist - rendre accessible globalement
        window.toggleFocusAssist = function() {
            const newState = !focusAssistEnabled;
            focusAssistEnabled = newState;
            updateToggleButton('focusAssistToggle', newState, 'Focus Assist');
            
            fetch('/set_focus_assist', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ enabled: newState })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    updateGlobalStatus('connected', 'Connecté');
                } else {
                    // Revert on error
                    focusAssistEnabled = !newState;
                    updateToggleButton('focusAssistToggle', !newState, 'Focus Assist');
                    updateGlobalStatus('disconnected', 'Erreur: ' + (data.error || 'Inconnue'));
                }
            })
            .catch(error => {
                // Revert on error
                focusAssistEnabled = !newState;
                updateToggleButton('focusAssistToggle', !newState, 'Focus Assist');
                updateGlobalStatus('disconnected', 'Erreur de connexion');
                console.error('Error:', error);
            });
        };
        
        // Toggle False Color - rendre accessible globalement
        window.toggleFalseColor = function() {
            const newState = !falseColorEnabled;
            falseColorEnabled = newState;
            updateToggleButton('falseColorToggle', newState, 'False Color');
            
            fetch('/set_false_color', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ enabled: newState })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    updateGlobalStatus('connected', 'Connecté');
                } else {
                    // Revert on error
                    falseColorEnabled = !newState;
                    updateToggleButton('falseColorToggle', !newState, 'False Color');
                    updateGlobalStatus('disconnected', 'Erreur: ' + (data.error || 'Inconnue'));
                }
            })
            .catch(error => {
                // Revert on error
                falseColorEnabled = !newState;
                updateToggleButton('falseColorToggle', !newState, 'False Color');
                updateGlobalStatus('disconnected', 'Erreur de connexion');
                console.error('Error:', error);
            });
        };
        
        // Toggle Cleanfeed - rendre accessible globalement
        window.toggleCleanfeed = function() {
            const newState = !cleanfeedEnabled;
            cleanfeedEnabled = newState;
            updateToggleButton('cleanfeedToggle', newState, 'Cleanfeed');
            
            fetch('/set_cleanfeed', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ enabled: newState })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    updateGlobalStatus('connected', 'Connecté');
                } else {
                    // Revert on error
                    cleanfeedEnabled = !newState;
                    updateToggleButton('cleanfeedToggle', !newState, 'Cleanfeed');
                    updateGlobalStatus('disconnected', 'Erreur: ' + (data.error || 'Inconnue'));
                }
            })
            .catch(error => {
                // Revert on error
                cleanfeedEnabled = !newState;
                updateToggleButton('cleanfeedToggle', !newState, 'Cleanfeed');
                updateGlobalStatus('disconnected', 'Erreur de connexion');
                console.error('Error:', error);
            });
        };
        
        // Autofocus - rendre accessible globalement
        window.doAutoFocus = function() {
            const btn = document.getElementById('autofocusBtn');
            if (btn) {
                btn.disabled = true;
                btn.textContent = '🔍 Autofocus...';
            }
            
            fetch('/do_autofocus', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ x: 0.5, y: 0.5 })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    updateGlobalStatus('connected', 'Autofocus déclenché');
                    if (btn) {
                        btn.textContent = '✓ Autofocus OK';
                        setTimeout(() => {
                            btn.textContent = '🔍 Autofocus';
                            btn.disabled = false;
                        }, 2000);
                    }
                } else {
                    updateGlobalStatus('disconnected', 'Erreur: ' + (data.error || 'Inconnue'));
                    if (btn) {
                        btn.textContent = '🔍 Autofocus';
                        btn.disabled = false;
                    }
                }
            })
            .catch(error => {
                updateGlobalStatus('disconnected', 'Erreur de connexion');
                console.error('Error:', error);
                if (btn) {
                    btn.textContent = '🔍 Autofocus';
                    btn.disabled = false;
                }
            });
        };
        
        // Handlers WebSocket pour les toggles
        if (socket) {
        socket.on('zebra_changed', (data) => {
                if (!websocketEventsReceived) {
                    websocketEventsReceived = true;
                    stopPollingFallback();
                    console.log('WebSocket actif, arrêt du polling de secours');
                }
            const enabled = data.enabled !== undefined ? data.enabled : (data.value !== undefined ? data.value : false);
            zebraEnabled = enabled;
            updateToggleButton('zebraToggle', enabled, 'Zebra');
                // Si on reçoit des événements, le WebSocket fonctionne
                updateGlobalStatus('connected', 'WebSocket caméra: Actif ✓');
        });
        
        socket.on('focusAssist_changed', (data) => {
                if (!websocketEventsReceived) {
                    websocketEventsReceived = true;
                    stopPollingFallback();
                    console.log('WebSocket actif, arrêt du polling de secours');
                }
            const enabled = data.enabled !== undefined ? data.enabled : (data.value !== undefined ? data.value : false);
            focusAssistEnabled = enabled;
            updateToggleButton('focusAssistToggle', enabled, 'Focus Assist');
                // Si on reçoit des événements, le WebSocket fonctionne
                updateGlobalStatus('connected', 'WebSocket caméra: Actif ✓');
        });
        
        socket.on('falseColor_changed', (data) => {
                if (!websocketEventsReceived) {
                    websocketEventsReceived = true;
                    stopPollingFallback();
                    console.log('WebSocket actif, arrêt du polling de secours');
                }
            const enabled = data.enabled !== undefined ? data.enabled : (data.value !== undefined ? data.value : false);
            falseColorEnabled = enabled;
            updateToggleButton('falseColorToggle', enabled, 'False Color');
                // Si on reçoit des événements, le WebSocket fonctionne
                updateGlobalStatus('connected', 'WebSocket caméra: Actif ✓');
        });
        
        socket.on('cleanfeed_changed', (data) => {
                if (!websocketEventsReceived) {
                    websocketEventsReceived = true;
                    stopPollingFallback();
                    console.log('WebSocket actif, arrêt du polling de secours');
                }
            const enabled = data.enabled !== undefined ? data.enabled : (data.value !== undefined ? data.value : false);
            cleanfeedEnabled = enabled;
            updateToggleButton('cleanfeedToggle', enabled, 'Cleanfeed');
                // Si on reçoit des événements, le WebSocket fonctionne
                updateGlobalStatus('connected', 'WebSocket caméra: Actif ✓');
        });
        }
        
        // Fonction pour mettre à jour les valeurs depuis les données reçues
        function updateValuesFromData(data) {
            if (data.focus !== undefined) {
                actualValue = data.focus;
                document.getElementById('focusValueActual').textContent = data.focus.toFixed(3);
                
                // Mettre à jour le slider seulement si on n'est pas en train de le manipuler
                if (!sliderLocked) {
                    const slider = document.getElementById('focusSlider');
                    if (slider) {
                        slider.value = data.focus;
                    }
                }
            }
            if (data.iris !== undefined) {
                if (data.iris.normalised !== undefined) {
                    actualIrisValue = data.iris.normalised;
                    document.getElementById('irisValueActual').textContent = data.iris.normalised.toFixed(3);
                }
                if (data.iris.apertureStop !== undefined) {
                    document.getElementById('irisApertureStop').textContent = data.iris.apertureStop.toFixed(2);
                }
            }
            if (data.gain !== undefined) {
                actualGainValue = data.gain;
                document.getElementById('gainValueActual').textContent = data.gain + ' dB';
            }
            if (data.shutter !== undefined && data.shutter.shutterSpeed !== undefined) {
                actualShutterValue = data.shutter.shutterSpeed;
                document.getElementById('shutterValueActual').textContent = `1/${data.shutter.shutterSpeed}s`;
            }
            if (data.zoom !== undefined) {
                if (data.zoom.focalLength !== undefined) {
                    document.getElementById('zoomFocalLength').textContent = data.zoom.focalLength + ' mm';
                }
                if (data.zoom.normalised !== undefined) {
                    document.getElementById('zoomNormalised').textContent = data.zoom.normalised.toFixed(3);
                }
            }
            if (data.zebra !== undefined) {
                zebraEnabled = data.zebra;
                updateToggleButton('zebraToggle', data.zebra, 'Zebra');
            }
            if (data.focusAssist !== undefined) {
                focusAssistEnabled = data.focusAssist;
                updateToggleButton('focusAssistToggle', data.focusAssist, 'Focus Assist');
            }
            if (data.falseColor !== undefined) {
                falseColorEnabled = data.falseColor;
                updateToggleButton('falseColorToggle', data.falseColor, 'False Color');
            }
            if (data.cleanfeed !== undefined) {
                cleanfeedEnabled = data.cleanfeed;
                updateToggleButton('cleanfeedToggle', data.cleanfeed, 'Cleanfeed');
            }
            updateGlobalStatus('connected', 'Connecté');
        }
        
        // Polling de secours pour mettre à jour les valeurs si le WebSocket ne fonctionne pas
        let pollingInterval = null;
        let lastPollTime = 0;
        const POLLING_INTERVAL_MS = 200; // 5 fois par seconde maximum (200ms)
        
        function startPollingFallback() {
            // Démarrer le polling seulement si pas déjà démarré
            if (pollingInterval) return;
            
            pollingInterval = setInterval(() => {
                const now = Date.now();
                // Limiter à 5 fois par seconde
                if (now - lastPollTime >= POLLING_INTERVAL_MS) {
                    lastPollTime = now;
                    fetch('/get_initial_values')
                        .then(response => response.json())
                        .then(data => {
                            if (data.success) {
                                updateValuesFromData(data);
                            }
                        })
                        .catch(error => {
                            console.error('Erreur polling:', error);
                        });
                }
            }, POLLING_INTERVAL_MS);
        }
        
        function stopPollingFallback() {
            if (pollingInterval) {
                clearInterval(pollingInterval);
                pollingInterval = null;
            }
        }
        
        // Initialiser le statut immédiatement dès que le script s'exécute (pas d'attente de window.onload)
        if (document.readyState === 'loading') {
            // Le DOM est encore en cours de chargement, attendre DOMContentLoaded
            document.addEventListener('DOMContentLoaded', function() {
                updateGlobalStatus('connected', 'Initialisation...');
                initializeSocketIO();
            });
        } else {
            // Le DOM est déjà chargé, initialiser immédiatement
            updateGlobalStatus('connected', 'Initialisation...');
            initializeSocketIO();
        }
        
        // Fonction d'initialisation Socket.IO
        function initializeSocketIO() {
            try {
                console.log('JavaScript: initializeSocketIO executing...');
                
                // Vérifier que Socket.IO est chargé avant de l'utiliser
                console.log('JavaScript: Checking if Socket.IO is available, typeof io:', typeof io);
                if (typeof io === 'undefined') {
                    console.error('Socket.IO n\\'est pas chargé. Vérifiez votre connexion internet.');
                    updateGlobalStatus('disconnected', 'Erreur: Socket.IO non chargé');
                } else {
                    console.log('JavaScript: Socket.IO available, connecting...');
                    // Mettre à jour le statut pour indiquer que Socket.IO est en cours de connexion
                    updateGlobalStatus('connected', 'Connexion Socket.IO en cours...');
                    
                    // Connexion WebSocket
                    socket = io();
                    console.log('JavaScript: socket = io() called, socket:', socket);
                    
                    // Configurer les handlers Socket.IO
                    if (socket) {
                        socket.on('connect', () => {
                            console.log('JavaScript: Socket.IO connect event received!');
                            updateGlobalStatus('connected', 'Socket.IO: Connecté, attente WebSocket caméra...');
                            console.log('Socket.IO connecté');
                        });
                        
                        socket.on('disconnect', () => {
                            updateGlobalStatus('disconnected', 'Socket.IO: Déconnecté');
                        });
                        
                        socket.on('connect_error', (error) => {
                            updateGlobalStatus('disconnected', 'Socket.IO: Erreur de connexion');
                            console.error('Socket.IO connection error:', error);
                        });
                        
                        socket.on('connected', (data) => {
                            console.log('Socket.IO: Connexion confirmée par le serveur');
                        });
                        
                        // Handler pour l'état de connexion WebSocket vers la caméra
                        socket.on('websocket_status', (data) => {
                            const connected = data.connected;
                            const message = data.message || '';
                            if (!websocketEventsReceived) {
                                if (connected) {
                                    updateGlobalStatus('connected', 'WebSocket caméra: ' + message);
                                } else {
                                    updateGlobalStatus('disconnected', 'WebSocket caméra: ' + message);
                                }
                            }
                        });
                        
                        // Handlers pour les événements de paramètres de la caméra
                        socket.on('focus_changed', (data) => {
                            if (!websocketEventsReceived) {
                                websocketEventsReceived = true;
                                stopPollingFallback();
                                console.log('WebSocket actif, arrêt du polling de secours');
                            }
                            const value = data.normalised !== undefined ? data.normalised : data.value;
                            if (value !== null && value !== undefined) {
                                actualValue = value;
                                const focusEl = document.getElementById('focusValueActual');
                                if (focusEl) focusEl.textContent = value.toFixed(3);
                                
                                // Mettre à jour le slider seulement si on n'est pas en train de le manipuler
                                if (!sliderLocked) {
                                    const slider = document.getElementById('focusSlider');
                                    if (slider) {
                                        slider.value = value;
                                    }
                                }
                                
                                updateGlobalStatus('connected', 'WebSocket caméra: Actif ✓');
                            }
                        });
                        
                        socket.on('iris_changed', (data) => {
                            if (!websocketEventsReceived) {
                                websocketEventsReceived = true;
                                stopPollingFallback();
                                console.log('WebSocket actif, arrêt du polling de secours');
                            }
                            const normalised = data.normalised;
                            const apertureStop = data.apertureStop;
                            if (normalised !== null && normalised !== undefined) {
                                actualIrisValue = normalised;
                                const irisEl = document.getElementById('irisValueActual');
                                if (irisEl) irisEl.textContent = normalised.toFixed(3);
                            }
                            if (apertureStop !== null && apertureStop !== undefined) {
                                const apertureEl = document.getElementById('irisApertureStop');
                                if (apertureEl) apertureEl.textContent = apertureStop.toFixed(2);
                            }
                            updateGlobalStatus('connected', 'WebSocket caméra: Actif ✓');
                        });
                        
                        socket.on('gain_changed', (data) => {
                            if (!websocketEventsReceived) {
                                websocketEventsReceived = true;
                                stopPollingFallback();
                                console.log('WebSocket actif, arrêt du polling de secours');
                            }
                            const value = data.gain !== undefined ? data.gain : data.value;
                            if (value !== null && value !== undefined) {
                                actualGainValue = value;
                                const gainEl = document.getElementById('gainValueActual');
                                if (gainEl) gainEl.textContent = value + ' dB';
                                updateGlobalStatus('connected', 'WebSocket caméra: Actif ✓');
                            }
                        });
                        
                        socket.on('shutter_changed', (data) => {
                            if (!websocketEventsReceived) {
                                websocketEventsReceived = true;
                                stopPollingFallback();
                                console.log('WebSocket actif, arrêt du polling de secours');
                            }
                            const value = data.shutterSpeed;
                            if (value !== null && value !== undefined) {
                                actualShutterValue = value;
                                const shutterEl = document.getElementById('shutterValueActual');
                                if (shutterEl) shutterEl.textContent = `1/${value}s`;
                                updateGlobalStatus('connected', 'WebSocket caméra: Actif ✓');
                            }
                        });
                        
                        socket.on('zoom_changed', (data) => {
                            if (!websocketEventsReceived) {
                                websocketEventsReceived = true;
                                stopPollingFallback();
                                console.log('WebSocket actif, arrêt du polling de secours');
                            }
                            const focal = data.focalLength;
                            const norm = data.normalised;
                            if (focal !== null && focal !== undefined) {
                                const focalEl = document.getElementById('zoomFocalLength');
                                if (focalEl) focalEl.textContent = focal + ' mm';
                            }
                            if (norm !== null && norm !== undefined) {
                                const normEl = document.getElementById('zoomNormalised');
                                if (normEl) normEl.textContent = norm.toFixed(3);
                            }
                            updateGlobalStatus('connected', 'WebSocket caméra: Actif ✓');
                        });
                        
                        socket.on('zebra_changed', (data) => {
                            if (!websocketEventsReceived) {
                                websocketEventsReceived = true;
                                stopPollingFallback();
                                console.log('WebSocket actif, arrêt du polling de secours');
                            }
                            const enabled = data.enabled !== undefined ? data.enabled : (data.value !== undefined ? data.value : false);
                            zebraEnabled = enabled;
                            updateToggleButton('zebraToggle', enabled, 'Zebra');
                            updateGlobalStatus('connected', 'WebSocket caméra: Actif ✓');
                        });
                        
                        socket.on('focusAssist_changed', (data) => {
                            if (!websocketEventsReceived) {
                                websocketEventsReceived = true;
                                stopPollingFallback();
                                console.log('WebSocket actif, arrêt du polling de secours');
                            }
                            const enabled = data.enabled !== undefined ? data.enabled : (data.value !== undefined ? data.value : false);
                            focusAssistEnabled = enabled;
                            updateToggleButton('focusAssistToggle', enabled, 'Focus Assist');
                            updateGlobalStatus('connected', 'WebSocket caméra: Actif ✓');
                        });
                        
                        socket.on('falseColor_changed', (data) => {
                            if (!websocketEventsReceived) {
                                websocketEventsReceived = true;
                                stopPollingFallback();
                                console.log('WebSocket actif, arrêt du polling de secours');
                            }
                            const enabled = data.enabled !== undefined ? data.enabled : (data.value !== undefined ? data.value : false);
                            falseColorEnabled = enabled;
                            updateToggleButton('falseColorToggle', enabled, 'False Color');
                            updateGlobalStatus('connected', 'WebSocket caméra: Actif ✓');
                        });
                        
                        socket.on('cleanfeed_changed', (data) => {
                            if (!websocketEventsReceived) {
                                websocketEventsReceived = true;
                                stopPollingFallback();
                                console.log('WebSocket actif, arrêt du polling de secours');
                            }
                            const enabled = data.enabled !== undefined ? data.enabled : (data.value !== undefined ? data.value : false);
                            cleanfeedEnabled = enabled;
                            updateToggleButton('cleanfeedToggle', enabled, 'Cleanfeed');
                            updateGlobalStatus('connected', 'WebSocket caméra: Actif ✓');
                        });
                    }
                }
                
                // Vérifier l'état de Socket.IO après un court délai
                setTimeout(() => {
                    if (socket && socket.connected) {
                        // Socket.IO est connecté, le statut devrait déjà être mis à jour par l'événement connect
                        console.log('Socket.IO vérifié: connecté');
                    } else if (socket) {
                        // Socket.IO existe mais n'est pas connecté
                        updateGlobalStatus('disconnected', 'Socket.IO: Tentative de connexion...');
                        console.log('Socket.IO vérifié: non connecté');
                    }
                }, 1000);
                
                // Charger les valeurs supportées (gain, shutter)
                loadSupportedGains();
                loadSupportedShutters();
                // Récupérer les valeurs initiales via HTTP (fallback si WebSocket ne fonctionne pas)
                fetch('/get_initial_values')
                    .then(response => response.json())
                    .then(data => {
                        if (data.success) {
                            updateValuesFromData(data);
                            console.log('Valeurs initiales récupérées via HTTP');
                        }
                    })
                    .catch(error => {
                        console.error('Erreur récupération valeurs initiales:', error);
                    });
                
                // Démarrer le polling de secours après 2 secondes
                // Si on reçoit des événements WebSocket, on arrêtera le polling
                setTimeout(() => {
                    if (!websocketEventsReceived) {
                        console.log('Démarrage du polling de secours (WebSocket inactif)');
                        startPollingFallback();
                    }
                }, 2000);
            } catch (error) {
                console.error('Erreur dans initializeSocketIO:', error);
            }
        }
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    """Page principale avec l'interface."""
    # #region agent log
    import json
    import time
    try:
        with open('/Users/laurenteyen/Documents/cursor/FocusBMrestAPI1/.cursor/debug.log', 'a') as f:
            f.write(json.dumps({'location':'focus_ui.py:1697','message':'index route called','data':{'controller_exists':controller is not None},'timestamp':int(time.time()*1000),'sessionId':'debug-session','runId':'run1','hypothesisId':'A'})+'\n')
    except:
        pass
    # #endregion
    if controller is None:
        return "Erreur: Contrôleur non initialisé. Vérifiez les paramètres de connexion.", 500
    try:
        result = render_template_string(HTML_TEMPLATE)
        # #region agent log
        try:
            with open('/Users/laurenteyen/Documents/cursor/FocusBMrestAPI1/.cursor/debug.log', 'a') as f:
                f.write(json.dumps({'location':'focus_ui.py:1704','message':'index route returning HTML','data':{'html_length':len(result)},'timestamp':int(time.time()*1000),'sessionId':'debug-session','runId':'run1','hypothesisId':'A'})+'\n')
        except:
            pass
        # #endregion
        return result
    except Exception as e:
        # #region agent log
        try:
            with open('/Users/laurenteyen/Documents/cursor/FocusBMrestAPI1/.cursor/debug.log', 'a') as f:
                f.write(json.dumps({'location':'focus_ui.py:1706','message':'index route exception','data':{'error':str(e)},'timestamp':int(time.time()*1000),'sessionId':'debug-session','runId':'run1','hypothesisId':'B'})+'\n')
        except:
            pass
        # #endregion
        return f"Erreur lors du rendu du template: {str(e)}", 500

@app.route('/set_focus', methods=['POST'])
def set_focus():
    """Définit la valeur du focus."""
    try:
        data = request.json
        value = float(data.get('value', 0))
        
        if not 0.0 <= value <= 1.0:
            return jsonify({'success': False, 'error': 'Valeur doit être entre 0.0 et 1.0'})
        
        success = controller.set_focus(value, silent=True)
        if success:
            return jsonify({'success': True, 'value': value})
        else:
            return jsonify({'success': False, 'error': 'Impossible de définir la valeur'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/set_iris', methods=['POST'])
def set_iris():
    """Définit la valeur de l'iris."""
    try:
        data = request.json
        value = float(data.get('value', 0))
        
        if not 0.0 <= value <= 1.0:
            return jsonify({'success': False, 'error': 'Valeur doit être entre 0.0 et 1.0'})
        
        success = controller.set_iris(value, silent=True)
        if success:
            return jsonify({'success': True, 'value': value})
        else:
            return jsonify({'success': False, 'error': 'Impossible de définir la valeur'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/get_supported_gains', methods=['GET'])
def get_supported_gains():
    """Récupère la liste des gains supportés."""
    try:
        gains = controller.get_supported_gains()
        if gains is not None:
            return jsonify({'success': True, 'supportedGains': gains})
        else:
            return jsonify({'success': False, 'error': 'Impossible de récupérer les gains supportés'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/set_gain', methods=['POST'])
def set_gain():
    """Définit la valeur du gain."""
    try:
        data = request.json
        value = int(data.get('value', 0))
        
        success = controller.set_gain(value, silent=True)
        if success:
            return jsonify({'success': True, 'value': value})
        else:
            return jsonify({'success': False, 'error': 'Impossible de définir la valeur'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/get_shutter_measurement', methods=['GET'])
def get_shutter_measurement():
    """Récupère le mode de mesure du shutter actuel."""
    try:
        mode = controller.get_shutter_measurement()
        if mode is not None:
            return jsonify({'success': True, 'measurement': mode})
        else:
            return jsonify({'success': False, 'error': 'Impossible de récupérer le mode'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/set_shutter_measurement', methods=['POST'])
def set_shutter_measurement():
    """Définit le mode de mesure du shutter."""
    try:
        data = request.json
        mode = data.get('measurement')
        
        if mode not in ['ShutterAngle', 'ShutterSpeed']:
            return jsonify({'success': False, 'error': 'Mode doit être ShutterAngle ou ShutterSpeed'})
        
        success = controller.set_shutter_measurement(mode, silent=True)
        if success:
            return jsonify({'success': True, 'measurement': mode})
        else:
            return jsonify({'success': False, 'error': 'Impossible de définir le mode'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/get_supported_shutters', methods=['GET'])
def get_supported_shutters():
    """Récupère les valeurs de shutter supportées."""
    try:
        shutters = controller.get_supported_shutters()
        if shutters is not None:
            return jsonify({'success': True, **shutters})
        else:
            return jsonify({'success': False, 'error': 'Impossible de récupérer les shutters supportés'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/set_shutter', methods=['POST'])
def set_shutter():
    """Définit la valeur du shutter (toujours en ShutterSpeed)."""
    try:
        data = request.json
        value = data.get('value')
        mode = data.get('mode', 'ShutterSpeed')  # Par défaut ShutterSpeed
        
        # Toujours utiliser ShutterSpeed
        success = controller.set_shutter(shutter_speed=int(value), silent=True)
        
        if success:
            return jsonify({'success': True, 'value': value, 'mode': 'ShutterSpeed'})
        else:
            return jsonify({'success': False, 'error': 'Impossible de définir la valeur'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/get_zebra', methods=['GET'])
def get_zebra():
    """Récupère l'état actuel du Zebra."""
    try:
        enabled = controller.get_zebra()
        if enabled is not None:
            return jsonify({'success': True, 'enabled': enabled})
        else:
            return jsonify({'success': False, 'error': 'Impossible de récupérer l\'état du Zebra'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/set_zebra', methods=['POST'])
def set_zebra():
    """Active ou désactive le Zebra."""
    try:
        data = request.json
        enabled = bool(data.get('enabled', False))
        
        success = controller.set_zebra(enabled, silent=True)
        if success:
            return jsonify({'success': True, 'enabled': enabled})
        else:
            return jsonify({'success': False, 'error': 'Impossible de définir l\'état du Zebra'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/get_focus_assist', methods=['GET'])
def get_focus_assist():
    """Récupère l'état actuel du Focus Assist."""
    try:
        enabled = controller.get_focus_assist()
        if enabled is not None:
            return jsonify({'success': True, 'enabled': enabled})
        else:
            return jsonify({'success': False, 'error': 'Impossible de récupérer l\'état du Focus Assist'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/set_focus_assist', methods=['POST'])
def set_focus_assist():
    """Active ou désactive le Focus Assist."""
    try:
        data = request.json
        enabled = bool(data.get('enabled', False))
        
        success = controller.set_focus_assist(enabled, silent=True)
        if success:
            return jsonify({'success': True, 'enabled': enabled})
        else:
            return jsonify({'success': False, 'error': 'Impossible de définir l\'état du Focus Assist'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/get_false_color', methods=['GET'])
def get_false_color():
    """Récupère l'état actuel du False Color."""
    try:
        enabled = controller.get_false_color()
        if enabled is not None:
            return jsonify({'success': True, 'enabled': enabled})
        else:
            return jsonify({'success': False, 'error': 'Impossible de récupérer l\'état du False Color'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/set_false_color', methods=['POST'])
def set_false_color():
    """Active ou désactive le False Color."""
    try:
        data = request.json
        enabled = bool(data.get('enabled', False))
        
        success = controller.set_false_color(enabled, silent=True)
        if success:
            return jsonify({'success': True, 'enabled': enabled})
        else:
            return jsonify({'success': False, 'error': 'Impossible de définir l\'état du False Color'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/get_cleanfeed', methods=['GET'])
def get_cleanfeed():
    """Récupère l'état actuel du Cleanfeed."""
    try:
        enabled = controller.get_cleanfeed()
        if enabled is not None:
            return jsonify({'success': True, 'enabled': enabled})
        else:
            return jsonify({'success': False, 'error': 'Impossible de récupérer l\'état du Cleanfeed'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/set_cleanfeed', methods=['POST'])
def set_cleanfeed():
    """Active ou désactive le Cleanfeed."""
    try:
        data = request.json
        enabled = bool(data.get('enabled', False))
        
        success = controller.set_cleanfeed(enabled, silent=True)
        if success:
            return jsonify({'success': True, 'enabled': enabled})
        else:
            return jsonify({'success': False, 'error': 'Impossible de définir l\'état du Cleanfeed'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/do_autofocus', methods=['POST'])
def do_autofocus():
    """Lance l'autofocus à une position donnée."""
    try:
        data = request.json or {}
        x = float(data.get('x', 0.5))
        y = float(data.get('y', 0.5))
        
        # Valider les valeurs
        if not (0.0 <= x <= 1.0) or not (0.0 <= y <= 1.0):
            return jsonify({'success': False, 'error': 'Les positions doivent être entre 0.0 et 1.0'})
        
        success = controller.do_autofocus(x=x, y=y, silent=True)
        if success:
            return jsonify({'success': True, 'x': x, 'y': y})
        else:
            return jsonify({'success': False, 'error': 'Impossible de déclencher l\'autofocus'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/get_initial_values', methods=['GET'])
def get_initial_values():
    """Récupère toutes les valeurs initiales via HTTP (fallback si WebSocket ne fonctionne pas)."""
    result = {'success': True}
    
    # Récupérer les valeurs principales (focus, iris, gain, shutter, zoom)
    # Ces valeurs sont essentielles et doivent fonctionner
    try:
        focus_value = controller.get_focus()
        if focus_value is not None:
            result['focus'] = focus_value
    except Exception as e:
        pass  # Ignorer les erreurs pour les valeurs optionnelles
    
    try:
        iris_data = controller.get_iris()
        if iris_data is not None:
            result['iris'] = iris_data
    except Exception as e:
        pass
    
    try:
        gain_value = controller.get_gain()
        if gain_value is not None:
            result['gain'] = gain_value
    except Exception as e:
        pass
    
    try:
        shutter_data = controller.get_shutter()
        if shutter_data is not None:
            result['shutter'] = shutter_data
    except Exception as e:
        pass
    
    try:
        zoom_data = controller.get_zoom()
        if zoom_data is not None:
            result['zoom'] = zoom_data
    except Exception as e:
        pass
    
    # Récupérer les valeurs optionnelles (zebra, focusAssist, falseColor, cleanfeed)
    # Ces valeurs peuvent échouer si les endpoints ne sont pas disponibles
    try:
        zebra_enabled = controller.get_zebra()
        if zebra_enabled is not None:
            result['zebra'] = zebra_enabled
    except Exception as e:
        pass  # Ignorer les erreurs 404 pour les endpoints optionnels
    
    try:
        focus_assist_enabled = controller.get_focus_assist()
        if focus_assist_enabled is not None:
            result['focusAssist'] = focus_assist_enabled
    except Exception as e:
        pass
    
    try:
        false_color_enabled = controller.get_false_color()
        if false_color_enabled is not None:
            result['falseColor'] = false_color_enabled
    except Exception as e:
        pass
    
    try:
        cleanfeed_enabled = controller.get_cleanfeed()
        if cleanfeed_enabled is not None:
            result['cleanfeed'] = cleanfeed_enabled
    except Exception as e:
        pass
    
    # Retourner success: True si au moins une valeur a été récupérée
    # (focus, iris, gain, shutter, ou zoom)
    if any(key in result for key in ['focus', 'iris', 'gain', 'shutter', 'zoom']):
        result['success'] = True
    else:
        result['success'] = False
        result['error'] = 'Aucune valeur n\'a pu être récupérée'
    
    return jsonify(result)

# Fonction pour traiter la queue d'événements
def process_event_queue():
    """Traite la queue d'événements et les émet via Socket.IO."""
    while True:
        try:
            event_name, data = event_queue.get(timeout=0.1)
            try:
                socketio.emit(event_name, data)
            except Exception as emit_error:
                logging.error(f"Erreur lors de l'émission Socket.IO: {emit_error}")
            event_queue.task_done()
        except queue.Empty:
            continue
        except Exception as e:
            logging.error(f"Erreur lors du traitement de la queue d'événements: {e}")

# Handlers SocketIO
@socketio.on('connect')
def handle_connect():
    """Gère la connexion d'un client WebSocket."""
    logging.info("Client WebSocket connecté")
    try:
        emit('connected', {'status': 'connected'})
    except Exception as emit_err:
        logging.error(f"Erreur lors de l'émission de l'événement 'connected': {emit_err}")
    
    # Émettre le statut actuel du WebSocket vers la caméra
    try:
        websocket_connected = websocket_client and websocket_client.websocket
        if websocket_connected:
            # WebSocket connecté
            event_queue.put(('websocket_status', {'connected': True, 'message': 'WebSocket caméra connecté'}))
        else:
            # WebSocket non connecté ou en cours de connexion
            event_queue.put(('websocket_status', {'connected': False, 'message': 'Tentative de connexion...'}))
    except Exception as queue_err:
        logging.error(f"Erreur lors de l'ajout du statut WebSocket à la queue: {queue_err}")
    
    # Envoyer les valeurs initiales via HTTP (fallback si WebSocket ne fonctionne pas)
    try:
        # Récupérer les valeurs initiales via HTTP
        focus_value = controller.get_focus()
        if focus_value is not None:
            emit('focus_changed', {'normalised': focus_value})
        
        iris_data = controller.get_iris()
        if iris_data is not None:
            emit('iris_changed', iris_data)
        
        gain_value = controller.get_gain()
        if gain_value is not None:
            emit('gain_changed', {'gain': gain_value})
        
        shutter_data = controller.get_shutter()
        if shutter_data is not None:
            emit('shutter_changed', shutter_data)
        
        zoom_data = controller.get_zoom()
        if zoom_data is not None:
            emit('zoom_changed', zoom_data)
    except Exception as e:
        logging.error(f"Erreur lors de la récupération des valeurs initiales: {e}")

@socketio.on('disconnect')
def handle_disconnect():
    """Gère la déconnexion d'un client WebSocket."""
    logging.info("Client WebSocket déconnecté")

def on_websocket_connection_status(connected: bool, message: str):
    """
    Callback appelé quand l'état de connexion WebSocket vers la caméra change.
    Émet l'événement vers tous les clients connectés.
    
    Args:
        connected: True si connecté, False sinon
        message: Message décrivant l'état
    """
    try:
        event_data = {
            'connected': connected,
            'message': message
        }
        event_queue.put(('websocket_status', event_data))
        logging.info(f"État WebSocket caméra: {message}")
    except Exception as e:
        logging.error(f"Erreur lors de l'émission de l'état WebSocket: {e}")

def on_parameter_change(param_type: str, data: dict):
    """
    Callback appelé quand un paramètre change via WebSocket.
    Émet l'événement vers tous les clients connectés.
    
    Args:
        param_type: Type de paramètre ('focus', 'iris', 'gain', 'shutter', 'zoom', 'zebra', 'focusAssist', 'falseColor', 'cleanfeed')
        data: Données du paramètre (format dict avec les champs de l'API REST)
    """
    try:
        # Émettre l'événement vers tous les clients via une queue
        event_name = f"{param_type}_changed"
        # Les données sont déjà dans le format de l'API REST (ex: {'normalised': 0.5} pour focus)
        # Depuis un thread externe, utiliser une queue pour émettre dans le bon contexte Flask-SocketIO
        try:
            event_queue.put((event_name, data))
        except Exception as queue_error:
            logging.error(f"Erreur lors de l'ajout à la queue: {queue_error}")
        
        logging.debug(f"Événement émis: {event_name} avec données: {data}")
    except Exception as e:
        logging.error(f"Erreur lors de l'émission de l'événement {param_type}: {e}")
        import traceback
        logging.error(traceback.format_exc())

def main():
    """Fonction principale."""
    parser = argparse.ArgumentParser(
        description="Interface web pour contrôler le focus Blackmagic",
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
    parser.add_argument(
        "--port",
        type=int,
        default=5002,
        help="Port pour le serveur web (défaut: 5002)"
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Adresse IP pour le serveur web (défaut: 127.0.0.1, utilisez 0.0.0.0 pour accès réseau)"
    )
    parser.add_argument(
        "--no-websocket",
        action="store_true",
        help="Désactiver WebSocket et utiliser le polling HTTP (pour debug)"
    )
    
    args = parser.parse_args()
    
    # Désactiver les avertissements SSL
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    
    # Créer le contrôleur
    global controller, websocket_client
    controller = BlackmagicFocusController(args.url, args.user, args.password)
    
    # Démarrer le thread qui traite la queue d'événements
    queue_thread = threading.Thread(target=process_event_queue, daemon=True)
    queue_thread.start()
    logging.info("Thread de traitement de la queue d'événements démarré")
    
    # Créer et démarrer le client WebSocket (sauf si désactivé)
    websocket_client = None
    if not args.no_websocket:
        try:
            websocket_client = BlackmagicWebSocketClient(
                args.url,
                args.user,
                args.password,
                on_change_callback=on_parameter_change,
                on_connection_status_callback=on_websocket_connection_status
            )
            websocket_client.start()
            logging.info("Client WebSocket démarré")
        except Exception as e:
            logging.error(f"Erreur lors du démarrage du client WebSocket: {e}")
            logging.warning("Le WebSocket n'est pas disponible, mais le serveur Flask continue...")
            websocket_client = None
    else:
        logging.info("WebSocket désactivé (mode polling HTTP)")
    
    print(f"\n{'='*60}")
    print("Interface Web de Contrôle Focus Blackmagic")
    print(f"{'='*60}")
    print(f"URL de la caméra: {args.url}")
    print(f"Interface web: http://{args.host}:{args.port}")
    if websocket_client:
        print(f"WebSocket: Activé (remplace le polling)")
    else:
        print(f"WebSocket: Désactivé (polling HTTP)")
    print(f"\nOuvrez votre navigateur à l'adresse ci-dessus")
    print(f"Appuyez sur Ctrl+C pour arrêter\n")
    
    # Démarrer le serveur Flask avec SocketIO
    try:
        socketio.run(app, host=args.host, port=args.port, debug=False, allow_unsafe_werkzeug=True)
    except Exception as e:
        raise

if __name__ == "__main__":
    main()

