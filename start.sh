#!/bin/bash
# Script de démarrage pour l'interface web de contrôle Focus Blackmagic

# Couleurs pour les messages
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Fonction pour nettoyer à l'arrêt
cleanup() {
    echo -e "\n${YELLOW}Arrêt de l'application...${NC}"
    exit 0
}

# Capturer les signaux
trap cleanup SIGINT SIGTERM

# Fonction pour afficher les messages d'erreur
error() {
    echo -e "${RED}❌ Erreur: $1${NC}" >&2
    exit 1
}

# Fonction pour afficher les messages de succès
success() {
    echo -e "${GREEN}✓ $1${NC}"
}

# Fonction pour afficher les messages d'information
info() {
    echo -e "${BLUE}ℹ $1${NC}"
}

# Fonction pour arrêter les processus existants
kill_existing_processes() {
    info "Recherche de processus focus_ui.py existants..."
    
    # Trouver les PID des processus focus_ui.py
    PIDS=$(ps aux | grep "[f]ocus_ui.py" | awk '{print $2}')
    
    if [ -z "$PIDS" ]; then
        success "Aucun processus existant trouvé"
        return 0
    fi
    
    # Compter le nombre de processus
    PROCESS_COUNT=$(echo "$PIDS" | wc -l | tr -d ' ')
    info "Processus existant(s) trouvé(s): $PROCESS_COUNT"
    
    # Arrêter chaque processus
    for PID in $PIDS; do
        if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
            info "Arrêt du processus PID: $PID"
            # Envoyer SIGTERM pour arrêt propre
            kill -TERM "$PID" 2>/dev/null
            
            # Attendre jusqu'à 5 secondes que le processus se termine
            WAIT_COUNT=0
            while kill -0 "$PID" 2>/dev/null && [ $WAIT_COUNT -lt 5 ]; do
                sleep 1
                WAIT_COUNT=$((WAIT_COUNT + 1))
            done
            
            # Si le processus est toujours actif, envoyer SIGKILL
            if kill -0 "$PID" 2>/dev/null; then
                info "Le processus $PID n'a pas répondu à SIGTERM, envoi de SIGKILL..."
                kill -KILL "$PID" 2>/dev/null
                sleep 1
            fi
            
            # Vérifier que le processus est bien arrêté
            if ! kill -0 "$PID" 2>/dev/null; then
                success "Processus $PID arrêté avec succès"
            else
                echo -e "${YELLOW}⚠ Avertissement: Impossible d'arrêter le processus $PID${NC}"
            fi
        fi
    done
    
    # Vérifier si le port est toujours utilisé (PORT doit être défini)
    if [ -n "$PORT" ] && command -v lsof &> /dev/null; then
        PORT_PID=$(lsof -ti:$PORT 2>/dev/null)
        if [ -n "$PORT_PID" ]; then
            info "Port $PORT toujours utilisé par PID: $PORT_PID"
            kill -TERM "$PORT_PID" 2>/dev/null
            sleep 1
            if kill -0 "$PORT_PID" 2>/dev/null; then
                kill -KILL "$PORT_PID" 2>/dev/null
            fi
            success "Port $PORT libéré"
        fi
    fi
    
    echo ""
}

# Afficher le message de démarrage
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  Interface Web Contrôle Focus Blackmagic${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# 1. Vérifier que Python 3 est installé
info "Vérification de Python 3..."
if ! command -v python3 &> /dev/null; then
    error "Python 3 n'est pas installé. Veuillez l'installer d'abord."
fi

PYTHON_VERSION=$(python3 --version 2>&1)
success "Python 3 trouvé: $PYTHON_VERSION"

# 2. Vérifier que le fichier focus_ui.py existe
info "Vérification des fichiers requis..."
if [ ! -f "focus_ui.py" ]; then
    error "Le fichier focus_ui.py est introuvable dans le répertoire actuel."
fi
success "focus_ui.py trouvé"

# 3. Vérifier que requirements.txt existe
if [ ! -f "requirements.txt" ]; then
    error "Le fichier requirements.txt est introuvable dans le répertoire actuel."
fi
success "requirements.txt trouvé"

# 4. Définir les paramètres par défaut avant de tuer les processus (pour kill_existing_processes)
PORT="5000"
HOST="127.0.0.1"

# 5. Arrêter les processus existants
kill_existing_processes

# 6. Vérifier et installer les dépendances
info "Vérification des dépendances Python..."
if ! python3 -c "import flask, flask_socketio, requests, websockets" &> /dev/null 2>&1; then
    info "Installation des dépendances depuis requirements.txt..."
    if ! python3 -m pip install -r requirements.txt --quiet; then
        error "Échec de l'installation des dépendances. Vérifiez votre connexion internet et les permissions."
    fi
    success "Dépendances installées avec succès"
else
    success "Dépendances déjà installées"
fi

# 7. Paramètres de connexion caméra
CAMERA_URL="http://Micro-Studio-Camera-4K-G2.local"
CAMERA_USER="roo"
CAMERA_PASSWORD="koko"

# Afficher les paramètres utilisés
echo ""
info "Paramètres de connexion:"
echo "  URL caméra: $CAMERA_URL"
echo "  Utilisateur: $CAMERA_USER"
echo "  Port: $PORT"
echo "  Host: $HOST"
echo ""

# 8. Vérifier et libérer le port si nécessaire
info "Vérification que le port $PORT est libre..."
if command -v lsof &> /dev/null; then
    PORT_PID=$(lsof -ti:$PORT 2>/dev/null)
    if [ -n "$PORT_PID" ]; then
        info "Port $PORT utilisé par le processus PID: $PORT_PID, libération..."
        kill -TERM "$PORT_PID" 2>/dev/null
        sleep 1
        if kill -0 "$PORT_PID" 2>/dev/null; then
            info "Le processus $PORT_PID n'a pas répondu à SIGTERM, envoi de SIGKILL..."
            kill -KILL "$PORT_PID" 2>/dev/null
            sleep 1
        fi
        if ! kill -0 "$PORT_PID" 2>/dev/null; then
            success "Port $PORT libéré (PID $PORT_PID arrêté)"
        else
            error "Impossible de libérer le port $PORT (PID $PORT_PID toujours actif). Arrêtez-le manuellement."
        fi
    else
        success "Port $PORT est libre"
    fi
else
    info "lsof non disponible, impossible de vérifier le port"
fi

# 9. Lancer l'application
info "Démarrage de l'application..."
echo -e "${GREEN}Interface web disponible à: http://$HOST:$PORT${NC}"
echo -e "${YELLOW}Appuyez sur Ctrl+C pour arrêter${NC}"
echo ""

# Lancer l'application avec les paramètres par défaut
# Ne pas lancer en arrière-plan pour voir les erreurs
python3 focus_ui.py \
    --url "$CAMERA_URL" \
    --user "$CAMERA_USER" \
    --pass "$CAMERA_PASSWORD" \
    --port "$PORT" \
    --host "$HOST"

# Si on arrive ici, l'application s'est arrêtée
EXIT_CODE=$?
if [ $EXIT_CODE -ne 0 ]; then
    error "L'application s'est arrêtée avec le code d'erreur $EXIT_CODE"
fi
cleanup

