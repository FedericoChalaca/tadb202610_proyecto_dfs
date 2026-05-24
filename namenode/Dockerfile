FROM python:3.11-slim

WORKDIR /app

# Instalar dependencias
RUN pip install --no-cache-dir fastapi uvicorn pydantic httpx python-multipart

# Copiar código fuente
COPY main.py ./namenode/main.py

# Variables de entorno con valores por defecto
ENV DB_PATH="/data/metadata.db"
ENV BLOCK_SIZE=67108864
ENV HEARTBEAT_TIMEOUT=90
ENV REPLICATION_FACTOR=2

# Crear directorio para datos persistentes
RUN mkdir -p /data

# Volumen para persistir metadata.db
VOLUME ["/data"]

EXPOSE 8000

CMD ["python", "namenode/main.py"]
