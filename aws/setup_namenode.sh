#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# setup_namenode.sh — Instalación del NameNode en una EC2 Ubuntu 22.04
# ─────────────────────────────────────────────────────────────────────────────
#
# Uso:
#   chmod +x setup_namenode.sh
#   sudo ./setup_namenode.sh
#
# Este script:
#   1. Actualiza paquetes del sistema
#   2. Instala Docker CE y Docker Compose plugin
#   3. Clona el repositorio del proyecto
#   4. Construye la imagen Docker del NameNode
#   5. Levanta el contenedor
#
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

# ── CONFIGURACIÓN ────────────────────────────────────────────────────────────

REPO_URL="https://github.com/FedericoChalaca/tadb202610_proyecto_dfs"  # ← Reemplazar con la URL del repositorio
INSTALL_DIR="/opt/dfs"

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
info "  Instalación del NameNode — DFS por Bloques"
info "═══════════════════════════════════════════════════════════════"

# ── PASO 1: ACTUALIZAR PAQUETES ─────────────────────────────────────────────

info "Paso 1/5: Actualizando paquetes del sistema..."
apt-get update -y
apt-get upgrade -y
apt-get install -y ca-certificates curl gnupg lsb-release git

# ── PASO 2: INSTALAR DOCKER ─────────────────────────────────────────────────

info "Paso 2/5: Instalando Docker CE..."

if command -v docker &> /dev/null; then
    info "Docker ya está instalado, saltando..."
else
    # Agregar clave GPG oficial de Docker
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | \
        gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg

    # Agregar repositorio de Docker
    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
      https://download.docker.com/linux/ubuntu \
      $(lsb_release -cs) stable" | \
      tee /etc/apt/sources.list.d/docker.list > /dev/null

    apt-get update -y
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

    # Permitir que ubuntu use docker sin sudo
    usermod -aG docker ubuntu
fi

info "Docker version: $(docker --version)"
info "Docker Compose version: $(docker compose version)"

# ── PASO 3: CLONAR REPOSITORIO ──────────────────────────────────────────────

info "Paso 3/5: Clonando repositorio..."

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

# ── PASO 4: CONSTRUIR IMAGEN ────────────────────────────────────────────────

info "Paso 4/5: Construyendo imagen Docker del NameNode..."

cd "$INSTALL_DIR"
docker compose -f aws/docker-compose.namenode.yml build

# ── PASO 5: LEVANTAR CONTENEDOR ─────────────────────────────────────────────

info "Paso 5/5: Levantando contenedor del NameNode..."

docker compose -f aws/docker-compose.namenode.yml up -d

# ── VERIFICACIÓN ─────────────────────────────────────────────────────────────

info "Esperando que el NameNode arranque..."
sleep 5

if curl -s http://localhost:8000/health | grep -q '"status":"ok"'; then
    info "═══════════════════════════════════════════════════════════════"
    info "  ✓ NameNode instalado y corriendo correctamente"
    info "  Puerto: 8000"
    info "  Health: http://localhost:8000/health"
    info "═══════════════════════════════════════════════════════════════"
else
    warn "El NameNode aún no responde. Revisa los logs:"
    warn "  docker compose -f $INSTALL_DIR/aws/docker-compose.namenode.yml logs"
fi
