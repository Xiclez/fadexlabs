"""Tracklist ID: comprimir → ACRCloud → (opcional) Shazam → tracklist.txt / tracklist.csv.

Mismo orden que djset/tracklist.ps1, sin la verificación con Panako (fuera de la beta).
"""
import csv
import os
import shlex
import shutil
from pathlib import Path

from app.core.config import get_settings
from app.models import ToolJob
from app.services import tools as svc
from worker import jobs, proc
from worker.jobs import JobError

TOOL = "tracklist"


def _cmd(override: str, name: str) -> list[str]:
    """El script vendorizado o, en pruebas, el comando alternativo configurado."""
    return shlex.split(override) if override else proc.script(TOOL, name)


def _summary(csv_path: Path, sources: list[str], notes: list[str], seconds: float | None) -> dict:
    with open(csv_path, encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    ids = sum(r["artist"] == "ID" and r["title"] == "ID" for r in rows)
    return {"tracks": len(rows) - ids, "unidentified": ids, "sources": sources, "notes": notes,
            "duration_seconds": seconds}


async def run(job: ToolJob) -> dict:
    s = get_settings()
    src = svc.input_path(job)
    work, results = svc.job_dir(job.id) / "work", svc.results_dir(job.id)
    work.mkdir(parents=True, exist_ok=True)
    results.mkdir(parents=True, exist_ok=True)
    log = work / "worker.log"
    if not src.exists():
        raise JobError("No encontramos el archivo subido. Vuelve a subirlo.", f"falta {src}")

    # 1. Comprimir: mismo reconocimiento con una fracción del tamaño (WAV de 2 h: ~1.2 GB → ~85 MB)
    await jobs.progress(job.id, 5, "Comprimiendo el set")
    scan_set = work / f"{job.id}_scan.mp3"
    r = await proc.run([*proc.script(TOOL, "comprimir.py"), str(src), str(scan_set), "--kbps", str(s.tracklist_kbps)],
                       log=log, timeout=3600)
    if not r.ok:
        raise JobError("No pudimos procesar el audio del set.", r.tail())
    if not scan_set.exists():  # ya era un MP3 liviano: comprimir.py indica usar el original tal cual
        scan_set = src

    sources, notes, args = [], [], []
    acr_json, shazam_jsonl = work / "acr_raw.json", work / "raw.jsonl"

    # 2. ACRCloud: la base (timestamps precisos, cubre todo el set)
    if os.environ.get("ACRCLOUD_TOKEN") or s.acr_scan_cmd:
        await jobs.progress(job.id, 20, "Reconociendo con ACRCloud")
        r = await proc.run([*_cmd(s.acr_scan_cmd, "acr_scan.py"), str(scan_set), str(acr_json)],
                           log=log, timeout=s.acr_max_seconds)
        if r.ok and acr_json.exists():
            sources.append("acrcloud")
            args += ["--acr", str(acr_json)]
        else:
            notes.append("ACRCloud no estuvo disponible: se usó solo Shazam.")
    else:
        notes.append("ACRCloud no está configurado: se usó solo Shazam.")

    # 3. Shazam: relleno con tope de tiempo si ACRCloud respondió; único motor (tope mayor) si no.
    limit = s.shazam_max_seconds if sources else s.shazam_fallback_max_seconds
    if limit > 0:
        await jobs.progress(job.id, 55, "Reconociendo con Shazam" if not sources else "Completando huecos con Shazam")
        r = await proc.run([*_cmd(s.shazam_scan_cmd, "scan.py"), str(scan_set), str(shazam_jsonl)],
                           log=log, timeout=limit)
        if r.timed_out and sources:
            notes.append("Shazam se cortó por tiempo: los huecos se completaron solo en parte.")
        elif r.timed_out:
            notes.append("Shazam se cortó por tiempo: el tracklist puede estar incompleto hacia el final.")
    if shazam_jsonl.exists() and shazam_jsonl.stat().st_size:
        sources.append("shazam")
        args += ["--shazam", str(shazam_jsonl)]
    if not sources:
        raise JobError("Los servicios de reconocimiento no respondieron. Intenta de nuevo más tarde.",
                       r.tail() if limit > 0 else "sin ACRCloud y con Shazam desactivado")

    # 4. Combinar y exportar
    await jobs.progress(job.id, 90, "Armando el tracklist")
    r = await proc.run([*proc.script(TOOL, "tracklist.py"), str(work / "tracklist"), *args], log=log, timeout=600)
    if not r.ok or not (work / "tracklist.csv").exists():
        raise JobError("No pudimos armar el tracklist con lo reconocido.", r.tail())
    for name in ("tracklist.txt", "tracklist.csv"):
        shutil.copyfile(work / name, results / name)

    summary = _summary(results / "tracklist.csv", sources, notes, ((job.result or {}).get("input") or {}).get("seconds"))
    found, ids = summary["tracks"], summary["unidentified"]
    message = f"{found} temas identificados" if found != 1 else "1 tema identificado"
    if ids:
        message += f", {ids} tramo{'s' if ids != 1 else ''} sin identificar"
    return {"summary": summary, "files": ["tracklist.txt", "tracklist.csv"], "message": message}
