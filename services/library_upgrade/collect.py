#!/usr/bin/env python3
# Vendorizado de dj-library-upgrader/upgrader/collect.py (sin cambios).
# No lo edites aquí: cambia el original y vuelve a copiarlo (ver services/README.md).
"""
collect.py — Reúne en una carpeta plana las canciones descargadas de una lista, las entrega
en el formato pedido (convirtiendo con ffmpeg solo cuando tiene sentido), conserva tags y
carátula, verifica la calidad real y deja un informe por pista.

Uso (desde la carpeta de trabajo de la lista, donde están state.json y formato.json):
    python3 collect.py --downloads /descargas --out /data/entrega/MI_LISTA [--formato aiff]
"""
import argparse
import csv
import json
import os
import re
import shutil
import sys
import unicodedata

import formats as F

FORMAT_FILE = "formato.json"
HEADER = ["#", "pedido", "archivo", "formato_encontrado", "formato_entregado", "conversion",
          "autenticidad", "coincidencia", "duracion", "usuario_soulseek", "nota"]


def match_of(c, t, path, verify):
    """Comparación de espectrogramas con el archivo original de la librería (si lo hay)."""
    if c.get("match"):
        return c["match"]
    src = t.get("source_path")
    if not (verify and src and os.path.exists(src)):
        return None
    import matching as M
    try:
        return M.same_recording(src, path)
    except Exception as ex:
        return {"verdict": "error", "similarity": 0, "text": f"no se pudo comparar ({ex.__class__.__name__})"}


def authenticity_of(c, path, cls, info, verify):
    """Resultado del análisis de espectro (solo sin pérdida). Reutiliza el hecho al descargar."""
    if cls not in F.LOSSLESS:
        return None
    if c.get("authenticity"):
        return c["authenticity"]
    if not verify:
        return None
    import authenticity as A
    try:
        return A.analyze(path, info.get("rate"), info.get("seconds"))
    except Exception as ex:
        return {"verdict": "no_concluyente", "text": f"no se pudo analizar ({ex.__class__.__name__})"}


def fold(s):
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def index_downloads(root):
    """basename exacto → [rutas] y basename 'plegado' → [rutas]."""
    exact, folded = {}, {}
    for dirpath, _, files in os.walk(root):
        for f in files:
            if not f.lower().endswith(F.AUDIO_EXTS):
                continue
            p = os.path.join(dirpath, f)
            exact.setdefault(f, []).append(p)
            folded.setdefault(fold(f), []).append(p)
    return exact, folded


def find_local(remote_path, exact, folded):
    parts = re.split(r"[\\/]", remote_path)
    base, parent = parts[-1], (parts[-2] if len(parts) > 1 else "")
    cands = exact.get(base) or folded.get(fold(base)) or []
    if len(cands) > 1:  # slskd guarda en <carpeta remota>/<archivo>: usamos eso para desempatar
        same_dir = [c for c in cands if os.path.basename(os.path.dirname(c)) == parent]
        cands = same_dir or cands
    return cands[0] if cands else None


def safe_name(s):
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", s).strip(" .")
    return re.sub(r"\s+", " ", s)[:180] or "sin_nombre"


def unique_dst(out_dir, name, src_size=None):
    """Si ya hay un archivo con ese nombre que es OTRA canción (otro tamaño), numerar."""
    dst = os.path.join(out_dir, name)
    if not os.path.exists(dst) or src_size is None or os.path.getsize(dst) == src_size:
        return dst
    stem, ext = os.path.splitext(name)
    i = 2
    while os.path.exists(os.path.join(out_dir, f"{stem} ({i}){ext}")):
        i += 1
    return os.path.join(out_dir, f"{stem} ({i}){ext}")


