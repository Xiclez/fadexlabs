"""DJ Library Upgrader: librería .zip → búsqueda y descarga en Soulseek (slskd) → verificación →
entrega en el formato pedido → Google Drive.

Mismo flujo que `upgrader todo <lista>` + `subir.sh --link` del proyecto original:
    biblioteca.py   extrae el zip de forma segura y decide qué pistas se pueden mejorar
    slskd_fetch.py  busca, descarga y verifica cada descarga contra el original (misma grabación,
                    sin falsos lossless); si una falla, prueba el siguiente candidato
    collect.py      arma la entrega (convierte solo cuando tiene sentido) + _informe.csv
    rclone          sube la entrega a Drive y saca el enlace para compartir
"""
import asyncio
import csv
import json
import logging
import os
import re
import shlex
import shutil
import unicodedata
from collections import Counter
from pathlib import Path
from urllib.parse import quote

import requests

from app.core.config import get_settings
from app.db import SessionLocal
from app.models import ToolJob, User
from app.services import tools as svc
from worker import jobs, proc
from worker.jobs import JobError

TOOL = "library_upgrade"
log = logging.getLogger("fadex.worker.library")

FINAL = ("downloaded", "not_found", "failed", "skipped_ambiguous", "timeout")


def downloads_dir() -> Path:
    s = get_settings()
    return Path(s.slskd_downloads_dir).resolve() if s.slskd_downloads_dir else svc.data_dir() / "slskd" / "downloads"


def _load(path: Path, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):  # a medio escribir: se lee en la siguiente vuelta
        return default


def _progress_of(state: dict) -> tuple[int, str]:
    """Avance a partir del state.json del upgrader: primero busca todo, luego vigila las descargas."""
    total = len(state) or 1
    c = Counter(e["status"] for e in state.values())
    done = sum(c[k] for k in FINAL)
    missing = c["not_found"] + c["failed"] + c["skipped_ambiguous"]
    tail = f"{c['downloaded']} listas, {c['queued']} descargando"
    tail += f", {missing} sin encontrar" if missing else ""
    tail += f", {c['timeout']} pendientes" if c["timeout"] else ""
    if c["pending"]:  # busca y descarga a la vez: lo ya encontrado baja mientras se busca el resto
        searched = total - c["pending"]
        pct = 10 + round(75 * (0.5 * searched + 0.5 * done) / total)
        return pct, f"Buscando {searched} de {total} pistas · {tail}"
    return 10 + round(75 * (0.5 * total + 0.5 * done) / total), f"Descargando · {tail}"


def _slug(text: str) -> str:
    t = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9]+", "-", t).strip("-")[:40] or "dj"


# ---------- slskd: limpiar lo que quede encolado si se corta por tiempo ----------

def _cancel_pending(state: dict) -> None:
    s = get_settings()
    wanted = {(e["current"]["username"], e["current"]["filename"])
              for e in state.values() if e["status"] == "queued" and e.get("current")}
    if not wanted:
        return
    base, headers = s.slskd_url.rstrip("/") + "/api/v0", {"X-API-Key": s.slskd_api_key}
    try:
        users = requests.get(f"{base}/transfers/downloads", headers=headers, timeout=30).json() or []
        for u in users:
            for d in u.get("directories") or []:
                for f in d.get("files") or []:
                    if (u.get("username"), f.get("filename")) in wanted and f.get("id"):
                        requests.delete(f"{base}/transfers/downloads/{quote(u['username'], safe='')}/{f['id']}",
                                        headers=headers, timeout=30)
    except (requests.RequestException, ValueError) as ex:
        log.warning("no pude cancelar descargas pendientes en slskd: %s", ex)


def _remove_downloads(state: dict, root: Path) -> int:
    """Borra de la carpeta de slskd los archivos que bajó este trabajo (todos los candidatos probados).
    slskd guarda cada uno en <carpeta remota>/<archivo>."""
    wanted = set()
    for e in state.values():
        for c in e.get("tried") or []:
            parts = re.split(r"[\\/]", c.get("filename") or "")
            if parts[-1]:
                wanted.add((parts[-2] if len(parts) > 1 else "", parts[-1]))
    n = 0
    for dirpath, _, files in os.walk(root, topdown=False):
        for f in files:
            if (os.path.basename(dirpath), f) in wanted:
                try:
                    os.remove(os.path.join(dirpath, f))
                    n += 1
                except OSError:
                    pass
        if Path(dirpath) != root:
            try:
                os.rmdir(dirpath)  # solo si quedó vacía
            except OSError:
                pass
    return n


