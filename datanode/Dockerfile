FROM python:3.11-slim

WORKDIR /app

# Instalar dependencias
RUN pip install --no-cache-dir fastapi uvicorn pydantic httpx python-multipart

# Copiar código fuente
COPY main.py ./datanode/main.py

# Variables de entorno con valores por defecto
ENV NODE_ID="DN1"
ENV PORT=8001
ENV HOST="datanode1"
ENV NAMENODE_URL="http://namenode:8000"
ENV BLOCKS_DIR="/data/blocks"
ENV HEARTBEAT_INTERVAL=30

# Crear directorio para bloques
RUN mkdir -p /data/blocks

# Volumen para persistir bloques
VOLUME ["/data/blocks"]

EXPOSE 8001

CMD ["python", "datanode/main.py"]
