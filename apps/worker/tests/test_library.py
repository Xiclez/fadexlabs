"""DJ Library Upgrader de punta a punta: .zip por la API → worker con slskd y rclone simulados → Drive.

La librería de prueba tiene cuatro pistas:
    House/Pista A.mp3     MP3 128 de la canción A. En Soulseek hay un FLAC real de A        → se entrega en AIFF
    Pista B.mp3           MP3 128 de B. Lo único que hay con ese nombre es OTRA canción     → no se entrega
    Pista C.mp3           MP3 128 de C. Solo existe un "FLAC" hecho desde un MP3 (falso)    → se entrega marcado, sin convertir
    Lossless/Ya.flac      ya está sin pérdida                                                → no se busca
"""
import csv
import io
import zipfile

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.db import SessionLocal
from app.models import ToolJob
from app.services import email
from app.services import tools as svc
from tests.conftest import FAKES, PY, bearer, ffmpeg, signup, upload
from tests.fakes.slskd import FakeSlskd
from worker import jobs, library, main


def song(path, melody, drums, seconds=60):
    """'Canción' sintética con estructura (igual que en las pruebas del upgrader): melodía + percusión."""
    ffmpeg("-f", "lavfi", "-i",
           f"aevalsrc='0.35*sin(2*PI*t*(196*pow(2,mod(floor(t*2)*{melody},12)/12)))"
           f"+0.25*sin(2*PI*t*(98*pow(2,mod(floor(t/2)*({melody}+3),7)/12)))':s=44100:d={seconds}",
           "-f", "lavfi", "-i", f"anoisesrc=color=white:seed={drums}:duration={seconds}:sample_rate=44100:amplitude=0.6",
           "-filter_complex",
           f"[1:a]volume='if(lt(mod(t*{2 + drums % 3},1),0.12),1,0.05)':eval=frame,highpass=f=2000[d];"
           "[0:a][d]amix=inputs=2:normalize=0", "-ac", "2", path)


@pytest.fixture(scope="session")
def audio(tmp_path_factory):
    d = tmp_path_factory.mktemp("lib")
    for name, melody, drums in (("A", 7, 11), ("B", 5, 23), ("C", 3, 31), ("D", 9, 47)):
        song(d / f"{name}.wav", melody, drums)
    tags = {"A": ("Artista Uno", "Tema Bueno"), "B": ("Otro Artista", "Otra Cancion"), "C": ("Grupo Tres", "Tercera Rola")}
    for name, (artist, title) in tags.items():
        ffmpeg("-i", d / f"{name}.wav", "-c:a", "libmp3lame", "-b:a", "128k", "-id3v2_version", "3",
               "-metadata", f"artist={artist}", "-metadata", f"title={title}", d / f"lib_{name}.mp3")
    ffmpeg("-i", d / "A.wav", "-c:a", "flac", d / "real_A.flac")        # la misma grabación, sin pérdida
    ffmpeg("-i", d / "D.wav", "-c:a", "flac", d / "otra_D.flac")        # otra canción con el nombre de B
    ffmpeg("-i", d / "lib_C.mp3", "-c:a", "flac", d / "falso_C.flac")   # falso lossless: FLAC desde un MP3
    zp = d / "Mi Libreria.zip"
    with zipfile.ZipFile(zp, "w") as z:
        z.write(d / "lib_A.mp3", "House/Pista A.mp3")
        z.write(d / "lib_B.mp3", "Pista B.mp3")
        z.write(d / "lib_C.mp3", "Pista C.mp3")
        z.write(d / "real_A.flac", "Lossless/Ya.flac")
        z.writestr("notas.txt", "no es audio")
        z.writestr("../fuera.mp3", b"x")  # zip slip: la extracción segura lo ignora
    return d, zp


