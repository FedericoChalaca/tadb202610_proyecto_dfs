import argparse
import httpx
import os
import sys
import math
 
NAMENODE_URL = os.environ.get("NAMENODE_URL", "http://localhost:8000")
BLOCK_SIZE = int(os.environ.get("BLOCK_SIZE", 64 * 1024 * 1024))  # 64 MB

# ─── CARGA DE ARCHIVO .env ────────────────────────────────────────────────────

def load_env_file(env_path):
    """Carga variables de entorno desde un archivo .env"""
    if not os.path.exists(env_path):
        print(f"Error: archivo '{env_path}' no encontrado.")
        return False
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ[key.strip()] = value.strip()
    return True
 
# ─── AUTENTICACIÓN ────────────────────────────────────────────────────────────
 
def get_auth():
    """Lee credenciales guardadas o las pide al usuario."""
    creds_file = ".dfs_credentials"
    if os.path.exists(creds_file):
        with open(creds_file) as f:
            lines = f.read().strip().split("\n")
            if len(lines) == 2:
                return (lines[0], lines[1])
    
    print("No hay sesión activa. Inicia sesión:")
    username = input("Usuario: ")
    password = input("Contraseña: ")
    return (username, password)
 
def save_auth(username, password):
    with open(".dfs_credentials", "w") as f:
        f.write(f"{username}\n{password}")
    print(f"Sesión guardada para '{username}'")
 
def clear_auth():
    if os.path.exists(".dfs_credentials"):
        os.remove(".dfs_credentials")
        print("Sesión cerrada.")
    else:
        print("No había sesión activa.")
 
# ─── COMANDOS ─────────────────────────────────────────────────────────────────
 
def cmd_login(args):
    username = input("Usuario: ")
    password = input("Contraseña: ")
    # Verificar credenciales contra el NameNode
    try:
        resp = httpx.get(f"{NAMENODE_URL}/files/ls", auth=(username, password))
        if resp.status_code == 200:
            save_auth(username, password)
        elif resp.status_code == 401:
            print("Error: usuario o contraseña incorrectos.")
        else:
            print(f"Error inesperado: {resp.status_code}")
    except Exception as e:
        print(f"No se pudo conectar al NameNode: {e}")
 
def cmd_logout(args):
    clear_auth()
 
def cmd_register(args):
    username = input("Nuevo usuario: ")
    password = input("Contraseña: ")
    try:
        resp = httpx.post(f"{NAMENODE_URL}/auth/register", json={
            "username": username,
            "password": password
        })
        data = resp.json()
        if resp.status_code == 200:
            print(f"Usuario '{username}' creado correctamente.")
            save_auth(username, password)
        else:
            print(f"Error: {data.get('detail', 'desconocido')}")
    except Exception as e:
        print(f"Error de conexión: {e}")
 
def cmd_put(args):
    filepath = args.file
    if not os.path.exists(filepath):
        print(f"Error: el archivo '{filepath}' no existe.")
        return
 
    auth = get_auth()
    filename = os.path.basename(filepath)
    total_size = os.path.getsize(filepath)
 
    print(f"Subiendo '{filename}' ({total_size} bytes)...")
 
    # 1. Solicitar plan de distribución al NameNode
    try:
        resp = httpx.post(f"{NAMENODE_URL}/files/put", auth=auth, json={
            "filename": filename,
            "total_size": total_size,
            "directory": "/"
        })
    except Exception as e:
        print(f"Error conectando al NameNode: {e}")
        return
 
    if resp.status_code == 401:
        print("Error de autenticación. Usa 'python client/cli.py login'")
        return
    if resp.status_code == 503:
        print(f"Error: {resp.json().get('detail')}")
        return
    if resp.status_code != 200:
        print(f"Error del NameNode: {resp.status_code} - {resp.text}")
        return
 
    plan = resp.json()
    blocks_info = plan["blocks"]
    num_blocks = plan["num_blocks"]
 
    print(f"Plan recibido: {num_blocks} bloque(s) distribuidos en {len(set(b['primary']['node_id'] for b in blocks_info))} nodo(s)")
 
    # 2. Subir cada bloque al DataNode primario
    with open(filepath, "rb") as f:
        for block in blocks_info:
            block_id = block["block_id"]
            block_index = block["block_index"]
            block_size = block["size"]
            primary = block["primary"]
            replica = block["replica"]
 
            # Leer el bloque del archivo
            chunk = f.read(block_size)
 
            primary_url = f"http://{primary['host']}:{primary['port']}/blocks/upload/{block_id}"
 
            print(f"  Bloque {block_index+1}/{num_blocks} → {primary['node_id']} ({len(chunk)} bytes)", end="")
 
            try:
                upload_resp = httpx.post(
                    primary_url,
                    files={"file": (block_id, chunk, "application/octet-stream")},
                    timeout=120
                )
                if upload_resp.status_code == 200:
                    print(f" ✓")
                else:
                    print(f" ✗ Error: {upload_resp.text}")
                    return
            except Exception as e:
                print(f" ✗ Error de conexión: {e}")
                return
 
            # 3. Replicar al DataNode secundario
            replicate_url = f"http://{primary['host']}:{primary['port']}/blocks/replicate"
            try:
                rep_resp = httpx.post(replicate_url, json={
                    "block_id": block_id,
                    "target_host": replica["host"],
                    "target_port": replica["port"]
                }, timeout=120)
                if rep_resp.status_code == 200:
                    print(f"    Réplica → {replica['node_id']} ✓")
                else:
                    print(f"    Réplica → {replica['node_id']} ✗ (continuando...)")
            except Exception as e:
                print(f"    Réplica fallida: {e} (continuando...)")
 
    print(f"\nArchivo '{filename}' subido correctamente.")
 
