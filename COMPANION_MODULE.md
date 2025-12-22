# Guide de développement du module Bitfocus Companion

Ce document explique comment créer un module Bitfocus Companion pour contrôler les caméras Blackmagic via l'application PySide6.

## Architecture

L'application PySide6 expose un serveur WebSocket sur le port **8765** qui permet à Companion de :
- Recevoir des mises à jour d'état en temps réel (snapshots et patchs incrémentaux)
- Envoyer des commandes pour contrôler les caméras (set_param, nudge, recall_preset, etc.)

## Connexion WebSocket

### URL de connexion
```
ws://localhost:8765
```

### Messages initiaux

#### 1. Envoyer un message `hello` à la connexion
```json
{
  "type": "hello",
  "client": "companion",
  "version": 1
}
```

#### 2. Recevoir un `snapshot` initial
L'application répondra immédiatement avec un snapshot complet de l'état :

```json
{
  "type": "snapshot",
  "state": {
    "active_cam": 1,
    "cams": {
      "1": {
        "connected": true,
        "focus": 0.12,
        "iris": 2.8,
        "gain": 12,
        "shutter": 0.02,
        "whiteBalance": 3200,
        "zoom": 0.0
      },
      "2": {
        "connected": false,
        "focus": null,
        "iris": null,
        "gain": null,
        "shutter": null,
        "whiteBalance": null,
        "zoom": null
      },
      ...
    },
    "meta": {
      "app": "koko-focus",
      "version": "0.1"
    }
  }
}
```

#### 3. Recevoir des `patch` incrémentaux
Après le snapshot initial, l'application enverra des patchs incrémentaux à chaque changement :

```json
{
  "type": "patch",
  "patch": {
    "cams": {
      "3": {
        "focus": 0.43
      }
    }
  }
}
```

```json
{
  "type": "patch",
  "patch": {
    "active_cam": 2
  }
}
```

**Important** : Les presets ne sont **jamais** inclus dans les snapshots ni les patchs. Companion n'a **jamais accès** au contenu des presets (focus, iris, gain, etc.). Companion peut seulement :
- Rappeler un preset par son numéro avec `recall_preset`
- Sauvegarder les valeurs actuelles dans un preset avec `store_preset`

Les valeurs des paramètres après un rappel de preset seront reçues normalement via les patchs WebSocket.

## Commandes disponibles

Toutes les commandes sont envoyées avec le format suivant :

```json
{
  "type": "cmd",
  "cmd": "<nom_commande>",
  ...
}
```

### 1. `set_active_cam`

