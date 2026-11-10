"""Herramientas de la beta cerrada: subida por partes, trabajos y descargas. Montado en /api/tools.

La subida es reanudable y va por partes porque Cloudflare Tunnel rechaza cuerpos de más de 100 MB:
    POST /uploads                      → {upload_id, chunk_size, total_parts, received_parts}
    PUT  /uploads/{id}/chunks/{n}      cuerpo binario; en orden (repetir la última parte es válido)
    POST /uploads/{id}/complete        valida el contenido real y deja el trabajo en cola
"""
import asyncio
import os
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse
from starlette.requests import ClientDisconnect
from sqlalchemy import func, select

from app.core import ratelimit
from app.core.config import get_settings
from app.core.deps import DB, BetaUser
from app.models import JobStatus, Tool, ToolJob, User
from app.schemas.tools import UPGRADE_FORMATS, JobOut, JobPage, ToolLimits, ToolsInfo, UploadInitIn, UploadOut
from app.services import tools as svc

router = APIRouter(prefix="/api/tools", tags=["tools"])

_not_found = HTTPException(status.HTTP_404_NOT_FOUND, "No encontrado")


async def tool_user(user: BetaUser) -> User:
    """Lugar en la beta (o admin) y email confirmado."""
    if not user.email_verified:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Confirma tu email para continuar")
    return user


ToolUser = Annotated[User, Depends(tool_user)]


async def _own_job(db, user: User, job_id: uuid.UUID) -> ToolJob:
    """El trabajo, solo si es del usuario. Si es de otro responde 404 (no revela que existe)."""
    job = (await db.execute(select(ToolJob).where(ToolJob.id == job_id, ToolJob.user_id == user.id))
           ).scalar_one_or_none()
    if not job:
        raise _not_found
    return job


def _upload_out(job: ToolJob) -> UploadOut:
    return UploadOut(upload_id=job.id, chunk_size=job.chunk_size, total_parts=job.total_parts,
                     received_parts=job.received_parts)


@router.get("", response_model=ToolsInfo)
async def info(user: ToolUser) -> ToolsInfo:
    """Límites vigentes, para que la web valide antes de subir."""
    s = get_settings()
    return ToolsInfo(
        chunk_size=s.upload_chunk_bytes, result_days=s.result_ttl_days,
        tracklist=ToolLimits(max_bytes=s.tracklist_max_bytes, per_day=s.tracklist_per_day,
                             extensions=list(svc.EXTENSIONS[Tool.tracklist])),
        library_upgrade=ToolLimits(max_bytes=s.library_max_bytes, per_day=s.library_per_day,
                                   extensions=list(svc.EXTENSIONS[Tool.library_upgrade])),
        library_max_files=s.library_max_files, formats=list(UPGRADE_FORMATS))


# ---------- subida por partes ----------

@router.post("/uploads", response_model=UploadOut)
async def init_upload(body: UploadInitIn, user: ToolUser, db: DB) -> UploadOut:
    s = get_settings()
    await ratelimit.hit(f"tools-init:{user.id}", s.tools_init_per_hour, 3600)
    ext = os.path.splitext(body.filename)[1].lower()
    if ext not in svc.EXTENSIONS[body.tool]:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Formato no admitido. Usa: " + ", ".join(svc.EXTENSIONS[body.tool]))
    if body.size > svc.max_bytes(body.tool):
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            f"El archivo supera el máximo de {svc.max_bytes(body.tool) / 1024**3:.0f} GB.")
    options = {"formato": body.formato} if body.tool == Tool.library_upgrade else {}

    # Una subida a medias de la misma herramienta: si es el mismo archivo se reanuda; si no, se reemplaza.
    pending = (await db.execute(select(ToolJob).where(
        ToolJob.user_id == user.id, ToolJob.tool == body.tool, ToolJob.status == JobStatus.uploading))
    ).scalars().all()
    for old in pending:
        if (old.input_name, old.input_bytes, old.options) == (body.filename, body.size, options) \
                and svc.upload_path(old.id).exists():
            return _upload_out(old)
        svc.remove_tree(svc.upload_dir(old.id))
        await db.delete(old)
    await svc.check_limits(db, user.id, body.tool)

    job = ToolJob(user_id=user.id, tool=body.tool, input_name=body.filename, input_bytes=body.size,
                  options=options, chunk_size=s.upload_chunk_bytes, message="Subiendo")
    db.add(job)
    await db.flush()
    svc.upload_dir(job.id).mkdir(parents=True, exist_ok=True)
    svc.upload_path(job.id).touch()
    await db.commit()
    return _upload_out(job)


@router.get("/uploads/{upload_id}", response_model=UploadOut)
async def upload_status(upload_id: uuid.UUID, user: ToolUser, db: DB) -> UploadOut:
    job = await _own_job(db, user, upload_id)
    if job.status != JobStatus.uploading:
        raise _not_found
    return _upload_out(job)


