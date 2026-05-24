# 🚀 Runbook de Despliegue — DFS en AWS EC2

Guía paso a paso para desplegar el Sistema de Archivos Distribuidos por Bloques
en instancias EC2 de AWS Academy.

## Arquitectura

```
┌─────────────────┐      ┌─────────────────┐
│   Laptop local  │      │  EC2 #1         │
│   (Cliente CLI) │─────▶│  NameNode       │
│                 │      │  Puerto 8000    │
└────────┬────────┘      └────────┬────────┘
         │                        │
         │    ┌───────────────────┼───────────────────┐
         │    │                   │                    │
         ▼    ▼                   ▼                    ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│  EC2 #2         │  │  EC2 #3         │  │  EC2 #4         │
│  DataNode 1     │  │  DataNode 2     │  │  DataNode 3     │
│  Puerto 8001    │  │  Puerto 8001    │  │  Puerto 8001    │
└─────────────────┘  └─────────────────┘  └─────────────────┘
```

Cada DataNode corre en su propia EC2 con el **mismo puerto 8001** (cada máquina
tiene su propia IP pública).

---

## Paso 1: Crear las 4 instancias EC2

### En la consola de AWS Academy:

1. Ir a **EC2 → Launch instances**
2. Configurar:

| Parámetro | Valor |
|---|---|
| **Name** | `dfs-namenode`, `dfs-datanode-1`, `dfs-datanode-2`, `dfs-datanode-3` |
| **AMI** | Ubuntu Server 22.04 LTS (HVM), SSD Volume Type |
| **Instance type** | `t2.micro` (free tier) o `t2.small` si necesitas más RAM |
| **Key pair** | Crear o seleccionar una key pair existente (guardar el `.pem`) |
| **Network** | VPC por defecto, subnet pública, Auto-assign Public IP: **Enable** |
| **Storage** | 15 GB gp2 (para tener espacio para Docker y bloques) |

3. Lanzar las 4 instancias (puedes lanzar las 4 a la vez y renombrar después)

4. **Anotar las IPs públicas** de cada instancia. Ejemplo:

```
dfs-namenode    → 54.123.45.67
dfs-datanode-1  → 54.123.45.68
dfs-datanode-2  → 54.123.45.69
dfs-datanode-3  → 54.123.45.70
```

> **⚠️ Importante:** Las IPs públicas cambian si detienes y vuelves a iniciar
> las instancias. Usa IPs elásticas si necesitas persistencia, o simplemente
> ejecuta `configure_aws.sh` de nuevo con las nuevas IPs.

---

## Paso 2: Crear y asignar Security Groups

### Security Group: `dfs-namenode-sg`

Ir a **EC2 → Security Groups → Create security group**

**Inbound Rules:**

| Type | Port Range | Source | Descripción |
|---|---|---|---|
| SSH | 22 | 0.0.0.0/0 | Acceso SSH para administración |
| Custom TCP | 8000 | 0.0.0.0/0 | API del NameNode (heartbeats de DataNodes + cliente CLI) |

**Outbound Rules:** Dejar por defecto (Allow all)

Asignar a: `dfs-namenode`

### Security Group: `dfs-datanode-sg`

**Inbound Rules:**

| Type | Port Range | Source | Descripción |
|---|---|---|---|
| SSH | 22 | 0.0.0.0/0 | Acceso SSH para administración |
| Custom TCP | 8001 | 0.0.0.0/0 | API del DataNode (upload/download de bloques + replicación entre DataNodes) |

**Outbound Rules:** Dejar por defecto (Allow all)

Asignar a: `dfs-datanode-1`, `dfs-datanode-2`, `dfs-datanode-3`

> **Nota:** Se usa `0.0.0.0/0` porque:
> - El cliente CLI corre desde una laptop con IP dinámica
> - Los DataNodes necesitan comunicarse entre sí para replicar bloques
> - En un entorno académico es aceptable; en producción se restringiría

