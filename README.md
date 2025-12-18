# Contrôleur de Focus Blackmagic

Script Python pour contrôler le focus d'une caméra Blackmagic via l'API REST.

## Installation

1. **Installer les dépendances** :
```bash
pip install -r requirements.txt
```

Ou si vous utilisez Python 3 spécifiquement :
```bash
pip3 install -r requirements.txt
```

## Lancement du script

### Interface Web (recommandé pour le contrôle visuel)

Interface graphique avec slider vertical et affichage en temps réel :

```bash
python3 focus_ui.py
```

Puis ouvrez votre navigateur à l'adresse affichée (par défaut: http://127.0.0.1:5000)

**Fonctionnalités :**
- Slider vertical pour contrôler le focus (0.0 à 1.0)
- Affichage en temps réel de la valeur actuelle du focus
- Mise à jour automatique toutes les 250ms
- Boutons pour actualiser et réinitialiser

**Options :**
- `--port` : Port du serveur web (défaut: 5000)
- `--host` : Adresse IP (défaut: 127.0.0.1, utilisez 0.0.0.0 pour accès réseau)
- `--url` : URL de la caméra
- `--user` : Nom d'utilisateur
- `--pass` : Mot de passe

**Exemple :**
```bash
# Interface web sur le port 8080
python3 focus_ui.py --port 8080

# Interface accessible depuis le réseau
python3 focus_ui.py --host 0.0.0.0 --port 5000
```

### Mode interactif (terminal)

Le mode interactif permet de changer le focus en temps réel sans redémarrer le script :

```bash
python blackmagic_focus_control.py --interactive
```

ou avec Python 3 :
```bash
python3 blackmagic_focus_control.py --interactive
```

Dans le mode interactif, vous pouvez :
- Taper une valeur (ex: `0.5`) pour changer le focus
- Utiliser `save 0.5` pour sauvegarder dans la config
- Utiliser `get` pour lire la valeur actuelle
- Utiliser `quit` pour quitter

### Autres modes

**Polling uniquement** (affiche la valeur 4 fois par seconde) :
```bash
python blackmagic_focus_control.py --polling
```

**Définir une valeur une fois** :
```bash
python blackmagic_focus_control.py --set 0.5
```

**Lire la valeur actuelle** :
```bash
python blackmagic_focus_control.py --get
```

**Polling + surveillance du fichier config** :
```bash
python blackmagic_focus_control.py --polling --watch-config
```

## Configuration

Pour définir une valeur par défaut, créez un fichier `focus_config.json` :
```json
{
  "target_focus": 0.5
}
```

Puis chargez-la :
```bash
python blackmagic_focus_control.py --load-config
```

## Options disponibles

- `--url` : URL de la caméra (défaut: https://Micro-Studio-Camera-4K-G2.local)
- `--user` : Nom d'utilisateur (défaut: roo)
- `--pass` : Mot de passe (défaut: koko)
- `--frequency` : Fréquence de polling en Hz (défaut: 4)
- `--interactive` ou `-i` : Mode interactif
- `--polling` : Démarrer le polling
- `--watch-config` : Surveiller le fichier de configuration

## Exemple complet

```bash
# 1. Installer les dépendances
pip install -r requirements.txt

# 2. Lancer en mode interactif
python blackmagic_focus_control.py --interactive

# 3. Dans le mode interactif, taper :
> 0.5        # Change le focus à 0.5
> 0.325      # Change le focus à 0.325
> save 0.4   # Change et sauvegarde
> quit       # Quitte
```