# ---------- entrega ----------

def _summary(informe: Path, state: dict, in_library: int | None, to_upgrade: int, formato: str) -> dict:
    rows = []
    if informe.exists():
        with open(informe, encoding="utf-8-sig", newline="") as fh:
            rows = list(csv.DictReader(fh))
    delivered = [r for r in rows if r.get("archivo")]
    c = Counter(e["status"] for e in state.values())
    return {
        "in_library": in_library, "to_upgrade": to_upgrade, "format": formato,
        "delivered": len(delivered),
        "by_format": dict(Counter((r["formato_entregado"].split() or ["?"])[0] for r in delivered)),
        "converted": sum(r["conversion"] == "sí" for r in delivered),
        "kept_original_format": sum(r["conversion"] == "no (evitada)" for r in delivered),
        "fake_lossless": sum("FALSO" in r["autenticidad"] for r in delivered),
        "doubtful_match": sum("dudosa" in r["coincidencia"] for r in delivered),
        "rejected_other_recording": sum(not r.get("archivo") and "MISMA GRABACIÓN" in r["nota"] for r in rows),
        "not_found": c["not_found"] + c["failed"] + c["skipped_ambiguous"],
        "pending_timeout": c["timeout"],   # ninguna fuente disponible a tiempo: reintentar más tarde u otro formato
        "unfinished": c["queued"] + c["pending"],
    }


async def _to_drive(job: ToolJob, entrega: Path, work: Path) -> str | None:
    """Sube la entrega con rclone y devuelve el enlace para compartir (None si no se pudo)."""
    s = get_settings()
    if not s.rclone_remote:
        return None
    async with SessionLocal() as db:
        user = await db.get(User, job.user_id)
    folder = f"{svc.utcnow():%Y%m%d}-{_slug(user.display_name if user else '')}-{str(job.id)[:8]}"
    dest = f"{s.rclone_remote.rstrip('/')}/{folder}"
    rclone, log_file = shlex.split(s.rclone_bin), work / "rclone.log"
    for attempt in range(3):  # es incremental: un reintento solo sube lo que falta
        r = await proc.run([*rclone, "copy", str(entrega), dest, "--transfers", "4"], log=log_file, timeout=6 * 3600)
        if r.ok:
            break
        await asyncio.sleep(5 * (attempt + 1))
    else:
        log.error("rclone copy falló para %s: %s", job.id, r.tail(600))
        return None
    link_out = work / "rclone_link.out"
    link_out.unlink(missing_ok=True)
    r = await proc.run([*rclone, "link", dest], log=link_out, timeout=300)
    urls = re.findall(r"https?://\S+", r.tail()) if r.ok else []
    if not urls:
        log.error("rclone link falló para %s: %s", job.id, r.tail(600))
    return urls[-1] if urls else None


