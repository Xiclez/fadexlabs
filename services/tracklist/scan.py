# Vendorizado de djset/scan.py, con cambios para la plataforma (ver services/README.md): reintentos
# cortos y corte por saturación (código de salida 3) en vez de esperar minutos por cada fragmento.
# No lo edites aquí: cambia el original y vuelve a copiarlo (ver services/README.md).
"""Escanea un DJ set con Shazam (shazamio) y guarda las respuestas crudas en JSONL.

Uso: python scan.py set.mp3 salida.jsonl [--step 20] [--window 12] [--pause 1.5]
       [--attempts 2] [--backoff 8] [--query-timeout 30] [--max-fail-streak 4]
Si salida.jsonl ya existe, reanuda saltando los offsets ya consultados.

Shazam limita por IP. Si rechaza --max-fail-streak fragmentos seguidos se da por saturado: el escaneo
termina con código 3 y lo ya reconocido queda en salida.jsonl, para que el trabajo siga con otros motores.
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

SATURATED = 3  # código de salida: Shazam está rechazando peticiones


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
    ap.add_argument("--attempts", type=int, default=2, help="intentos por fragmento")
    ap.add_argument("--backoff", type=float, default=8, help="segundos de espera entre intentos de un fragmento")
    ap.add_argument("--query-timeout", type=float, default=30, help="segundos máximos por consulta")
    ap.add_argument("--max-fail-streak", type=int, default=4,
                    help="fragmentos seguidos rechazados para dar a Shazam por saturado y terminar")
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
    streak, saturated = 0, False
    with open(a.out, "a", encoding="utf-8") as f:
        for i, t in enumerate(todo, 1):
            cut(a.set, t, a.window, seg)
            r = None
            for attempt in range(a.attempts):
                try:
                    r = await asyncio.wait_for(shazam.recognize(seg), a.query_timeout)
                    break
                except Exception as e:  # red / rate limit
                    reason = "sin respuesta" if isinstance(e, asyncio.TimeoutError) else f"{type(e).__name__}: {e}"
                    print(f"  t={t} Shazam limitando ({reason})", flush=True)
                    if attempt + 1 < a.attempts:
                        await asyncio.sleep(a.backoff)
            if r is None:
                streak += 1
                f.write(json.dumps({"t": t, "window": a.window, "response": {"error": "sin respuesta"}}) + "\n")
                f.flush()
                if streak >= a.max_fail_streak:
                    saturated = True
                    print(f"Shazam rechazó {streak} fragmentos seguidos: se da por saturado y se detiene "
                          f"({i - streak} de {len(todo)} fragmentos escaneados en esta corrida)", flush=True)
                    break
                continue
            streak = 0
            f.write(json.dumps({"t": t, "window": a.window, "response": r}, ensure_ascii=False) + "\n")
            f.flush()
            tr = r.get("track") or {}
            print(f"[{i}/{len(todo)}] {t//3600}:{t%3600//60:02d}:{t%60:02d}  "
                  f"{tr.get('subtitle', '-')} - {tr.get('title', '-')}", flush=True)
            await asyncio.sleep(a.pause)
    if os.path.exists(seg):
        os.remove(seg)
    if saturated:
        sys.exit(SATURATED)


if __name__ == "__main__":
    asyncio.run(main())
