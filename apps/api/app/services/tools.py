"""Herramientas de la beta: rutas en disco, validación del contenido subido y límites por usuario.

Disposición de FADEX_DATA_DIR (compartida entre la API y el worker):
    uploads/<id>/input.part        subida en curso (las partes se escriben en su posición)
    jobs/<id>/input/<id><.ext>     archivo validado, listo para el worker (se borra al terminar)
    jobs/<id>/work/                carpeta de trabajo del worker (se borra al terminar)
    jobs/<id>/results/<nombre>     lo que el usuario puede descargar (se borra al expirar)
"""
import json
import os
import shutil
import subprocess
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import ACTIVE, JobStatus, Tool, ToolJob

SET_EXTS = (".wav", ".mp3", ".flac", ".aiff", ".aif", ".m4a")
LIBRARY_AUDIO_EXTS = (".mp3", ".flac", ".wav", ".aif", ".aiff", ".m4a")  # = formats.AUDIO_EXTS del upgrader
EXTENSIONS = {Tool.tracklist: SET_EXTS, Tool.library_upgrade: (".zip",)}

# Lista blanca de descargas por herramienta: nunca se sirve un nombre que no esté aquí.
RESULT_FILES = {
    Tool.tracklist: ("tracklist.txt", "tracklist.csv"),
    Tool.library_upgrade: ("informe.csv", "no_encontradas.txt", "revision.csv"),
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def aware(dt: datetime | None) -> datetime | None:
    """SQLite devuelve las fechas sin zona; en la base siempre son UTC."""
    return dt.replace(tzinfo=timezone.utc) if dt and dt.tzinfo is None else dt


# ---------- rutas ----------

def data_dir() -> Path:
    return Path(get_settings().data_dir).resolve()


def upload_dir(job_id: uuid.UUID) -> Path:
    return data_dir() / "uploads" / str(job_id)


def upload_path(job_id: uuid.UUID) -> Path:
    return upload_dir(job_id) / "input.part"


def job_dir(job_id: uuid.UUID) -> Path:
    return data_dir() / "jobs" / str(job_id)


def input_path(job: ToolJob) -> Path:
    # En disco el archivo lleva el id del trabajo, no el nombre del usuario: evita rutas raras y,
    # en ACRCloud (que reutiliza resultados por nombre de archivo), que dos sets se confundan.
    ext = os.path.splitext(job.input_name)[1].lower()
    return job_dir(job.id) / "input" / f"{job.id}{ext}"


def results_dir(job_id: uuid.UUID) -> Path:
    return job_dir(job_id) / "results"


def remove_tree(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


# ---------- límites ----------

def max_bytes(tool: str) -> int:
    s = get_settings()
    return s.tracklist_max_bytes if tool == Tool.tracklist else s.library_max_bytes


def per_day(tool: str) -> int:
    s = get_settings()
    return s.tracklist_per_day if tool == Tool.tracklist else s.library_per_day


async def check_limits(db: AsyncSession, user_id: uuid.UUID, tool: str) -> None:
    """Un trabajo activo por usuario y herramienta, y un tope diario."""
    active = (await db.execute(select(func.count()).where(
        ToolJob.user_id == user_id, ToolJob.tool == tool, ToolJob.status.in_(ACTIVE)))).scalar_one()
    if active:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Ya tienes un trabajo en curso con esta herramienta. Espera a que termine.")
    since = utcnow() - timedelta(days=1)
    today = (await db.execute(select(func.count()).where(
        ToolJob.user_id == user_id, ToolJob.tool == tool, ToolJob.created_at >= since,
        ToolJob.status.in_((JobStatus.queued, JobStatus.running, JobStatus.done))))).scalar_one()
    if today >= per_day(tool):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            f"Llegaste al límite de {per_day(tool)} trabajos por día con esta herramienta.")


# ---------- validación del contenido (nunca se confía en la extensión) ----------

class InvalidUpload(Exception):
    """El archivo subido no es lo que dice ser. El mensaje es para el usuario."""


def probe_audio(path: Path) -> float:
    """Duración en segundos si ffprobe encuentra una pista de audio; si no, InvalidUpload."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
             "stream=codec_name:format=duration", "-of", "json", str(path)],
            capture_output=True, text=True, timeout=120)
        info = json.loads(out.stdout or "{}")
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        raise InvalidUpload("No pudimos leer el archivo de audio.") from None
    if out.returncode != 0 or not info.get("streams"):
        raise InvalidUpload("El archivo no es un audio válido (wav, mp3, flac, aiff o m4a).")
    try:
        seconds = float((info.get("format") or {}).get("duration") or 0)
    except ValueError:
        seconds = 0.0
    minimum = get_settings().tracklist_min_seconds
    if seconds < minimum:
        raise InvalidUpload(f"El set es demasiado corto (mínimo {minimum} segundos).")
    return seconds


def probe_library(path: Path) -> dict:
    """Cuenta las pistas de audio del zip sin extraerlo. Aplica los topes de archivos y de tamaño."""
    s = get_settings()
    if not zipfile.is_zipfile(path):
        raise InvalidUpload("El archivo no es un .zip válido.")
    try:
        with zipfile.ZipFile(path) as z:
            members = [m for m in z.infolist() if not m.is_dir()]
    except (zipfile.BadZipFile, OSError):
        raise InvalidUpload("El .zip está dañado.") from None
    def usable(name: str) -> bool:  # lo mismo que extraerá el upgrader (safe_extract)
        name = name.replace("\\", "/")
        return (name.lower().endswith(LIBRARY_AUDIO_EXTS) and "__MACOSX/" not in name
                and not os.path.basename(name).startswith("._")
                and not name.startswith("/") and ".." not in name.split("/"))

    audio = [m for m in members if usable(m.filename)]
    if not audio:
        raise InvalidUpload("El .zip no contiene audio (mp3, flac, wav, aiff o m4a).")
    if len(audio) > s.library_max_files:
        raise InvalidUpload(f"El .zip tiene {len(audio)} pistas; el máximo por librería es {s.library_max_files}.")
    unpacked = sum(m.file_size for m in audio)
    if unpacked > s.library_max_unpacked_gb * 1e9:
        raise InvalidUpload(f"La librería descomprimida supera {s.library_max_unpacked_gb:.0f} GB.")
    return {"tracks": len(audio), "unpacked_bytes": unpacked}


def validate_input(tool: str, path: Path) -> dict:
    if tool == Tool.tracklist:
        return {"seconds": round(probe_audio(path), 1)}
    return probe_library(path)


# ---------- salida ----------

def available_files(job: ToolJob) -> list[str]:
    if job.status != JobStatus.done:
        return []
    listed = (job.result or {}).get("files") or []
    return [n for n in RESULT_FILES.get(job.tool, ()) if n in listed]


def job_out(job: ToolJob) -> dict:
    """Vista pública de un trabajo. `error` (detalle interno) nunca se incluye."""
    result = job.result or {}
    out = {
        "id": job.id, "tool": job.tool, "status": job.status, "input_name": job.input_name,
        "input_bytes": job.input_bytes, "options": job.options or {}, "progress": job.progress,
        "message": job.message, "created_at": aware(job.created_at), "started_at": aware(job.started_at),
        "finished_at": aware(job.finished_at), "expires_at": aware(job.expires_at),
        "summary": result.get("summary"), "files": available_files(job),
        "drive_url": result.get("drive_url") if job.status == JobStatus.done else None,
    }
    if job.status == JobStatus.uploading:
        out.update(chunk_size=job.chunk_size, total_parts=job.total_parts, received_parts=job.received_parts)
    return out