@pytest.fixture
def slskd(monkeypatch, tmp_path, audio):
    d, _ = audio
    s = get_settings()
    fake = FakeSlskd(library.downloads_dir())
    flac = {"sampleRate": 44100, "bitDepth": 16, "bitRate": 900}
    fake.offer("tema bueno", "u_real", "Music\\Artista Uno\\Artista Uno - Tema Bueno.flac", d / "real_A.flac", 60, **flac)
    fake.offer("otra cancion", "u_otra", "Music\\Otro Artista\\Otro Artista - Otra Cancion.flac", d / "otra_D.flac", 60, **flac)
    fake.offer("tercera rola", "u_falso", "Music\\Grupo Tres\\Grupo Tres - Tercera Rola.flac", d / "falso_C.flac", 60, **flac)
    monkeypatch.setattr(s, "slskd_url", fake.url)
    monkeypatch.setattr(s, "slskd_api_key", fake.api_key)
    monkeypatch.setattr(s, "rclone_bin", f'"{PY}" "{FAKES / "rclone.py"}"')
    monkeypatch.setattr(s, "rclone_remote", "gdrive:FADEX/Entregas")
    monkeypatch.setenv("FAKE_RCLONE_DIR", str(tmp_path / "drive"))
    fake.drive = tmp_path / "drive"
    yield fake
    fake.close()


async def run_next():
    job = await jobs.claim("library_upgrade")
    assert job is not None
    await main.process(job)
    async with SessionLocal() as db:
        return (await db.execute(select(ToolJob).where(ToolJob.id == job.id))).scalar_one()


async def test_library_upgrade_end_to_end(client, audio, slskd):
    _, zp = audio
    access = await signup(client)
    queued = await upload(client, access, zp, "library_upgrade", formato="aiff", accept_rights=True)
    assert queued["status"] == "queued" and queued["options"] == {"formato": "aiff"}
    job = await run_next()
    assert job.status == "done", (job.message, job.error)

    h = bearer(access)
    detail = (await client.get(f"/api/tools/jobs/{job.id}", headers=h)).json()
    summary = detail["summary"]
    assert summary["in_library"] == 4 and summary["to_upgrade"] == 3 and summary["format"] == "aiff"
    assert summary["delivered"] == 2 and summary["converted"] == 1
    assert summary["fake_lossless"] == 1 and summary["not_found"] == 1 and summary["delivery"] == "drive"
    assert summary["by_format"] == {"AIFF": 1, "FLAC": 1}
    assert detail["message"] == "2 de 3 pistas mejoradas"
    assert detail["files"] == ["informe.csv", "no_encontradas.txt", "revision.csv"]

    # la entrega llegó a Drive: respeta nombre y subcarpeta del original, en el formato pedido
    folder = detail["drive_url"].rsplit("/", 1)[-1]
    assert detail["drive_url"].startswith("https://drive.google.com/") and folder.endswith(f"-DJ-Prueba-{str(job.id)[:8]}")
    drive = slskd.drive / "gdrive" / "FADEX" / "Entregas" / folder
    delivered = sorted(p.relative_to(drive).as_posix() for p in drive.rglob("*") if p.is_file())
    assert delivered == ["House/Pista A.aiff", "Pista C.flac", "_informe.csv", "_no_encontradas.txt"]

    informe = {r["pedido"]: r for r in csv.DictReader(io.StringIO(
        (await client.get(f"/api/tools/jobs/{job.id}/files/informe.csv", headers=h)).content.decode("utf-8-sig")))}
    a, c = informe["House/Pista A.mp3"], informe["Pista C.mp3"]
    assert a["archivo"] == "House/Pista A.aiff" and a["conversion"] == "sí" and a["autenticidad"] == "real"
    assert "(misma)" in a["coincidencia"] and a["formato_entregado"].startswith("AIFF")
    assert c["archivo"] == "Pista C.flac" and c["autenticidad"] == "FALSO" and c["conversion"] == "no (evitada)"
    # B: lo que había con ese nombre era otra canción → nunca se entrega
    assert "Pista B.mp3" not in informe or not informe["Pista B.mp3"]["archivo"]
    missing = (await client.get(f"/api/tools/jobs/{job.id}/files/no_encontradas.txt", headers=h)).text
    assert "Pista B.mp3" in missing and "Pista A" not in missing
    revision = (await client.get(f"/api/tools/jobs/{job.id}/files/revision.csv", headers=h)).content.decode("utf-8-sig")
    assert "ya está sin pérdida" in revision and "fuera.mp3" not in revision

    # limpieza: ni el zip, ni la librería extraída, ni las descargas de slskd, ni la entrega local
    root = svc.job_dir(job.id)
    assert sorted(p.name for p in root.iterdir()) == ["results", "state.json"]
    assert not [p for p in library.downloads_dir().rglob("*") if p.is_file()]
    assert not list(svc.data_dir().rglob("*.zip")) and not list(svc.data_dir().rglob("*.mp3"))
    assert len(slskd.transfers) == 3  # se bajó una por pista; ninguna de más

    msg = email.outbox[-1]
    assert "DJ Library Upgrader" in msg["Subject"] and f"/herramientas/trabajos/{job.id}" in msg.get_content()


