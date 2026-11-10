# Vendorizado de djset/tracklist.py (sin cambios).
# No lo edites aquí: cambia el original y vuelve a copiarlo (ver services/README.md).
"""Genera un tracklist con timestamps combinando ACRCloud (acr_scan.py) y/o Shazam (scan.py).

Uso: python tracklist.py salida_base [--acr acr_raw.json] [--shazam raw.jsonl]
     [--min-hits 2] [--max-gap 2] [--id-gap 60]
Genera salida_base.txt y salida_base.csv

ACRCloud es la base (timestamps precisos, cubre todo el set). Shazam rellena los huecos
y los tramos donde ACRCloud solo reconoció el mix de otro DJ.
"""
import argparse
import csv
import json
import re
import unicodedata

# Resultados que son mixes/sets de otros DJs subidos al catálogo, no tracks reales.
# "(Original Mix)", "Extended Mix", "Remix" o "Bzrp Music Sessions, Vol. 52" sí son tracks.
NOT_A_TRACK = re.compile(
    r"(?<!original )(?<!extended )(?<!radio )(?<!club )\bmix\b(?! *\))"
    r"|live set|set live|dj set|mixtape|megamix|enganchad|mega previa|sesi[oó]n\b"
    r"|\b(?<!sessions, )vol\.? *\d|canciones para|after party \d|bailalo ya \d|verano \d\d",
    re.I)


def hms(sec):
    sec = int(round(sec))
    return f"{sec // 3600}:{sec % 3600 // 60:02d}:{sec % 60:02d}"


def norm(title):
    """Título comparable: sin acentos, sin paréntesis/feat, solo letras y números."""
    t = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode().lower()
    t = re.sub(r"[\(\[].*?[\)\]]|\bfeat\..*$|\bft\..*$", "", t)
    return re.sub(r"[^a-z0-9]", "", t)


def seg(start, end, artist, title, source, score):
    return {"start": start, "end": end, "artist": artist, "title": title, "source": source,
            "score": score, "mix": bool(NOT_A_TRACK.search(title))}


# ---------- ACRCloud ----------

