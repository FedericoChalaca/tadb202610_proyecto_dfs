#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# setup_datanode.sh — Instalación de un DataNode en una EC2 Ubuntu 22.04
# ─────────────────────────────────────────────────────────────────────────────
#
# Uso:
#   chmod +x setup_datanode.sh
#   sudo ./setup_datanode.sh <NODE_ID> <NAMENODE_IP> <OWN_PUBLIC_IP>
#
# Ejemplo:
#   sudo ./setup_datanode.sh DN1 54.123.45.67 54.123.45.68
#
# Parámetros:
#   NODE_ID       — Identificador del nodo (DN1, DN2, DN3)
#   NAMENODE_IP   — IP pública de la EC2 del NameNode
#   OWN_PUBLIC_IP — IP pública de ESTA EC2 (para registro en el NameNode)
#
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

# ── CONFIGURACIÓN ────────────────────────────────────────────────────────────

REPO_URL="https://github.com/FedericoChalaca/tadb202610_proyecto_dfs"  # ← Reemplazar con la URL del repositorio
INSTALL_DIR="/opt/dfs"
DATANODE_PORT=8001  # Todos los DataNodes usan el mismo puerto en AWS

# ── PARÁMETROS ───────────────────────────────────────────────────────────────

if [[ $# -lt 3 ]]; then
    echo "Uso: sudo $0 <NODE_ID> <NAMENODE_IP> <OWN_PUBLIC_IP>"
    echo ""
    echo "Ejemplo: sudo $0 DN1 54.123.45.67 54.123.45.68"
    exit 1
fi

NODE_ID="$1"
NAMENODE_IP="$2"
OWN_PUBLIC_IP="$3"

# ── COLORES ──────────────────────────────────────────────────────────────────

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

# ── VERIFICACIONES ───────────────────────────────────────────────────────────

if [[ $EUID -ne 0 ]]; then
   error "Este script debe ejecutarse como root (usa sudo)"
fi

info "═══════════════════════════════════════════════════════════════"
info "  Instalación del DataNode $NODE_ID — DFS por Bloques"
info "═══════════════════════════════════════════════════════════════"
info "  NODE_ID:        $NODE_ID"
info "  Puerto:         $DATANODE_PORT"
info "  NameNode:       http://$NAMENODE_IP:8000"
info "  IP pública:     $OWN_PUBLIC_IP"
info "═══════════════════════════════════════════════════════════════"

# ── PASO 1: ACTUALIZAR PAQUETES ─────────────────────────────────────────────

info "Paso 1/6: Actualizando paquetes del sistema..."
apt-get update -y
apt-get upgrade -y
apt-get install -y ca-certificates curl gnupg lsb-release git

# ── PASO 2: INSTALAR DOCKER ─────────────────────────────────────────────────

info "Paso 2/6: Instalando Docker CE..."

if command -v docker &> /dev/null; then
    info "Docker ya está instalado, saltando..."
else
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | \
        gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg

    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
      https://download.docker.com/linux/ubuntu \
      $(lsb_release -cs) stable" | \
      tee /etc/apt/sources.list.d/docker.list > /dev/null

    apt-get update -y
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

    usermod -aG docker ubuntu
fi

info "Docker version: $(docker --version)"
info "Docker Compose version: $(docker compose version)"

# ── PASO 3: CLONAR REPOSITORIO ──────────────────────────────────────────────

info "Paso 3/6: Clonando repositorio..."

if [[ "$REPO_URL" == "YOUR_GITHUB_REPO_URL" ]]; then
    error "Debes editar REPO_URL en este script con la URL real del repositorio"
fi

if [[ -d "$INSTALL_DIR" ]]; then
    warn "Directorio $INSTALL_DIR ya existe, actualizando..."
    cd "$INSTALL_DIR"
    git pull origin main || git pull origin master || true
else
    git clone "$REPO_URL" "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi

# ── PASO 4: CREAR ARCHIVO .env ──────────────────────────────────────────────

info "Paso 4/6: Creando archivo .env para $NODE_ID..."

cat > "$INSTALL_DIR/aws/.env" <<EOF
# ─── Configuración del DataNode $NODE_ID ─────────────────────────────────────
# Generado por setup_datanode.sh el $(date)

NODE_ID=$NODE_ID
PORT=$DATANODE_PORT
HOST=$OWN_PUBLIC_IP
NAMENODE_URL=http://$NAMENODE_IP:8000
HEARTBEAT_INTERVAL=30
EOF

info "Archivo .env creado:"
cat "$INSTALL_DIR/aws/.env"

# ── PASO 5: CONSTRUIR IMAGEN ────────────────────────────────────────────────

info "Paso 5/6: Construyendo imagen Docker del DataNode..."

cd "$INSTALL_DIR"
docker compose -f aws/docker-compose.datanode.yml build

# ── PASO 6: LEVANTAR CONTENEDOR ─────────────────────────────────────────────

info "Paso 6/6: Levantando contenedor del DataNode $NODE_ID..."

cd "$INSTALL_DIR"
docker compose --env-file aws/.env -f aws/docker-compose.datanode.yml up -d

# ── VERIFICACIÓN ─────────────────────────────────────────────────────────────

info "Esperando que el DataNode arranque..."
sleep 5

if curl -s "http://localhost:$DATANODE_PORT/health" | grep -q '"status":"ok"'; then
    info "═══════════════════════════════════════════════════════════════"
    info "  ✓ DataNode $NODE_ID instalado y corriendo correctamente"
    info "  Puerto: $DATANODE_PORT"
    info "  NameNode: http://$NAMENODE_IP:8000"
    info "  HOST registrado: $OWN_PUBLIC_IP"
    info "  Health: http://localhost:$DATANODE_PORT/health"
    info "═══════════════════════════════════════════════════════════════"
else
    warn "El DataNode aún no responde. Revisa los logs:"
    warn "  docker compose --env-file $INSTALL_DIR/aws/.env -f $INSTALL_DIR/aws/docker-compose.datanode.yml logs"
fi
