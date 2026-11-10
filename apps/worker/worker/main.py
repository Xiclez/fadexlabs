"""Worker de las herramientas: toma trabajos en cola de la base de datos y los procesa.

Uso (con las mismas variables FADEX_* que la API; desde apps/api para compartir ./dev.db y ./data):
    PYTHONPATH=../worker python -m worker.main

Una tracklist a la vez (límites de ACRCloud y Shazam) y una librería a la vez (una sola cuenta de
Soulseek); las dos herramientas sí corren en paralelo entre sí.
"""
import asyncio
import logging
import signal
import traceback
from datetime import timedelta

from sqlalchemy import select, update

from app.core.config import get_settings
from app.db import SessionLocal, engine
from app.models import JobStatus, ToolJob
from app.services import tools as svc
from worker import jobs, library, tracklist
from worker.jobs import JobError

log = logging.getLogger("fadex.worker")
HANDLERS = {"tracklist": tracklist.run, "library_upgrade": library.run}
HOUSEKEEPING_SECONDS = 600


async def process(job: ToolJob) -> None:
    """Corre un trabajo. Un fallo nunca tumba el worker: queda registrado y el usuario ve un mensaje claro."""
    log.info("trabajo %s (%s) de %s: empieza", job.id, job.tool, job.user_id)
    try:
        result = await HANDLERS[job.tool](job)
        await jobs.finish(job.id, result=result)
        log.info("trabajo %s: listo (%s)", job.id, result.get("message"))
    except asyncio.CancelledError:
        # apagado ordenado: vuelve a la cola con sus archivos intactos para retomarlo al arrancar
        async with SessionLocal() as db:
            await db.execute(update(ToolJob).where(ToolJob.id == job.id, ToolJob.status == JobStatus.running)
                             .values(status=JobStatus.queued, message="En cola (se reanuda)"))
            await db.commit()
        raise
    except JobError as ex:
        log.warning("trabajo %s: falló: %s\n%s", job.id, ex.message, ex.detail[-2000:])
        await jobs.finish(job.id, failure=ex)
    except Exception:
        log.exception("trabajo %s: error inesperado", job.id)
        await jobs.finish(job.id, failure=JobError(
            "Ocurrió un error inesperado al procesar tu archivo. Ya lo estamos revisando.", traceback.format_exc()))
    # Éxito o error: el audio subido y la carpeta de trabajo se borran; solo quedan los resultados.
    root = svc.job_dir(job.id)
    svc.remove_tree(root / "input")
    svc.remove_tree(root / "work")


async def tool_loop(tool: str) -> None:
    poll = get_settings().worker_poll_seconds
    while True:
        try:
            job = await jobs.claim(tool)
        except Exception:  # p. ej. la base no responde: reintentar, no morir
            log.exception("no pude consultar la cola de %s", tool)
            job = None
        if job:
            await process(job)
        else:
            await asyncio.sleep(poll)


async def housekeeping() -> dict:
    """Borra subidas abandonadas y resultados vencidos."""
    s, now, n = get_settings(), svc.utcnow(), {"uploads": 0, "expired": 0}
    async with SessionLocal() as db:
        stale = (await db.execute(select(ToolJob).where(
            ToolJob.status == JobStatus.uploading,
            ToolJob.created_at < now - timedelta(seconds=s.upload_ttl_seconds)))).scalars().all()
        for job in stale:
            svc.remove_tree(svc.upload_dir(job.id))
            await db.delete(job)
            n["uploads"] += 1
        old = (await db.execute(select(ToolJob).where(
            ToolJob.status.in_((JobStatus.done, JobStatus.failed)), ToolJob.expires_at.is_not(None),
            ToolJob.expires_at < now))).scalars().all()
        for job in old:
            svc.remove_tree(svc.job_dir(job.id))
            job.status, job.message = JobStatus.expired, "Los resultados ya no están disponibles"
            job.result = {"summary": (job.result or {}).get("summary")}
            n["expired"] += 1
        await db.commit()
    return n


async def housekeeping_loop() -> None:
    while True:
        try:
            n = await housekeeping()
            if any(n.values()):
                log.info("limpieza: %s", n)
        except Exception:
            log.exception("falló la limpieza")
        await asyncio.sleep(HOUSEKEEPING_SECONDS)


async def run_forever() -> None:
    n = await jobs.requeue_orphans()
    if n:
        log.info("%s trabajos interrumpidos vuelven a la cola", n)
    svc.data_dir().mkdir(parents=True, exist_ok=True)
    log.info("worker listo. datos en %s", svc.data_dir())
    tasks = [asyncio.create_task(tool_loop(t), name=t) for t in HANDLERS]
    tasks.append(asyncio.create_task(housekeeping_loop(), name="housekeeping"))

    loop = asyncio.get_running_loop()
    stop = asyncio.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # Windows: Ctrl+C llega como KeyboardInterrupt
            pass
    try:
        await stop.wait()
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await engine.dispose()
        log.info("worker detenido")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        asyncio.run(run_forever())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