def load_acr(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    out = []
    for m in (data.get("results") or {}).get("music") or []:
        r, dur, score = m["result"], m.get("played_duration") or 0, m["result"].get("score") or 0
        # Filtro de débiles (ajustado con datos reales): el ruido de transiciones son
        # segmentos cortos con score bajo; los cortes rápidos reales tienen score alto.
        if not (dur >= 30 or (score >= 60 and dur >= 15) or score >= 90):
            continue
        artist = ", ".join(a["name"] for a in r.get("artists", []))
        out.append(seg(m["offset"], m["offset"] + dur, artist, r.get("title", ""), "acrcloud", score))
    return sorted(out, key=lambda s: s["start"]), data.get("duration")


# ---------- Shazam ----------

def load_shazam(path, min_hits, max_gap):
    rows, window = [], 12
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                d = json.loads(line)
                window = d.get("window", window)
                tr = (d.get("response") or {}).get("track") or {}
                rows.append((d["t"], tr.get("subtitle", ""), tr.get("title", "")))
    rows.sort()
    step = rows[1][0] - rows[0][0] if len(rows) > 1 else 20

    # Agrupa por título normalizado (Shazam alterna entre versiones del mismo tema),
    # tolerando hasta max_gap fragmentos fallidos o con otra coincidencia aislada.
    groups = []
    for t, artist, title in rows:
        if not title:
            continue
        key = norm(title)
        g = next((g for g in reversed(groups[-(max_gap + 1):]) if g["key"] == key
                  and t - g["last"] <= step * (max_gap + 1)), None)
        if g:
            g["last"], g["hits"] = t, g["hits"] + 1
        else:
            groups.append({"key": key, "artist": artist, "title": title, "first": t, "last": t, "hits": 1})
    out = [seg(g["first"], g["last"] + window, g["artist"], g["title"], "shazam", g["hits"])
           for g in groups if g["hits"] >= min_hits]
    return sorted(out, key=lambda s: s["start"]), (rows[-1][0] + window if rows else 0)


# ---------- Combinar ----------

def overlap(a, b):
    return max(0, min(a["end"], b["end"]) - max(a["start"], b["start"]))


def combine(acr, shz):
    """Base = ACRCloud sin mixes. Shazam aporta tracks donde ACRCloud no tiene nada
    o solo un mix ajeno, y corrige el artista cuando ambos coinciden en el título."""
    base = [dict(s) for s in acr if not s["mix"]]
    for s in base:
        for z in shz:
            if not z["mix"] and overlap(s, z) > 0 and norm(z["title"]) == norm(s["title"]):
                s["artist"], s["source"] = z["artist"], "acrcloud+shazam"
                break
    for z in shz:
        if z["mix"] or any(norm(z["title"]) == norm(s["title"]) and overlap(s, z) > 0 for s in base):
            continue
        # se acepta si la mayor parte de su tramo no la cubre ya un track de ACRCloud
        covered = sum(overlap(z, s) for s in base)
        if covered < 0.5 * (z["end"] - z["start"]):
            base.append(dict(z))
    base.sort(key=lambda s: s["start"])

    # une entradas consecutivas del mismo tema; también cuando un título incluye al otro
    # ("Daddy yankee - gasolina" de un remix vs. "Gasolina"). Conserva el inicio más temprano
    # y los metadatos de Shazam, que suelen ser los del original.
    def same(a, b):
        x, y = norm(a), norm(b)
        return x == y or (min(len(x), len(y)) >= 5 and (x.endswith(y) or y.endswith(x)))

    merged = []
    for s in base:
        p = merged[-1] if merged else None
        if p and same(p["title"], s["title"]):
            p["end"] = max(p["end"], s["end"])
            if "shazam" in s["source"] and "shazam" not in p["source"]:
                p.update(artist=s["artist"], title=s["title"], source=p["source"] + "+shazam")
        else:
            merged.append(s)
    return merged


def build(tracks, mixes, total, id_gap):
    """Inserta 'ID - ID' en huecos > id_gap s; anota el mix ajeno que cubre ese tramo."""
    def note(a, b):
        names = [f"{m['artist']} - {m['title']}" for m in mixes
                 if overlap(m, {"start": a, "end": b}) > 0]
        return ("aparece en: " + " / ".join(dict.fromkeys(names))) if names else ""

    out, cursor = [], 0
    for s in tracks:
        if s["start"] - cursor > id_gap:
            out.append({"start": cursor, "artist": "ID", "title": "ID", "source": "", "score": "",
                        "note": note(cursor, s["start"])})
        out.append({**s, "note": ""})
        cursor = max(cursor, s["end"])
    if total - cursor > id_gap:
        out.append({"start": cursor, "artist": "ID", "title": "ID", "source": "", "score": "",
                    "note": note(cursor, total)})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out_base")
    ap.add_argument("--acr", help="acr_raw.json de acr_scan.py")
    ap.add_argument("--shazam", help="raw.jsonl de scan.py")
    ap.add_argument("--min-hits", type=int, default=2, help="coincidencias Shazam mínimas por track")
    ap.add_argument("--max-gap", type=int, default=2, help="fragmentos Shazam fallidos tolerados dentro de un track")
    ap.add_argument("--id-gap", type=int, default=60, help="segundos sin identificar para marcar ID - ID")
    a = ap.parse_args()
    if not (a.acr or a.shazam):
        ap.error("indica --acr y/o --shazam")

    acr, total_a = load_acr(a.acr) if a.acr else ([], 0)
    shz, total_s = load_shazam(a.shazam, a.min_hits, a.max_gap) if a.shazam else ([], 0)
    total = max(total_a or 0, total_s)
    mixes = [s for s in acr + shz if s["mix"]]
    tracks = build(combine(acr, shz), mixes, total, a.id_gap)

    lines = [f"{hms(t['start'])}  {t['artist']} - {t['title']}" for t in tracks]
    with open(a.out_base + ".txt", "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    with open(a.out_base + ".csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["#", "start", "start_seconds", "artist", "title", "source", "score_or_hits", "note"])
        for i, t in enumerate(tracks, 1):
            w.writerow([i, hms(t["start"]), int(t["start"]), t["artist"], t["title"],
                        t["source"], t["score"], t["note"]])
    print("\n".join(lines))
    n_id = sum(t["artist"] == "ID" for t in tracks)
    print(f"\n{len(tracks) - n_id} tracks identificados, {n_id} huecos ID -> {a.out_base}.txt / .csv")


if __name__ == "__main__":
    main()
