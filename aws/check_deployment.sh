#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# check_deployment.sh — Verificación del despliegue DFS en AWS
# ─────────────────────────────────────────────────────────────────────────────
#
# Corre LOCALMENTE desde la laptop. Verifica que todos los componentes
# del DFS estén corriendo correctamente antes de la demo.
#
# Uso:
#   bash check_deployment.sh --env .env.client
#   bash check_deployment.sh --namenode 54.123.45.67 --dn1 54.123.45.68 --dn2 54.123.45.69 --dn3 54.123.45.70
#
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

# ── COLORES ──────────────────────────────────────────────────────────────────

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

OK="${GREEN}✓${NC}"
FAIL="${RED}✗${NC}"
WARN="${YELLOW}⚠${NC}"

# ── PARSE ARGUMENTOS ────────────────────────────────────────────────────────

NAMENODE_IP=""
DN1_IP=""
DN2_IP=""
DN3_IP=""
ENV_FILE=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --env)      ENV_FILE="$2";    shift 2 ;;
        --namenode) NAMENODE_IP="$2"; shift 2 ;;
        --dn1)     DN1_IP="$2";      shift 2 ;;
        --dn2)     DN2_IP="$2";      shift 2 ;;
        --dn3)     DN3_IP="$2";      shift 2 ;;
        *)
            echo "Uso: $0 --env .env.client"
            echo "  o: $0 --namenode <IP> --dn1 <IP> --dn2 <IP> --dn3 <IP>"
            exit 1
            ;;
    esac
done

# Si se pasó --env, extraer NAMENODE_URL
if [[ -n "$ENV_FILE" ]]; then
    if [[ ! -f "$ENV_FILE" ]]; then
        echo -e "${RED}Error: archivo $ENV_FILE no encontrado${NC}"
        exit 1
    fi
    NAMENODE_URL=$(grep "^NAMENODE_URL=" "$ENV_FILE" | cut -d'=' -f2-)
    if [[ -z "$NAMENODE_URL" ]]; then
        echo -e "${RED}Error: NAMENODE_URL no encontrada en $ENV_FILE${NC}"
        exit 1
    fi
    # Extraer IP del NAMENODE_URL (http://IP:8000)
    NAMENODE_IP=$(echo "$NAMENODE_URL" | sed 's|http://||' | sed 's|:.*||')
fi

if [[ -z "$NAMENODE_IP" ]]; then
    echo "Error: Se requiere --env o --namenode"
    echo ""
    echo "Uso:"
    echo "  bash $0 --env .env.client"
    echo "  bash $0 --namenode <IP> --dn1 <IP> --dn2 <IP> --dn3 <IP>"
    exit 1
fi

# ── CONTADORES ───────────────────────────────────────────────────────────────

TOTAL_CHECKS=0
PASSED=0
FAILED=0

check() {
    TOTAL_CHECKS=$((TOTAL_CHECKS + 1))
    local description="$1"
    local url="$2"
    local expected="$3"
    local timeout="${4:-5}"

    echo -ne "  Verificando $description... "

    RESPONSE=$(curl -s --connect-timeout "$timeout" --max-time "$timeout" "$url" 2>/dev/null) || RESPONSE=""

    if [[ -z "$RESPONSE" ]]; then
        echo -e "$FAIL No responde"
        FAILED=$((FAILED + 1))
        return 1
    elif echo "$RESPONSE" | grep -q "$expected"; then
        echo -e "$OK"
        PASSED=$((PASSED + 1))
        return 0
    else
        echo -e "$FAIL Respuesta inesperada: $RESPONSE"
        FAILED=$((FAILED + 1))
        return 1
    fi
}

# ── BANNER ───────────────────────────────────────────────────────────────────

echo ""
echo -e "${CYAN}${BOLD}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${CYAN}${BOLD}  Verificación del Despliegue DFS en AWS${NC}"
echo -e "${CYAN}${BOLD}═══════════════════════════════════════════════════════════════${NC}"
echo ""

# ── CHECK 1: NAMENODE HEALTH ────────────────────────────────────────────────

echo -e "${BOLD}1. NameNode (${NAMENODE_IP}:8000)${NC}"
check "health" "http://$NAMENODE_IP:8000/health" '"status":"ok"'
echo ""

# ── CHECK 2: DATANODE STATUS VÍA NAMENODE ────────────────────────────────────

echo -e "${BOLD}2. Estado de DataNodes (vía NameNode)${NC}"
echo -ne "  Consultando /datanode/status... "

DN_STATUS=$(curl -s --connect-timeout 5 --max-time 5 "http://$NAMENODE_IP:8000/datanode/status" 2>/dev/null) || DN_STATUS=""

if [[ -z "$DN_STATUS" ]]; then
    echo -e "$FAIL No se pudo obtener estado de DataNodes"
    FAILED=$((FAILED + 1))
    TOTAL_CHECKS=$((TOTAL_CHECKS + 1))
