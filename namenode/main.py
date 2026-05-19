from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel
from typing import Optional
import sqlite3
import time
import hashlib
import secrets
import os
 
app = FastAPI(title="DFS NameNode")
security = HTTPBasic()
 
DB_PATH = "namenode/metadata.db"
BLOCK_SIZE = 64 * 1024 * 1024  # 64 MB
HEARTBEAT_TIMEOUT = 90  # segundos
REPLICATION_FACTOR = 2
 
# ─── BASE DE DATOS ────────────────────────────────────────────────────────────
 
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn
 
def init_db():
    os.makedirs("namenode", exist_ok=True)
    conn = get_db()
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password_hash TEXT NOT NULL
        );
 
        CREATE TABLE IF NOT EXISTS datanodes (
            node_id TEXT PRIMARY KEY,
            host TEXT NOT NULL,
            port INTEGER NOT NULL,
            last_heartbeat REAL NOT NULL
        );
 
        CREATE TABLE IF NOT EXISTS files (
            file_id TEXT PRIMARY KEY,
            filename TEXT NOT NULL,
            owner TEXT NOT NULL,
            total_size INTEGER NOT NULL,
            num_blocks INTEGER NOT NULL,
            created_at REAL NOT NULL,
            directory TEXT NOT NULL DEFAULT '/'
        );
 
        CREATE TABLE IF NOT EXISTS blocks (
            block_id TEXT PRIMARY KEY,
            file_id TEXT NOT NULL,
            block_index INTEGER NOT NULL,
            size INTEGER NOT NULL,
            primary_node TEXT NOT NULL,
            replica_node TEXT NOT NULL,
            FOREIGN KEY (file_id) REFERENCES files(file_id)
        );
 
        CREATE TABLE IF NOT EXISTS directories (
            path TEXT PRIMARY KEY,
            owner TEXT NOT NULL,
            created_at REAL NOT NULL
        );
    """)
    # Usuario de prueba: admin / admin123
    admin_hash = hashlib.sha256("admin123".encode()).hexdigest()
    c.execute("INSERT OR IGNORE INTO users VALUES (?, ?)", ("admin", admin_hash))
    conn.commit()
    conn.close()
 
# ─── AUTENTICACIÓN ────────────────────────────────────────────────────────────
 
def authenticate(credentials: HTTPBasicCredentials = Depends(security)):
    conn = get_db()
    user = conn.execute(
        "SELECT * FROM users WHERE username = ?", (credentials.username,)
    ).fetchone()
    conn.close()
 
    if not user:
        raise HTTPException(status_code=401, detail="Usuario no existe")
 
    password_hash = hashlib.sha256(credentials.password.encode()).hexdigest()
    if not secrets.compare_digest(user["password_hash"], password_hash):
        raise HTTPException(status_code=401, detail="Contraseña incorrecta")
 
    return credentials.username
 
# ─── HELPERS ─────────────────────────────────────────────────────────────────
 
def get_active_nodes(conn):
    cutoff = time.time() - HEARTBEAT_TIMEOUT
    nodes = conn.execute(
        "SELECT * FROM datanodes WHERE last_heartbeat > ?", (cutoff,)
    ).fetchall()
    return nodes
 
def assign_nodes(blocks_count, active_nodes):
    """Round-robin: asigna primario y réplica a cada bloque."""
    n = len(active_nodes)
    assignments = []
    for i in range(blocks_count):
        primary = active_nodes[i % n]["node_id"]
        replica = active_nodes[(i + 1) % n]["node_id"]
        assignments.append({"primary": primary, "replica": replica})
    return assignments
 
# ─── MODELOS ─────────────────────────────────────────────────────────────────
 
class DataNodeRegister(BaseModel):
    node_id: str
    host: str
    port: int
 
class PutRequest(BaseModel):
    filename: str
    total_size: int
    directory: str = "/"
 
class MkdirRequest(BaseModel):
    path: str
 
class RegisterUser(BaseModel):
    username: str
    password: str
 
# ─── ENDPOINTS: DATANODES ─────────────────────────────────────────────────────
 
@app.post("/datanode/register")
def register_datanode(data: DataNodeRegister):
    conn = get_db()
    conn.execute(
        "INSERT OR REPLACE INTO datanodes VALUES (?, ?, ?, ?)",
        (data.node_id, data.host, data.port, time.time())
    )
    conn.commit()
    conn.close()
    return {"status": "ok", "message": f"DataNode {data.node_id} registrado"}
 
@app.post("/datanode/heartbeat/{node_id}")
def heartbeat(node_id: str):
    conn = get_db()
    node = conn.execute("SELECT * FROM datanodes WHERE node_id = ?", (node_id,)).fetchone()
    if not node:
        conn.close()
        raise HTTPException(status_code=404, detail="DataNode no registrado")
    conn.execute(
        "UPDATE datanodes SET last_heartbeat = ? WHERE node_id = ?",
        (time.time(), node_id)
    )
    conn.commit()
    conn.close()
    return {"status": "ok"}
 
@app.get("/datanode/status")
def datanode_status():
    conn = get_db()
    all_nodes = conn.execute("SELECT * FROM datanodes").fetchall()
    conn.close()
    cutoff = time.time() - HEARTBEAT_TIMEOUT
    result = []
    for n in all_nodes:
        result.append({
            "node_id": n["node_id"],
            "host": n["host"],
            "port": n["port"],
            "active": n["last_heartbeat"] > cutoff,
            "last_heartbeat": n["last_heartbeat"]
        })
    return result
 
# ─── ENDPOINTS: ARCHIVOS ──────────────────────────────────────────────────────
 
@app.post("/files/put")
def put_file(req: PutRequest, username: str = Depends(authenticate)):
    conn = get_db()
    active_nodes = get_active_nodes(conn)
 
    if len(active_nodes) < REPLICATION_FACTOR:
        conn.close()
        raise HTTPException(
            status_code=503,
            detail=f"Se necesitan al menos {REPLICATION_FACTOR} DataNodes activos. Activos: {len(active_nodes)}"
        )
 
    num_blocks = max(1, -(-req.total_size // BLOCK_SIZE))  # ceil division
    file_id = hashlib.sha256(f"{username}{req.filename}{time.time()}".encode()).hexdigest()[:16]
 
    assignments = assign_nodes(num_blocks, active_nodes)
 
    # Guardar metadatos del archivo
    conn.execute(
        "INSERT INTO files VALUES (?, ?, ?, ?, ?, ?, ?)",
        (file_id, req.filename, username, req.total_size, num_blocks, time.time(), req.directory)
    )
 
    # Generar y guardar bloques
    blocks_info = []
    for i, assignment in enumerate(assignments):
        block_id = hashlib.sha256(f"{file_id}{i}{time.time()}".encode()).hexdigest()[:24]
        primary_node = next(n for n in active_nodes if n["node_id"] == assignment["primary"])
        replica_node = next(n for n in active_nodes if n["node_id"] == assignment["replica"])
 
        # Tamaño del bloque (el último puede ser menor)
        if i < num_blocks - 1:
            block_size = BLOCK_SIZE
        else:
            block_size = req.total_size - (BLOCK_SIZE * (num_blocks - 1))
 
        conn.execute(
            "INSERT INTO blocks VALUES (?, ?, ?, ?, ?, ?)",
            (block_id, file_id, i, block_size, assignment["primary"], assignment["replica"])
        )
 
        blocks_info.append({
            "block_index": i,
            "block_id": block_id,
            "size": block_size,
            "primary": {
                "node_id": primary_node["node_id"],
                "host": primary_node["host"],
                "port": primary_node["port"]
            },
            "replica": {
                "node_id": replica_node["node_id"],
                "host": replica_node["host"],
                "port": replica_node["port"]
            }
        })
 
    conn.commit()
    conn.close()
 
    return {
        "file_id": file_id,
        "filename": req.filename,
        "num_blocks": num_blocks,
        "block_size": BLOCK_SIZE,
        "blocks": blocks_info
    }
 
@app.get("/files/get/{filename}")
def get_file(filename: str, username: str = Depends(authenticate)):
    conn = get_db()
    file = conn.execute(
        "SELECT * FROM files WHERE filename = ? AND owner = ?", (filename, username)
    ).fetchone()
 
    if not file:
        conn.close()
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
 
    blocks = conn.execute(
        "SELECT b.*, "
        "pn.host as primary_host, pn.port as primary_port, "
        "rn.host as replica_host, rn.port as replica_port "
        "FROM blocks b "
        "JOIN datanodes pn ON b.primary_node = pn.node_id "
        "JOIN datanodes rn ON b.replica_node = rn.node_id "
        "WHERE b.file_id = ? ORDER BY b.block_index",
        (file["file_id"],)
    ).fetchall()
    conn.close()
 
    blocks_info = []
    for b in blocks:
        blocks_info.append({
            "block_index": b["block_index"],
            "block_id": b["block_id"],
            "size": b["size"],
            "primary": {
                "node_id": b["primary_node"],
                "host": b["primary_host"],
                "port": b["primary_port"]
            },
            "replica": {
                "node_id": b["replica_node"],
                "host": b["replica_host"],
                "port": b["replica_port"]
            }
        })
 
    return {
        "file_id": file["file_id"],
        "filename": file["filename"],
        "total_size": file["total_size"],
        "num_blocks": file["num_blocks"],
        "blocks": blocks_info
    }
 
@app.get("/files/ls")
def list_files(directory: str = "/", username: str = Depends(authenticate)):
    conn = get_db()
    files = conn.execute(
        "SELECT filename, total_size, num_blocks, created_at, directory FROM files WHERE owner = ? AND directory = ?",
        (username, directory)
    ).fetchall()
    dirs = conn.execute(
        "SELECT path FROM directories WHERE owner = ? AND path LIKE ?",
        (username, f"{directory}%")
    ).fetchall()
    conn.close()
 
    return {
        "directory": directory,
        "files": [dict(f) for f in files],
        "subdirectories": [d["path"] for d in dirs]
    }
 
@app.delete("/files/rm/{filename}")
def remove_file(filename: str, username: str = Depends(authenticate)):
    conn = get_db()
    file = conn.execute(
        "SELECT * FROM files WHERE filename = ? AND owner = ?", (filename, username)
    ).fetchone()
 
    if not file:
        conn.close()
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
 
    conn.execute("DELETE FROM blocks WHERE file_id = ?", (file["file_id"],))
    conn.execute("DELETE FROM files WHERE file_id = ?", (file["file_id"],))
    conn.commit()
    conn.close()
    return {"status": "ok", "message": f"Archivo {filename} eliminado"}
 
@app.post("/files/mkdir")
def mkdir(req: MkdirRequest, username: str = Depends(authenticate)):
    conn = get_db()
    existing = conn.execute(
        "SELECT * FROM directories WHERE path = ? AND owner = ?", (req.path, username)
    ).fetchone()
    if existing:
        conn.close()
        raise HTTPException(status_code=400, detail="El directorio ya existe")
    conn.execute(
        "INSERT INTO directories VALUES (?, ?, ?)", (req.path, username, time.time())
    )
    conn.commit()
    conn.close()
    return {"status": "ok", "message": f"Directorio {req.path} creado"}
 
@app.delete("/files/rmdir/{path:path}")
def rmdir(path: str, username: str = Depends(authenticate)):
    conn = get_db()
    conn.execute(
        "DELETE FROM directories WHERE path = ? AND owner = ?", (path, username)
    )
    conn.commit()
    conn.close()
    return {"status": "ok", "message": f"Directorio /{path} eliminado"}
 
# ─── ENDPOINTS: USUARIOS ─────────────────────────────────────────────────────
 
@app.post("/auth/register")
def register_user(data: RegisterUser):
    conn = get_db()
    existing = conn.execute("SELECT * FROM users WHERE username = ?", (data.username,)).fetchone()
    if existing:
        conn.close()
        raise HTTPException(status_code=400, detail="El usuario ya existe")
    password_hash = hashlib.sha256(data.password.encode()).hexdigest()
    conn.execute("INSERT INTO users VALUES (?, ?)", (data.username, password_hash))
    conn.commit()
    conn.close()
    return {"status": "ok", "message": f"Usuario {data.username} creado"}
 
@app.get("/health")
def health():
    return {"status": "ok", "node": "namenode"}
 
# ─── INICIO ───────────────────────────────────────────────────────────────────
 
init_db()
 
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)