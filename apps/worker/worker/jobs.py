"""Cola de trabajos sobre la base de datos (sin brokers): tomar, publicar progreso y cerrar."""
import logging
import uuid
from datetime import timedelta

from sqlalchemy import select, update

from app.core.config import get_settings
from app.db import SessionLocal
from app.models import JobStatus, ToolJob, User
from app.services import email
from app.services import tools as svc

log = logging.getLogger("fadex.worker")


class JobError(Exception):
    """Fallo con un mensaje apto para el usuario. `detail` es el detalle interno (logs)."""

    def __init__(self, message: str, detail: str = ""):
        super().__init__(message)
        self.message, self.detail = message, detail


async def claim(tool: str) -> ToolJob | None:
    """Toma el trabajo más antiguo en cola de esa herramienta y lo marca en ejecución.
    En Postgres, FOR UPDATE SKIP LOCKED evita que dos workers tomen el mismo; SQLite lo ignora
    (en desarrollo hay un solo worker)."""
    async with SessionLocal() as db:
        async with db.begin():
            job = (await db.execute(
                select(ToolJob).where(ToolJob.status == JobStatus.queued, ToolJob.tool == tool)
                .order_by(ToolJob.created_at).limit(1).with_for_update(skip_locked=True))).scalar_one_or_none()
            if job:
                job.status, job.started_at = JobStatus.running, svc.utcnow()
                job.progress, job.message = 1, "Empezando"
        return job


async def progress(job_id: uuid.UUID, pct: int, message: str) -> None:
    async with SessionLocal() as db:
        await db.execute(update(ToolJob).where(ToolJob.id == job_id, ToolJob.status == JobStatus.running)
                         .values(progress=max(0, min(99, int(pct))), message=message[:300]))
        await db.commit()


async def finish(job_id: uuid.UUID, *, result: dict | None = None, failure: JobError | None = None) -> None:
    """Cierra el trabajo y avisa por email al usuario con el enlace a su trabajo."""
    s = get_settings()
    async with SessionLocal() as db:
        job = await db.get(ToolJob, job_id)
        if not job:
            return
        job.finished_at = svc.utcnow()
        job.expires_at = svc.utcnow() + timedelta(days=s.result_ttl_days)
        if failure:
            job.status, job.message, job.error = JobStatus.failed, failure.message[:300], failure.detail[-4000:]
        else:
            job.status, job.progress, job.result = JobStatus.done, 100, result
            job.message = ((result or {}).get("message") or "Listo")[:300]
        user = await db.get(User, job.user_id)
        name, tool, status, message = job.input_name, job.tool, job.status, job.message
        await db.commit()
    if not user:
        return
    title = "Tracklist ID" if tool == "tracklist" else "DJ Library Upgrader"
    url = f"{s.public_url}/herramientas/trabajos/{job_id}"
    if status == JobStatus.done:
        body = (f"Hola,\n\nTu trabajo de {title} con «{name}» terminó: {message}\n\n"
                f"Míralo y descarga los resultados aquí:\n{url}\n\n"
                f"Los resultados estarán disponibles {s.result_ttl_days} días.\n")
        subject = f"{title}: tu trabajo está listo · FADEX Labs"
    else:
        body = (f"Hola,\n\nNo pudimos terminar tu trabajo de {title} con «{name}»: {message}\n\n"
                f"Detalles: {url}\n\nSi se repite, escríbenos por WhatsApp y lo revisamos.\n")
        subject = f"{title}: no pudimos terminar tu trabajo · FADEX Labs"
    await email.send(user.email, subject, body)


async def requeue_orphans() -> int:
    """Al arrancar: lo que quedó 'running' es de un worker que murió; vuelve a la cola.
    (El upgrader retoma donde iba gracias a su state.json; la tracklist empieza de nuevo.)"""
    async with SessionLocal() as db:
        res = await db.execute(update(ToolJob).where(ToolJob.status == JobStatus.running)
                               .values(status=JobStatus.queued, message="En cola (se reanuda)"))
        await db.commit()
        return res.rowcount or 0
