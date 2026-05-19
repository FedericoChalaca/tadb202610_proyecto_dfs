from fastapi import FastAPI, HTTPException, UploadFile, File
from pydantic import BaseModel
import httpx
import asyncio
import os
import time
import sys
 
# ─── CONFIGURACIÓN ────────────────────────────────────────────────────────────
 
# Se pasan como argumentos al correr: python datanode/main.py DN1 8001
NODE_ID = sys.argv[1] if len(sys.argv) > 1 else "DN1"
PORT    = int(sys.argv[2]) if len(sys.argv) > 2 else 8001
HOST    = "localhost"
NAMENODE_URL = "http://localhost:8000"
BLOCKS_DIR   = f"datanode/blocks_{NODE_ID}"
HEARTBEAT_INTERVAL = 30  # segundos
 
from contextlib import asynccontextmanager
 
@asynccontextmanager
async def lifespan(app):
    init()
    await register_with_namenode()
    asyncio.create_task(heartbeat_loop())
    yield
 
app = FastAPI(title=f"DFS DataNode - {NODE_ID}", lifespan=lifespan)
 
# ─── INICIO ───────────────────────────────────────────────────────────────────
 
def init():
    os.makedirs(BLOCKS_DIR, exist_ok=True)
    print(f"[{NODE_ID}] Almacenamiento en: {BLOCKS_DIR}")
 
# ─── REGISTRO Y HEARTBEAT ─────────────────────────────────────────────────────
 
async def register_with_namenode():
    """Se registra en el NameNode al arrancar."""
    async with httpx.AsyncClient() as client:
        for attempt in range(5):
            try:
                resp = await client.post(f"{NAMENODE_URL}/datanode/register", json={
                    "node_id": NODE_ID,
                    "host": HOST,
                    "port": PORT
                })
                if resp.status_code == 200:
                    print(f"[{NODE_ID}] Registrado en NameNode correctamente")
                    return
            except Exception as e:
                print(f"[{NODE_ID}] Intento {attempt+1} fallido: {e}")
                await asyncio.sleep(2)
    print(f"[{NODE_ID}] No se pudo registrar en el NameNode")
 
async def heartbeat_loop():
    """Manda heartbeat al NameNode cada 30 segundos."""
    async with httpx.AsyncClient() as client:
        while True:
            try:
                await client.post(f"{NAMENODE_URL}/datanode/heartbeat/{NODE_ID}")
            except Exception as e:
                print(f"[{NODE_ID}] Error en heartbeat: {e}")
            await asyncio.sleep(HEARTBEAT_INTERVAL)
 
# ─── MODELOS ─────────────────────────────────────────────────────────────────
 
class ReplicateRequest(BaseModel):
    block_id: str
    target_host: str
    target_port: int
 
# ─── ENDPOINTS: BLOQUES ───────────────────────────────────────────────────────
 
@app.post("/blocks/upload/{block_id}")
async def upload_block(block_id: str, file: UploadFile = File(...)):
    """Recibe un bloque y lo guarda en disco."""
    block_path = os.path.join(BLOCKS_DIR, block_id)
    content = await file.read()
    with open(block_path, "wb") as f:
        f.write(content)
    print(f"[{NODE_ID}] Bloque guardado: {block_id} ({len(content)} bytes)")
    return {"status": "ok", "block_id": block_id, "size": len(content)}
 
@app.get("/blocks/download/{block_id}")
async def download_block(block_id: str):
    """Entrega un bloque al cliente."""
    from fastapi.responses import FileResponse
    block_path = os.path.join(BLOCKS_DIR, block_id)
    if not os.path.exists(block_path):
        raise HTTPException(status_code=404, detail=f"Bloque {block_id} no encontrado")
    return FileResponse(block_path, media_type="application/octet-stream", filename=block_id)
 
@app.post("/blocks/replicate")
async def replicate_block(req: ReplicateRequest):
    """Replica un bloque a otro DataNode."""
    block_path = os.path.join(BLOCKS_DIR, req.block_id)
    if not os.path.exists(block_path):
        raise HTTPException(status_code=404, detail=f"Bloque {req.block_id} no encontrado localmente")
 
    with open(block_path, "rb") as f:
        content = f.read()
 
    target_url = f"http://{req.target_host}:{req.target_port}/blocks/upload/{req.block_id}"
    async with httpx.AsyncClient(timeout=60) as client:
        try:
            resp = await client.post(
                target_url,
                files={"file": (req.block_id, content, "application/octet-stream")}
            )
            if resp.status_code == 200:
                print(f"[{NODE_ID}] Bloque {req.block_id} replicado a {req.target_host}:{req.target_port}")
                return {"status": "ok", "replicated_to": f"{req.target_host}:{req.target_port}"}
            else:
                raise HTTPException(status_code=500, detail="Error al replicar")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error de conexión al replicar: {e}")
 
@app.delete("/blocks/delete/{block_id}")
async def delete_block(block_id: str):
    """Elimina un bloque del disco."""
    block_path = os.path.join(BLOCKS_DIR, block_id)
    if not os.path.exists(block_path):
        raise HTTPException(status_code=404, detail="Bloque no encontrado")
    os.remove(block_path)
    print(f"[{NODE_ID}] Bloque eliminado: {block_id}")
    return {"status": "ok", "block_id": block_id}
 
@app.get("/blocks/list")
async def list_blocks():
    """Lista todos los bloques almacenados en este DataNode."""
    blocks = os.listdir(BLOCKS_DIR)
    return {
        "node_id": NODE_ID,
        "total_blocks": len(blocks),
        "blocks": blocks
    }
 
@app.get("/health")
async def health():
    blocks = os.listdir(BLOCKS_DIR)
    return {
        "status": "ok",
        "node_id": NODE_ID,
        "host": HOST,
        "port": PORT,
        "total_blocks": len(blocks)
    }
 
# ─── MAIN ─────────────────────────────────────────────────────────────────────
 
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)