else
    echo -e "$OK"
    TOTAL_CHECKS=$((TOTAL_CHECKS + 1))
    PASSED=$((PASSED + 1))

    # Parsear DataNodes del JSON de forma simple
    ACTIVE_COUNT=$(echo "$DN_STATUS" | grep -o '"active":true' | wc -l)
    INACTIVE_COUNT=$(echo "$DN_STATUS" | grep -o '"active":false' | wc -l)
    TOTAL_DN=$((ACTIVE_COUNT + INACTIVE_COUNT))

    echo -e "  DataNodes registrados: $TOTAL_DN"
    echo -e "  DataNodes activos:     ${GREEN}$ACTIVE_COUNT${NC}"
    if [[ $INACTIVE_COUNT -gt 0 ]]; then
        echo -e "  DataNodes caídos:      ${RED}$INACTIVE_COUNT${NC}"
    fi

    # Mostrar detalle de cada nodo
    echo ""
    echo "  Detalle:"
    # Extraer info básica con grep/sed
    echo "$DN_STATUS" | python3 -c "
import sys, json
try:
    nodes = json.load(sys.stdin)
    for n in nodes:
        status = '✓ activo' if n['active'] else '✗ caído'
        print(f\"    {n['node_id']}: {n['host']}:{n['port']} — {status}\")
except:
    print('    (no se pudo parsear la respuesta)')
" 2>/dev/null || echo "    (python3 no disponible para parsear JSON)"
fi
echo ""

# ── CHECK 3: DATANODES DIRECTAMENTE ─────────────────────────────────────────

echo -e "${BOLD}3. DataNodes (acceso directo)${NC}"

# Si tenemos IPs individuales, verificar directamente
if [[ -n "$DN1_IP" ]]; then
    check "DN1 ($DN1_IP:8001)" "http://$DN1_IP:8001/health" '"status":"ok"'
fi
if [[ -n "$DN2_IP" ]]; then
    check "DN2 ($DN2_IP:8001)" "http://$DN2_IP:8001/health" '"status":"ok"'
fi
if [[ -n "$DN3_IP" ]]; then
    check "DN3 ($DN3_IP:8001)" "http://$DN3_IP:8001/health" '"status":"ok"'
fi

# Si no se pasaron IPs individuales, intentar extraerlas del status del NameNode
if [[ -z "$DN1_IP" && -n "$DN_STATUS" ]]; then
    echo "  (Extrayendo IPs de DataNodes desde el NameNode...)"
    DN_HOSTS=$(echo "$DN_STATUS" | python3 -c "
import sys, json
try:
    nodes = json.load(sys.stdin)
    for n in nodes:
        print(f\"{n['node_id']} {n['host']} {n['port']}\")
except:
    pass
" 2>/dev/null)

    if [[ -n "$DN_HOSTS" ]]; then
        while IFS= read -r line; do
            DN_NODE_ID=$(echo "$line" | awk '{print $1}')
            DN_HOST=$(echo "$line" | awk '{print $2}')
            DN_PORT=$(echo "$line" | awk '{print $3}')
            check "$DN_NODE_ID ($DN_HOST:$DN_PORT)" "http://$DN_HOST:$DN_PORT/health" '"status":"ok"'
        done <<< "$DN_HOSTS"
    fi
fi
echo ""

# ── RESUMEN ──────────────────────────────────────────────────────────────────

echo -e "${BOLD}═══════════════════════════════════════════════════════════════${NC}"
if [[ $FAILED -eq 0 ]]; then
    echo -e "  ${GREEN}${BOLD}RESULTADO: TODO OK ✓${NC}"
    echo -e "  $PASSED/$TOTAL_CHECKS verificaciones pasaron"
else
    echo -e "  ${RED}${BOLD}RESULTADO: HAY PROBLEMAS ✗${NC}"
    echo -e "  $PASSED/$TOTAL_CHECKS pasaron, ${RED}$FAILED fallaron${NC}"
    echo ""
    echo -e "${BOLD}  Diagnóstico:${NC}"
    echo ""
    echo "  Si el NameNode no responde:"
    echo "    ssh -i tu-key.pem ubuntu@$NAMENODE_IP"
    echo "    sudo docker compose -f /opt/dfs/aws/docker-compose.namenode.yml logs"
    echo ""
    echo "  Si un DataNode no responde (reemplaza <IP>):"
    echo "    ssh -i tu-key.pem ubuntu@<IP_DATANODE>"
    echo "    sudo docker compose --env-file /opt/dfs/aws/.env -f /opt/dfs/aws/docker-compose.datanode.yml logs"
    echo ""
    echo "  Si un DataNode no aparece registrado en el NameNode:"
    echo "    - Verificar que el Security Group permite tráfico en el puerto 8001"
    echo "    - Verificar que el NameNode Security Group permite tráfico en el puerto 8000"
    echo "    - Verificar que la IP del NameNode en el .env del DataNode es correcta"
fi
echo -e "${BOLD}═══════════════════════════════════════════════════════════════${NC}"
echo ""

exit $FAILED