async def test_drive_failure_keeps_delivery_for_manual_upload(client, audio, slskd, monkeypatch):
    _, zp = audio
    monkeypatch.setenv("FAKE_RCLONE_FAIL", "1")

    async def no_wait(_):
        return None
    monkeypatch.setattr(library.asyncio, "sleep", no_wait)  # sin esperar entre reintentos de rclone
    access = await signup(client)
    await upload(client, access, zp, "library_upgrade", formato="flac", accept_rights=True)
    job = await run_next()
    assert job.status == "done", job.error               # horas de descarga no se tiran por un fallo de Drive
    assert job.result["drive_url"] is None and job.result["summary"]["delivery"] == "pending"
    assert "preparando tu enlace" in job.message
    entrega = svc.job_dir(job.id) / "entrega"
    assert (entrega / "House" / "Pista A.flac").exists()   # pedido FLAC y encontrado FLAC: sin convertir
    assert not [p for p in library.downloads_dir().rglob("*") if p.is_file()]


async def test_soulseek_unavailable_fails_cleanly(client, audio, slskd):
    _, zp = audio
    slskd.logged_in = False
    get_settings()  # (el upgrader espera hasta 180 s a que slskd conecte; aquí la API falsa responde 401)
    slskd.api_key = "otra"
    access = await signup(client)
    await upload(client, access, zp, "library_upgrade", accept_rights=True)
    job = await run_next()
    assert job.status == "failed"
    assert job.message == "No pudimos conectar con la red de descargas. Intenta de nuevo más tarde."
    assert "401" in job.error
    assert not (svc.job_dir(job.id) / "input").exists() and not (svc.job_dir(job.id) / "work").exists()


async def test_time_cap_delivers_what_was_downloaded(client, audio, slskd, monkeypatch):
    """Una descarga que nunca arranca no bloquea la librería: al llegar al tope se entrega lo conseguido."""
    d, zp = audio
    slskd.catalog = [c for c in slskd.catalog if c["username"] != "u_falso"]
    slskd.offer("tercera rola", "u_ausente", "Music\\Grupo Tres\\Grupo Tres - Tercera Rola.flac", d / "falso_C.flac", 60,
                stuck=True, sampleRate=44100, bitDepth=16, bitRate=900)
    monkeypatch.setattr(get_settings(), "upgrade_max_hours", 25 / 3600)
    access = await signup(client)
    await upload(client, access, zp, "library_upgrade", formato="aiff", accept_rights=True)
    job = await run_next()
    assert job.status == "done", (job.message, job.error)
    summary = job.result["summary"]
    assert summary["delivered"] == 1 and summary["unfinished"] == 1 and summary["delivery"] == "drive"
    assert "tiempo máximo" in summary["notes"][0]
    stuck = next(t for t in slskd.transfers if t["username"] == "u_ausente")
    assert slskd.cancelled == [stuck["id"]]  # lo que quedó encolado en slskd se cancela


async def test_nothing_to_upgrade(client, audio, slskd, tmp_path):
    d, _ = audio
    zp = tmp_path / "ya-buena.zip"
    with zipfile.ZipFile(zp, "w") as z:
        z.write(d / "real_A.flac", "Ya.flac")
    access = await signup(client)
    await upload(client, access, zp, "library_upgrade", accept_rights=True)
    job = await run_next()
    assert job.status == "done" and "no hay nada que mejorar" in job.message
    assert job.result["files"] == ["revision.csv"] and job.result["summary"]["to_upgrade"] == 0
    assert slskd.searches == {}  # ni siquiera se buscó