def cmd_get(args):
    filename = args.file
    auth = get_auth()
    output_path = args.output if args.output else filename
 
    print(f"Descargando '{filename}'...")
 
    # 1. Obtener ubicación de bloques del NameNode
    try:
        resp = httpx.get(f"{NAMENODE_URL}/files/get/{filename}", auth=auth)
    except Exception as e:
        print(f"Error conectando al NameNode: {e}")
        return
 
    if resp.status_code == 404:
        print(f"Error: archivo '{filename}' no encontrado.")
        return
    if resp.status_code == 401:
        print("Error de autenticación.")
        return
    if resp.status_code != 200:
        print(f"Error: {resp.status_code} - {resp.text}")
        return
 
    file_info = resp.json()
    blocks = file_info["blocks"]
    total_size = file_info["total_size"]
 
    print(f"Archivo encontrado: {len(blocks)} bloque(s), {total_size} bytes en total")
 
    # 2. Descargar cada bloque
    with open(output_path, "wb") as out_file:
        for block in blocks:
            block_id = block["block_id"]
            block_index = block["block_index"]
            primary = block["primary"]
            replica = block["replica"]
 
            downloaded = False
 
            # Intentar primero el nodo primario, luego la réplica
            for node in [primary, replica]:
                url = f"http://{node['host']}:{node['port']}/blocks/download/{block_id}"
                print(f"  Bloque {block_index+1}/{len(blocks)} ← {node['node_id']}", end="")
                try:
                    dl_resp = httpx.get(url, timeout=120)
                    if dl_resp.status_code == 200:
                        out_file.write(dl_resp.content)
                        print(f" ✓ ({len(dl_resp.content)} bytes)")
                        downloaded = True
                        break
                    else:
                        print(f" ✗ (intentando réplica...)")
                except Exception as e:
                    print(f" ✗ Error: {e} (intentando réplica...)")
 
            if not downloaded:
                print(f"  ERROR: no se pudo obtener el bloque {block_id} de ningún nodo.")
                os.remove(output_path)
                return
 
    print(f"\nArchivo descargado como '{output_path}' ({os.path.getsize(output_path)} bytes)")
 
def cmd_ls(args):
    auth = get_auth()
    directory = args.directory if args.directory else "/"
    try:
        resp = httpx.get(f"{NAMENODE_URL}/files/ls", auth=auth, params={"directory": directory})
        if resp.status_code == 401:
            print("Error de autenticación.")
            return
        data = resp.json()
        files = data.get("files", [])
        dirs = data.get("subdirectories", [])
 
        print(f"\nContenido de '{directory}':")
        if not files and not dirs:
            print("  (vacío)")
        for d in dirs:
            print(f"  [DIR]  {d}")
        for f in files:
            size_kb = f['total_size'] / 1024
            print(f"  [FILE] {f['filename']}  ({size_kb:.1f} KB, {f['num_blocks']} bloque(s))")
    except Exception as e:
        print(f"Error: {e}")
 
