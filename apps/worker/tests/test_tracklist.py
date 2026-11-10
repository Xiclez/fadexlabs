"""Tracklist ID de punta a punta: subida por la API → worker (ACRCloud y Shazam simulados) → descarga."""
import csv
import io
import uuid

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.db import SessionLocal
from app.models import ToolJob
from app.services import email
from app.services import tools as svc
from tests.conftest import bearer, ffmpeg, signup, upload
from worker import jobs, main


@pytest.fixture(scope="session")
def set_wav(tmp_path_factory):
    """Un 'set' de 6 min generado con ffmpeg (tono que cambia + ruido), en WAV para que haya que comprimirlo."""
    path = tmp_path_factory.mktemp("set") / "Mi Set 2026.wav"
    ffmpeg("-f", "lavfi", "-i", "aevalsrc='0.3*sin(2*PI*t*(220+40*floor(t/30)))':s=22050:d=360",
           "-f", "lavfi", "-i", "anoisesrc=color=pink:duration=360:sample_rate=22050:amplitude=0.2",
           "-filter_complex", "amix=inputs=2:normalize=0", "-ac", "1", path)
    return path


async def run_next(tool="tracklist"):
    job = await jobs.claim(tool)
    assert job is not None
    await main.process(job)
    async with SessionLocal() as db:
        return (await db.execute(select(ToolJob).where(ToolJob.id == job.id))).scalar_one()


async def test_tracklist_end_to_end(client, set_wav):
    access = await signup(client)
    queued = await upload(client, access, set_wav, "tracklist")
    assert queued["status"] == "queued"
    job = await run_next()
    assert job.status == "done", (job.message, job.error)

    h = bearer(access)
    detail = (await client.get(f"/api/tools/jobs/{job.id}", headers=h)).json()
    assert detail["progress"] == 100 and detail["files"] == ["tracklist.txt", "tracklist.csv"]
    assert detail["summary"]["sources"] == ["acrcloud", "shazam"] and detail["summary"]["notes"] == []
    assert detail["summary"]["tracks"] == 4 and detail["summary"]["unidentified"] == 1
    assert detail["message"] == "4 temas identificados, 1 tramo sin identificar"

    txt = (await client.get(f"/api/tools/jobs/{job.id}/files/tracklist.txt", headers=h)).text.splitlines()
    assert txt == [
        "0:00:00  Artista Uno - Primer Tema (Extended Mix)",  # ACRCloud y Shazam coinciden en el tema
        "0:01:00  Artista Dos, Invitada - Segundo Tema",
        "0:02:20  Artista Tres - Tema Del Hueco",            # Shazam rellena donde ACRCloud solo vio un mix ajeno
        "0:03:32  ID - ID",                                  # hueco de más de 60 s
        "0:05:00  Artista Cuatro - Ultimo Tema (Original Mix)",
    ]
    assert not any("Transicion" in line or "DJ Set" in line for line in txt)  # débiles y mixes ajenos fuera
    rows = list(csv.DictReader(io.StringIO(
        (await client.get(f"/api/tools/jobs/{job.id}/files/tracklist.csv", headers=h)).content.decode("utf-8-sig"))))
    assert [r["source"] for r in rows] == ["acrcloud+shazam", "acrcloud", "shazam", "", "acrcloud"]
    assert rows[3]["note"].startswith("aparece en: Otro DJ")

    # limpieza: el audio subido y la carpeta de trabajo ya no existen; los resultados sí
    root = svc.job_dir(job.id)
    assert not (root / "input").exists() and not (root / "work").exists()
    assert sorted(p.name for p in (root / "results").iterdir()) == ["tracklist.csv", "tracklist.txt"]
    assert not list(svc.data_dir().rglob("*.wav")) and not list(svc.data_dir().rglob("*.mp3"))
    assert job.expires_at is not None

    # aviso por email con el enlace al trabajo
    msg = email.outbox[-1]
    assert msg["To"] == "dj@example.com" and "está listo" in msg["Subject"]
    assert f"http://test/herramientas/trabajos/{job.id}" in msg.get_content()


async def test_acrcloud_down_falls_back_to_shazam(client, set_wav, monkeypatch):
    monkeypatch.setenv("FAKE_ACR_FAIL", "1")
    access = await signup(client)
    await upload(client, access, set_wav, "tracklist")
    job = await run_next()
    assert job.status == "done", job.error
    summary = job.result["summary"]
    assert summary["sources"] == ["shazam"]
    assert summary["notes"] == ["ACRCloud no estuvo disponible: se usó solo Shazam."]
    txt = (svc.results_dir(job.id) / "tracklist.txt").read_text(encoding="utf-8")
    assert "Artista Uno - PRIMER TEMA" in txt and "Segundo Tema" not in txt  # solo lo que oyó Shazam


async def test_shazam_time_cap(client, set_wav, monkeypatch):
    """Shazam es relleno opcional: si se pasa de su tope se corta y se usa lo escaneado hasta ahí."""
    monkeypatch.setenv("FAKE_SHAZAM_SLOW", "1")
    monkeypatch.setattr(get_settings(), "shazam_max_seconds", 3)
    access = await signup(client)
    await upload(client, access, set_wav, "tracklist")
    job = await run_next()
    assert job.status == "done", job.error
    assert job.result["summary"]["notes"] == ["Shazam se cortó por tiempo: los huecos se completaron solo en parte."]
    txt = (svc.results_dir(job.id) / "tracklist.txt").read_text(encoding="utf-8")
    assert "Artista Dos, Invitada - Segundo Tema" in txt  # la base de ACRCloud está completa


async def test_no_engine_available_fails_with_clear_message(client, set_wav, monkeypatch):
    monkeypatch.setenv("FAKE_ACR_FAIL", "1")
    monkeypatch.setenv("FAKE_SHAZAM_FAIL", "1")
    access = await signup(client)
    queued = await upload(client, access, set_wav, "tracklist")
    job = await run_next()
    assert job.status == "failed"
    assert job.message == "Los servicios de reconocimiento no respondieron. Intenta de nuevo más tarde."
    assert "429 simulado" in job.error                       # el detalle queda para nosotros…
    detail = (await client.get(f"/api/tools/jobs/{queued['id']}", headers=bearer(access))).json()
    assert "429" not in str(detail) and detail["files"] == []  # …y no sale por la API
    assert not (svc.job_dir(job.id) / "input").exists()        # también se limpia cuando falla
    assert "no pudimos terminar" in email.outbox[-1]["Subject"]
    # el usuario puede volver a intentarlo: un trabajo fallido no cuenta como activo
    again = await upload(client, access, set_wav, "tracklist")
    assert again["status"] == "queued"


async def test_unexpected_error_does_not_kill_the_worker(client, set_wav, monkeypatch):
    access = await signup(client)
    first = await upload(client, access, set_wav, "tracklist")

    async def boom(job):
        raise RuntimeError("explotó algo interno")

    monkeypatch.setitem(main.HANDLERS, "tracklist", boom)
    job = await run_next()
    assert job.status == "failed" and "error inesperado" in job.message
    assert "RuntimeError: explotó algo interno" in job.error and "explotó" not in job.message
    monkeypatch.undo()
    # el siguiente trabajo se procesa con normalidad
    async with SessionLocal() as db:
        assert (await db.get(ToolJob, uuid.UUID(first["id"]))).status == "failed"
