# Vendorizado de djset/scan.py (sin cambios).
# No lo edites aquí: cambia el original y vuelve a copiarlo (ver services/README.md).
"""Escanea un DJ set con Shazam (shazamio) y guarda las respuestas crudas en JSONL.

Uso: python scan.py set.mp3 salida.jsonl [--step 20] [--window 12] [--pause 1.5]
Si salida.jsonl ya existe, reanuda saltando los offsets ya consultados.
"""
import argparse
import asyncio
import json
import os
import subprocess
import sys
import tempfile
import warnings

warnings.filterwarnings("ignore")
import logging  # noqa: E402
logging.disable(logging.CRITICAL)  # silencia avisos de sesiones aiohttp sin cerrar
from aiohttp_retry import ExponentialRetry  # noqa: E402
from shazamio import HTTPClient, Shazam  # noqa: E402

QUERY_TIMEOUT = 90  # s máximos por consulta antes de darla por fallida


def duration(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
        capture_output=True, text=True, check=True).stdout
    return float(out.strip())


def cut(src, start, dur, out):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(start), "-t", str(dur), "-i", src,
                    "-ac", "1", "-ar", "16000", out], check=True)


def done_offsets(path):
    if not os.path.exists(path):
        return set()
    with open(path, encoding="utf-8") as f:
        return {json.loads(line)["t"] for line in f if line.strip()}


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("set")
    ap.add_argument("out")
    ap.add_argument("--step", type=int, default=20, help="segundos entre fragmentos")
    ap.add_argument("--window", type=int, default=12, help="duración de cada fragmento")
    ap.add_argument("--pause", type=float, default=1.5, help="pausa entre consultas")
    a = ap.parse_args()

    total = duration(a.set)
    offsets = list(range(0, int(total - a.window) + 1, a.step))
    done = done_offsets(a.out)
    todo = [t for t in offsets if t not in done]
    print(f"{a.set}: {total:.0f}s, {len(offsets)} fragmentos, {len(todo)} pendientes", flush=True)

    # shazamio reintenta hasta 20 veces en silencio ante un 429; lo bajamos a 3
    # y hacemos nuestro propio backoff visible en el log.
    shazam = Shazam(http_client=HTTPClient(retry_options=ExponentialRetry(
        attempts=3, max_timeout=20, statuses={500, 502, 503, 504, 429})))
    seg = os.path.join(tempfile.gettempdir(), f"shz_{os.getpid()}.wav")
    with open(a.out, "a", encoding="utf-8") as f:
        for i, t in enumerate(todo, 1):
            cut(a.set, t, a.window, seg)
            for attempt in range(6):
                try:
                    r = await asyncio.wait_for(shazam.recognize(seg), QUERY_TIMEOUT)
                    break
                except Exception as e:  # red / rate limit: backoff
                    wait = 30 * (attempt + 1)
                    reason = "sin respuesta" if isinstance(e, asyncio.TimeoutError) else f"{type(e).__name__}: {e}"
                    print(f"  t={t} Shazam limitando ({reason}); espero {wait}s", flush=True)
                    await asyncio.sleep(wait)
            else:
                r = {"error": "max retries"}
            f.write(json.dumps({"t": t, "window": a.window, "response": r}, ensure_ascii=False) + "\n")
            f.flush()
            tr = r.get("track") or {}
            print(f"[{i}/{len(todo)}] {t//3600}:{t%3600//60:02d}:{t%60:02d}  "
                  f"{tr.get('subtitle', '-')} - {tr.get('title', '-')}", flush=True)
            await asyncio.sleep(a.pause)
    if os.path.exists(seg):
        os.remove(seg)


if __name__ == "__main__":
    asyncio.run(main())
