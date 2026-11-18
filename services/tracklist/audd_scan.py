"""Escanea un DJ set con AudD (endpoint enterprise, https://docs.audd.io/enterprise/) y guarda la respuesta cruda.

Uso: python audd_scan.py set.mp3 salida.json [--piece 600] [--every 1] [--skip 1]
Requiere la variable de entorno AUDD_API_TOKEN (token del dashboard de AudD).

AudD reconoce en tramos de 12 s y cobra 1 petición por tramo consultado. Con --every 1 --skip 1 consulta
un tramo de cada dos (cada 24 s): la mitad del costo y de sobra para tracks de varios minutos.
El set se manda en piezas de --piece s (múltiplo de 12 * (every + skip)) para no subir un archivo enorme
de una vez; salida.json se reescribe tras cada pieza y, si ya existe, se reanuda desde la siguiente.

salida.json: {"duration", "step", "window", "pieces", "pieces_done",
              "results": [{"t": segundos en el set, "songs": [...respuesta de AudD...]}]}
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid

API = os.environ.get("AUDD_API_URL", "https://enterprise.audd.io/")  # otra URL solo para pruebas
WINDOW = 12
FATAL = 2  # código de salida: token inválido, sin saldo u otro error que no se arregla reintentando
RETRYABLE = {"300"}


def token():
    if os.environ.get("AUDD_API_TOKEN"):
        return os.environ["AUDD_API_TOKEN"]
    sys.exit("Falta la variable de entorno AUDD_API_TOKEN")


def duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                         capture_output=True, text=True, check=True).stdout
    return float(out.strip())


def cut(src, start, dur, out):
    """Pieza del set en MP3 mono de 64 kbps: suficiente para reconocer y liviano para subir."""
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(start), "-t", str(dur), "-i", src,
                    "-ac", "1", "-b:a", "64k", out], check=True)


def seconds(offset):
    """'MM:SS' o 'HH:MM:SS' → segundos."""
    total = 0
    for part in str(offset).split(":"):
        total = total * 60 + int(float(part))
    return total


def post(path, fields, attempts=4):
    boundary = uuid.uuid4().hex
    with open(path, "rb") as f:
        audio = f.read()
    parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
             for k, v in fields.items()]
    parts += [(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="pieza.mp3"\r\n'
               f'Content-Type: audio/mpeg\r\n\r\n').encode(), audio, b"\r\n", f"--{boundary}--\r\n".encode()]
    req = urllib.request.Request(API, data=b"".join(parts), method="POST",
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=900) as r:
                data = json.loads(r.read() or b"{}")
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            code = getattr(e, "code", None)
            if code and code < 500 and code != 429:
                sys.exit(f"AudD -> HTTP {code}: {e.read().decode(errors='replace')[:800]}")
            print(f"  AudD sin respuesta ({e}); reintento {attempt + 1} de {attempts - 1}", flush=True)
            time.sleep(10 * (attempt + 1))
            continue
        if data.get("status") == "success":
            return data.get("result") or []
        err = data.get("error") or {}
        msg = f"AudD error {err.get('error_code')}: {err.get('error_message')}"
        # solo #300 (falla interna de AudD) se arregla reintentando; 900 token inválido, 901 sin token o sin
        # saldo, 400 archivo muy grande, 500 audio inválido, etc. no
        if str(err.get("error_code")) not in RETRYABLE or attempt + 1 == attempts:
            print(msg, flush=True)
            sys.exit(FATAL)
        print(f"  {msg}; reintento {attempt + 1} de {attempts - 1}", flush=True)
        time.sleep(10 * (attempt + 1))
    sys.exit("AudD no respondió tras varios intentos")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("set")
    ap.add_argument("out")
    ap.add_argument("--piece", type=int, default=600, help="segundos por pieza enviada")
    ap.add_argument("--every", type=int, default=1, help="tramos de 12 s seguidos que se consultan")
    ap.add_argument("--skip", type=int, default=1, help="tramos de 12 s que se saltan después")
    a = ap.parse_args()
    tok = token()

    step = WINDOW * (a.every + a.skip)
    piece = max(step, a.piece // step * step)  # cada pieza empieza en la rejilla de tramos
    total = duration(a.set)
    starts = list(range(0, int(total), piece))
    doc = {"duration": total, "step": step, "window": WINDOW, "pieces": len(starts), "pieces_done": 0,
           "results": []}
    if os.path.exists(a.out):
        with open(a.out, encoding="utf-8") as fh:
            prev = json.load(fh)
        if prev.get("step") == step and prev.get("pieces") == len(starts):
            doc = prev
            print(f"Reanudando: {doc['pieces_done']} de {len(starts)} piezas ya consultadas", flush=True)
    print(f"{a.set}: {total:.0f}s, {len(starts)} piezas de {piece}s, un tramo de {WINDOW}s cada {step}s", flush=True)

    tmp = os.path.join(tempfile.gettempdir(), f"audd_{os.getpid()}.mp3")
    try:
        for i in range(doc["pieces_done"], len(starts)):
            start = starts[i]
            cut(a.set, start, piece, tmp)
            result = post(tmp, {"api_token": tok, "every": a.every, "skip": a.skip, "accurate_offsets": "true"})
            for r in result:
                if r.get("songs"):
                    doc["results"].append({"t": start + seconds(r.get("offset") or 0), "songs": r["songs"]})
            doc["pieces_done"] = i + 1
            with open(a.out, "w", encoding="utf-8") as fh:
                json.dump(doc, fh, ensure_ascii=False)
            found = sum(1 for r in result if r.get("songs"))
            print(f"[{i + 1}/{len(starts)}] {start // 3600}:{start % 3600 // 60:02d}:{start % 60:02d}  "
                  f"{found} tramos reconocidos", flush=True)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    print(f"{len(doc['results'])} tramos con coincidencia -> {a.out}", flush=True)


if __name__ == "__main__":
    main()
