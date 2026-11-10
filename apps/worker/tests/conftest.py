import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
API = HERE.parents[1] / "api"
sys.path[:0] = [str(HERE.parent), str(API)]  # worker.* y app.* (el worker reutiliza el paquete de la API)
WORKDIR = HERE.parent / ".test-run"

os.environ.update({
    "FADEX_ENV": "test",
    "FADEX_DATABASE_URL": f"sqlite+aiosqlite:///{WORKDIR.as_posix()}/test.db",
    "FADEX_COOKIE_SECURE": "false",
    "FADEX_CORS_ORIGINS": '["http://test"]',
    "FADEX_PUBLIC_URL": "http://test",
    "FADEX_BETA_SEATS": "2",
    "FADEX_DATA_DIR": str(WORKDIR / "data"),
    "FADEX_UPLOAD_CHUNK_BYTES": str(4 * 1024 * 1024),
    "FADEX_TRACKLIST_MIN_SECONDS": "1",
    "FADEX_UPGRADE_SEARCH_DELAY": "0",     # sin pausas entre búsquedas ni entre revisiones
    "FADEX_UPGRADE_WATCH_SECONDS": "1",
})
os.environ.pop("ACRCLOUD_TOKEN", None)       # las pruebas nunca hablan con ACRCloud ni con Shazam
WORKDIR.mkdir(exist_ok=True)

import shutil  # noqa: E402
import subprocess  # noqa: E402

import fakeredis.aioredis  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.core import ratelimit  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.services import email  # noqa: E402

FAKES = HERE / "fakes"
PY = sys.executable


@pytest_asyncio.fixture(autouse=True)
async def _clean(monkeypatch):
    ratelimit.set_redis(fakeredis.aioredis.FakeRedis(decode_responses=True))
    email.outbox.clear()
    shutil.rmtree(WORKDIR / "data", ignore_errors=True)
    s = get_settings()
    # por defecto: ACRCloud y Shazam simulados con respuestas fijas en el formato real
    monkeypatch.setattr(s, "acr_scan_cmd", f'"{PY}" "{FAKES / "acr_scan.py"}"')
    monkeypatch.setattr(s, "shazam_scan_cmd", f'"{PY}" "{FAKES / "shazam_scan.py"}"')
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *map(str, args)], check=True)


def bearer(token):
    return {"authorization": f"Bearer {token}"}


async def signup(client, address="dj@example.com"):
    """Cuenta con email confirmado y lugar en la beta. Devuelve el access token."""
    data = {"email": address, "password": "una-clave-segura-123", "display_name": "DJ Prueba",
            "whatsapp": "6141151657", "accept_privacy": True}
    assert (await client.post("/api/auth/register", json=data)).status_code == 202
    token = email.outbox[-1].get_content().split("token=")[1].split()[0]
    assert (await client.post("/api/auth/verify-email", json={"token": token})).status_code == 200
    email.outbox.clear()
    return (await client.post("/api/auth/login", json=data)).json()["access_token"]


async def upload(client, access, path: Path, tool: str, **extra):
    """Sube un archivo por partes por la API, como lo hace la web. Devuelve el trabajo en cola."""
    data, h = path.read_bytes(), bearer(access)
    r = await client.post("/api/tools/uploads", headers=h,
                          json={"tool": tool, "filename": path.name, "size": len(data), **extra})
    assert r.status_code == 200, r.text
    up = r.json()
    for i in range(up["total_parts"]):
        piece = data[i * up["chunk_size"]:(i + 1) * up["chunk_size"]]
        r = await client.put(f"/api/tools/uploads/{up['upload_id']}/chunks/{i}", headers=h, content=piece)
        assert r.status_code == 200, r.text
    r = await client.post(f"/api/tools/uploads/{up['upload_id']}/complete", headers=h)
    assert r.status_code == 200, r.text
    return r.json()