def cmd_rm(args):
    auth = get_auth()
    filename = args.file
    try:
        resp = httpx.delete(f"{NAMENODE_URL}/files/rm/{filename}", auth=auth)
        if resp.status_code == 200:
            print(f"Archivo '{filename}' eliminado.")
        elif resp.status_code == 404:
            print(f"Archivo '{filename}' no encontrado.")
        else:
            print(f"Error: {resp.text}")
    except Exception as e:
        print(f"Error: {e}")
 
def cmd_mkdir(args):
    auth = get_auth()
    try:
        resp = httpx.post(f"{NAMENODE_URL}/files/mkdir", auth=auth, json={"path": args.path})
        if resp.status_code == 200:
            print(f"Directorio '{args.path}' creado.")
        else:
            print(f"Error: {resp.json().get('detail')}")
    except Exception as e:
        print(f"Error: {e}")
 
def cmd_rmdir(args):
    auth = get_auth()
    try:
        resp = httpx.delete(f"{NAMENODE_URL}/files/rmdir/{args.path}", auth=auth)
        if resp.status_code == 200:
            print(f"Directorio '{args.path}' eliminado.")
        else:
            print(f"Error: {resp.text}")
    except Exception as e:
        print(f"Error: {e}")
 
def cmd_status(args):
    """Muestra el estado del cluster."""
    try:
        resp = httpx.get(f"{NAMENODE_URL}/datanode/status")
        nodes = resp.json()
        print("\nEstado del cluster DFS:")
        print(f"  NameNode: {NAMENODE_URL} ✓")
        for n in nodes:
            estado = "✓ activo" if n["active"] else "✗ caído"
            print(f"  {n['node_id']}: {n['host']}:{n['port']} — {estado}")
    except Exception as e:
        print(f"No se pudo conectar al NameNode: {e}")
 
# ─── PARSER ───────────────────────────────────────────────────────────────────
 
def main():
    parser = argparse.ArgumentParser(
        prog="dfs",
        description="Cliente CLI para el Sistema de Archivos Distribuidos"
    )
    parser.add_argument("--env", help="Archivo .env con configuración (ej: .env.client)", default=None)
    subparsers = parser.add_subparsers(dest="command")
 
    # login / logout / register
    subparsers.add_parser("login", help="Iniciar sesión")
    subparsers.add_parser("logout", help="Cerrar sesión")
    subparsers.add_parser("register", help="Registrar nuevo usuario")
 
    # put
    p_put = subparsers.add_parser("put", help="Subir un archivo al DFS")
    p_put.add_argument("file", help="Ruta del archivo local a subir")
 
    # get
    p_get = subparsers.add_parser("get", help="Descargar un archivo del DFS")
    p_get.add_argument("file", help="Nombre del archivo en el DFS")
    p_get.add_argument("-o", "--output", help="Nombre del archivo de salida", default=None)
 
    # ls
    p_ls = subparsers.add_parser("ls", help="Listar archivos")
    p_ls.add_argument("directory", nargs="?", default="/", help="Directorio a listar")
 
    # rm
    p_rm = subparsers.add_parser("rm", help="Eliminar un archivo")
    p_rm.add_argument("file", help="Nombre del archivo a eliminar")
 
    # mkdir / rmdir
    p_mkdir = subparsers.add_parser("mkdir", help="Crear directorio")
    p_mkdir.add_argument("path", help="Ruta del directorio")
    p_rmdir = subparsers.add_parser("rmdir", help="Eliminar directorio")
    p_rmdir.add_argument("path", help="Ruta del directorio")
 
    # status
    subparsers.add_parser("status", help="Ver estado del cluster")
 
    args = parser.parse_args()
 
    # ── Cargar archivo .env si se proporcionó o existe .env.client ──
    global NAMENODE_URL, BLOCK_SIZE
    if args.env:
        load_env_file(args.env)
    elif os.path.exists(".env.client"):
        load_env_file(".env.client")
    # Recargar variables después de cargar .env
    NAMENODE_URL = os.environ.get("NAMENODE_URL", "http://localhost:8000")
    BLOCK_SIZE = int(os.environ.get("BLOCK_SIZE", 67108864))
 
    commands = {
        "login": cmd_login,
        "logout": cmd_logout,
        "register": cmd_register,
        "put": cmd_put,
        "get": cmd_get,
        "ls": cmd_ls,
        "rm": cmd_rm,
        "mkdir": cmd_mkdir,
        "rmdir": cmd_rmdir,
        "status": cmd_status,
    }
 
    if args.command in commands:
        commands[args.command](args)
    else:
        parser.print_help()
 
if __name__ == "__main__":
    main()