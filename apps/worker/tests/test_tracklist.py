"""Tracklist ID de punta a punta: subida por la API → worker (ACRCloud y Shazam simulados) → descarga."""
import csv
import io
import json
import os
import subprocess
import sys
import uuid

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.db import SessionLocal
from app.models import ToolJob
from app.services import email
from app.services import tools as svc
from tests.conftest import FAKES, bearer, ffmpeg, signup, upload
from worker import jobs, main, proc
from worker.tracklist import confidence, level


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
    # ACRCloud y AudD son los motores; Shazam (reserva) no corre porque los dos terminaron
    assert detail["summary"]["sources"] == ["acrcloud", "audd"] and detail["summary"]["notes"] == []
    assert detail["summary"]["tracks"] == 4 and detail["summary"]["unidentified"] == 1
    assert detail["summary"]["coverage"] == 100
    assert detail["message"] == "4 temas identificados, 1 tramo sin identificar"
    assert not (svc.job_dir(job.id) / "work" / "raw.jsonl").exists()

    txt = (await client.get(f"/api/tools/jobs/{job.id}/files/tracklist.txt", headers=h)).text.splitlines()
    assert txt == [
        "0:00:00  Artista Uno - Primer Tema (Extended Mix)",  # ACRCloud y AudD coinciden en el tema
        "0:01:00  Artista Dos, Invitada - Segundo Tema",
        "0:02:24  Artista Tres - Tema Del Hueco",            # AudD rellena donde ACRCloud solo vio un mix ajeno
        "0:03:48  ID - ID",                                  # hueco de más de 60 s
        "0:05:00  Artista Cuatro - Ultimo Tema (Original Mix)",
    ]
    assert not any("Transicion" in line or "DJ Set" in line for line in txt)  # débiles y mixes ajenos fuera
    rows = list(csv.DictReader(io.StringIO(
        (await client.get(f"/api/tools/jobs/{job.id}/files/tracklist.csv", headers=h)).content.decode("utf-8-sig"))))
    assert [r["source"] for r in rows] == ["acrcloud+audd", "acrcloud", "audd", "", "acrcloud"]
    assert rows[3]["note"].startswith("aparece en: Otro DJ")
    # cada coincidencia va puntuada; los tramos ID - ID no
    assert [(r["confianza"], r["nivel"]) for r in rows] == [
        ("100", "alta"), ("85", "alta"), ("95", "alta"), ("", ""), ("100", "alta")]
    assert detail["summary"]["confidence"] == {"alta": 4, "media": 0, "baja": 0}

    # limpieza: el audio subido y la carpeta de trabajo ya no existen; los resultados sí
    root = svc.job_dir(job.id)
    assert not (root / "input").exists() and not (root / "work").exists()
    assert sorted(p.name for p in (root / "results").iterdir()) == ["tracklist.csv", "tracklist.txt", "visual.json"]

    # vista estilo SoundCloud: forma de onda del set + tramos con metadatos y enlaces
    assert detail["visual"] is True and detail["stopped"] is False
    view = (await client.get(f"/api/tools/jobs/{job.id}/visual", headers=h)).json()
    assert view["duration"] == pytest.approx(360, abs=1)
    assert 1000 <= len(view["peaks"]) <= 1200 and max(view["peaks"]) == 100 and min(view["peaks"]) >= 0
    t = view["tracks"]
    assert [(x["n"], x["start"]) for x in t] == [(1, 0), (2, 60), (3, 144), (4, 228), (5, 300)]
    assert [x["end"] for x in t] == [60, 144, 228, 300, pytest.approx(360, abs=1)]
    first, hueco, unknown = t[0], t[2], t[3]
    assert first["links"]["spotify"] == "https://open.spotify.com/track/SPOTIFY1"      # id directo de ACRCloud
    assert first["links"]["youtube"] == "https://www.youtube.com/watch?v=YTVID1"
    assert first["links"]["deezer"] == "https://www.deezer.com/track/123"
    assert first["meta"]["label"] == "Sello" and first["meta"]["year"] == "2024" and first["meta"]["genre"] == "House"
    assert first["confidence"] == 100 and first["level"] == "alta"
    assert hueco["links"]["youtube"].startswith("https://www.youtube.com/results?search_query=Artista+Tres+Tema+Del+Hueco")
    assert "shazam" not in hueco["links"]                                                # Shazam no corrió
    assert hueco["meta"] == {"album": "Disco Hueco", "label": "Sello Tres", "year": "2025",  # metadatos de AudD
                             "isrc": "MX0000000001"}
    assert unknown["unidentified"] and unknown["links"] == {} and unknown["note"].startswith("aparece en")
    assert not list(svc.data_dir().rglob("*.wav")) and not list(svc.data_dir().rglob("*.mp3"))
    assert job.expires_at is not None

    # aviso por email con el enlace al trabajo
    msg = email.outbox[-1]
    assert msg["To"] == "dj@example.com" and "está listo" in msg["Subject"]
    assert f"http://test/herramientas/trabajos/{job.id}" in msg.get_content()


