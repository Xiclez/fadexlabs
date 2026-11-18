"""Detener trabajos, encuesta al terminar (web y escritorio), vista del waveform y envío por EmailJS."""
import json
import uuid

import pytest
from sqlalchemy import update

from app.core.config import get_settings
from app.db import SessionLocal
from app.models import ToolJob
from app.services import email
from app.services import tools as svc
from tests.test_profile_beta import bearer, signup
from tests.test_tools import finish, set_mp3, upload  # noqa: F401 (fixture)

pytestmark = pytest.mark.asyncio


async def queued_job(client, set_mp3):  # noqa: F811
    access, _ = await signup(client, "dj@example.com")
    r = await upload(client, access, set_mp3)
    assert r.status_code == 200, r.text
    return access, r.json()["id"]


async def test_stop_queued_cancels_and_cleans(client, set_mp3):  # noqa: F811
    access, job_id = await queued_job(client, set_mp3)
    r = await client.post(f"/api/tools/jobs/{job_id}/stop", headers=bearer(access))
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "cancelled" and body["files"] == [] and "antes de que empezara" in body["message"]
    assert not svc.job_dir(uuid.UUID(job_id)).exists()
    # ya terminado: no se puede detener otra vez
    assert (await client.post(f"/api/tools/jobs/{job_id}/stop", headers=bearer(access))).status_code == 409


async def test_stop_running_marks_request_for_worker(client, set_mp3):  # noqa: F811
    access, job_id = await queued_job(client, set_mp3)
    async with SessionLocal() as db:
        await db.execute(update(ToolJob).where(ToolJob.id == uuid.UUID(job_id)).values(status="running"))
        await db.commit()
    r = await client.post(f"/api/tools/jobs/{job_id}/stop", headers=bearer(access))
    assert r.status_code == 200 and r.json()["status"] == "running" and r.json()["stopping"] is True
    async with SessionLocal() as db:
        assert (await db.get(ToolJob, uuid.UUID(job_id))).stop_requested_at is not None
    # otro usuario no puede detenerlo (404, no revela que existe)
    other, _ = await signup(client, "otro@example.com")
    assert (await client.post(f"/api/tools/jobs/{job_id}/stop", headers=bearer(other))).status_code == 404


async def test_feedback_web_once_with_form_invite(client, set_mp3, monkeypatch):  # noqa: F811
    monkeypatch.setattr(get_settings(), "feedback_form_url", "https://forms.gle/prueba")
    access, job_id = await queued_job(client, set_mp3)
    await finish(job_id)
    h = bearer(access)
    detail = (await client.get(f"/api/tools/jobs/{job_id}", headers=h)).json()
    assert detail["feedback_given"] is False

    no_comment = {"source": "web", "tool": "tracklist", "job_ref": job_id, "rating": 4, "comment": ""}
    r = await client.post("/api/feedback", headers=h, json=no_comment)
    assert r.status_code == 201 and r.json()["form_url"] is None   # sin comentario no hay invitación
    msg = email.outbox[-1]
    assert msg["To"] == "ibarraorvil@gmail.com" and "★★★★☆" in msg["Subject"]
    assert "user_email: dj@example.com" in msg.get_content()
    assert (await client.get(f"/api/tools/jobs/{job_id}", headers=h)).json()["feedback_given"] is True
    assert (await client.post("/api/feedback", headers=h, json=no_comment)).status_code == 409  # una por trabajo


async def test_feedback_comment_gets_form_and_desktop_refs(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "feedback_form_url", "https://forms.gle/prueba")
    access, _ = await signup(client, "dj@example.com")
    r = await client.post("/api/feedback", headers=bearer(access), json={
        "source": "desktop", "tool": "library_upgrade", "job_ref": "20261110-120000-abc123", "rating": 5,
        "comment": "Muy buena, encontró casi todo", "stopped": True,
        "details": {"delivered": 40, "total": 52, "ruta": "C:\\\\Users\\\\x" * 50}})
    assert r.status_code == 201 and r.json()["form_url"] == "https://forms.gle/prueba"
    body = email.outbox[-1].get_content()
    assert "Lo detuvo antes de terminar" in body and "app de escritorio" in body and "Muy buena" in body
    assert len(json.loads(body.split("details: ", 1)[1].splitlines()[0])["ruta"]) <= 80


