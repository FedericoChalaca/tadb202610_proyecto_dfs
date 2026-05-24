# DFS - Sistema de Archivos Distribuidos por Bloques

Proyecto para el curso de Arquitecturas de Nube y Sistemas Distribuidos - UPB 2026

## Componentes
- **NameNode**: servidor central de metadatos (puerto 8000)
- **DataNode**: nodos de almacenamiento (puertos 8001, 8002, 8003)
- **Cliente CLI**: interfaz de línea de comandos

## Requisitos
- Python 3.11+
- pip install fastapi uvicorn pydantic httpx python-multipart

## Arrancar el sistema (local sin Docker)

```bash
# Terminal 1 - NameNode
python namenode/main.py

# Terminal 2, 3 y 4 - DataNodes
python datanode/main.py DN1 8001
python datanode/main.py DN2 8002
python datanode/main.py DN3 8003
```

## Arrancar con Docker Compose (local)

```bash
cp .env.example .env
docker compose up -d --build
```

## Uso del cliente

```bash
python client/cli.py register     # crear usuario
python client/cli.py put archivo  # subir archivo
python client/cli.py get archivo  # descargar archivo
python client/cli.py ls           # listar archivos
python client/cli.py status       # ver estado del cluster
```

## Despliegue en AWS EC2

El sistema puede desplegarse en 4 instancias EC2 de AWS Academy para demostrar
un sistema verdaderamente distribuido corriendo en internet.

### Arquitectura

```
  EC2 #1 → NameNode    (puerto 8000)
  EC2 #2 → DataNode 1  (puerto 8001)
  EC2 #3 → DataNode 2  (puerto 8001)
  EC2 #4 → DataNode 3  (puerto 8001)
```

### Guía rápida

```bash
# 1. Configurar IPs de las EC2
bash aws/configure_aws.sh \
  --namenode <IP_NAMENODE> \
  --dn1 <IP_DN1> \
  --dn2 <IP_DN2> \
  --dn3 <IP_DN3>

# 2. Verificar que todo está corriendo
bash aws/check_deployment.sh --env .env.client

# 3. Usar el cliente apuntando a AWS
python client/cli.py --env .env.client status
python client/cli.py --env .env.client put archivo.txt
python client/cli.py --env .env.client get archivo.txt
```

### Runbook completo

Ver **[DEPLOY.md](DEPLOY.md)** para instrucciones detalladas paso a paso,
incluyendo creación de instancias, Security Groups, instalación, verificación,
y procedimiento de demo con tolerancia a fallos.

### Scripts incluidos

| Script | Ubicación | Descripción |
|---|---|---|
| `setup_namenode.sh` | `aws/` | Instala Docker y levanta el NameNode en una EC2 |
| `setup_datanode.sh` | `aws/` | Instala Docker y levanta un DataNode en una EC2 |
| `configure_aws.sh` | `aws/` | Genera archivos .env con las IPs reales de AWS |
| `check_deployment.sh` | `aws/` | Verifica que todos los componentes estén OK |