@router.put("/uploads/{upload_id}/chunks/{index}", response_model=UploadOut)
async def put_chunk(upload_id: uuid.UUID, index: int, request: Request, user: ToolUser, db: DB) -> UploadOut:
    job = await _own_job(db, user, upload_id)
    if job.status != JobStatus.uploading:
        raise HTTPException(status.HTTP_409_CONFLICT, "Esta subida ya se cerró")
    if not 0 <= index < job.total_parts:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Índice de parte fuera de rango")
    if index > job.received_parts:  # en orden; repetir una parte ya enviada (reintento) sí se permite
        raise HTTPException(status.HTTP_409_CONFLICT, f"Falta la parte {job.received_parts}")
    last = index == job.total_parts - 1
    expected = job.input_bytes - job.chunk_size * index if last else job.chunk_size
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) != expected:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"La parte {index} debe medir {expected} bytes")

    path = svc.upload_path(job.id)
    if not path.exists():
        raise HTTPException(status.HTTP_410_GONE, "La subida expiró. Empieza de nuevo.")
    written = 0
    # Directo a disco, en su posición dentro del archivo final: nada de partes en memoria ni ensamblado.
    try:
        with open(path, "r+b") as f:
            f.seek(job.chunk_size * index)
            async for piece in request.stream():
                written += len(piece)
                if written > expected:
                    raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, f"La parte {index} excede su tamaño")
                await asyncio.to_thread(f.write, piece)
    except ClientDisconnect:  # se cortó la conexión a media parte: el cliente la reintenta
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"La parte {index} se interrumpió") from None
    if written != expected:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"La parte {index} llegó incompleta ({written} de {expected} bytes)")
    job.received_parts = max(job.received_parts, index + 1)
    await db.commit()
    return _upload_out(job)


@router.post("/uploads/{upload_id}/complete", response_model=JobOut)
async def complete_upload(upload_id: uuid.UUID, user: ToolUser, db: DB) -> dict:
    s = get_settings()
    await ratelimit.hit(f"tools-complete:{user.id}", s.tools_init_per_hour, 3600)
    job = await _own_job(db, user, upload_id)
    if job.status != JobStatus.uploading:
        raise HTTPException(status.HTTP_409_CONFLICT, "Esta subida ya se cerró")
    path = svc.upload_path(job.id)
    if job.received_parts != job.total_parts or not path.exists() or path.stat().st_size != job.input_bytes:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"La subida está incompleta: faltan partes desde la {job.received_parts}")
    await svc.check_limits(db, user.id, job.tool)

    # El contenido real, no la extensión: ffprobe para sets, zipfile para librerías.
    try:
        meta = await asyncio.to_thread(svc.validate_input, job.tool, path)
    except svc.InvalidUpload as ex:
        svc.remove_tree(svc.upload_dir(job.id))
        await db.delete(job)
        await db.commit()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(ex)) from None

    dest = svc.input_path(job)
    dest.parent.mkdir(parents=True, exist_ok=True)
    os.replace(path, dest)  # mismo volumen: es un renombrado, no una copia
    svc.remove_tree(svc.upload_dir(job.id))
    job.status, job.message, job.progress = JobStatus.queued, "En cola", 0
    job.result = {"input": meta}
    job.created_at = svc.utcnow()  # la cola y el tope diario cuentan desde que entra, no desde que empezó a subir
    await db.commit()
    return svc.job_out(job)


@router.delete("/uploads/{upload_id}", status_code=204)
async def cancel_upload(upload_id: uuid.UUID, user: ToolUser, db: DB) -> None:
    job = await _own_job(db, user, upload_id)
    if job.status != JobStatus.uploading:
        raise HTTPException(status.HTTP_409_CONFLICT, "Esta subida ya se cerró")
    svc.remove_tree(svc.upload_dir(job.id))
    await db.delete(job)
    await db.commit()


# ---------- trabajos y resultados ----------

@router.get("/jobs", response_model=JobPage)
async def my_jobs(user: ToolUser, db: DB, limit: int = 20, offset: int = 0) -> dict:
    limit, offset = max(1, min(limit, 50)), max(0, offset)
    mine = (ToolJob.user_id == user.id, ToolJob.status != JobStatus.uploading)
    total = (await db.execute(select(func.count()).where(*mine))).scalar_one()
    rows = (await db.execute(select(ToolJob).where(*mine).order_by(ToolJob.created_at.desc())
                             .limit(limit).offset(offset))).scalars().all()
    return {"items": [svc.job_out(j) for j in rows], "total": total}


@router.get("/jobs/{job_id}", response_model=JobOut)
async def job_detail(job_id: uuid.UUID, user: ToolUser, db: DB) -> dict:
    return svc.job_out(await _own_job(db, user, job_id))


@router.get("/jobs/{job_id}/files/{name}")
async def job_file(job_id: uuid.UUID, name: str, user: ToolUser, db: DB) -> FileResponse:
    job = await _own_job(db, user, job_id)
    # Lista blanca: `name` nunca se usa para armar una ruta si no es uno de los nombres permitidos.
    if name not in svc.available_files(job):
        raise _not_found
    path = svc.results_dir(job.id) / name
    if not path.is_file():
        raise _not_found
    return FileResponse(path, filename=name, media_type="text/csv" if name.endswith(".csv") else "text/plain")