async def test_acrcloud_down_audd_carries_the_set(client, set_wav, monkeypatch):
    """Sin ACRCloud, AudD solo cubre el set completo: Shazam sigue sin hacer falta."""
    monkeypatch.setenv("FAKE_ACR_FAIL", "1")
    access = await signup(client)
    await upload(client, access, set_wav, "tracklist")
    job = await run_next()
    assert job.status == "done", job.error
    summary = job.result["summary"]
    assert summary["sources"] == ["audd"] and summary["coverage"] == 100
    assert summary["notes"] == ["ACRCloud no estuvo disponible."]
    txt = (svc.results_dir(job.id) / "tracklist.txt").read_text(encoding="utf-8")
    assert "Artista Uno - Primer Tema" in txt and "Artista Tres - Tema Del Hueco" in txt
    assert "Segundo Tema" not in txt  # solo lo que oyó AudD


async def test_primary_engines_down_fall_back_to_shazam(client, set_wav, monkeypatch, caplog):
    """Shazam es la reserva: solo corre si ni ACRCloud ni AudD terminaron."""
    monkeypatch.setenv("FAKE_ACR_FAIL", "1")
    monkeypatch.setenv("FAKE_AUDD_FAIL", "1")
    access = await signup(client)
    await upload(client, access, set_wav, "tracklist")
    job = await run_next()
    assert job.status == "done", job.error
    summary = job.result["summary"]
    assert summary["sources"] == ["shazam"]
    assert summary["notes"] == ["ACRCloud no estuvo disponible.", "AudD no estuvo disponible.",
                                "Se usó Shazam como reserva."]
    txt = (svc.results_dir(job.id) / "tracklist.txt").read_text(encoding="utf-8")
    assert "Artista Uno - PRIMER TEMA" in txt and "Segundo Tema" not in txt  # solo lo que oyó Shazam
    logged = "\n".join(r.getMessage() for r in caplog.records if r.name == "fadex.worker.tracklist")
    assert "AudD no disponible" in logged and "error 900" in logged


async def test_audd_cut_midway_is_used_with_shazam(client, set_wav, monkeypatch):
    """AudD se cae a la mitad: se usa lo que alcanzó y Shazam (reserva) completa el resto."""
    monkeypatch.setenv("FAKE_ACR_FAIL", "1")
    monkeypatch.setenv("FAKE_AUDD_PARTIAL", "1")
    access = await signup(client)
    await upload(client, access, set_wav, "tracklist")
    job = await run_next()
    assert job.status == "done", job.error
    summary = job.result["summary"]
    assert summary["sources"] == ["audd", "shazam"] and summary["coverage"] == 100
    assert summary["notes"] == ["ACRCloud no estuvo disponible.", "AudD se interrumpió (alcanzó a revisar 50% del set).",
                                "Se usó Shazam como reserva."]
    rows = list(csv.DictReader(io.StringIO((svc.results_dir(job.id) / "tracklist.csv").read_text(encoding="utf-8-sig"))))
    assert rows[0]["source"] == "audd+shazam" and rows[0]["confianza"] == "95"  # dos motores de acuerdo: +10


async def test_shazam_time_cap(client, set_wav, monkeypatch):
    """Shazam como reserva tiene tope de tiempo: se corta y se usa lo escaneado hasta ahí."""
    monkeypatch.setenv("FAKE_ACR_FAIL", "1")
    monkeypatch.setenv("FAKE_AUDD_FAIL", "1")
    monkeypatch.setenv("FAKE_SHAZAM_SLOW", "1")
    monkeypatch.setattr(get_settings(), "shazam_max_seconds", 3)
    access = await signup(client)
    await upload(client, access, set_wav, "tracklist")
    job = await run_next()
    assert job.status == "done", job.error
    assert job.result["summary"]["notes"][-1] == "Shazam se cortó por tiempo (alcanzó a revisar 56% del set)."
    assert job.result["summary"]["coverage"] == 56 and "incomplete" not in job.result["summary"]


