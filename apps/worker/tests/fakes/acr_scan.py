"""ACRCloud simulado: misma interfaz que services/tracklist/acr_scan.py (set, salida.json) y una
respuesta fija con la forma real de acr_raw.json (File Scanning, modo traverse)."""
import json
import os
import sys

if os.environ.get("FAKE_ACR_FAIL"):
    sys.exit("ACRCloud GET ... -> HTTP 503: simulado")


def hit(offset, played, title, artists, score=100, duration_ms=200000):
    return {"offset": float(offset), "played_duration": played, "type": "traverse", "result": {
        "external_ids": {"isrc": "XX0000000000"}, "acrid": "0" * 32,
        "artists": [{"name": a} for a in artists], "title": title, "score": score, "duration_ms": duration_ms,
        "sample_begin_time_offset_ms": 0.0, "sample_end_time_offset_ms": played * 1000.0,
        "db_begin_time_offset_ms": 0, "db_end_time_offset_ms": played * 1000, "result_from": 1,
        "album": {"name": title}, "release_date": "2024-01-01", "label": "Sello", "genres": [{"name": "House"}]}}


music = [
    hit(0, 50, "Primer Tema (Extended Mix)", ["Artista Uno"]),
    hit(52, 8, "Ruido De Transicion", ["Nadie"], score=40),              # débil: corto y score bajo → se filtra
    hit(60, 55, "Segundo Tema", ["Artista Dos", "Invitada"], score=85),
    hit(120, 110, "Verano 24 DJ Set Vol. 3", ["Otro DJ"], score=95),      # mix ajeno: no es un track
    hit(300, 50, "Ultimo Tema (Original Mix)", ["Artista Cuatro"]),
]
path, out = sys.argv[1:3]
doc = {"id": "f-1", "uid": 1, "cid": 1, "name": os.path.basename(path), "duration": 360, "uri": "", "url": "",
       "data_type": "audio", "engine": 1, "count": 0, "state": 1, "detail": "", "created_at": "", "updated_at": "",
       "total": len(music), "results": {"music": music}, "deepright": False}
with open(out, "w", encoding="utf-8") as fh:
    json.dump(doc, fh, ensure_ascii=False, indent=1)
print(f"Estado 1; {len(music)} coincidencias -> {out}")
