"""Login con Google: se sustituyen las dos llamadas a Google (canje de código y verificación del
id_token) para probar todo el flujo propio: state/PKCE, alta, vinculación, perfil y beta."""
from urllib.parse import parse_qs, urlparse

import pytest

from app.routers import google
from tests.conftest import CSRF

pytestmark = pytest.mark.asyncio


def bearer(token):
    return {"authorization": f"Bearer {token}"}


@pytest.fixture
def fake_google(monkeypatch):
    identity = {"sub": "google-123", "email": "Nueva@Gmail.com", "email_verified": True, "name": "DJ Google"}
    seen = {}

    async def exchange_code(code, verifier):
        seen["verifier"] = verifier
        return {"id_token": "fake"}

    def verify_id_token(id_token, nonce):
        seen["nonce"] = nonce
        return {**identity, "nonce": nonce}

    monkeypatch.setattr(google, "exchange_code", exchange_code)
    monkeypatch.setattr(google, "verify_id_token", verify_id_token)
    return identity, seen


async def start(client, next_path="/cuenta"):
    r = await client.get("/api/auth/google/start", params={"next": next_path})
    assert r.status_code == 303
    q = parse_qs(urlparse(r.headers["location"]).query)
    assert q["code_challenge_method"] == ["S256"] and q["scope"] == ["openid email profile"]
    return q["state"][0]


async def test_google_signup_requires_profile_then_joins_beta(client, fake_google):
    state = await start(client)
    r = await client.get("/api/auth/google/callback", params={"code": "abc", "state": state})
    assert r.status_code == 303
    assert r.headers["location"].startswith("http://test/completar-perfil")
    assert "fx_refresh" in r.headers.get("set-cookie", "")

    access = (await client.post("/api/auth/refresh", headers=CSRF)).json()["access_token"]
    me = (await client.get("/api/auth/me", headers=bearer(access))).json()
    assert me["email"] == "nueva@gmail.com" and me["email_verified"] and me["google_linked"]
    assert me["has_password"] is False and me["profile_complete"] is False and me["beta"] is False

    r = await client.post("/api/auth/complete-profile", headers=bearer(access),
                          json={"whatsapp": "+52 614 115 1657", "accept_privacy": True})
    assert r.status_code == 200
    me = (await client.get("/api/auth/me", headers=bearer(r.json()["access_token"]))).json()
    assert me["whatsapp"] == "+526141151657" and me["beta_seat"] == 1


async def test_google_cannot_log_in_with_password(client, fake_google):
    state = await start(client)
    await client.get("/api/auth/google/callback", params={"code": "abc", "state": state})
    r = await client.post("/api/auth/login", json={"email": "nueva@gmail.com", "password": "!"})
    assert r.status_code == 401


async def test_google_links_existing_account(client, fake_google, user_data):
    identity, _ = fake_google
    identity["email"] = user_data["email"]  # ya registrada con contraseña
    await client.post("/api/auth/register", json=user_data)
    state = await start(client, "/herramientas")
    r = await client.get("/api/auth/google/callback", params={"code": "abc", "state": state})
    assert r.headers["location"] == "http://test/herramientas"  # perfil ya completo
    access = (await client.post("/api/auth/refresh", headers=CSRF)).json()["access_token"]
    me = (await client.get("/api/auth/me", headers=bearer(access))).json()
    assert me["google_linked"] and me["has_password"] and me["email_verified"]


async def test_state_mismatch_and_reuse_rejected(client, fake_google):
    state = await start(client)
    client.cookies.set("fx_oauth_state", "otro", path="/api/auth/google")
    r = await client.get("/api/auth/google/callback", params={"code": "abc", "state": state})
    assert "error=google_estado" in r.headers["location"]

    client.cookies.clear()
    state = await start(client)
    ok = await client.get("/api/auth/google/callback", params={"code": "abc", "state": state})
    assert "error" not in ok.headers["location"]
    client.cookies.set("fx_oauth_state", state, path="/api/auth/google")
    again = await client.get("/api/auth/google/callback", params={"code": "abc", "state": state})
    assert "error=google_vencido" in again.headers["location"]  # el state es de un solo uso


async def test_unverified_google_email_rejected(client, fake_google):
    fake_google[0]["email_verified"] = False
    state = await start(client)
    r = await client.get("/api/auth/google/callback", params={"code": "abc", "state": state})
    assert "error=google_email" in r.headers["location"]


async def test_open_redirect_blocked(client, fake_google):
    state = await start(client, "https://evil.example/robar")
    r = await client.get("/api/auth/google/callback", params={"code": "abc", "state": state})
    assert r.headers["location"].startswith("http://test/")
    assert "evil.example" not in r.headers["location"].split("?")[0]


async def test_pkce_verifier_matches_challenge(client, fake_google):
    import base64
    import hashlib
    r = await client.get("/api/auth/google/start")
    q = parse_qs(urlparse(r.headers["location"]).query)
    await client.get("/api/auth/google/callback", params={"code": "abc", "state": q["state"][0]})
    verifier = fake_google[1]["verifier"]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    assert challenge == q["code_challenge"][0] and fake_google[1]["nonce"] == q["nonce"][0]
