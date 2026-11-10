#!/usr/bin/env python3
# Vendorizado de dj-library-upgrader/upgrader/biblioteca.py (sin cambios).
# No lo edites aquí: cambia el original y vuelve a copiarlo (ver services/README.md).
"""
biblioteca.py — Prepara una lista a partir de la LIBRERÍA REAL del DJ (archivos de audio) en vez
de un .txt con nombres. Con el audio original, cada descarga se verifica comparando espectrogramas
(matching.py), así que solo se aceptan coincidencias exactas de la misma grabación.

Fuentes (en /data/biblioteca):
    <lista>.zip      se extrae de forma segura a trabajo/<lista>/biblioteca/
    <lista>/         carpeta (por ejemplo, traída de Google Drive con ./traer.sh)

Uso (desde la carpeta de trabajo de la lista):
    python3 biblioteca.py /data/biblioteca <lista> -o tracks.json --csv revision.csv [--formato aiff] [--todas]

Por defecto solo entran las pistas que se pueden mejorar según el formato pedido
(con --todas entran todas).
"""
import argparse
import csv
import json
import os
import re
import sys
import zipfile

import formats as F
from normalize import parse_line

MAX_FILES = 20000
MAX_RATIO = 200           # compresión sospechosa (zip bomb)
FORMAT_FILE = "formato.json"


# ---------- extracción segura del zip ----------

def safe_extract(zip_path, dest, max_bytes):
    """Extrae solo audio, sin rutas absolutas ni '..' (zip slip) y con límite de tamaño."""
    dest_real = os.path.realpath(dest)
    total, n = 0, 0
    with zipfile.ZipFile(zip_path) as z:
        members = [m for m in z.infolist() if not m.is_dir()]
        if len(members) > MAX_FILES:
            sys.exit(f"El zip tiene {len(members)} archivos (máximo {MAX_FILES}).")
        for m in members:
            name = m.filename.replace("\\", "/")
            if not name.lower().endswith(F.AUDIO_EXTS) or "/__MACOSX/" in f"/{name}" or \
                    os.path.basename(name).startswith("._"):
                continue
            target = os.path.realpath(os.path.join(dest, name))
            if not target.startswith(dest_real + os.sep):
                print(f"  ! ignorado (ruta insegura): {name}")
                continue
            if m.compress_size and m.file_size / m.compress_size > MAX_RATIO:
                print(f"  ! ignorado (compresión sospechosa): {name}")
                continue
            total += m.file_size
            if total > max_bytes:
                sys.exit(f"El zip descomprimido supera el límite de {max_bytes / 1e9:.0f} GB (--max-gb).")
            if os.path.exists(target) and os.path.getsize(target) == m.file_size:
                n += 1
                continue  # ya extraído en una corrida anterior
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with z.open(m) as src, open(target, "wb") as out:
                written = 0
                while chunk := src.read(1 << 20):
                    written += len(chunk)
                    if written > m.file_size:  # el tamaño declarado mentía
                        sys.exit(f"Tamaño inconsistente en {name}: zip corrupto o manipulado.")
                    out.write(chunk)
            n += 1
    return n


# ---------- análisis de cada archivo ----------

def needs_upgrade(cls, info, target):
    """(¿mejorar?, motivo)."""
    kbps = info.get("kbps") or 0
    if cls in F.LOSSLESS:
        return False, "ya está sin pérdida"
    if target in F.LOSSLESS:
        return True, f"{F.describe(cls, info)} → buscar sin pérdida"
    if cls == "mp3" and kbps >= F.MIN_KBPS["mp3"] - 4 and not info.get("vbr"):
        return False, "ya es MP3 320"
    if cls == "aac" and target == "aac" and kbps >= F.MIN_KBPS["aac"] - 4:
        return False, "ya es AAC 256"
    return True, f"{F.describe(cls, info)} → mejorar"


def clean(s):
    return re.sub(r"\s+", " ", (s or "").replace("_", " ")).strip()


