import os

os.environ.update({
    "FADEX_ENV": "test",
    "FADEX_DATABASE_URL": "sqlite+aiosqlite:///./test.db",
    "FADEX_COOKIE_SECURE": "false",   # el cliente de pruebas usa http://
    "FADEX_CORS_ORIGINS": '["http://test"]',
    "FADEX_PUBLIC_URL": "http://test",
    "FADEX_BETA_SEATS": "2",               # pocos lugares para probar que se agotan
    "FADEX_GOOGLE_CLIENT_ID": "test-client.apps.googleusercontent.com",
    "FADEX_DATA_DIR": "./test-data",        # subidas y resultados de las herramientas
    "FADEX_UPLOAD_CHUNK_BYTES": "65536",   # partes chicas para probar la subida por partes
    "FADEX_TRACKLIST_MIN_SECONDS": "1",
    "FADEX_TRACKLIST_PER_DAY": "2",
    "FADEX_LIBRARY_MAX_FILES": "3",
})

import shutil  # noqa: E402

import fakeredis.aioredis  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.core import ratelimit  # noqa: E402
from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.services import email  # noqa: E402

CSRF = {"x-fadex-csrf": "1", "origin": "http://test"}


@pytest_asyncio.fixture(autouse=True)
async def _db():
    ratelimit.set_redis(fakeredis.aioredis.FakeRedis(decode_responses=True))
    email.outbox.clear()
    shutil.rmtree("./test-data", ignore_errors=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


def token_from_outbox(kind: str) -> str:
    """Saca el token del último email enviado de ese tipo."""
    for msg in reversed(email.outbox):
        body = msg.get_content()
        if kind in body:
            return body.split("token=")[1].split()[0]
    raise AssertionError("no se envió el email")


@pytest.fixture
def user_data():
    return {"email": "Dj@Example.com", "password": "una-clave-segura-123", "display_name": "DJ Test",
            "whatsapp": "614 115 1657", "accept_privacy": True}
