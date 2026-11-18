"""Vista del resultado de Tracklist ID: forma de onda del set (estilo SoundCloud) + cada track con su tramo,
metadatos y enlaces para escucharlo. Se guarda en results/visual.json (no es descargable; lo lee la web).

    peaks()   decodifica el set con ffmpeg (mono, 4 kHz) y calcula el nivel RMS de N tramos iguales.
              Se hace antes de borrar el audio subido: el set nunca se guarda.
    enrich()  toma las filas de tracklist.csv y les suma lo que respondieron ACRCloud (acr_raw.json) y
              Shazam (raw.jsonl) en ese tramo: álbum, sello, año, género, ISRC, carátula e ids de
              Spotify / Deezer / YouTube. Sin id directo, el enlace es una búsqueda en ese servicio.
"""
import csv
import json
import re
import subprocess
import unicodedata
from pathlib import Path
from urllib.parse import quote, quote_plus

import numpy as np

BINS = 1200
RATE = 4000


def peaks(path: Path, seconds: float | None, bins: int = BINS) -> list[int]:
    """Nivel 0-100 de cada tramo del set (RMS normalizado al percentil 99, con curva suave)."""
    if not seconds:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                              str(path)], capture_output=True, text=True, check=True).stdout
        seconds = float(out.strip())
    per_bin = max(1, int(np.ceil(seconds * RATE / bins)))
    proc = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a:0", "-ac", "1", "-ar", str(RATE),
                             "-f", "s16le", "-"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    levels, buf = [], np.zeros(0, dtype=np.float32)
    try:
        while True:
            chunk = proc.stdout.read(per_bin * 2 * 64)
            if not chunk:
                break
            x = np.frombuffer(chunk[: len(chunk) // 2 * 2], dtype=np.int16).astype(np.float32) / 32768
            buf = np.concatenate([buf, x])
            n = len(buf) // per_bin
            if n:
                block = buf[: n * per_bin].reshape(n, per_bin)
                levels.extend(np.sqrt((block ** 2).mean(axis=1)).tolist())
                buf = buf[n * per_bin:]
        if len(buf):
            levels.append(float(np.sqrt((buf ** 2).mean())))
    finally:
        proc.stdout.close()
        proc.wait()
    if not levels:
        return []
    arr = np.array(levels)
    ref = np.percentile(arr, 99) or arr.max() or 1.0
    arr = np.clip(arr / ref, 0, 1) ** 0.7  # curva suave: los tramos tranquilos no desaparecen
    return [int(round(v * 100)) for v in arr]


def norm(title: str) -> str:
    """Título comparable (igual que services/tracklist/tracklist.py): sin acentos, paréntesis ni feat."""
    t = unicodedata.normalize("NFKD", title or "").encode("ascii", "ignore").decode().lower()
    t = re.sub(r"[\(\[].*?[\)\]]|\bfeat\..*$|\bft\..*$", "", t)
    return re.sub(r"[^a-z0-9]", "", t)


def _same(a: str, b: str) -> bool:
    x, y = norm(a), norm(b)
    return bool(x and y) and (x == y or (min(len(x), len(y)) >= 5 and (x in y or y in x)))


def _acr_meta(r: dict) -> dict:
    ext = r.get("external_metadata") or {}
    sp = ((ext.get("spotify") or {}).get("track") or {}).get("id")
    dz = ((ext.get("deezer") or {}).get("track") or {}).get("id")
    yt = (ext.get("youtube") or {}).get("vid")
    genres = [g.get("name") for g in r.get("genres") or [] if g.get("name")]
    return {"album": (r.get("album") or {}).get("name"), "label": r.get("label"),
            "year": (r.get("release_date") or "")[:4] or None, "genre": genres[0] if genres else None,
            "isrc": (r.get("external_ids") or {}).get("isrc"), "spotify_id": sp, "deezer_id": dz, "youtube_id": yt}


def _shazam_meta(tr: dict) -> dict:
    meta = {"cover": (tr.get("images") or {}).get("coverart"), "genre": (tr.get("genres") or {}).get("primary"),
            "isrc": tr.get("isrc"), "shazam_url": tr.get("url")}
    for sec in tr.get("sections") or []:
        for m in sec.get("metadata") or []:
            key = {"Album": "album", "Label": "label", "Released": "year"}.get(m.get("title"))
            if key and m.get("text"):
                meta[key] = m["text"]
    for prov in (tr.get("hub") or {}).get("providers") or []:
        if prov.get("type") == "SPOTIFY":
            for act in prov.get("actions") or []:
                uri = act.get("uri") or ""
                if uri.startswith("spotify:track:"):
                    meta["spotify_id"] = uri.rsplit(":", 1)[-1]
    return meta


def links(artist: str, title: str, meta: dict) -> dict:
    q = f"{artist} {title}".strip()
    out = {
        "youtube": f"https://www.youtube.com/watch?v={quote(meta['youtube_id'])}" if meta.get("youtube_id")
        else f"https://www.youtube.com/results?search_query={quote_plus(q)}",
        "spotify": f"https://open.spotify.com/track/{quote(meta['spotify_id'])}" if meta.get("spotify_id")
        else f"https://open.spotify.com/search/{quote(q)}",
        "beatport": f"https://www.beatport.com/search?q={quote_plus(q)}",
        "soundcloud": f"https://soundcloud.com/search/sounds?q={quote_plus(q)}",
        "apple_music": f"https://music.apple.com/search?term={quote_plus(q)}",
    }
    if meta.get("deezer_id"):
        out["deezer"] = f"https://www.deezer.com/track/{quote(str(meta['deezer_id']))}"
    if meta.get("shazam_url", "").startswith("https://"):
        out["shazam"] = meta["shazam_url"]
    return out


def _load_acr(path: Path | None) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path and path.exists() else {}
    except (OSError, ValueError):
        return []
    return [{"start": m.get("offset") or 0, "end": (m.get("offset") or 0) + (m.get("played_duration") or 0),
             "title": (m.get("result") or {}).get("title", ""), "meta": _acr_meta(m.get("result") or {})}
            for m in (data.get("results") or {}).get("music") or []]


def _load_shazam(path: Path | None) -> list[dict]:
    out = []
    if not (path and path.exists()):
        return out
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            tr = (d.get("response") or {}).get("track")
            if tr:
                out.append({"t": d.get("t", 0), "title": tr.get("title", ""), "meta": _shazam_meta(tr)})
    return out


def _load_audd(path: Path | None) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path and path.exists() else {}
    except (OSError, ValueError):
        return []
    out = []
    for r in data.get("results") or []:
        song = max(r.get("songs") or [{}], key=lambda x: x.get("score") or 0)
        out.append({"t": r.get("t", 0), "title": song.get("title", ""),
                    "meta": {"album": song.get("album"), "label": song.get("label"),
                             "year": (song.get("release_date") or "")[:4] or None, "isrc": song.get("isrc")}})
    return out


def enrich(csv_path: Path, acr_json: Path | None, shazam_jsonl: Path | None, duration: float | None,
           audd_json: Path | None = None) -> list[dict]:
    with open(csv_path, encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    acr, shz = _load_acr(acr_json), _load_shazam(shazam_jsonl)
    # AudD y Shazam tienen la misma forma (fragmento en t con metadatos): se recorren igual, AudD primero
    fragments = _load_audd(audd_json) + shz
    starts = [float(r.get("start_seconds") or 0) for r in rows]
    total = float(duration or 0) or (starts[-1] + 120 if starts else 0)
    tracks = []
    for i, r in enumerate(rows):
        start = starts[i]
        end = starts[i + 1] if i + 1 < len(rows) else max(total, start + 1)
        unidentified = r.get("artist") == "ID" and r.get("title") == "ID"
        meta: dict = {}
        if not unidentified:
            for a in acr:  # ACRCloud primero: trae ids directos de Spotify / Deezer / YouTube
                if min(a["end"], end) - max(a["start"], start) > 0 and _same(a["title"], r["title"]):
                    meta.update({k: v for k, v in a["meta"].items() if v})
                    break
            for z in fragments:
                if start - 12 <= z["t"] < end and _same(z["title"], r["title"]):
                    for k, v in z["meta"].items():
                        if v:
                            meta.setdefault(k, v)
        conf = r.get("confianza") or ""
        tracks.append({
            "n": int(r.get("#") or i + 1), "start": start, "end": end, "artist": r.get("artist", ""),
            "title": r.get("title", ""), "unidentified": unidentified, "source": r.get("source", ""),
            "confidence": int(conf) if conf.isdigit() else None, "level": r.get("nivel") or None,
            "note": r.get("note", ""),
            "meta": {k: meta.get(k) for k in ("album", "label", "year", "genre", "isrc", "cover") if meta.get(k)},
            "links": {} if unidentified else links(r.get("artist", ""), r.get("title", ""), meta),
        })
    return tracks
