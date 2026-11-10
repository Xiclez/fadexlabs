# Vendorizado de djset/acr_scan.py (con un cambio: el token llega solo por variable de entorno, nunca de un .env).
# No lo edites aquí: cambia el original y vuelve a copiarlo (ver services/README.md).
"""Escanea un DJ set completo con ACRCloud File Scanning y guarda la respuesta cruda.

Uso: python acr_scan.py set.mp3 salida.json
Requiere la variable de entorno ACRCLOUD_TOKEN (token personal de la consola de ACRCloud).
Si el archivo ya se subió al contenedor (mismo nombre), reutiliza ese resultado.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

CONTAINER_NAME = "djset-tracklist"
REGION = "us-west-2"
API = "https://api-v2.acrcloud.com/api"
API_REGION = f"https://api-{REGION}.acrcloud.com/api"
POLL = 30


def token():
    # Cambio respecto al original: aquí no hay .env; el worker pasa el token por variable de entorno.
    if os.environ.get("ACRCLOUD_TOKEN"):
        return os.environ["ACRCLOUD_TOKEN"]
    sys.exit("Falta la variable de entorno ACRCLOUD_TOKEN")


def call(method, url, body=None, content_type="application/json"):
    data = body if isinstance(body, bytes) or body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {TOKEN}", "Accept": "application/json",
        **({"Content-Type": content_type} if data is not None else {})})
    for attempt in range(6):
        time.sleep(0.6)  # la consola permite 2 consultas/s
        try:
            with urllib.request.urlopen(req, timeout=600) as r:
                return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 5:
                time.sleep(2 * (attempt + 1))
                continue
            sys.exit(f"ACRCloud {method} {url} -> HTTP {e.code}: {e.read().decode(errors='replace')[:800]}")


def get_container():
    for c in call("GET", f"{API}/fs-containers?per_page=100")["data"]:
        if c["name"] == CONTAINER_NAME:
            return c["id"]
    print(f"Creando contenedor '{CONTAINER_NAME}' en {REGION}...", flush=True)
    c = call("POST", f"{API}/fs-containers", {
        "name": CONTAINER_NAME, "region": REGION, "audio_type": "linein",
        "buckets": ["ACRCloud Music"], "engine": 1,
        "policy": {"type": "traverse", "interval": 0, "rec_length": 10}})
    return c["data"]["id"]


def find_file(cid, name):
    q = urllib.parse.quote(name)
    for f in call("GET", f"{API_REGION}/fs-containers/{cid}/files?search={q}&per_page=50")["data"]:
        if f["name"] == name:
            return f["id"]
    return None


def upload(cid, path):
    name = os.path.basename(path)
    boundary = uuid.uuid4().hex
    with open(path, "rb") as f:
        audio = f.read()
    parts = [
        f'--{boundary}\r\nContent-Disposition: form-data; name="data_type"\r\n\r\naudio\r\n'.encode(),
        f'--{boundary}\r\nContent-Disposition: form-data; name="name"\r\n\r\n{name}\r\n'.encode(),
        (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\n'
         f'Content-Type: application/octet-stream\r\n\r\n').encode(), audio, b"\r\n",
        f"--{boundary}--\r\n".encode()]
    print(f"Subiendo {name} ({len(audio) / 1e6:.0f} MB)...", flush=True)
    r = call("POST", f"{API_REGION}/fs-containers/{cid}/files", b"".join(parts),
             f"multipart/form-data; boundary={boundary}")
    return r["data"]["id"]


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    path, out = sys.argv[1:]
    cid = get_container()
    fid = find_file(cid, os.path.basename(path))
    if fid:
        print("El archivo ya estaba en el contenedor; reutilizo su resultado.", flush=True)
    else:
        fid = upload(cid, path)
    started = time.time()
    while True:
        data = call("GET", f"{API_REGION}/fs-containers/{cid}/files/{fid}")["data"]
        f = data[0] if isinstance(data, list) else data
        state = f.get("state")
        if state != 0:
            break
        print(f"  procesando... {int(time.time() - started)}s", flush=True)
        time.sleep(POLL)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(f, fh, ensure_ascii=False, indent=1)
    music = ((f.get("results") or {}).get("music")) or []
    print(f"Estado {state}; {len(music)} coincidencias -> {out}", flush=True)
    if state not in (1, -1):
        sys.exit(f"ACRCloud devolvió estado de error {state}")


TOKEN = token()
if __name__ == "__main__":
    main()
