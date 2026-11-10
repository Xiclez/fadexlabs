import io
import subprocess
import sys
import uuid
import zipfile

import pytest
from sqlalchemy import select, update

from app.db import SessionLocal
from app.models import ToolJob, User
from app.services import tools as svc
from tests.test_profile_beta import bearer, signup

CHUNK = 65536  # FADEX_UPLOAD_CHUNK_BYTES en conftest


@pytest.fixture(scope="session")
def set_mp3(tmp_path_factory) -> bytes:
    """Un 'set' corto de verdad (ffprobe lo valida por contenido)."""
    path = tmp_path_factory.mktemp("audio") / "set.mp3"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "anoisesrc=duration=12:color=pink",
                    "-c:a", "libmp3lame", "-b:a", "128k", str(path)], check=True)
    return path.read_bytes()


def library_zip(names=("House/Pista A.mp3", "Pista B.flac"), extra=()) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n in names:
            z.writestr(n, b"\x00" * 2048)
        for n in extra:
            z.writestr(n, b"x")
    return buf.getvalue()


def parts(data: bytes):
    return [data[i:i + CHUNK] for i in range(0, len(data), CHUNK)]


async def upload(client, access, data: bytes, filename="set.mp3", tool="tracklist", complete=True, **extra):
    h = bearer(access)
    r = await client.post("/api/tools/uploads", headers=h,
                          json={"tool": tool, "filename": filename, "size": len(data), **extra})
    assert r.status_code == 200, r.text
    up = r.json()
    for i, piece in enumerate(parts(data)):
        r = await client.put(f"/api/tools/uploads/{up['upload_id']}/chunks/{i}", headers=h, content=piece)
        assert r.status_code == 200, r.text
    if not complete:
        return up
    return await client.post(f"/api/tools/uploads/{up['upload_id']}/complete", headers=h)


async def set_role(email: str, role: str):
    async with SessionLocal() as db:
        await db.execute(update(User).where(User.email == email).values(role=role))
        await db.commit()


async def finish(job_id: str, files=("tracklist.txt", "tracklist.csv")):
    """Simula al worker: deja el trabajo terminado con sus resultados en disco."""
    out = svc.results_dir(uuid.UUID(job_id))
    out.mkdir(parents=True, exist_ok=True)
    for name in files:
        (out / name).write_text(f"contenido de {name}\n", encoding="utf-8")
    (out / "secreto.txt").write_text("no descargable", encoding="utf-8")
    async with SessionLocal() as db:
        await db.execute(update(ToolJob).where(ToolJob.id == uuid.UUID(job_id)).values(
            status="done", progress=100, result={"summary": {"tracks": 3}, "files": list(files)}, error="detalle interno"))
        await db.commit()


# ---------- acceso ----------

async def test_only_beta_members_with_verified_email(client):
    a1, _ = await signup(client, "uno@example.com")
    await signup(client, "dos@example.com")
    a3, _ = await signup(client, "tres@example.com")  # solo hay 2 lugares
    assert (await client.get("/api/tools", headers=bearer(a1))).status_code == 200
    for method, url in (("get", "/api/tools"), ("get", "/api/tools/jobs"), ("post", "/api/tools/uploads")):
        r = await getattr(client, method)(url, headers=bearer(a3))
        assert r.status_code == 403 and "beta cerrada" in r.text
    assert (await client.get("/api/tools/jobs")).status_code == 401

    # un admin sin lugar entra, pero no sin confirmar su email
    a4, _ = await signup(client, "admin@example.com", verify=False)
    await set_role("admin@example.com", "admin")
    r = await client.get("/api/tools", headers=bearer(a4))
    assert r.status_code == 403 and "Confirma tu email" in r.text


async def test_jobs_are_private_404_between_users(client, set_mp3):
    a1, _ = await signup(client, "uno@example.com")
    a2, _ = await signup(client, "dos@example.com")
    job = (await upload(client, a1, set_mp3)).json()
    await finish(job["id"])
    assert (await client.get(f"/api/tools/jobs/{job['id']}", headers=bearer(a1))).status_code == 200
    for url in (f"/api/tools/jobs/{job['id']}", f"/api/tools/jobs/{job['id']}/files/tracklist.txt",
                f"/api/tools/uploads/{job['id']}"):
        assert (await client.get(url, headers=bearer(a2))).status_code == 404  # 404, no 403
    assert (await client.get("/api/tools/jobs", headers=bearer(a2))).json() == {"items": [], "total": 0}
    r = await client.put(f"/api/tools/uploads/{job['id']}/chunks/0", headers=bearer(a2), content=b"x")
    assert r.status_code == 404