def describe_track(path, root):
    cls, info = F.classify_local(path)
    if cls is None:
        return None
    tags, _ = F.read_tags(path)
    artist, title = clean(tags.get("artist")), clean(tags.get("title"))
    stem = os.path.splitext(os.path.basename(path))[0]
    stem = re.sub(r"^\s*\d{1,3}\s*[-._)]\s*", "", stem)  # "03 - Artista - Tema" → "Artista - Tema"
    text = f"{artist} - {title}" if artist and title else clean(stem)
    return {"path": path, "rel": os.path.relpath(path, root), "cls": cls, "info": info, "text": text}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("base", help="carpeta de librerías (/data/biblioteca)")
    ap.add_argument("lista")
    ap.add_argument("-o", "--output", default="tracks.json")
    ap.add_argument("--csv", default="revision.csv")
    ap.add_argument("--formato", help="formato pedido (si no, el de formato.json o 'original')")
    ap.add_argument("--todas", action="store_true", help="incluir también las que ya están en buena calidad")
    ap.add_argument("--max-gb", type=float, default=40, help="tamaño máximo del zip descomprimido")
    args, _ = ap.parse_known_args()  # ignora opciones del buscador (se pasan juntas en "todo")

    saved = {}
    if os.path.exists(FORMAT_FILE):
        with open(FORMAT_FILE, encoding="utf-8") as fh:
            saved = json.load(fh)
    target = F.target_from_name(args.formato or saved.get("formato") or "original")
    if args.formato:
        with open(FORMAT_FILE, "w", encoding="utf-8") as fh:
            json.dump({"formato": target, "preferencia": ",".join(F.default_preference(target))}, fh)

    zip_path = os.path.join(args.base, args.lista + ".zip")
    folder = os.path.join(args.base, args.lista)
    if os.path.isfile(zip_path):
        root = os.path.abspath("biblioteca")
        os.makedirs(root, exist_ok=True)
        print(f"Extrayendo {zip_path} …", flush=True)
        print(f"  {safe_extract(zip_path, root, int(args.max_gb * 1e9))} archivos de audio")
    elif os.path.isdir(folder):
        root = os.path.abspath(folder)
    else:
        sys.exit(f"No existe {zip_path} ni la carpeta {folder}")

    files = sorted(os.path.join(dp, f) for dp, _, fs in os.walk(root) for f in fs
                   if f.lower().endswith(F.AUDIO_EXTS) and not f.startswith("._"))
    print(f"Analizando {len(files)} archivos de la librería (formato pedido: {target}) …", flush=True)

    tracks, review, merged = {}, [], 0
    for i, path in enumerate(files, 1):
        d = describe_track(path, root)
        if not d:
            review.append([i, os.path.relpath(path, root), "", "", "no", "no se pudo leer el audio"])
            continue
        upgrade, why = needs_upgrade(d["cls"], d["info"], target)
        quality = F.describe(d["cls"], d["info"])
        review.append([i, d["rel"], d["text"], quality, "sí" if upgrade or args.todas else "no", why])
        if not (upgrade or args.todas):
            continue
        t = parse_line(f"{i}. {d['text']}", detect_truncation=False)
        if not t or not t["queries"]:
            review[-1][-1] += "; no se pudo armar la búsqueda"
            continue
        t.update(original=d["rel"], source_path=d["path"], source_rel=d["rel"],
                 duration=round(d["info"].get("seconds") or 0, 1), current_quality=quality,
                 current_kbps=d["info"].get("kbps"),
                 # con el audio original cada descarga se verifica: un título corto ya no es riesgo
                 ambiguous=False)
        if t["key"] in tracks:
            merged += 1  # la misma canción dos veces en la librería: se busca una vez
            continue
        tracks[t["key"]] = t

    out = sorted(tracks.values(), key=lambda x: x["index"])
    with open(args.output, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    with open(args.csv, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["#", "archivo", "artista - título", "calidad_actual", "se_busca", "motivo"])
        w.writerows(review)

    print(f"Para mejorar: {len(out)} de {len(files)}  (duplicados fusionados: {merged})")
    print(f"  sin artista en tags ni nombre: {sum(t['no_artist'] for t in out)}")
    print(f"→ {args.output}   (revisión: {args.csv})")


if __name__ == "__main__":
    main()