async def test_shazam_saturated_marks_result_incomplete(client, set_wav, monkeypatch, caplog):
    """Si los motores principales fallan y Shazam se satura, se entrega lo poco reconocido, marcado incompleto."""
    monkeypatch.setenv("FAKE_SHAZAM_SATURATED", "1")
    monkeypatch.setenv("FAKE_ACR_FAIL", "1")
    monkeypatch.setenv("FAKE_AUDD_FAIL", "1")
    access = await signup(client)
    sent = []

    async def capture(to, subject, body, **kw):
        sent.append(subject)

    monkeypatch.setattr(email, "send", capture)
    await upload(client, access, set_wav, "tracklist")
    job = await run_next()
    assert job.status == "done", job.error
    summary = job.result["summary"]
    assert summary["sources"] == ["shazam"] and len(summary["notes"]) == 4
    assert summary["notes"][-1] == "Shazam rechazó peticiones por saturación y se detuvo (alcanzó a revisar 22% del set)."
    assert summary["coverage"] == 22 and summary["incomplete"] is True
    assert job.message.startswith("Incompleto · solo pudimos revisar el 22% del set (1 tema identificado")
    assert sent == ["Tracklist ID: resultado incompleto · FADEX Labs"]
    # el motivo de cada motor queda en el log del worker (work/ se borra al terminar)
    logged = "\n".join(r.getMessage() for r in caplog.records if r.name == "fadex.worker.tracklist")
    assert "ACRCloud no disponible" in logged and "HTTP 503: simulado" in logged
    assert "Shazam saturado" in logged
    assert "Artista Uno - PRIMER TEMA" in (svc.results_dir(job.id) / "tracklist.txt").read_text(encoding="utf-8")