# ---------- subida por partes ----------

async def test_chunked_upload_happy_path(client, set_mp3):
    access, _ = await signup(client, "uno@example.com")
    assert len(set_mp3) > 2 * CHUNK  # de verdad son varias partes
    r = await upload(client, access, set_mp3, filename="C:\\sets\\Mi Set (final).MP3")
    assert r.status_code == 200, r.text
    job = r.json()
    assert job["status"] == "queued" and job["input_name"] == "Mi Set (final).MP3" and job["files"] == []
    async with SessionLocal() as db:
        row = (await db.execute(select(ToolJob))).scalar_one()
    stored = svc.input_path(row)
    assert stored.name == f"{row.id}.mp3" and stored.read_bytes() == set_mp3  # en disco, con el id del trabajo
    assert not svc.upload_dir(row.id).exists()
    listed = (await client.get("/api/tools/jobs", headers=bearer(access))).json()
    assert listed["total"] == 1 and listed["items"][0]["id"] == job["id"]


async def test_chunks_order_sizes_and_repeat(client, set_mp3):
    access, _ = await signup(client, "uno@example.com")
    h, pieces = bearer(access), parts(set_mp3)
    up = (await client.post("/api/tools/uploads", headers=h,
                            json={"tool": "tracklist", "filename": "set.mp3", "size": len(set_mp3)})).json()
    url = f"/api/tools/uploads/{up['upload_id']}/chunks"
    assert up["total_parts"] == len(pieces) and up["received_parts"] == 0

    assert (await client.put(f"{url}/1", headers=h, content=pieces[1])).status_code == 409        # fuera de orden
    assert (await client.put(f"{url}/{len(pieces)}", headers=h, content=b"x")).status_code == 422  # índice inválido
    assert (await client.put(f"{url}/0", headers=h, content=pieces[0][:-1])).status_code == 422    # parte corta
    assert (await client.put(f"{url}/0", headers=h, content=pieces[0] + b"x")).status_code == 422  # parte larga
    assert (await client.put(f"{url}/0", headers=h, content=pieces[0])).json()["received_parts"] == 1
    # reintento de una parte ya enviada (p. ej. se cortó la respuesta): se acepta y no retrocede
    assert (await client.put(f"{url}/0", headers=h, content=pieces[0])).json()["received_parts"] == 1

    # cerrar antes de tiempo: incompleta
    r = await client.post(f"/api/tools/uploads/{up['upload_id']}/complete", headers=h)
    assert r.status_code == 409 and "incompleta" in r.text

    # reanudar: iniciar de nuevo con el mismo archivo devuelve la misma subida y por dónde va
    again = (await client.post("/api/tools/uploads", headers=h,
                               json={"tool": "tracklist", "filename": "set.mp3", "size": len(set_mp3)})).json()
    assert again["upload_id"] == up["upload_id"] and again["received_parts"] == 1
    for i in range(1, len(pieces)):
        assert (await client.put(f"{url}/{i}", headers=h, content=pieces[i])).status_code == 200
    r = await client.post(f"/api/tools/uploads/{up['upload_id']}/complete", headers=h)
    assert r.status_code == 200 and r.json()["status"] == "queued"
    # ya cerrada: no admite más partes ni cerrarla otra vez
    assert (await client.put(f"{url}/0", headers=h, content=pieces[0])).status_code == 409
    assert (await client.post(f"/api/tools/uploads/{up['upload_id']}/complete", headers=h)).status_code == 409


async def test_declared_size_and_extension_limits(client):
    access, _ = await signup(client, "uno@example.com")
    h = bearer(access)
    r = await client.post("/api/tools/uploads", headers=h, json={"tool": "tracklist", "filename": "set.exe", "size": 10})
    assert r.status_code == 422 and "Formato no admitido" in r.text
    r = await client.post("/api/tools/uploads", headers=h,
                          json={"tool": "tracklist", "filename": "set.wav", "size": 4 * 1024**3})
    assert r.status_code == 413
    r = await client.post("/api/tools/uploads", headers=h, json={"tool": "otra", "filename": "set.wav", "size": 10})
    assert r.status_code == 422


