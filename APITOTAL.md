# API Documentation - ESP32 Slider Controller

## Vue d'ensemble

Ce document liste toutes les routes **OSC**, **HTTP** et **WebSocket** disponibles pour contrôler le slider depuis un logiciel externe.

### Connexion

- **OSC** : Port UDP **8000** (défini dans `Config.h`)
- **HTTP** : Port **80** (défini dans `Config.h`)
- **WebSocket** : `ws://hostname.local/ws/positions` ou `ws://IP/ws/positions`
- **mDNS** : Accessible via `hostname.local` (ex: `slider1.local`)

---

## Table des matières

1. [Routes OSC](#routes-osc)
   - [Contrôle des axes](#contrôle-des-axes-osc)
   - [Joystick et jog](#joystick-et-jog-osc)
   - [Presets](#presets-osc)
   - [Interpolation](#interpolation-osc)
   - [Gestion des banques](#gestion-des-banques-osc)
   - [Configuration des moteurs](#configuration-des-moteurs-osc)
   - [Homing](#homing-osc)
   - [Offsets](#offsets-osc)
   - [Configuration système](#configuration-système-osc)

2. [Routes HTTP](#routes-http)
   - [Statut et informations](#statut-et-informations-http)
   - [Contrôle des axes](#contrôle-des-axes-http)
   - [Joystick](#joystick-http)
   - [Presets](#presets-http)
   - [Interpolation](#interpolation-http)
   - [Gestion des banques](#gestion-des-banques-http)
   - [Homing](#homing-http)
   - [Offsets](#offsets-http)
   - [Configuration des moteurs](#configuration-des-moteurs-http)
   - [Réseau et système](#réseau-et-système-http)

3. [WebSocket](#websocket)
   - [Publication des positions](#websocket-positions)

---

## Routes OSC

### Contrôle des axes (OSC)

| Adresse | Arguments | Description |
|---------|-----------|-------------|
| `/axis_pan` | `float` (0.0-1.0) | Position absolue Pan (0=min, 1=max) |
| `/axis_tilt` | `float` (0.0-1.0) | Position absolue Tilt (0=min, 1=max) |
| `/axis_zoom` | `float` (0.0-1.0) | Position absolue Zoom (0=min, 1=max) |
| `/axis_slide` | `float` (0.0-1.0) | Position absolue Slide (0=min, 1=max) |

**Comportement :** Annule automatiquement les mouvements synchronisés en cours si la politique d'annulation l'autorise.

**Exemple :**
```
/axis_pan 0.5        # Pan à 50%
/axis_tilt 0.8       # Tilt à 80%
```

---

### Joystick et jog (OSC)

| Adresse | Arguments | Description |
|---------|-----------|-------------|
| `/pan` | `float` (-1.0 à +1.0) | Jog Pan en continu (vitesse relative) |
| `/tilt` | `float` (-1.0 à +1.0) | Jog Tilt en continu (vitesse relative) |
| `/zoom` | `float` (-1.0 à +1.0) | Offset Zoom direct |
| `/slide` | `float` (-1.0 à +1.0) | Jog Slide en continu (vitesse relative) |
| `/slide/jog` | `float` (-1.0 à +1.0) | Alias pour `/slide` (rétrocompatibilité) |
| `/joy/pt` | `float pan, float tilt` | Jog Pan et Tilt simultanés |
| `/joy/zoom` | `float` (-1.0 à +1.0) | Alias pour `/zoom` |
| `/joy/config` | `float deadzone, float expo, float slew_per_s, float filt_hz, float slide_speed` | Configuration du joystick |

**Configuration joystick :**
- `deadzone` : Zone morte (0.0-0.5)
- `expo` : Courbure exponentielle (0.0-0.95)
- `slew_per_s` : Vitesse de slew (steps/s)
- `filt_hz` : Fréquence de filtrage (Hz)
- `slide_speed` : Vitesse du slide (0.1-3.0x)

**Exemple :**
```
/pan 0.3              # Jog Pan à 30% de vitesse
/slide/jog -0.5       # Jog Slide à -50% de vitesse
/joy/config 0.1 0.3 500.0 10.0 1.5
```

---

### Presets (OSC)

| Adresse | Arguments | Description |
|---------|-----------|-------------|
| `/preset/set` | `int index, int pan, int tilt, int zoom, int slide` | Définit un preset avec positions absolues (steps) |
| `/preset/store` | `int index` | Capture les positions actuelles et les sauvegarde dans le preset |
| `/preset/recall` | `int index, float duration_sec` | Rappel d'un preset avec durée spécifiée (défaut: 2.0s) |
| `/slide/goto` | `float position` (0.0-1.0), `float duration_sec` | Déplacement slide à position relative avec durée |

**Exemple :**
```
/preset/store 0       # Capturer position actuelle dans preset 0
/preset/recall 0 3.0   # Rappel preset 0 en 3 secondes
/slide/goto 0.75 5.0   # Slide à 75% en 5 secondes
```

---

### Interpolation (OSC)

| Adresse | Arguments | Description |
|---------|-----------|-------------|
| `/interp/setpoints` | `int N, int preset1, float fraction1, int preset2, float fraction2, ...` | Définit les points d'interpolation (2-6 points) |
| `/interp/auto` | `int enable` (0/1), `float duration_sec` | Active l'interpolation automatique (défaut: 5.0s) |
| `/interp/goto` | `float fraction` (0.0-1.0) | Va à une position interpolée immédiatement |
| `/interp/jog` | `float speed` (-1.0 à +1.0) | Jog de l'axe d'interpolation |

**Exemple setpoints :**
```
/interp/setpoints 3 0 0.0 1 0.5 2 1.0
```
Définit 3 points : preset 0 à 0%, preset 1 à 50%, preset 2 à 100%.

**Exemple :**
```
/interp/auto 1 10.0   # Auto interpolation 10 secondes
/interp/goto 0.5      # Aller à 50% de l'interpolation
/interp/jog 0.3       # Jog à 30% de vitesse
```

---

### Gestion des banques (OSC)

| Adresse | Arguments | Description |
|---------|-----------|-------------|
| `/bank/set` | `int bank_index` (0-9) | Change la banque active et recharge les points d'interpolation |
| `/bank/save` | Aucun | Sauvegarde la banque active |
| `/bank/get_interp` | Aucun | Retourne les points d'interpolation actuels (JSON sur Serial) |

**Comportement :** Le changement de banque recharge automatiquement les points d'interpolation et réinitialise les offsets.

---

### Configuration des moteurs (OSC)

| Adresse | Arguments | Description |
|---------|-----------|-------------|
| `/motor/pan/max_speed` | `int speed` (2000-20000) | Vitesse max Pan (steps/s) |
| `/motor/pan/max_accel` | `int accel` (1000-999999) | Accélération max Pan (steps/s²) |
| `/motor/tilt/max_speed` | `int speed` (2000-20000) | Vitesse max Tilt (steps/s) |
| `/motor/tilt/max_accel` | `int accel` (1000-999999) | Accélération max Tilt (steps/s²) |
| `/motor/zoom/max_speed` | `int speed` (2000-20000) | Vitesse max Zoom (steps/s) |
| `/motor/zoom/max_accel` | `int accel` (1000-999999) | Accélération max Zoom (steps/s²) |
| `/motor/slide/max_speed` | `int speed` (2000-20000) | Vitesse max Slide (steps/s) |
| `/motor/slide/max_accel` | `int accel` (1000-999999) | Accélération max Slide (steps/s²) |
| `/motor/config` | `int id, int microsteps, int current_mA, int spreadCycle` | Configuration complète driver TMC2209 |
| `/motor/microsteps` | `int id` (0-3), `int microsteps` {1,2,4,8,16,32,64,128,256} | Change uniquement les microsteps |
| `/motor/current` | `int id` (0-3), `int current_mA` (0-2000) | Change uniquement le courant |
| `/motor/mode` | `int id` (0-3), `int spreadCycle` (0/1) | Change uniquement le mode (SpreadCycle) |

**Exemple :**
```
/motor/pan/max_speed 5000
/motor/slide/max_accel 2000
/motor/config 0 16 800 1    # Pan: 16 microsteps, 800mA, SpreadCycle ON
```

---

### Homing (OSC)

| Adresse | Arguments | Description |
|---------|-----------|-------------|
| `/slide/home` | Aucun | Lance le homing du slide (StallGuard) |
| `/slide/sgthrs` | `int threshold` (0-255) | Seuil StallGuard pour le slide |

**Comportement :** Un seul homing à la fois autorisé. Si déjà en cours, la commande est ignorée.

---

### Offsets (OSC)

| Adresse | Arguments | Description |
|---------|-----------|-------------|
| `/offset/zero` | `int do_pan` (0/1), `int do_tilt` (0/1) | Remet les offsets à zéro (défaut: pan=1, tilt=1) |
| `/offset/add` | `long pan, long tilt, long zoom, long slide` | Ajoute aux offsets actuels |
| `/offset/set` | `long pan, long tilt, long zoom, long slide` | Définit les offsets absolus |
| `/offset/bake` | Aucun | Intègre les offsets dans le mouvement en cours et les réinitialise |
| `/offset/reset_all` | Aucun | Réinitialise tous les offsets et baselines |

**Comportement :** Les offsets sont "latched" (verrouillés) et persistent jusqu'à reset.

---

### Configuration système (OSC)

| Adresse | Arguments | Description |
|---------|-----------|-------------|
| `/config/offset_range` | `int min_range, int max_range` | Définit la plage des offsets |
| `/network/info` | Aucun | Affiche les informations réseau (Serial) |
| `/network/reset` | Aucun | Réinitialise la config réseau et redémarre en mode AP |
| `/system/restart` | Aucun | Redémarre l'ESP32 |

---

## Routes HTTP

Toutes les routes HTTP utilisent le format JSON pour les requêtes et réponses.

### Statut et informations (HTTP)

#### `GET /api/v1/status`
Retourne l'état complet du système.

**Réponse :**
```json
{
  "motors": {
    "pan": 12345,
    "tilt": 67890,
    "zoom": 11111,
    "slide": 22222
  },
  "motors_percent": {
    "pan": 50.5,
    "tilt": 75.2,
    "zoom": 30.0,
    "slide": 60.0
  },
  "config": {
    "pan": {
      "max_speed": 5000,
      "max_accel": 2000,
      "min_limit": 0,
      "max_limit": 100000,
      "inverted": false
    },
    "tilt": {...},
    "zoom": {...},
    "slide": {...}
  },
  "interpolation": {
    "count": 3,
    "autoActive": false,
    "autoDuration_ms": 5000,
    "jog_cmd": 0.0,
    "position": 0.5,
    "points": [
      {"presetIndex": 0, "fraction": 0.0},
      {"presetIndex": 1, "fraction": 0.5},
      {"presetIndex": 2, "fraction": 1.0}
    ]
  },
  "modes": {
    "syncMove": false,
    "interpAuto": false,
    "homing": false
  },
  "bank": {
    "active": 0,
    "preset": 0
  },
  "network": {
    "mode": "AP+STA",
    "ip": "192.168.1.100",
    "rssi": -45,
    "hostname": "slider1",
    "apClients": 1
  }
}
```

#### `GET /api/v1/move/status`
Retourne le statut du mouvement synchronisé en cours.

**Réponse :**
```json
{
  "active": true,
  "progress": 0.65,
  "remaining_ms": 3500,
  "remaining_sec": 3.5
}
```

#### `GET /api/v1/logs`
Retourne les 100 derniers logs du système.

**Réponse :**
```json
{
  "status": "ok",
  "logs": [
    {
      "timestamp": 1234567890,
      "message": "🔧 Pan max_speed = 5000 steps/s"
    },
    ...
  ]
}
```

#### `GET /api/v1/network/info`
Retourne les informations réseau détaillées.

**Réponse :**
```json
{
  "hostname": "slider1",
  "ip": "192.168.1.100",
  "gateway": "192.168.1.1",
  "subnet": "255.255.255.0",
  "dns": "192.168.1.1",
  "useDHCP": true,
  "staticIP": "",
  "staticGateway": "",
  "staticSubnet": "",
  "staticDNS": "",
  "network": {
    "mode": "AP+STA",
    "ip": "192.168.1.100",
    "rssi": -45,
    "hostname": "slider1",
    "apClients": 1
  }
}
```

---

### Contrôle des axes (HTTP)

#### `POST /api/v1/axes/move`
Déplace un axe à une position normalisée (0.0-1.0).

**Requête :**
```json
{
  "axis": "pan",
  "value": 0.5
}
```

**Réponse :**
```json
{
  "status": "ok",
  "axis": "pan",
  "target": 50000
}
```

#### `POST /api/v1/axes/move_absolute`
Déplace un axe à une position absolue en steps.

**Requête :**
```json
{
  "axis": "pan",
  "steps": 50000,
  "override_min": 0,      // Optionnel
  "override_max": 100000   // Optionnel
}
```

**Réponse :**
```json
{
  "status": "ok",
  "axis": "pan",
  "target": 50000,
  "limits": {
    "min": 0,
    "max": 100000
  }
}
```

#### `POST /api/v1/axes/move_multiple`
Déplace plusieurs axes simultanément (pan, tilt, zoom, slide) en une seule requête. Les axes non spécifiés conservent leur position actuelle.

**Requête :**
```json
{
  "pan": 0.5,      // Optionnel (0.0-1.0)
  "tilt": 0.75,   // Optionnel (0.0-1.0)
  "zoom": 0.3,    // Optionnel (0.0-1.0)
  "slide": 0.6,   // Optionnel (0.0-1.0)
  "duration": 2.0 // Optionnel, durée en secondes pour synchronisation
}
```

**Comportement :**
- Si `duration` est fourni et > 0 : tous les axes se déplacent de manière synchronisée vers leurs positions cibles en même temps
- Si `duration` n'est pas fourni ou = 0 : chaque axe se déplace individuellement (non synchronisé)

**Réponse (avec synchronisation) :**
```json
{
  "status": "ok",
  "synchronized": true,
  "requested_duration_ms": 2000,
  "requested_duration_sec": 2.0,
  "actual_duration_ms": 2500,
  "actual_duration_sec": 2.5,
  "duration_adjusted": true,
  "targets": {
    "pan": 50000,
    "tilt": 75000,
    "zoom": 30000,
    "slide": 60000
  }
}
```

**Réponse (sans synchronisation) :**
```json
{
  "status": "ok",
  "synchronized": false,
  "targets": {
    "pan": 50000,
    "tilt": 75000,
    "zoom": 30000,
    "slide": 60000
  }
}
```

**Exemple d'utilisation :**
```bash
# Déplacer pan et tilt simultanément en 3 secondes
curl -X POST http://slider1.local/api/v1/axes/move_multiple \
  -H "Content-Type: application/json" \
  -d '{"pan": 0.5, "tilt": 0.75, "duration": 3.0}'

# Déplacer tous les axes individuellement (non synchronisé)
curl -X POST http://slider1.local/api/v1/axes/move_multiple \
  -H "Content-Type: application/json" \
  -d '{"pan": 0.5, "tilt": 0.75, "zoom": 0.3, "slide": 0.6}'
```

#### `GET /api/axes/status` (Legacy)
Retourne les positions normalisées des axes (0.0-1.0).

**Réponse :**
```json
{
  "pan": 0.5,
  "tilt": 0.75,
  "zoom": 0.3,
  "slide": 0.6
}
```

---

### Joystick (HTTP)

#### `POST /api/v1/joy`
Définit les valeurs du joystick.

**Requête :**
```json
{
  "pan": 0.3,      // Optionnel (-1.0 à +1.0)
  "tilt": -0.5,    // Optionnel (-1.0 à +1.0)
  "slide": 0.2,    // Optionnel (-1.0 à +1.0)
  "zoom": 0.1     // Optionnel (-1.0 à +1.0)
}
```

**Réponse :**
```json
{
  "status": "ok"
}
```

#### `POST /api/v1/joy/config`
Configure les paramètres du joystick.

**Requête :**
```json
{
  "deadzone": 0.1,        // Optionnel (0.0-0.5)
  "expo": 0.3,            // Optionnel (0.0-0.95)
  "slew_per_s": 500.0,    // Optionnel (≥0)
  "filt_hz": 10.0,        // Optionnel (≥0)
  "slide_speed": 1.5      // Optionnel (0.1-3.0)
}
```

**Réponse :**
```json
{
  "status": "ok",
  "config": {
    "deadzone": 0.1,
    "expo": 0.3,
    "slew_per_s": 500.0,
    "filt_hz": 10.0,
    "slide_speed": 1.5
  }
}
```

---

### Presets (HTTP)

#### `POST /api/v1/presets/set`
Définit un preset avec des positions absolues.

**Requête :**
```json
{
  "index": 0,
  "p": 10000,   // Optionnel
  "t": 20000,   // Optionnel
  "z": 30000,   // Optionnel
  "s": 40000    // Optionnel
}
```

**Réponse :**
```json
{
  "status": "ok",
  "index": 0
}
```

#### `POST /api/v1/presets/store`
Capture les positions actuelles et les sauvegarde dans un preset.

**Requête :**
```json
{
  "index": 0
}
```

**Réponse :**
```json
{
  "status": "ok",
  "index": 0
}
```

#### `POST /api/v1/presets/recall`
Rappelle un preset avec une durée spécifiée.

**Requête :**
```json
{
  "index": 0,
  "duration": 3.0  // Optionnel, défaut: 2.0 secondes
}
```

**Réponse :**
```json
{
  "status": "ok",
  "index": 0,
  "requested_duration_ms": 3000,
  "requested_duration_sec": 3.0,
  "actual_duration_ms": 3500,
  "actual_duration_sec": 3.5,
  "duration_adjusted": true
}
```

---

### Interpolation (HTTP)

#### `POST /api/v1/interp/setpoints`
Définit les points d'interpolation.

**Requête :**
```json
{
  "points": [
    {"preset": 0, "fraction": 0.0},
    {"preset": 1, "fraction": 0.5},
    {"preset": 2, "fraction": 1.0}
  ]
}
```

**Réponse :**
```json
{
  "status": "ok",
  "count": 3
}
```

#### `POST /api/v1/interp/auto`
Active/désactive l'interpolation automatique.

**Requête :**
```json
{
  "enable": true,
  "duration": 10.0  // Optionnel, défaut: 5.0 secondes
}
```

**Réponse :**
```json
{
  "status": "ok",
  "active": true,
  "duration_ms": 10000,
  "duration_sec": 10.0
}
```

#### `POST /api/v1/interp/goto`
Va à une position interpolée immédiatement.

**Requête :**
```json
{
  "fraction": 0.5  // 0.0-1.0
}
```

**Réponse :**
```json
{
  "status": "ok",
  "fraction": 0.5
}
```

#### `POST /api/v1/interp/jog`
Jog de l'axe d'interpolation.

**Requête :**
```json
{
  "amount": 0.3  // -1.0 à +1.0
}
```

**Réponse :**
```json
{
  "status": "ok",
  "amount": 0.3
}
```

---

### Gestion des banques (HTTP)

#### `POST /api/v1/banks/select`
Change la banque active.

**Requête :**
```json
{
  "index": 1  // 0-9
}
```

**Réponse :**
```json
{
  "status": "ok",
  "activeBank": 1,
  "aligned_u0": 0.5
}
```

#### `POST /api/v1/banks/save`
Sauvegarde une banque.

**Requête :**
```json
{
  "index": 1  // Optionnel, défaut: banque active
}
```

**Réponse :**
```json
{
  "status": "ok",
  "savedBank": 1
}
```

#### `GET /api/v1/banks/{index}`
Récupère les presets et points d'interpolation d'une banque.

**Réponse :**
```json
{
  "presets": [
    {"p": 10000, "t": 20000, "z": 30000, "s": 40000},
    ...
  ],
  "interpCount": 3,
  "interpPoints": [
    {"presetIndex": 0, "fraction": 0.0},
    {"presetIndex": 1, "fraction": 0.5},
    {"presetIndex": 2, "fraction": 1.0}
  ]
}
```

---

### Homing (HTTP)

#### `POST /api/v1/homing/slide`
Lance le homing du slide.

**Requête :**
```json
{}
```

**Réponse :**
```json
{
  "status": "ok"
}
```

**Erreur (409) :**
```json
{
  "error": "Homing déjà en cours"
}
```

#### `POST /api/v1/homing/slide/sgthrs`
Définit le seuil StallGuard pour le slide.

**Requête :**
```json
{
  "threshold": 128  // 0-255
}
```

**Réponse :**
```json
{
  "status": "ok",
  "threshold": 128
}
```

---

### Offsets (HTTP)

#### `POST /api/v1/offsets/zero`
Remet les offsets à zéro.

**Requête :**
```json
{
  "pan": true,    // Optionnel, défaut: true
  "tilt": true,   // Optionnel, défaut: true
  "zoom": false,  // Optionnel, défaut: false
  "slide": false  // Optionnel, défaut: false
}
```

**Réponse :**
```json
{
  "status": "ok"
}
```

#### `POST /api/v1/offsets/add`
Ajoute aux offsets actuels.

**Requête :**
```json
{
  "pan": 100,     // Optionnel, défaut: 0
  "tilt": -50,    // Optionnel, défaut: 0
  "zoom": 0,      // Optionnel, défaut: 0
  "slide": 0      // Optionnel, défaut: 0
}
```

**Réponse :**
```json
{
  "status": "ok"
}
```

#### `POST /api/v1/offsets/set`
Définit les offsets absolus.

**Requête :**
```json
{
  "pan": 100,     // Optionnel, défaut: valeur actuelle
  "tilt": -50,    // Optionnel, défaut: valeur actuelle
  "zoom": 0,      // Optionnel, défaut: valeur actuelle
  "slide": 0      // Optionnel, défaut: valeur actuelle
}
```

**Réponse :**
```json
{
  "status": "ok"
}
```

#### `POST /api/v1/offsets/bake`
Intègre les offsets dans le mouvement en cours et les réinitialise.

**Requête :**
```json
{}
```

**Réponse :**
```json
{
  "status": "ok"
}
```

#### `POST /api/v1/offsets/reset_all`
Réinitialise tous les offsets et baselines.

**Requête :**
```json
{}
```

**Réponse :**
```json
{
  "status": "ok"
}
```

---

### Configuration des moteurs (HTTP)

#### `GET /api/v1/motors/config`
Récupère la configuration de tous les moteurs.

**Réponse :**
```json
{
  "pan": {
    "max_speed": 5000,
    "max_accel": 2000,
    "min_limit": 0,
    "max_limit": 100000,
    "microsteps": 16,
    "inverted": false
  },
  "tilt": {...},
  "zoom": {...},
  "slide": {...}
}
```

#### `POST /api/v1/motors/config`
Modifie la configuration d'un moteur.

**Requête :**
```json
{
  "axis": "pan",
  "max_speed": 5000,      // Optionnel
  "max_accel": 2000,      // Optionnel
  "min_limit": 0,         // Optionnel
  "max_limit": 100000,    // Optionnel
  "microsteps": 16,       // Optionnel {1,2,4,8,16,32,64,128,256}
  "inverted": false       // Optionnel
}
```

**Réponse :**
```json
{
  "status": "ok",
  "axis": "pan",
  "changes": {
    "max_speed": true,
    "max_accel": false,
    "min_limit": false,
    "max_limit": false,
    "microsteps": false,
    "inverted": false
  },
  "limits_adjusted": false,
  "limits": {
    "min": 0,
    "max": 100000
  },
  "microsteps": 16,
  "current_position": 50000
}
```

#### `POST /api/v1/motors/driver`
Modifie les paramètres du driver TMC2209.

**Requête :**
```json
{
  "id": 0,              // 0-3 (pan, tilt, zoom, slide)
  "microsteps": 16,     // Optionnel {1,2,4,8,16,32,64,128,256}
  "current": 800,        // Optionnel (0-2000 mA)
  "spreadCycle": true   // Optionnel (0/1)
}
```

**Réponse :**
```json
{
  "status": "ok",
  "id": 0
}
```

#### `POST /api/v1/motors/virtual-homing`
Effectue un "virtual homing" : centre les limites autour de 0 et met la position actuelle à 0.

**Requête :**
```json
{
  "axis": "pan"
}
```

**Réponse :**
```json
{
  "status": "ok",
  "axis": "pan",
  "previous_position": 50000,
  "min_limit": -50000,
  "max_limit": 50000
}
```

---

### Réseau et système (HTTP)

#### `POST /api/v1/network/reset`
Réinitialise la configuration réseau et redémarre en mode AP.

**Requête :**
```json
{}
```

**Réponse :**
```json
{
  "success": true,
  "message": "Activation du portail WiFiManager, redémarrage..."
}
```

#### `POST /api/v1/network/start-portal`
Démarre le portail WiFiManager (redémarrage en mode AP).

**Requête :**
```json
{}
```

**Réponse :**
```json
{
  "success": true,
  "message": "Redémarrage en mode AP pour configuration WiFi..."
}
```

#### `POST /api/v1/system/restart`
Redémarre l'ESP32.

**Requête :**
```json
{}
```

**Réponse :**
```json
{
  "success": true,
  "message": "Redémarrage..."
}
```

---

## Routes Legacy (HTTP)

Ces routes sont maintenues pour la rétrocompatibilité mais peuvent être dépréciées :

- `GET /api/status` → Alias pour `GET /api/v1/status`
- `GET /api/network/info` → Alias pour `GET /api/v1/network/info`
- `POST /api/network/reset` → Alias pour `POST /api/v1/network/reset`
- `POST /api/system/restart` → Alias pour `POST /api/v1/system/restart`
- `GET /api/bank/*` → Retourne 410 (Gone), utiliser `GET /api/v1/banks/{index}`

---

## Notes importantes

### Format des valeurs

- **Positions normalisées** : 0.0 = limite min, 1.0 = limite max
- **Jog/Joystick** : -1.0 = vitesse max négative, +1.0 = vitesse max positive, 0.0 = arrêt
- **Steps** : Valeurs absolues en steps (entiers longs)
- **Durées** : En secondes (float) pour HTTP, en secondes (float) pour OSC

### Validation

- Toutes les valeurs sont automatiquement clampées dans leurs plages valides
- Les commandes invalides sont ignorées silencieusement (OSC) ou retournent une erreur 400 (HTTP)
- Les logs détaillés sont disponibles via `GET /api/v1/logs` ou sur le port série

### Comportements

- **Annulation automatique** : Les mouvements synchronisés sont automatiquement annulés lors de l'utilisation du joystick ou des axes directs (si la politique l'autorise)
- **Interpolation** : Support jusqu'à 6 points d'interpolation, mode automatique et manuel disponibles
- **Homing** : Un seul homing à la fois autorisé, utilise le StallGuard des drivers TMC
- **Offsets** : Les offsets sont "latched" (verrouillés) et persistent jusqu'à reset ou bake

### Exemples d'utilisation

#### Python (OSC)
```python
from pythonosc import osc_message_builder, udp_client

client = udp_client.SimpleUDPClient('slider1.local', 8000)
client.send_message('/axis_pan', [0.5])
client.send_message('/preset/recall', [0, 3.0])
```

#### Python (HTTP)
```python
import requests

response = requests.post('http://slider1.local/api/v1/axes/move', json={
    'axis': 'pan',
    'value': 0.5
})
print(response.json())
```

#### JavaScript (HTTP)
```javascript
fetch('http://slider1.local/api/v1/status')
  .then(res => res.json())
  .then(data => console.log(data));
```

#### Node.js (OSC)
```javascript
const osc = require('osc');

const udpPort = new osc.UDPPort({
  localAddress: "0.0.0.0",
  localPort: 57121
});

udpPort.open();

udpPort.send({
  address: "/axis_pan",
  args: [0.5]
}, "slider1.local", 8000);
```

#### cURL (HTTP)
```bash
# Récupérer le statut
curl http://slider1.local/api/v1/status

# Déplacer Pan à 50%
curl -X POST http://slider1.local/api/v1/axes/move \
  -H "Content-Type: application/json" \
  -d '{"axis": "pan", "value": 0.5}'

# Rappeler preset 0 en 3 secondes
curl -X POST http://slider1.local/api/v1/presets/recall \
  -H "Content-Type: application/json" \
  -d '{"index": 0, "duration": 3.0}'
```

---

## WebSocket

### Publication des positions

Le WebSocket permet de recevoir les positions pan, tilt, zoom et slide en temps réel. Les données sont publiées à **5 Hz** (toutes les 200ms), mais seulement si les positions ont changé.

#### Connexion

**URL :** `ws://hostname.local/ws/positions` ou `ws://IP/ws/positions`

**Exemple :**
- `ws://slider1.local/ws/positions`
- `ws://192.168.1.37/ws/positions`

#### Format du message

Les messages sont envoyés au format JSON avec les positions en **steps** et **normalisé** (0.0-1.0) :

```json
{
  "pan": {
    "steps": 12345,
    "normalized": 0.5
  },
  "tilt": {
    "steps": 6789,
    "normalized": 0.75
  },
  "zoom": {
    "steps": 1000,
    "normalized": 0.3
  },
  "slide": {
    "steps": 5000,
    "normalized": 0.6
  },
  "timestamp": 1234567890
}
```

#### Comportement

- **Fréquence** : 5 Hz (toutes les 200ms)
- **Publication conditionnelle** : Les messages sont envoyés uniquement si au moins une position (pan, tilt, zoom ou slide) a changé
- **Support multi-clients** : Plusieurs clients peuvent se connecter simultanément
- **Pas de messages si aucun client** : Si aucun client n'est connecté, aucun message n'est généré

#### Exemples d'utilisation

**JavaScript (navigateur)**
```javascript
const ws = new WebSocket('ws://slider1.local/ws/positions');

ws.onopen = () => {
  console.log('WebSocket connecté');
};

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log('Pan:', data.pan.steps, '(', data.pan.normalized, ')');
  console.log('Tilt:', data.tilt.steps, '(', data.tilt.normalized, ')');
  console.log('Zoom:', data.zoom.steps, '(', data.zoom.normalized, ')');
  console.log('Slide:', data.slide.steps, '(', data.slide.normalized, ')');
};

ws.onerror = (error) => {
  console.error('Erreur WebSocket:', error);
};

ws.onclose = () => {
  console.log('WebSocket fermé');
};
```

**Python**
```python
import asyncio
import websockets
import json

async def listen_positions():
    uri = "ws://slider1.local/ws/positions"
    async with websockets.connect(uri) as websocket:
        while True:
            message = await websocket.recv()
            data = json.loads(message)
            print(f"Pan: {data['pan']['steps']} ({data['pan']['normalized']})")
            print(f"Tilt: {data['tilt']['steps']} ({data['tilt']['normalized']})")
            print(f"Zoom: {data['zoom']['steps']} ({data['zoom']['normalized']})")
            print(f"Slide: {data['slide']['steps']} ({data['slide']['normalized']})")

asyncio.run(listen_positions())
```

**Node.js**
```javascript
const WebSocket = require('ws');

const ws = new WebSocket('ws://slider1.local/ws/positions');

ws.on('open', () => {
  console.log('WebSocket connecté');
});

ws.on('message', (data) => {
  const positions = JSON.parse(data);
  console.log('Positions:', positions);
});

ws.on('error', (error) => {
  console.error('Erreur:', error);
});
```

#### Notes importantes

- Les positions sont publiées uniquement si elles ont changé (détection de variance)
- Le timestamp est en millisecondes depuis le démarrage de l'ESP32 (`millis()`)
- Les valeurs normalisées sont calculées entre les limites min/max de chaque axe
- Tous les axes (pan, tilt, zoom, slide) sont inclus dans chaque message
- Le WebSocket se reconnecte automatiquement en cas de déconnexion (selon l'implémentation du client)

---

## Support

Pour plus d'informations, consultez :
- `OSC_API.md` - Documentation OSC détaillée
- `OSC_ROUTES.md` - Référence rapide des routes OSC
- `README.md` - Documentation générale du projet

