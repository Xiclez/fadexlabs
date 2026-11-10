import pytest

from app.services import email
from tests.conftest import CSRF, token_from_outbox

pytestmark = pytest.mark.asyncio


async def register_and_login(client, user_data, verify=True):
    assert (await client.post("/api/auth/register", json=user_data)).status_code == 202
    if verify:
        token = token_from_outbox("verificar-email")
        assert (await client.post("/api/auth/verify-email", json={"token": token})).status_code == 200
    r = await client.post("/api/auth/login", json={"email": user_data["email"], "password": user_data["password"]})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def bearer(token):
    return {"authorization": f"Bearer {token}"}


async def test_register_login_me(client, user_data):
    access = await register_and_login(client, user_data)
    r = await client.get("/api/auth/me", headers=bearer(access))
    assert r.status_code == 200
    body = r.json()
    assert body["email"] == "dj@example.com"  # normalizado
    assert body["email_verified"] is True
    assert "password_hash" not in body


async def test_refresh_cookie_flags(client, user_data):
    await client.post("/api/auth/register", json=user_data)
    r = await client.post("/api/auth/login", json={"email": user_data["email"], "password": user_data["password"]})
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "path=/api/auth" in cookie


async def test_register_does_not_reveal_existing_email(client, user_data):
    first = await client.post("/api/auth/register", json=user_data)
    second = await client.post("/api/auth/register", json={**user_data, "password": "otra-clave-larga-99"})
    assert first.status_code == second.status_code == 202
    assert first.json() == second.json()
    assert "ya tienes una" in email.outbox[-1].get_content()


async def test_login_generic_error_and_rate_limit(client, user_data):
    await client.post("/api/auth/register", json=user_data)
    wrong = await client.post("/api/auth/login", json={"email": user_data["email"], "password": "x" * 12})
    unknown = await client.post("/api/auth/login", json={"email": "nadie@example.com", "password": "x" * 12})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()
    for _ in range(10):
        r = await client.post("/api/auth/login", json={"email": user_data["email"], "password": "x" * 12})
    assert r.status_code == 429 and "retry-after" in r.headers


async def test_weak_password_rejected(client, user_data):
    r = await client.post("/api/auth/register", json={**user_data, "password": "corta"})
    assert r.status_code == 422


async def test_refresh_rotation_and_reuse_detection(client, user_data):
    await register_and_login(client, user_data)
    old = client.cookies.get("fx_refresh")
    r1 = await client.post("/api/auth/refresh", headers=CSRF)
    assert r1.status_code == 200
    new = client.cookies.get("fx_refresh")
    assert new and new != old

    # un atacante reutiliza el token viejo -> se revoca toda la sesión
    client.cookies.set("fx_refresh", old, path="/api/auth")
    assert (await client.post("/api/auth/refresh", headers=CSRF)).status_code == 401
    client.cookies.set("fx_refresh", new, path="/api/auth")
    assert (await client.post("/api/auth/refresh", headers=CSRF)).status_code == 401


async def test_refresh_requires_csrf_header_and_origin(client, user_data):
    await register_and_login(client, user_data)
    assert (await client.post("/api/auth/refresh")).status_code == 403
    bad_origin = {"x-fadex-csrf": "1", "origin": "https://evil.example"}
    assert (await client.post("/api/auth/refresh", headers=bad_origin)).status_code == 403


async def test_logout_revokes_refresh(client, user_data):
    await register_and_login(client, user_data)
    token = client.cookies.get("fx_refresh")
    assert (await client.post("/api/auth/logout", headers=CSRF)).status_code == 204
    client.cookies.set("fx_refresh", token, path="/api/auth")
    assert (await client.post("/api/auth/refresh", headers=CSRF)).status_code == 401


async def test_password_reset_revokes_sessions_and_old_tokens(client, user_data):
    access = await register_and_login(client, user_data)
    refresh = client.cookies.get("fx_refresh")
    assert (await client.post("/api/auth/forgot-password", json={"email": user_data["email"]})).status_code == 202
    token = token_from_outbox("restablecer")
    new_pw = "nueva-clave-segura-456"
    r = await client.post("/api/auth/reset-password", json={"token": token, "password": new_pw})
    assert r.status_code == 200
    # el token de reset es de un solo uso
    again = await client.post("/api/auth/reset-password", json={"token": token, "password": new_pw + "x"})
    assert again.status_code == 400
    # la sesión anterior queda revocada
    client.cookies.set("fx_refresh", refresh, path="/api/auth")
    assert (await client.post("/api/auth/refresh", headers=CSRF)).status_code == 401
    # login con la nueva contraseña funciona; con la vieja no
    ok = await client.post("/api/auth/login", json={"email": user_data["email"], "password": new_pw})
    old = await client.post("/api/auth/login", json={"email": user_data["email"], "password": user_data["password"]})
    assert ok.status_code == 200 and old.status_code == 401
    # el access token emitido antes del cambio de contraseña ya no sirve
    assert (await client.get("/api/auth/me", headers=bearer(access))).status_code == 401


async def test_forgot_password_unknown_email_same_response(client):
    r = await client.post("/api/auth/forgot-password", json={"email": "nadie@example.com"})
    assert r.status_code == 202 and not email.outbox


async def test_sessions_list_and_revoke(client, user_data):
    access = await register_and_login(client, user_data)
    sessions = (await client.get("/api/auth/sessions", headers=bearer(access))).json()
    assert len(sessions) == 1 and sessions[0]["current"] is True
    sid = sessions[0]["id"]
    assert (await client.delete(f"/api/auth/sessions/{sid}", headers=bearer(access))).status_code == 204
    assert (await client.post("/api/auth/refresh", headers=CSRF)).status_code == 401


async def test_protected_route_rejects_bad_tokens(client):
    assert (await client.get("/api/auth/me")).status_code == 401
    assert (await client.get("/api/auth/me", headers=bearer("abc.def.ghi"))).status_code == 401


async def test_jwks_exposes_only_public_key(client):
    keys = (await client.get("/api/auth/.well-known/jwks.json")).json()["keys"]
    assert keys[0]["kty"] == "OKP" and keys[0]["crv"] == "Ed25519" and "d" not in keys[0]


async def test_security_headers(client):
    r = await client.get("/api/auth/.well-known/jwks.json")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