def quality_note(cls, info, min_bitrate):
    if cls == "mp3":
        if info.get("kbps") and info["kbps"] < min_bitrate - 4:
            return f"BITRATE BAJO ({info['kbps']} kbps)"
        if info.get("vbr"):
            return "VBR"
    elif cls in F.LOSSLESS:
        if (info.get("rate") or 44100) < 44100 or (info.get("bits") or 16) < 16:
            return "sin pérdida de baja resolución"
    return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", default="state.json")
    ap.add_argument("--downloads", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--formato", help="sobrescribe el formato guardado en formato.json")
    ap.add_argument("--min-bitrate", type=int, default=320)
    ap.add_argument("--no-verificar", dest="verificar", action="store_false",
                    help="no analizar el espectro de los archivos sin pérdida")
    args = ap.parse_args()

    if not os.path.exists(args.state):
        print("Todavía no hay descargas para esta lista (ejecuta primero 'descargar').")
        return 1
    saved = {}
    if os.path.exists(FORMAT_FILE):
        with open(FORMAT_FILE, encoding="utf-8") as fh:
            saved = json.load(fh)
    try:
        target = F.target_from_name(args.formato or saved.get("formato") or "original")
    except ValueError as ex:
        print(ex)
        return 1

    with open(args.state, encoding="utf-8") as fh:
        state = json.load(fh)
    os.makedirs(args.out, exist_ok=True)
    exact, folded = index_downloads(args.downloads)

    rows = []
    n = {"nuevas": 0, "convertidas": 0, "originales": 0, "baja": 0, "faltan": 0, "error": 0, "falsos": 0,
         "distintas": 0}
    todo = [e for e in sorted(state.values(), key=lambda x: x["track"]["index"])
            if e["status"] == "downloaded" and e.get("current")]
    print(f"Descargadas según el progreso: {len(todo)}. Formato pedido: {target}. Armando la entrega…", flush=True)

    for i, e in enumerate(todo, 1):
        t, c = e["track"], e["current"]

        def fail(note, found="", coincidence=""):
            rows.append([t["index"], t["original"], "", found, "", "", "", coincidence, "", c["username"], note])

        src = find_local(c["filename"], exact, folded)
        if not src:
            n["faltan"] += 1
            fail("NO ENCONTRADO EN DISCO")
            continue
        src_cls, src_info = F.classify_local(src)
        if src_cls is None:
            n["error"] += 1
            fail("no se pudo leer el audio")
            continue

        match = match_of(c, t, src, args.verificar)
        if match and match.get("verdict") == "distinta":
            n["distintas"] += 1
            fail("NO ES LA MISMA GRABACIÓN que el original: no se entrega", F.describe(src_cls, src_info),
                 match["text"])
            continue

        action, note = F.decide(src_cls, target)
        auth = authenticity_of(c, src, src_cls, src_info, args.verificar)
        fake = bool(auth) and auth.get("verdict") in ("falso", "hires_falso")
        if fake:
            n["falsos"] += 1
            if action == "convert":
                # convertir un falso lossless (a AIFF, WAV… o recomprimirlo a MP3) solo lo maquilla
                action, note = "keep", "falso lossless: se entrega tal cual, sin convertir"
        # Desde una librería real se respeta el nombre y la subcarpeta del original:
        # la entrega reemplaza directamente los archivos de la librería.
        rel = t.get("source_rel")
        out_dir = os.path.join(args.out, os.path.dirname(rel)) if rel else args.out
        os.makedirs(out_dir, exist_ok=True)
        stem = safe_name(os.path.splitext(os.path.basename(rel or src))[0])
        if action == "convert":
            dst = unique_dst(out_dir, stem + F.EXT[target])
            if not os.path.exists(dst):  # ya convertida en una pasada anterior: no repetir
                try:
                    F.convert(src, dst, target, src_info)
                except RuntimeError as ex:
                    n["error"] += 1
                    fail(str(ex), F.describe(src_cls, src_info))
                    continue
                n["nuevas"] += 1
                print(f"  [{i}/{len(todo)}] ⇄ {os.path.basename(dst)}  ({F.LABEL[src_cls]} → {F.LABEL[target]})", flush=True)
            n["convertidas"] += 1
            conversion = "sí"
        else:
            dst = unique_dst(out_dir, stem + os.path.splitext(src)[1].lower(), os.path.getsize(src))
            if not os.path.exists(dst):
                shutil.copy2(src, dst)
                n["nuevas"] += 1
                print(f"  [{i}/{len(todo)}] + {os.path.basename(dst)}", flush=True)
            conversion = "no (evitada)" if action == "keep" else "no"
            if action == "keep":
                n["originales"] += 1

        out_cls, out_info = F.classify_local(dst)
        q = quality_note(out_cls, out_info, args.min_bitrate)
        if q:
            n["baja"] += 1
        secs = out_info.get("seconds")
        dur = f"{int(secs // 60)}:{int(secs % 60):02d}" if secs else ""
        verdict = {"ok": "real", "dudoso": "dudoso", "falso": "FALSO", "hires_falso": "HI-RES FALSO",
                   "no_concluyente": "no concluyente"}.get((auth or {}).get("verdict"), "")
        auth_note = auth["text"] if auth and auth.get("verdict") in ("falso", "hires_falso", "dudoso") else ""
        match_note = f"coincidencia dudosa con el original ({match['text']})" \
            if match and match.get("verdict") == "dudosa" else ""
        rows.append([t["index"], t["original"], os.path.relpath(dst, args.out), F.describe(src_cls, src_info),
                     F.describe(out_cls, out_info), conversion, verdict, (match or {}).get("text", ""), dur,
                     c["username"], "; ".join(x for x in (note, auth_note, match_note, q) if x) or "ok"])

    with open(os.path.join(args.out, "_informe.csv"), "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(HEADER)
        w.writerows(rows)

    nf = "no_encontradas.txt"
    if os.path.exists(nf):
        shutil.copy2(nf, os.path.join(args.out, "_no_encontradas.txt"))

    print(f"Nuevas en esta pasada: {n['nuevas']}   en la carpeta: {len([r for r in rows if r[2]])}")
    if n["convertidas"]:
        print(f"  {n['convertidas']} convertidas a {F.LABEL.get(target, target)} desde sin pérdida")
    if n["originales"]:
        print(f"  {n['originales']} en su formato original: no había versión sin pérdida (ver _informe.csv)")
    if n["distintas"]:
        print(f"  ⚠ {n['distintas']} descargas no eran la misma grabación que el original: no se entregaron")
    if n["falsos"]:
        print(f"  ⚠ {n['falsos']} falsos lossless (vienen de un MP3/AAC): entregados sin convertir, ver _informe.csv")
    if n["baja"]:
        print(f"  ⚠ {n['baja']} con calidad menor a la esperada (ver _informe.csv)")
    if n["faltan"]:
        print(f"  ⚠ {n['faltan']} marcadas como descargadas pero no están en disco")
    if n["error"]:
        print(f"  ⚠ {n['error']} con error al leer o convertir (ver _informe.csv)")
    print(f"→ {args.out}")


if __name__ == "__main__":
    sys.exit(main())
