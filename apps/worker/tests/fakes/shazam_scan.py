"""Shazam simulado: misma interfaz que services/tracklist/scan.py (set, salida.jsonl) y líneas con la
forma real de raw.jsonl: {"t", "window", "response": {"matches": [...], "track": {"title", "subtitle"}}}."""
import json
import os
import sys
import time

if os.environ.get("FAKE_SHAZAM_FAIL"):
    sys.exit("shazam: 429 simulado")


def title_at(t):
    if t < 50:
        return "PRIMER TEMA", "Artista Uno"          # coincide con ACRCloud: corrige el artista
    if 130 <= t < 220:
        return "Tema Del Hueco", "Artista Tres"      # tramo donde ACRCloud solo vio el mix de otro DJ
    return None


path, out = sys.argv[1:3]
with open(out, "a", encoding="utf-8") as fh:
    for i, t in enumerate(range(0, 360 - 12 + 1, 20)):
        found = title_at(t)
        resp = {"matches": [], "location": {"accuracy": 0.01}, "timestamp": 0, "timezone": "UTC"}
        if found:
            resp["matches"] = [{"id": "1", "offset": 10.0, "timeskew": 0.0, "frequencyskew": 0.0}]
            resp["track"] = {"layout": "5", "type": "MUSIC", "key": "1", "title": found[0], "subtitle": found[1]}
        fh.write(json.dumps({"t": t, "window": 12, "response": resp}, ensure_ascii=False) + "\n")
        fh.flush()
        if os.environ.get("FAKE_SHAZAM_SLOW") and i >= 9:   # un escaneo que no termina a tiempo
            time.sleep(60)
        if os.environ.get("FAKE_SHAZAM_SATURATED") and i >= 3:   # como scan.py cuando Shazam limita por IP
            print("Shazam rechazó 4 fragmentos seguidos: se da por saturado y se detiene")
            sys.exit(3)
