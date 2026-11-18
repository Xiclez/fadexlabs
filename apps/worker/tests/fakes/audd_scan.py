"""AudD simulado: misma interfaz que services/tracklist/audd_scan.py (set, salida.json [opciones]) y salida con
la forma real de audd_raw.json: {"duration", "step", "window", "pieces", "pieces_done", "results": [{"t", "songs"}]}.
Un tramo de 12 s cada 24 s, en dos partes."""
import json
import os
import sys
import time

if os.environ.get("FAKE_AUDD_FAIL"):
    print("AudD error 900: Invalid api_token")
    sys.exit(2)


def song_at(t):
    if t < 50:
        return {"artist": "Artista Uno", "title": "Primer Tema", "score": 100,   # coincide con ACRCloud
                "album": "Primer Disco", "release_date": "2024-01-01", "label": "Sello", "timecode": "00:10",
                "song_link": "https://lis.tn/primer"}
    if 130 <= t < 220:
        return {"artist": "Artista Tres", "title": "Tema Del Hueco", "score": 100,  # donde ACRCloud vio un mix ajeno
                "album": "Disco Hueco", "release_date": "2025-03-01", "label": "Sello Tres",
                "isrc": "MX0000000001", "timecode": "01:30", "song_link": "https://lis.tn/hueco"}
    return None


path, out = sys.argv[1:3]
doc = {"duration": 360, "step": 24, "window": 12, "pieces": 2, "pieces_done": 0, "results": []}
for piece, (a, b) in enumerate(((0, 192), (192, 360)), 1):  # partes alineadas a la rejilla de 24 s
    for t in range(a, b, 24):
        if t + 12 <= 360 and (found := song_at(t)):
            doc["results"].append({"t": t, "songs": [found]})
    doc["pieces_done"] = piece
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False)
    print(f"[{piece}/2] parte lista")
    if piece == 1 and os.environ.get("FAKE_AUDD_PARTIAL"):   # se cae a la mitad (red, saldo…)
        sys.exit("AudD no respondió tras varios intentos")
    if piece == 1 and os.environ.get("FAKE_AUDD_SLOW"):      # una parte que tarda en responder
        time.sleep(60)
print(f"{len(doc['results'])} tramos con coincidencia -> {out}")