def test_scan_stops_fast_when_shazam_rejects(set_wav, tmp_path):
    """El scan.py real: tras 4 fragmentos rechazados seguidos termina con código 3, sin esperas largas."""
    out = tmp_path / "raw.jsonl"
    stub = FAKES / "shazamio_stub"
    r = subprocess.run([sys.executable, str(proc.services_dir() / "tracklist" / "scan.py"), str(set_wav), str(out),
                        "--pause", "0", "--backoff", "0", "--max-fail-streak", "4"],
                       env={**os.environ, "PYTHONPATH": str(stub), "STUB_SHAZAM_OK": "3"},
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 3, r.stdout + r.stderr
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert [bool(x["response"].get("track")) for x in rows] == [True] * 3 + [False] * 4  # 18 fragmentos: paró en el 7
    assert "se da por saturado" in r.stdout


def test_scan_pauses_and_retries_when_shazam_blocks(set_wav, tmp_path):
    """El scan.py real con pausas: si Shazam bloquea un rato, espera y reintenta esos mismos fragmentos."""
    out = tmp_path / "raw.jsonl"
    stub = FAKES / "shazamio_stub"
    # reconoce 3, rechaza las 8 consultas siguientes (4 fragmentos × 2 intentos) y vuelve a responder
    r = subprocess.run([sys.executable, str(proc.services_dir() / "tracklist" / "scan.py"), str(set_wav), str(out),
                        "--pause", "0", "--backoff", "0", "--max-fail-streak", "4",
                        "--cooldown", "0", "--max-cooldowns", "2"],
                       env={**os.environ, "PYTHONPATH": str(stub), "STUB_SHAZAM_OK": "3", "STUB_SHAZAM_BLOCKED": "8"},
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert [x["t"] for x in rows] == list(range(0, 360 - 12 + 1, 20))   # los 18 fragmentos, sin huecos ni repetidos
    assert all(x["response"].get("track") for x in rows)               # los bloqueados se reintentaron con éxito
    assert "pausa 0s (1 de 2) y reintento" in r.stdout


@pytest.fixture
def audd_server():
    """AudD de mentira en localhost: responde cada parte con un tema reconocido a los 24 s de esa parte."""
    import http.server
    import threading

    calls = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            calls.append(body)
            if b"token-malo" in body:
                out = {"status": "error", "error": {"error_code": 900, "error_message": "Invalid api_token"}}
            else:
                out = {"status": "success", "result": [
                    {"offset": "00:00", "songs": []},
                    {"offset": "00:24", "songs": [{"artist": "Artista", "title": f"Tema {len(calls)}", "score": 90}]}]}
            data = json.dumps(out).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/", calls
    srv.shutdown()


def test_audd_scan_real_script(set_wav, tmp_path, audd_server):
    """El audd_scan.py real: parte el set, pasa los offsets al tiempo del set, reanuda y corta con token inválido."""
    url, calls = audd_server
    out = tmp_path / "audd_raw.json"
    script = [sys.executable, str(proc.services_dir() / "tracklist" / "audd_scan.py"), str(set_wav), str(out),
              "--piece", "130", "--every", "1", "--skip", "1"]
    env = {**os.environ, "AUDD_API_URL": url, "AUDD_API_TOKEN": "token-bueno"}
    r = subprocess.run(script, env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    doc = json.loads(out.read_text(encoding="utf-8"))
    # partes de 120 s (130 redondeado a la rejilla de 24 s): 0, 120, 240 → el tema de cada una a los +24 s
    assert (doc["step"], doc["pieces"], doc["pieces_done"]) == (24, 3, 3)
    assert [(x["t"], x["songs"][0]["title"]) for x in doc["results"]] == [(24, "Tema 1"), (144, "Tema 2"), (264, "Tema 3")]
    assert all(b'name="skip"\r\n\r\n1' in c and b"token-bueno" in c for c in calls)

    # reanuda: con todo consultado no vuelve a gastar peticiones
    subprocess.run(script, env=env, capture_output=True, text=True, timeout=120, check=True)
    assert len(calls) == 3

    # token inválido: termina con código 2 sin reintentar
    out.unlink()
    r = subprocess.run(script, env={**env, "AUDD_API_TOKEN": "token-malo"}, capture_output=True, text=True, timeout=120)
    assert r.returncode == 2 and "AudD error 900" in r.stdout and len(calls) == 4


def test_confidence_scale():
    assert confidence("", "") is None                                   # ID - ID
    assert (confidence("acrcloud", "60"), confidence("acrcloud", "100")) == (60, 100)
    assert confidence("acrcloud+shazam", "90") == 100                   # dos motores de acuerdo: +15
    assert confidence("acrcloud+audd+shazam", "90") == 100
    assert [confidence("shazam", str(h)) for h in (2, 3, 4, 9)] == [70, 85, 95, 95]
    assert [confidence("audd", str(h)) for h in (2, 3)] == [70, 85]     # AudD se puntúa igual: por tramos
    assert (confidence("audd+shazam", "2"), confidence("audd+shazam", "9")) == (80, 100)  # confirmado: +10
    assert [level(c) for c in (100, 85, 84, 60, 59)] == ["alta", "alta", "media", "media", "baja"]


async def test_no_engine_available_fails_with_clear_message(client, set_wav, monkeypatch):
    monkeypatch.setenv("FAKE_ACR_FAIL", "1")
    monkeypatch.setenv("FAKE_AUDD_FAIL", "1")
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


async def test_stop_builds_tracklist_with_what_was_recognized(client, set_wav, monkeypatch):
    """Detener a media corrida: ACRCloud ya terminó y AudD se corta; se entrega lo reconocido hasta ahí."""
    monkeypatch.setenv("FAKE_AUDD_SLOW", "1")
    access = await signup(client)
    queued = await upload(client, access, set_wav, "tracklist")
    work = svc.job_dir(uuid.UUID(queued["id"])) / "work"

    async def stop_after_acr(job_id):  # el usuario pulsa "Detener" mientras AudD sigue consultando
        return (work / "acr_raw.json").exists()

    monkeypatch.setattr(jobs, "stop_requested", stop_after_acr)
    job = await run_next()
    assert job.status == "done", (job.message, job.error)
    summary = job.result["summary"]
    assert summary["stopped"] is True and summary["sources"] == ["acrcloud", "audd"]
    assert summary["notes"] == ["Lo detuviste: el tracklist se armó con lo reconocido hasta ese momento.",
                                "AudD alcanzó a revisar 50% del set antes de que lo detuvieras."]
    assert not (work / "raw.jsonl").exists()  # al detener no se recurre a Shazam
    assert job.message.startswith("Detenido · ") and job.result["visual"] is True
    assert "Artista Tres - Tema Del Hueco" in (svc.results_dir(job.id) / "tracklist.txt").read_text(encoding="utf-8")


async def test_stop_with_only_shazam_partial(client, set_wav, monkeypatch):
    """Motores principales caídos y el usuario detiene: se entrega lo que Shazam (reserva) alcanzó a reconocer."""
    async def always(job_id):
        return True

    monkeypatch.setenv("FAKE_ACR_FAIL", "1")
    monkeypatch.setenv("FAKE_AUDD_FAIL", "1")
    monkeypatch.setenv("FAKE_SHAZAM_SLOW", "1")
    monkeypatch.setattr(jobs, "stop_requested", always)
    access = await signup(client)
    await upload(client, access, set_wav, "tracklist")
    job = await run_next()
    assert job.status == "done", (job.message, job.error)
    summary = job.result["summary"]
    assert summary["stopped"] is True and summary["sources"] == ["shazam"]
    assert summary["notes"][:4] == ["Lo detuviste: el tracklist se armó con lo reconocido hasta ese momento.",
                                    "ACRCloud no estuvo disponible.", "AudD no estuvo disponible.",
                                    "Se usó Shazam como reserva."]
    assert job.message.startswith("Detenido · ")