async def test_non_audio_rejected_by_content(client):
    access, _ = await signup(client, "uno@example.com")
    r = await upload(client, access, b"esto no es audio " * 10000, filename="set.mp3")
    assert r.status_code == 422 and "audio válido" in r.text
    async with SessionLocal() as db:  # no queda trabajo ni archivo
        assert (await db.execute(select(ToolJob))).first() is None
    assert not list(svc.data_dir().rglob("*.part")) and not list(svc.data_dir().rglob("*.mp3"))


async def test_library_zip_validated_by_content(client):
    access, _ = await signup(client, "uno@example.com")
    r = await client.post("/api/tools/uploads", headers=bearer(access),
                          json={"tool": "library_upgrade", "filename": "lib.zip", "size": 10})
    assert r.status_code == 422 and "derecho a usar" in r.text  # falta aceptar

    ok = {"tool": "library_upgrade", "accept_rights": True, "formato": "flac"}
    r = await upload(client, access, b"PK no soy un zip" * 100, filename="lib.zip", **ok)
    assert r.status_code == 422 and ".zip válido" in r.text
    r = await upload(client, access, library_zip(names=(), extra=("notas.txt",)), filename="lib.zip", **ok)
    assert r.status_code == 422 and "no contiene audio" in r.text
    many = library_zip(names=[f"t{i}.mp3" for i in range(4)])  # FADEX_LIBRARY_MAX_FILES=3
    r = await upload(client, access, many, filename="lib.zip", **ok)
    assert r.status_code == 422 and "máximo por librería" in r.text

    r = await upload(client, access, library_zip(extra=("notas.txt", "__MACOSX/._x.mp3")), filename="lib.zip", **ok)
    assert r.status_code == 200, r.text
    job = r.json()
    assert job["status"] == "queued" and job["options"] == {"formato": "flac"}
    r = await client.post("/api/tools/uploads", headers=bearer(access),
                          json={"tool": "library_upgrade", "filename": "l.zip", "size": 10, "formato": "ogg",
                                "accept_rights": True})
    assert r.status_code == 422


async def test_cancel_and_replace_pending_upload(client, set_mp3):
    access, _ = await signup(client, "uno@example.com")
    h = bearer(access)
    first = await upload(client, access, set_mp3, complete=False)
    # otro archivo de la misma herramienta reemplaza la subida a medias
    second = (await client.post("/api/tools/uploads", headers=h,
                                json={"tool": "tracklist", "filename": "otro.wav", "size": 1000})).json()
    assert second["upload_id"] != first["upload_id"]
    assert (await client.get(f"/api/tools/uploads/{first['upload_id']}", headers=h)).status_code == 404
    assert not svc.upload_dir(uuid.UUID(first["upload_id"])).exists()
    assert (await client.delete(f"/api/tools/uploads/{second['upload_id']}", headers=h)).status_code == 204
    assert not svc.upload_dir(uuid.UUID(second["upload_id"])).exists()


# ---------- límites ----------

async def test_one_active_job_and_daily_limit(client, set_mp3):
    access, _ = await signup(client, "uno@example.com")
    h = bearer(access)
    first = (await upload(client, access, set_mp3)).json()
    r = await client.post("/api/tools/uploads", headers=h,
                          json={"tool": "tracklist", "filename": "b.mp3", "size": len(set_mp3)})
    assert r.status_code == 409 and "en curso" in r.text
    # la otra herramienta no se bloquea
    r = await client.post("/api/tools/uploads", headers=h, json={
        "tool": "library_upgrade", "filename": "l.zip", "size": 100, "accept_rights": True})
    assert r.status_code == 200

    await finish(first["id"])
    second = (await upload(client, access, set_mp3, filename="b.mp3")).json()
    await finish(second["id"])
    r = await client.post("/api/tools/uploads", headers=h,  # FADEX_TRACKLIST_PER_DAY=2
                          json={"tool": "tracklist", "filename": "c.mp3", "size": len(set_mp3)})
    assert r.status_code == 429 and "límite de 2" in r.text


