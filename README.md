# DFS - Sistema de Archivos Distribuidos por Bloques

Proyecto para el curso de Arquitecturas de Nube y Sistemas Distribuidos - UPB 2026

## Componentes
- **NameNode**: servidor central de metadatos (puerto 8000)
- **DataNode**: nodos de almacenamiento (puertos 8001, 8002, 8003)
- **Cliente CLI**: interfaz de línea de comandos

## Requisitos
- Python 3.11+
- pip install fastapi uvicorn pydantic httpx python-multipart

## Arrancar el sistema

```bash
# Terminal 1 - NameNode
python namenode/main.py

# Terminal 2, 3 y 4 - DataNodes
python datanode/main.py DN1 8001
python datanode/main.py DN2 8002
python datanode/main.py DN3 8003
```

## Uso del cliente

```bash
python client/cli.py register     # crear usuario
python client/cli.py put archivo  # subir archivo
python client/cli.py get archivo  # descargar archivo
python client/cli.py ls           # listar archivos
python client/cli.py status       # ver estado del cluster
```