async def run(job: ToolJob) -> dict:
    s = get_settings()
    root = svc.job_dir(job.id)
    work, results, entrega = root / "work", svc.results_dir(job.id), root / "entrega"
    for d in (work, results):
        d.mkdir(parents=True, exist_ok=True)
    downloads = downloads_dir()
    downloads.mkdir(parents=True, exist_ok=True)
    logf = work / "worker.log"
    formato = (job.options or {}).get("formato") or "aiff"
    lib = proc.script(TOOL, "biblioteca.py")[:-1]  # [python, -u]
    script = lambda name: [*lib, str(proc.services_dir() / TOOL / name)]  # noqa: E731
    env = {"SLSKD_URL": s.slskd_url, "SLSKD_API_KEY": s.slskd_api_key}
    notes: list[str] = []

    # 1. Extraer y analizar (se salta si el trabajo se está reanudando tras un reinicio del worker)
    zip_path = svc.input_path(job)
    if not (work / "tracks.json").exists():
        if not zip_path.exists():
            raise JobError("No encontramos el archivo subido. Vuelve a subirlo.", f"falta {zip_path}")
        await jobs.progress(job.id, 3, "Analizando tu librería")
        r = await proc.run([*script("biblioteca.py"), str(zip_path.parent), str(job.id), "-o", "tracks.json",
                            "--csv", "revision.csv", "--formato", formato, "--max-gb", str(s.library_max_unpacked_gb)],
                           cwd=work, log=logf, timeout=2 * 3600)
        if not r.ok or not (work / "tracks.json").exists():
            raise JobError("No pudimos leer tu librería. Revisa que el .zip no esté dañado.", r.tail())
    zip_path.unlink(missing_ok=True)  # ya está extraída en work/biblioteca
    tracks = _load(work / "tracks.json", [])
    in_library = ((job.result or {}).get("input") or {}).get("tracks")
    files = []
    if (work / "revision.csv").exists():
        shutil.copyfile(work / "revision.csv", results / "revision.csv")
        files.append("revision.csv")
    if not tracks:
        return {"summary": _summary(Path("-"), {}, in_library, 0, formato), "files": files,
                "message": "Tu librería ya está en la calidad pedida: no hay nada que mejorar."}

    # 2. Buscar y descargar. slskd_fetch guarda su avance en state.json: de ahí sale el progreso.
    async def tick():
        state = _load(work / "state.json", None)
        if state:
            await jobs.progress(job.id, *_progress_of(state))

    await jobs.progress(job.id, 10, f"Buscando en Soulseek: 0 de {len(tracks)} pistas")
    r = await proc.run([*script("slskd_fetch.py"), "run", "--formato", formato, "--downloads", str(downloads),
                        "--delay", str(s.upgrade_search_delay), "--watch", str(s.upgrade_watch_seconds),
                        "--song-timeout", str(s.upgrade_song_timeout_seconds),
                        "--candidate-wait", str(s.upgrade_candidate_wait_seconds),
                        "--stall", str(s.upgrade_stall_seconds)],
                       cwd=work, env=env, log=logf, timeout=s.upgrade_max_hours * 3600, on_tick=tick, tick=10)
    state = _load(work / "state.json", {})
    if r.timed_out:
        notes.append(f"Se alcanzó el tiempo máximo ({s.upgrade_max_hours:g} h): se entrega lo conseguido hasta ahora.")
        await asyncio.to_thread(_cancel_pending, state)
    elif not r.ok:
        tail = r.tail()
        if "no quedó conectado" in tail or "401" in tail or "ConnectionError" in tail:
            raise JobError("No pudimos conectar con la red de descargas. Intenta de nuevo más tarde.", tail)
        raise JobError("La búsqueda de tu librería se interrumpió. Intenta de nuevo más tarde.", tail)

    # 3. Armar la entrega en el formato pedido + informe por pista
    await jobs.progress(job.id, 86, "Armando tu librería en el formato pedido")
    await proc.run([*script("slskd_fetch.py"), "report"], cwd=work, log=logf, timeout=600)
    r = await proc.run([*script("collect.py"), "--downloads", str(downloads), "--out", str(entrega)],
                       cwd=work, log=logf, timeout=6 * 3600)
    if not r.ok:
        raise JobError("No pudimos armar la entrega de tu librería.", r.tail())
    for src, name in (("_informe.csv", "informe.csv"), ("_no_encontradas.txt", "no_encontradas.txt")):
        if (entrega / src).exists():
            shutil.copyfile(entrega / src, results / name)
            files.append(name)
    summary = _summary(results / "informe.csv", state, in_library, len(tracks), formato)
    summary["notes"] = notes

    # 4. Entregar por Google Drive
    drive_url = None
    if summary["delivered"]:
        await jobs.progress(job.id, 93, "Subiendo tu librería a Google Drive")
        drive_url = await _to_drive(job, entrega, work)
        summary["delivery"] = "drive" if drive_url else "pending"
        left = summary["pending_timeout"]
        message = (f"{summary['delivered']} de {len(tracks)} pistas mejoradas"
                   + (f", {left} pendiente{'s' if left != 1 else ''}" if left else "") if drive_url else
                   f"{summary['delivered']} pistas listas. Estamos preparando tu enlace de descarga: "
                   "te lo enviamos por WhatsApp.")
    else:
        summary["delivery"] = "none"
        message = ("Ninguna fuente estuvo disponible a tiempo. Intenta de nuevo más tarde o con otro formato."
                   if summary["pending_timeout"] else
                   "No encontramos versiones en mejor calidad de tus pistas. Revisa el informe.")

    # 5. Limpiar: originales, descargas de slskd y, si ya está en Drive, la entrega local
    removed = await asyncio.to_thread(_remove_downloads, state, downloads)
    log.info("trabajo %s: %s descargas borradas de slskd", job.id, removed)
    if (work / "state.json").exists():
        shutil.copyfile(work / "state.json", root / "state.json")  # diagnóstico; no es descargable
    if drive_url or not summary["delivered"]:
        svc.remove_tree(entrega)
    return {"summary": summary, "files": files, "drive_url": drive_url, "message": message}