# ---------- descargas ----------

async def test_download_only_whitelisted_names(client, set_mp3):
    access, _ = await signup(client, "uno@example.com")
    h = bearer(access)
    job = (await upload(client, access, set_mp3)).json()
    url = f"/api/tools/jobs/{job['id']}/files"
    assert (await client.get(f"{url}/tracklist.txt", headers=h)).status_code == 404  # aún no termina
    await finish(job["id"], files=("tracklist.txt",))

    detail = (await client.get(f"/api/tools/jobs/{job['id']}", headers=h)).json()
    assert detail["status"] == "done" and detail["files"] == ["tracklist.txt"] and detail["summary"] == {"tracks": 3}
    assert "error" not in detail and "detalle interno" not in str(detail)  # el detalle interno no sale
    r = await client.get(f"{url}/tracklist.txt", headers=h)
    assert r.status_code == 200 and "contenido de tracklist.txt" in r.text
    assert "attachment" in r.headers["content-disposition"]
    for name in ("secreto.txt",        # existe en disco pero no está en la lista blanca
                 "tracklist.csv",      # permitido, pero este trabajo no lo generó
                 "informe.csv",        # de la otra herramienta
                 "..%2F..%2Finput%2Fx", "%2e%2e%2fsecreto.txt"):
        assert (await client.get(f"{url}/{name}", headers=h)).status_code == 404, name
    assert (await client.get(f"{url}/tracklist.txt")).status_code == 401


# ---------- admin ----------

async def test_admin_seats_and_jobs(client, set_mp3):
    a1, _ = await signup(client, "uno@example.com")
    await signup(client, "dos@example.com")
    a3, _ = await signup(client, "tres@example.com")  # sin lugar
    assert (await client.get("/api/admin/beta/users", headers=bearer(a1))).status_code == 403
    await set_role("tres@example.com", "admin")
    h = bearer(a3)

    seated = (await client.get("/api/admin/beta/users", headers=h)).json()
    assert [u["beta_seat"] for u in seated] == [1, 2]
    everyone = (await client.get("/api/admin/beta/users?all=true", headers=h)).json()
    assert len(everyone) == 3
    ids = {u["email"]: u["id"] for u in everyone}

    # lleno: no se puede dar otro lugar hasta liberar uno
    r = await client.put(f"/api/admin/beta/users/{ids['tres@example.com']}/seat", headers=h)
    assert r.status_code == 409 and "No quedan lugares" in r.text
    r = await client.delete(f"/api/admin/beta/users/{ids['uno@example.com']}/seat", headers=h)
    assert r.status_code == 200 and r.json()["beta_seat"] is None
    r = await client.put(f"/api/admin/beta/users/{ids['tres@example.com']}/seat", headers=h)
    assert r.json()["beta_seat"] == 1  # reutiliza el lugar liberado
    assert (await client.get("/api/beta")).json()["taken"] == 2
    # quien perdió su lugar pierde el acceso de inmediato
    assert (await client.get("/api/tools", headers=bearer(a1))).status_code == 403
    assert (await client.put(f"/api/admin/beta/users/{uuid.uuid4()}/seat", headers=h)).status_code == 404

    job = (await upload(client, a3, set_mp3)).json()
    await finish(job["id"])
    jobs = (await client.get("/api/admin/jobs", headers=h)).json()
    assert jobs[0]["user_email"] == "tres@example.com" and jobs[0]["error"] == "detalle interno"


# ---------- migración ----------

def test_migration_0003_up_and_down(tmp_path):
    import os
    import sqlite3
    db = tmp_path / "mig.db"
    env = {**os.environ, "FADEX_DATABASE_URL": f"sqlite+aiosqlite:///{db}"}

    def alembic(*args):
        subprocess.run([sys.executable, "-m", "alembic", *args], check=True, env=env, capture_output=True)

    def tables():
        with sqlite3.connect(db) as con:
            return {r[0] for r in con.execute("select name from sqlite_master where type='table'")}

    alembic("upgrade", "head")
    assert "tool_jobs" in tables()
    alembic("downgrade", "0002_profile_beta_google")
    assert "tool_jobs" not in tables() and "users" in tables()
    alembic("upgrade", "head")
    assert "tool_jobs" in tables()