async def test_feedback_rules(client, set_mp3):  # noqa: F811
    access, job_id = await queued_job(client, set_mp3)
    h = bearer(access)
    base = {"source": "web", "tool": "tracklist", "job_ref": job_id, "rating": 3}
    assert (await client.post("/api/feedback", headers=h, json={**base, "rating": 6})).status_code == 422
    assert (await client.post("/api/feedback", headers=h, json={**base, "comment": "x" * 501})).status_code == 422
    assert (await client.post("/api/feedback", headers=h, json={**base, "tool": "library_upgrade"})).status_code == 404
    other, _ = await signup(client, "otro@example.com")
    assert (await client.post("/api/feedback", headers=bearer(other), json=base)).status_code == 404
    assert (await client.post("/api/feedback", json=base)).status_code == 401


async def test_visual_only_when_ready(client, set_mp3):  # noqa: F811
    access, job_id = await queued_job(client, set_mp3)
    h = bearer(access)
    assert (await client.get(f"/api/tools/jobs/{job_id}/visual", headers=h)).status_code == 404
    await finish(job_id)
    out = svc.results_dir(uuid.UUID(job_id))
    (out / "visual.json").write_text(json.dumps({"duration": 60, "peaks": [1, 2], "tracks": []}), encoding="utf-8")
    assert (await client.get(f"/api/tools/jobs/{job_id}/visual", headers=h)).status_code == 404  # result sin visual
    async with SessionLocal() as db:
        await db.execute(update(ToolJob).where(ToolJob.id == uuid.UUID(job_id)).values(
            result={"summary": {}, "files": ["tracklist.txt"], "visual": True}))
        await db.commit()
    r = await client.get(f"/api/tools/jobs/{job_id}/visual", headers=h)
    assert r.status_code == 200 and r.json()["peaks"] == [1, 2]
    assert (await client.get(f"/api/tools/jobs/{job_id}", headers=h)).json()["visual"] is True


async def test_emailjs_payload(monkeypatch):
    s = get_settings()
    for k, v in {"env": "prod", "emailjs_service_id": "service_fx", "emailjs_public_key": "pub",
                 "emailjs_private_key": "priv", "emailjs_template_generic": "tpl_generic",
                 "emailjs_template_feedback": "tpl_feedback"}.items():
        monkeypatch.setattr(s, k, v)
    sent = []

    async def fake_post(template_id, params):
        sent.append((template_id, params))

    monkeypatch.setattr(email, "post_emailjs", fake_post)
    await email.send_verify_email("dj@example.com", "tok<en>")
    tpl, p = sent[-1]
    assert tpl == "tpl_generic" and p["to_email"] == "dj@example.com" and p["title"] == "Confirma tu email"
    assert p["button_url"].endswith("/verificar-email?token=tok<en>") and p["button_label"] == "Confirmar mi email"
    assert p["message_html"].startswith("<p>Hola,</p>") and "<en>" not in p["message_html"]

    await email.send_feedback(user_email="dj@example.com", user_name="DJ <b>", source="web", tool="tracklist",
                              rating=5, comment="", stopped=False, job_ref="abc", details="{}")
    tpl, p = sent[-1]
    assert tpl == "tpl_feedback" and p["to_email"] == "ibarraorvil@gmail.com" and p["reply_to"] == "dj@example.com"
    assert p["stars"] == "★★★★★" and p["comment"] == "(sin comentario)" and p["tool"] == "Tracklist ID"
