FROM python:3.11-slim

WORKDIR /app

# Instalar dependencias
RUN pip install --no-cache-dir httpx

# Copiar código fuente
COPY cli.py ./client/cli.py

# Variables de entorno
ENV NAMENODE_URL="http://namenode:8000"
ENV BLOCK_SIZE=67108864

# Directorio para persistir credenciales
RUN mkdir -p /data

# Volumen para persistir .dfs_credentials
VOLUME ["/data"]

# El working directory es /data para que .dfs_credentials se guarde ahí
WORKDIR /data

ENTRYPOINT ["python", "/app/client/cli.py"]
