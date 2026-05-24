#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# configure_aws.sh — Genera archivos .env para cada nodo con las IPs de AWS
# ─────────────────────────────────────────────────────────────────────────────
#
# Corre LOCALMENTE desde la laptop. Genera los .env que luego se pueden
# copiar a cada EC2 vía SCP, o usar como referencia para el setup manual.
#
# Uso:
#   bash configure_aws.sh \
#     --namenode 54.123.45.67 \
#     --dn1 54.123.45.68 \
#     --dn2 54.123.45.69 \
#     --dn3 54.123.45.70
#
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

# ── COLORES ──────────────────────────────────────────────────────────────────

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
header(){ echo -e "${CYAN}${BOLD}$1${NC}"; }

# ── PARSE ARGUMENTOS ────────────────────────────────────────────────────────

NAMENODE_IP=""
DN1_IP=""
DN2_IP=""
DN3_IP=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --namenode) NAMENODE_IP="$2"; shift 2 ;;
        --dn1)     DN1_IP="$2";      shift 2 ;;
        --dn2)     DN2_IP="$2";      shift 2 ;;
        --dn3)     DN3_IP="$2";      shift 2 ;;
        *)
            echo "Uso: $0 --namenode <IP> --dn1 <IP> --dn2 <IP> --dn3 <IP>"
            exit 1
            ;;
    esac
done

if [[ -z "$NAMENODE_IP" || -z "$DN1_IP" || -z "$DN2_IP" || -z "$DN3_IP" ]]; then
    echo "Error: Se requieren las 4 IPs."
    echo ""
    echo "Uso:"
    echo "  bash $0 \\"
    echo "    --namenode 54.123.45.67 \\"
    echo "    --dn1 54.123.45.68 \\"
    echo "    --dn2 54.123.45.69 \\"
    echo "    --dn3 54.123.45.70"
    exit 1
fi

# ── CREAR DIRECTORIO DE SALIDA ───────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT_DIR="$SCRIPT_DIR/envs"
mkdir -p "$OUTPUT_DIR"

# ── GENERAR .env PARA NAMENODE ───────────────────────────────────────────────

cat > "$OUTPUT_DIR/namenode.env" <<EOF
# ─── NameNode — Configuración para AWS EC2 ───────────────────────────────────
# Generado por configure_aws.sh el $(date)
# IP: $NAMENODE_IP

DB_PATH=/data/metadata.db
BLOCK_SIZE=67108864
HEARTBEAT_TIMEOUT=90
REPLICATION_FACTOR=2
EOF

info "Generado: $OUTPUT_DIR/namenode.env"

# ── GENERAR .env PARA CADA DATANODE ──────────────────────────────────────────

for i in 1 2 3; do
    eval "DN_IP=\$DN${i}_IP"
    cat > "$OUTPUT_DIR/datanode${i}.env" <<EOF
# ─── DataNode DN${i} — Configuración para AWS EC2 ────────────────────────────
# Generado por configure_aws.sh el $(date)
# IP: $DN_IP

NODE_ID=DN${i}
PORT=8001
HOST=$DN_IP
NAMENODE_URL=http://$NAMENODE_IP:8000
HEARTBEAT_INTERVAL=30
EOF
    info "Generado: $OUTPUT_DIR/datanode${i}.env"
done

# ── GENERAR .env.client PARA EL CLIENTE CLI ──────────────────────────────────

cat > "$SCRIPT_DIR/../.env.client" <<EOF
# ─── Cliente CLI — Configuración para AWS ────────────────────────────────────
# Generado por configure_aws.sh el $(date)
#
# Uso:
#   python client/cli.py --env .env.client status
#   NAMENODE_URL=http://$NAMENODE_IP:8000 python client/cli.py status

NAMENODE_URL=http://$NAMENODE_IP:8000
BLOCK_SIZE=67108864
EOF

info "Generado: .env.client (raíz del proyecto)"

# ── RESUMEN ──────────────────────────────────────────────────────────────────

echo ""
header "═══════════════════════════════════════════════════════════════"
header "  Configuración generada para AWS EC2"
header "═══════════════════════════════════════════════════════════════"
echo ""
echo -e "  ${BOLD}NameNode${NC}    → $NAMENODE_IP:8000"
echo -e "  ${BOLD}DataNode 1${NC}  → $DN1_IP:8001  (DN1)"
echo -e "  ${BOLD}DataNode 2${NC}  → $DN2_IP:8001  (DN2)"
echo -e "  ${BOLD}DataNode 3${NC}  → $DN3_IP:8001  (DN3)"
echo ""
header "───────────────────────────────────────────────────────────────"
echo ""
echo -e "  Archivos generados:"
echo -e "    ${GREEN}aws/envs/namenode.env${NC}    → Copiar a EC2 del NameNode"
echo -e "    ${GREEN}aws/envs/datanode1.env${NC}   → Copiar a EC2 del DataNode 1"
echo -e "    ${GREEN}aws/envs/datanode2.env${NC}   → Copiar a EC2 del DataNode 2"
echo -e "    ${GREEN}aws/envs/datanode3.env${NC}   → Copiar a EC2 del DataNode 3"
echo -e "    ${GREEN}.env.client${NC}              → Usar localmente con el CLI"
echo ""
header "───────────────────────────────────────────────────────────────"
echo ""
echo "  Para copiar los .env a las EC2 por SCP:"
echo ""
echo "    scp -i tu-key.pem aws/envs/namenode.env   ubuntu@$NAMENODE_IP:/opt/dfs/aws/.env"
echo "    scp -i tu-key.pem aws/envs/datanode1.env  ubuntu@$DN1_IP:/opt/dfs/aws/.env"
echo "    scp -i tu-key.pem aws/envs/datanode2.env  ubuntu@$DN2_IP:/opt/dfs/aws/.env"
echo "    scp -i tu-key.pem aws/envs/datanode3.env  ubuntu@$DN3_IP:/opt/dfs/aws/.env"
echo ""
echo "  Para usar el cliente CLI desde la laptop:"
echo ""
echo "    python client/cli.py --env .env.client status"
echo "    NAMENODE_URL=http://$NAMENODE_IP:8000 python client/cli.py status"
echo ""
header "═══════════════════════════════════════════════════════════════"
