"""Cola y limpieza del worker."""
import uuid
from datetime import timedelta

from sqlalchemy import select

from app.db import SessionLocal
from app.models import ToolJob, User
from app.services import tools as svc
from tests.conftest import signup
from worker import jobs, main


async def make_job(user_id, **values) -> ToolJob:
    async with SessionLocal() as db:
        job = ToolJob(user_id=user_id, tool="tracklist", input_name="set.mp3", input_bytes=10, options={},
                      chunk_size=4, **values)
        db.add(job)
        await db.commit()
        return job


async def user_id(client):
    await signup(client)
    async with SessionLocal() as db:
        return (await db.execute(select(User.id))).scalar_one()


async def test_claim_takes_oldest_queued_per_tool_and_requeues_orphans(client):
    uid, now = await user_id(client), svc.utcnow()
    newer = await make_job(uid, status="queued", created_at=now)
    older = await make_job(uid, status="queued", created_at=now - timedelta(minutes=5))
    await make_job(uid, status="uploading")
    assert await jobs.claim("library_upgrade") is None      # cada herramienta tiene su cola
    first = await jobs.claim("tracklist")
    assert first.id == older.id and first.status == "running" and first.started_at is not None
    assert (await jobs.claim("tracklist")).id == newer.id
    assert await jobs.claim("tracklist") is None             # las subidas a medias no se toman

    # un worker que murió deja trabajos 'running': al arrancar vuelven a la cola
    assert await jobs.requeue_orphans() == 2
    assert (await jobs.claim("tracklist")).id == older.id


async def test_housekeeping_removes_abandoned_uploads_and_expired_results(client):
    uid, now = await user_id(client), svc.utcnow()
    stale = await make_job(uid, status="uploading", created_at=now - timedelta(hours=25))
    fresh = await make_job(uid, status="uploading", created_at=now - timedelta(hours=1))
    old = await make_job(uid, status="done", expires_at=now - timedelta(days=1),
                         result={"summary": {"tracks": 9}, "files": ["tracklist.txt"]})
    live = await make_job(uid, status="done", expires_at=now + timedelta(days=29), result={"files": []})
    for job in (stale, fresh):
        svc.upload_dir(job.id).mkdir(parents=True)
        svc.upload_path(job.id).write_bytes(b"x")
    for job in (old, live):
        svc.results_dir(job.id).mkdir(parents=True)
        (svc.results_dir(job.id) / "tracklist.txt").write_text("x")

    assert await main.housekeeping() == {"uploads": 1, "expired": 1}
    assert not svc.upload_dir(stale.id).exists() and svc.upload_path(fresh.id).exists()
    assert not svc.job_dir(old.id).exists() and svc.results_dir(live.id).exists()
    async with SessionLocal() as db:
        assert await db.get(ToolJob, stale.id) is None
        expired = await db.get(ToolJob, old.id)
        assert expired.status == "expired" and expired.result == {"summary": {"tracks": 9}}
        assert (await db.get(ToolJob, live.id)).status == "done"
    assert svc.available_files(expired) == []
    assert await main.housekeeping() == {"uploads": 0, "expired": 0}
    assert uuid.UUID(str(live.id))
