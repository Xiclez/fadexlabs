# Vendorizado de djset/scan.py, con cambios para la plataforma (ver services/README.md): reintentos
# cortos y corte por saturación (código de salida 3) en vez de esperar minutos por cada fragmento.
# No lo edites aquí: cambia el original y vuelve a copiarlo (ver services/README.md).
"""Escanea un DJ set con Shazam (shazamio) y guarda las respuestas crudas en JSONL.

Uso: python scan.py set.mp3 salida.jsonl [--step 20] [--window 12] [--pause 1.5]
       [--attempts 2] [--backoff 8] [--query-timeout 30] [--max-fail-streak 4]
       [--cooldown 0] [--max-cooldowns 0]
Si salida.jsonl ya existe, reanuda saltando los offsets ya consultados.

Shazam limita por IP. Si rechaza --max-fail-streak fragmentos seguidos, espera --cooldown s y vuelve a
probar esos mismos fragmentos (hasta --max-cooldowns veces). Si sigue rechazando se da por saturado: el
escaneo termina con código 3 y lo ya reconocido queda en salida.jsonl, para que el trabajo siga con otros
motores.
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
                    help="fragmentos seguidos rechazados para pausar (o, sin pausas restantes, terminar)")
    ap.add_argument("--cooldown", type=float, default=0, help="segundos de pausa cuando Shazam limita")
    ap.add_argument("--max-cooldowns", type=int, default=0, help="pausas antes de darlo por saturado")
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
    failed, cooldowns, saturated = [], 0, False  # failed: offsets rechazados seguidos, aún sin escribir

    def write(f, t, response):
        f.write(json.dumps({"t": t, "window": a.window, "response": response}, ensure_ascii=False) + "\n")
        f.flush()

    with open(a.out, "a", encoding="utf-8") as f:
        i = 0
        while i < len(todo):
            t = todo[i]
            i += 1
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
                failed.append(t)
                if len(failed) < a.max_fail_streak:
                    continue
                if cooldowns < a.max_cooldowns:
                    # pausa y se reintentan los mismos fragmentos: no se pierde ningún tramo del set
                    cooldowns += 1
                    print(f"Shazam rechazó {len(failed)} fragmentos seguidos: pausa {a.cooldown:.0f}s "
                          f"({cooldowns} de {a.max_cooldowns}) y reintento", flush=True)
                    i -= len(failed)
                    failed = []
                    await asyncio.sleep(a.cooldown)
                    continue
                for ft in failed:
                    write(f, ft, {"error": "sin respuesta"})
                saturated = True
                print(f"Shazam rechazó {len(failed)} fragmentos seguidos: se da por saturado y se detiene "
                      f"({i - len(failed)} de {len(todo)} fragmentos escaneados en esta corrida)", flush=True)
                break
            for ft in failed:  # rechazos sueltos entre aciertos: quedan registrados como sin respuesta
                write(f, ft, {"error": "sin respuesta"})
            failed = []
            write(f, t, r)
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