**Para asignar el SG a una instancia existente:**
1. Seleccionar la instancia → Actions → Security → Change Security Groups
2. Agregar el Security Group correspondiente
3. Guardar

---

## Paso 3: Instalar el NameNode (EC2 #1)

### 3.1. Conectarse por SSH

```bash
ssh -i tu-key.pem ubuntu@54.123.45.67
```

### 3.2. Editar y ejecutar el script de setup

```bash
# Descargar el script directamente desde el repo (o copiar con scp)
# Opción A: Clonar el repo primero y ejecutar el script
git clone YOUR_GITHUB_REPO_URL /opt/dfs
cd /opt/dfs

# Editar la URL del repositorio en el script
nano aws/setup_namenode.sh
# Cambiar REPO_URL="YOUR_GITHUB_REPO_URL" por la URL real

# Ejecutar
chmod +x aws/setup_namenode.sh
sudo ./aws/setup_namenode.sh
```

> **Alternativa rápida:** Si ya clonaste el repo, puedes saltar el script
> y ejecutar manualmente:
> ```bash
> # Instalar Docker (Ubuntu 22.04)
> sudo apt-get update -y
> sudo apt-get install -y ca-certificates curl gnupg lsb-release
> sudo install -m 0755 -d /etc/apt/keyrings
> curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
> sudo chmod a+r /etc/apt/keyrings/docker.gpg
> echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
> sudo apt-get update -y
> sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
>
> # Levantar NameNode
> cd /opt/dfs
> sudo docker compose -f aws/docker-compose.namenode.yml up -d --build
> ```

---

## Paso 4: Verificar que el NameNode está healthy

```bash
# Desde la propia EC2 del NameNode
curl http://localhost:8000/health
# Respuesta esperada: {"status":"ok","node":"namenode"}

# Desde tu laptop (usando la IP pública)
curl http://54.123.45.67:8000/health
# Misma respuesta
```

Si no responde:
```bash
sudo docker compose -f /opt/dfs/aws/docker-compose.namenode.yml logs
sudo docker ps
```

---

## Paso 5: Instalar los DataNodes (EC2 #2, #3, #4)

### Para cada DataNode, conectarse por SSH y ejecutar:

**DataNode 1 (EC2 #2):**
```bash
ssh -i tu-key.pem ubuntu@54.123.45.68

git clone YOUR_GITHUB_REPO_URL /opt/dfs
cd /opt/dfs
nano aws/setup_datanode.sh  # Editar REPO_URL

chmod +x aws/setup_datanode.sh
sudo ./aws/setup_datanode.sh DN1 54.123.45.67 54.123.45.68
#                            ^^^ ^^^^^^^^^^^^^ ^^^^^^^^^^^^^
#                          NODE_ID  NAMENODE_IP  MI_IP_PUBLICA
```

**DataNode 2 (EC2 #3):**
```bash
ssh -i tu-key.pem ubuntu@54.123.45.69

git clone YOUR_GITHUB_REPO_URL /opt/dfs
cd /opt/dfs
nano aws/setup_datanode.sh  # Editar REPO_URL

chmod +x aws/setup_datanode.sh
sudo ./aws/setup_datanode.sh DN2 54.123.45.67 54.123.45.69
```

**DataNode 3 (EC2 #4):**
```bash
ssh -i tu-key.pem ubuntu@54.123.45.70

git clone YOUR_GITHUB_REPO_URL /opt/dfs
cd /opt/dfs
nano aws/setup_datanode.sh  # Editar REPO_URL

chmod +x aws/setup_datanode.sh
sudo ./aws/setup_datanode.sh DN3 54.123.45.67 54.123.45.70
```

---

## Paso 6: Verificar que los DataNodes se registraron

```bash
# Desde tu laptop
curl http://54.123.45.67:8000/datanode/status
```

Respuesta esperada (los 3 DataNodes activos):
```json
[
  {"node_id": "DN1", "host": "54.123.45.68", "port": 8001, "active": true, ...},
  {"node_id": "DN2", "host": "54.123.45.69", "port": 8001, "active": true, ...},
  {"node_id": "DN3", "host": "54.123.45.70", "port": 8001, "active": true, ...}
]
```

### Script de verificación completa

Desde tu laptop, en la raíz del proyecto:

```bash
# Primero generar la configuración local
bash aws/configure_aws.sh \
  --namenode 54.123.45.67 \
  --dn1 54.123.45.68 \
  --dn2 54.123.45.69 \
  --dn3 54.123.45.70

# Luego verificar todo
bash aws/check_deployment.sh --env .env.client
```

---

## Paso 7: Subir un archivo de prueba

```bash
# Crear un archivo de prueba de ~15 MB (para generar al menos 1 bloque)
# En tu laptop:
dd if=/dev/urandom of=test_15mb.bin bs=1M count=15    # Linux/Mac
# o en PowerShell:
# $bytes = [byte[]]::new(15MB); (New-Object Random).NextBytes($bytes); [IO.File]::WriteAllBytes("test_15mb.bin", $bytes)

# Calcular hash antes de subir
md5sum test_15mb.bin        # Linux/Mac
# certutil -hashfile test_15mb.bin MD5  # Windows

# Subir al DFS
python client/cli.py --env .env.client login
python client/cli.py --env .env.client put test_15mb.bin
```

Salida esperada:
```
Subiendo 'test_15mb.bin' (15728640 bytes)...
Plan recibido: 1 bloque(s) distribuidos en 1 nodo(s)
  Bloque 1/1 → DN1 (15728640 bytes) ✓
    Réplica → DN2 ✓

Archivo 'test_15mb.bin' subido correctamente.
```

---

## Paso 8: Verificar distribución de bloques

```bash
# Listar archivos en el DFS
python client/cli.py --env .env.client ls

# Verificar bloques en cada DataNode directamente
curl http://54.123.45.68:8001/blocks/list   # DN1
curl http://54.123.45.69:8001/blocks/list   # DN2
curl http://54.123.45.70:8001/blocks/list   # DN3
```

---

## Paso 9: Simular caída de un DataNode

### Desde la consola de AWS:
1. Seleccionar la instancia del DataNode que tiene el bloque primario (ej: `dfs-datanode-1`)
2. **Instance state → Stop instance**
3. Esperar a que el estado sea "Stopped"

### Verificar que el NameNode lo detecta como caído:
```bash
# Esperar ~90 segundos (HEARTBEAT_TIMEOUT) y luego:
curl http://54.123.45.67:8000/datanode/status
# DN1 debería aparecer con "active": false
```

### Descargar el archivo — debe usar la réplica automáticamente:
```bash
python client/cli.py --env .env.client get test_15mb.bin -o test_15mb_downloaded.bin
```

Salida esperada:
```
Descargando 'test_15mb.bin'...
Archivo encontrado: 1 bloque(s), 15728640 bytes en total
  Bloque 1/1 ← DN1 ✗ Error: ... (intentando réplica...)
  Bloque 1/1 ← DN2 ✓ (15728640 bytes)

Archivo descargado como 'test_15mb_downloaded.bin' (15728640 bytes)
```

### Verificar integridad:
```bash
md5sum test_15mb_downloaded.bin   # Debe coincidir con el hash original
# certutil -hashfile test_15mb_downloaded.bin MD5  # Windows
```

---

## Paso 10: Recuperar el DataNode caído

### Desde la consola de AWS:
1. Seleccionar `dfs-datanode-1`
2. **Instance state → Start instance**
3. **⚠️ Anotar la nueva IP pública** (puede haber cambiado)

### Reiniciar el contenedor si la IP cambió:

```bash
ssh -i tu-key.pem ubuntu@<NUEVA_IP_DN1>

# Actualizar el .env con la nueva IP
cd /opt/dfs
sudo sed -i "s/^HOST=.*/HOST=<NUEVA_IP_DN1>/" aws/.env

# Reiniciar el contenedor
sudo docker compose --env-file aws/.env -f aws/docker-compose.datanode.yml down
sudo docker compose --env-file aws/.env -f aws/docker-compose.datanode.yml up -d
```

### Verificar re-registro:
```bash
curl http://54.123.45.67:8000/datanode/status
# DN1 debería volver a aparecer como activo
```

---

## Troubleshooting

### El DataNode no se registra en el NameNode
1. Verificar que el Security Group del NameNode permite tráfico en el puerto 8000
2. Verificar que la IP del NameNode en el `.env` del DataNode es correcta
3. Revisar logs: `sudo docker compose --env-file /opt/dfs/aws/.env -f /opt/dfs/aws/docker-compose.datanode.yml logs`

### El cliente no puede subir/descargar bloques
1. Verificar que los Security Groups de los DataNodes permiten tráfico en el puerto 8001
2. Verificar que `HOST` en el `.env` del DataNode es su IP **pública** (no la privada)
3. Probar acceso directo: `curl http://<IP_DATANODE>:8001/health`

### Docker no inicia
```bash
sudo systemctl status docker
sudo systemctl start docker
sudo docker ps -a
```

### Las IPs cambiaron después de reiniciar instancias
```bash
# Desde la laptop, regenerar configuración:
bash aws/configure_aws.sh \
  --namenode <NUEVA_IP_NN> \
  --dn1 <NUEVA_IP_DN1> \
  --dn2 <NUEVA_IP_DN2> \
  --dn3 <NUEVA_IP_DN3>

# En cada DataNode, actualizar y reiniciar:
sudo sed -i "s/^HOST=.*/HOST=<NUEVA_IP>/" /opt/dfs/aws/.env
sudo docker compose --env-file /opt/dfs/aws/.env -f /opt/dfs/aws/docker-compose.datanode.yml down
sudo docker compose --env-file /opt/dfs/aws/.env -f /opt/dfs/aws/docker-compose.datanode.yml up -d
```

---

## Consideraciones para la Demo del Video

Lista de evidencias para cumplir el criterio de evaluación:

| # | Evidencia | Qué mostrar |
|---|---|---|
| 1 | **Consola de AWS** | Las 4 instancias EC2 con sus IPs públicas y estado "Running" |
| 2 | **check_deployment.sh** | Script corriendo y mostrando TODO OK ✓ |
| 3 | **put de archivo grande** | Subir archivo ≥10 MB, mostrar distribución de bloques |
| 4 | **ls en el DFS** | `python client/cli.py --env .env.client ls` mostrando el archivo |
| 5 | **Logs de DataNodes** | `curl http://<IP>:8001/blocks/list` mostrando qué bloques tiene cada nodo |
| 6 | **get + integridad** | Descargar archivo y verificar md5sum antes/después |
| 7 | **Tolerancia a fallos** | Apagar una EC2 desde la consola de AWS |
| 8 | **Failover automático** | `get` del mismo archivo, mostrando que usa la réplica |
| 9 | **Instancia detenida** | Consola de AWS mostrando la instancia en estado "Stopped" |

### Flujo sugerido para el video:

1. Mostrar consola de AWS con las 4 instancias corriendo
2. Ejecutar `check_deployment.sh` → todo OK
3. Subir archivo grande: `put test_file.bin`
4. Listar: `ls`
5. Verificar bloques en cada DataNode
6. Descargar: `get test_file.bin` → verificar md5
7. **Ir a la consola de AWS → Stop instance (un DataNode)**
8. Esperar y mostrar que `datanode/status` lo marca como caído
9. `get test_file.bin` → funciona con la réplica (mostrar el failover en la salida)
10. Opcionalmente: volver a iniciar el DataNode y mostrar re-registro