Change la caméra active (affichée dans l'UI). **Note** : Cela ne désactive pas les autres caméras, toutes restent contrôlables.

```json
{
  "type": "cmd",
  "cmd": "set_active_cam",
  "cam": 3
}
```

**Réponse** :
```json
{
  "type": "ack",
  "ok": true
}
```

ou en cas d'erreur :
```json
{
  "type": "ack",
  "ok": false,
  "error": "Numéro de caméra invalide: 9 (doit être entre 1 et 8)"
}
```

### 2. `set_param`

Définit la valeur d'un paramètre pour une caméra spécifique.

**Paramètres supportés** : `focus`, `iris`, `gain`, `shutter`, `whiteBalance`

```json
{
  "type": "cmd",
  "cmd": "set_param",
  "cam": 3,
  "param": "focus",
  "value": 0.42
}
```

```json
{
  "type": "cmd",
  "cmd": "set_param",
  "cam": 3,
  "param": "iris",
  "value": 0.65
}
```

```json
{
  "type": "cmd",
  "cmd": "set_param",
  "cam": 3,
  "param": "gain",
  "value": 18
}
```

```json
{
  "type": "cmd",
  "cmd": "set_param",
  "cam": 3,
  "param": "shutter",
  "value": 50
}
```

```json
{
  "type": "cmd",
  "cmd": "set_param",
  "cam": 3,
  "param": "whiteBalance",
  "value": 3200
}
```

**Valeurs** :
- `focus` : 0.0 à 1.0 (float)
- `iris` : 0.0 à 1.0 (float) - **Note** : Dans les snapshots et patchs, `iris` est envoyé en aperture stop (f/2.8, f/4, etc.) au lieu de la valeur normalisée. Pour `set_param`, utilisez toujours la valeur normalisée (0.0-1.0).
- `gain` : Valeur entière en dB (doit correspondre à une valeur supportée par la caméra)
- `shutter` : Valeur entière en fractions de seconde (doit correspondre à une valeur supportée par la caméra)
- `whiteBalance` : Valeur entière en Kelvin (doit être dans la plage min/max de la caméra, généralement 2000K-10000K)

**Réponse** :
```json
{
  "type": "ack",
  "ok": true
}
```

### 3. `nudge`

Ajuste un paramètre d'une valeur delta relative.

```json
{
  "type": "cmd",
  "cmd": "nudge",
  "cam": 3,
  "param": "focus",
  "delta": -0.01
}
```

```json
{
  "type": "cmd",
  "cmd": "nudge",
  "cam": 3,
  "param": "iris",
  "delta": 0.05
}
```

```json
{
  "type": "cmd",
  "cmd": "nudge",
  "cam": 3,
  "param": "gain",
  "delta": 3
}
```

```json
{
  "type": "cmd",
  "cmd": "nudge",
  "cam": 3,
  "param": "whiteBalance",
  "delta": 100
}
```

**Comportement** :
- **Pour `focus` et `iris` uniquement** : Le delta est ajouté à la valeur actuelle (normalisée), puis la valeur est clampée entre 0.0 et 1.0
- **Note** : `nudge` ne fonctionne que pour `focus` et `iris` (valeurs continues). Pour `gain`, `shutter` et `whiteBalance` (valeurs discrètes), utilisez la commande `adjust_param` avec `direction: "up"` ou `"down"`.
- Pour `iris` : Même si Companion reçoit l'aperture stop dans les snapshots/patchs, le delta pour `nudge` doit être en valeur normalisée (ex: 0.01 pour un petit ajustement).

**Réponse** :
```json
{
  "type": "ack",
  "ok": true
}
```

### 4. `recall_preset`

Rappelle un preset sauvegardé pour une caméra.

```json
{
  "type": "cmd",
  "cmd": "recall_preset",
  "cam": 3,
  "preset_number": 1
}
```

**Presets** : Numérotés de 1 à 10

**Important** : 
- Companion n'a **jamais accès au contenu** des presets (focus, iris, gain, etc.)
- Companion peut seulement rappeler un preset par son numéro
- Si la transition progressive est activée dans l'UI, le focus sera interpolé sur 2 secondes. Sinon, tous les paramètres sont appliqués instantanément
- Après le rappel, les nouvelles valeurs seront reçues via les patchs WebSocket normaux

**Réponse** :
```json
{
  "type": "ack",
  "ok": true
}
```

### 5. `store_preset`

Sauvegarde les valeurs actuelles d'une caméra dans un preset.

```json
{
  "type": "cmd",
  "cmd": "store_preset",
  "cam": 3,
  "preset_number": 1
}
```

**Presets** : Numérotés de 1 à 10

**Important** :
- Cette commande sauvegarde les valeurs **actuelles** de la caméra (focus, iris, gain, shutter, whiteBalance, zoom)
- Le contenu du preset sauvegardé n'est **pas envoyé** à Companion
- Companion n'a pas besoin de connaître ce qui a été sauvegardé, seulement de pouvoir le rappeler plus tard avec `recall_preset`

**Réponse** :
```json
{
  "type": "ack",
  "ok": true
}
```

### 6. `do_autofocus`

Déclenche l'autofocus sur une caméra spécifique.

```json
{
  "type": "cmd",
  "cmd": "do_autofocus",
  "cam": 3
}
```

**Paramètres** :
- `cam` : Numéro de la caméra (1-8)

**Comportement** :
- Déclenche l'autofocus sur la caméra spécifiée avec position ROI à (0.5, 0.5) - centre de l'image
- L'autofocus peut prendre quelques secondes à se terminer
- La nouvelle valeur de focus sera automatiquement reçue via les patchs WebSocket normaux après l'autofocus
- L'ack est renvoyé immédiatement après l'envoi de la commande à la caméra (ne pas attendre la fin de l'autofocus)

**Réponse** :
```json
{
  "type": "ack",
  "ok": true
}
```

ou en cas d'erreur :
```json
{
  "type": "ack",
  "ok": false,
  "error": "Caméra 3 non connectée"
}
```

### 7. `do_autowhitebalance`

Déclenche l'auto white balance sur une caméra spécifique.

```json
{
  "type": "cmd",
  "cmd": "do_autowhitebalance",
  "cam": 3
}
```

**Paramètres** :
- `cam` : Numéro de la caméra (1-8)

**Comportement** :
- Déclenche l'auto white balance sur la caméra spécifiée
- L'auto white balance peut prendre quelques secondes à se terminer
- La nouvelle valeur de white balance sera automatiquement reçue via les patchs WebSocket normaux après l'auto white balance
- L'ack est renvoyé immédiatement après l'envoi de la commande à la caméra (ne pas attendre la fin de l'auto white balance)

**Réponse** :
```json
{
  "type": "ack",
  "ok": true
}
```

ou en cas d'erreur :
```json
{
  "type": "ack",
  "ok": false,
  "error": "Caméra 3 non connectée"
}
```

### 8. `adjust_param`

Ajuste un paramètre discret (gain, shutter, whiteBalance) d'un pas vers le haut ou le bas, exactement comme les boutons +/- dans l'UI.

```json
{
  "type": "cmd",
  "cmd": "adjust_param",
  "cam": 3,
  "param": "gain",
  "direction": "up"
}
```

```json
{
  "type": "cmd",
  "cmd": "adjust_param",
  "cam": 3,
  "param": "gain",
  "direction": "down"
}
```

```json
{
  "type": "cmd",
  "cmd": "adjust_param",
  "cam": 3,
  "param": "shutter",
  "direction": "up"
}
```

```json
{
  "type": "cmd",
  "cmd": "adjust_param",
  "cam": 3,
  "param": "whiteBalance",
  "direction": "down"
}
```

**Paramètres supportés** : `gain`, `shutter`, `whiteBalance`

**Direction** : `"up"` ou `"down"`

**Comportement** :
- **Pour `gain`** : Passe à la valeur suivante/précédente dans la liste des gains supportés (ex: -12, -6, 0, 6, 12, 18 dB)
- **Pour `shutter`** : Passe à la vitesse suivante/précédente dans la liste des vitesses supportées (ex: 50, 60, 120, 240)
- **Pour `whiteBalance`** : Incrémente/décrémente de 100K (avec respect des limites min/max, généralement 2000K-10000K)

**Réponse** :
```json
{
  "type": "ack",
  "ok": true
}
```

ou en cas d'erreur :
```json
{
  "type": "ack",
  "ok": false,
  "error": "Caméra 3 non connectée"
}
```

ou si le paramètre n'est pas supporté :
```json
{
  "type": "ack",
  "ok": false,
  "error": "Paramètre non supporté pour adjust_param: focus (supportés: gain, shutter, whiteBalance)"
}
```

## Structure de données

### État d'une caméra

```typescript
interface CameraState {
  connected: boolean;
  focus: number | null;      // 0.0 à 1.0
  iris: number | null;        // Aperture stop (f/2.8, f/4, etc.) - pas la valeur normalisée
  gain: number | null;        // dB (entier)
  shutter: number | null;    // fractions de seconde (entier)
  whiteBalance: number | null; // Kelvin (entier, généralement 2000K-10000K)
  zoom: number | null;       // 0.0 à 1.0
}
```

### État complet

```typescript
interface AppState {
  active_cam: number;           // 1-8
  cams: {
    [key: string]: CameraState;  // "1" à "8"
  };
  meta: {
    app: string;
    version: string;
  };
}
```

**Important** : Les presets ne sont **jamais** inclus dans l'état. Companion n'a **jamais accès** au contenu des presets. Companion peut seulement :
- Rappeler un preset par son numéro (1-10) avec `recall_preset`
- Sauvegarder les valeurs actuelles dans un preset avec `store_preset`

Les valeurs des paramètres après un rappel de preset seront reçues normalement via les patchs WebSocket.

## Exemple de code JavaScript/TypeScript

```javascript
class CompanionModule {
  constructor() {
    this.ws = null;
    this.state = null;
    this.reconnectDelay = 5000;
  }

  connect() {
    this.ws = new WebSocket('ws://localhost:8765');
    
    this.ws.onopen = () => {
      console.log('Connected to PySide6 app');
      // Envoyer hello
      this.ws.send(JSON.stringify({
        type: 'hello',
        client: 'companion',
        version: 1
      }));
    };
    
    this.ws.onmessage = (event) => {
      const message = JSON.parse(event.data);
      this.handleMessage(message);
    };
    
    this.ws.onerror = (error) => {
      console.error('WebSocket error:', error);
    };
    
    this.ws.onclose = () => {
      console.log('WebSocket closed, reconnecting...');
      setTimeout(() => this.connect(), this.reconnectDelay);
    };
  }

  handleMessage(message) {
    switch (message.type) {
      case 'snapshot':
        this.state = message.state;
        console.log('Received snapshot:', this.state);
        this.onStateUpdate();
        break;
        
      case 'patch':
        this.applyPatch(message.patch);
        console.log('Applied patch:', message.patch);
        this.onStateUpdate();
        break;
        
      case 'ack':
        console.log('Ack received:', message.ok, message.error || '');
        break;
    }
  }

  applyPatch(patch) {
    if (!this.state) return;
    
    // Mettre à jour active_cam
    if (patch.active_cam !== undefined) {
      this.state.active_cam = patch.active_cam;
    }
    
    // Mettre à jour les caméras
    if (patch.cams) {
      for (const [camKey, camData] of Object.entries(patch.cams)) {
        if (!this.state.cams[camKey]) {
          this.state.cams[camKey] = {};
        }
        Object.assign(this.state.cams[camKey], camData);
      }
    }
    
    // Note: Les presets ne sont pas inclus dans les patchs
  }

  sendCommand(cmd) {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      console.error('WebSocket not connected');
      return;
    }
    
    const message = {
      type: 'cmd',
      ...cmd
    };
    
    this.ws.send(JSON.stringify(message));
  }

  // Méthodes de commande
  setActiveCam(cam) {
    this.sendCommand({
      cmd: 'set_active_cam',
      cam: cam
    });
  }

  setParam(cam, param, value) {
    this.sendCommand({
      cmd: 'set_param',
      cam: cam,
      param: param,
      value: value
    });
  }

  nudge(cam, param, delta) {
    this.sendCommand({
      cmd: 'nudge',
      cam: cam,
      param: param,
      delta: delta
    });
  }

  recallPreset(cam, presetNumber) {
    this.sendCommand({
      cmd: 'recall_preset',
      cam: cam,
      preset_number: presetNumber
    });
  }

  storePreset(cam, presetNumber) {
    this.sendCommand({
      cmd: 'store_preset',
      cam: cam,
      preset_number: presetNumber
    });
  }

  doAutofocus(cam) {
    this.sendCommand({
      cmd: 'do_autofocus',
      cam: cam
    });
  }

  doAutowhitebalance(cam) {
    this.sendCommand({
      cmd: 'do_autowhitebalance',
      cam: cam
    });
  }

  adjustParam(cam, param, direction) {
    this.sendCommand({
      cmd: 'adjust_param',
      cam: cam,
      param: param,
      direction: direction
    });
  }

  onStateUpdate() {
    // Callback appelé quand l'état est mis à jour
    // À implémenter selon les besoins du module Companion
  }
}

// Utilisation
const module = new CompanionModule();
module.connect();

// Exemples d'utilisation
setTimeout(() => {
  // Changer le focus de la caméra 1
  module.setParam(1, 'focus', 0.5);
  
  // Ajuster le focus de la caméra 2
  module.nudge(2, 'focus', 0.01);
  
  // Rappeler le preset 1 de la caméra 3
  module.recallPreset(3, 1);
  
  // Déclencher l'autofocus sur la caméra 2
  module.doAutofocus(2);
  
  // Déclencher l'auto white balance sur la caméra 1
  module.doAutowhitebalance(1);
  
  // Définir le white balance de la caméra 1 à 3200K
  module.setParam(1, 'whiteBalance', 3200);
  
  // Ajuster le gain de la caméra 2 vers le haut (valeur suivante)
  module.adjustParam(2, 'gain', 'up');
  
  // Ajuster le shutter de la caméra 3 vers le bas (vitesse précédente)
  module.adjustParam(3, 'shutter', 'down');
  
  // Ajuster le white balance de la caméra 1 vers le haut (+100K)
  module.adjustParam(1, 'whiteBalance', 'up');
}, 2000);
```

## Gestion des erreurs

Toutes les commandes retournent un `ack` avec `ok: true` en cas de succès, ou `ok: false` avec un champ `error` en cas d'erreur.

**Erreurs courantes** :
- `"Champ 'cam' manquant"` : Le numéro de caméra n'a pas été fourni
- `"Numéro de caméra invalide: X (doit être entre 1 et 8)"` : Le numéro de caméra est hors limites
- `"Caméra X non configurée"` : La caméra n'existe pas dans la configuration
- `"Caméra X non connectée"` : La caméra n'est pas connectée à l'application
- `"Paramètre inconnu: X"` : Le paramètre n'est pas supporté
- `"Gains supportés non chargés pour cette caméra"` : Les valeurs supportées n'ont pas encore été chargées

## Notes importantes

1. **Toutes les caméras restent actives** : Changer la caméra active (`set_active_cam`) ne désactive pas les autres caméras. Toutes les caméras connectées peuvent être contrôlées simultanément, même si elles ne sont pas affichées dans l'UI.

2. **Valeurs supportées pour gain, shutter et whiteBalance** : Les valeurs de `gain` et `shutter` doivent correspondre aux valeurs supportées par la caméra. Ces valeurs sont chargées automatiquement lors de la connexion. Si vous essayez de définir une valeur non supportée, l'application sélectionnera automatiquement la valeur la plus proche. Pour `whiteBalance`, la valeur doit être dans la plage min/max de la caméra (généralement 2000K-10000K), qui est également chargée automatiquement lors de la connexion.

3. **Throttling** : L'application gère automatiquement le throttling pour éviter d'envoyer trop de requêtes à la caméra. Pour le focus, il y a un délai de 50ms entre chaque envoi. Pour les autres paramètres, le throttling est de 500ms.

4. **Presets** : Companion n'a **jamais accès** au contenu des presets. Les presets ne sont jamais envoyés dans les snapshots ni les patchs. Companion peut seulement rappeler et sauvegarder des presets par leur numéro (1-10). Les valeurs des paramètres après un rappel de preset seront reçues normalement via les patchs WebSocket.

5. **Transition progressive** : Si la transition progressive est activée dans l'UI, le focus sera interpolé sur 2 secondes lors du rappel d'un preset. Cette fonctionnalité est contrôlée par l'utilisateur dans l'UI et ne peut pas être modifiée via l'API.

6. **Reconnexion automatique** : En cas de déconnexion, le module Companion doit gérer la reconnexion automatique. L'application enverra automatiquement un nouveau snapshot à la reconnexion.

## Tests

Pour tester la connexion, vous pouvez utiliser un client WebSocket comme `wscat` :

```bash
npm install -g wscat
wscat -c ws://localhost:8765
```

Ensuite, envoyez :
```json
{"type":"hello","client":"companion","version":1}
```

Vous devriez recevoir un snapshot immédiatement.

Pour tester une commande :
```json
{"type":"cmd","cmd":"set_active_cam","cam":2}
```

Vous devriez recevoir :
```json
{"type":"ack","ok":true}
```

