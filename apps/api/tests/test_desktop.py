"""Login de la app de escritorio (RFC 8252): PKCE, state, código de un solo uso y con vencimiento, redirección
solo a loopback, refresh de dispositivo separado de la cookie, revocación desde la web y claim `beta`."""
import base64
import hashlib
import secrets
from urllib.parse import parse_qs, urlparse

import jwt
import pytest

from app.core import ratelimit
from tests.conftest import CSRF
from tests.test_auth import bearer, register_and_login

pytestmark = pytest.mark.asyncio


def pkce():
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


async def authorize(client, access, challenge, port=53111, state="estado-de-la-app-123456", **extra):
    return await client.post("/api/auth/desktop/authorize", headers=bearer(access), json={
        "code_challenge": challenge, "state": state, "redirect_port": port, "device_name": "PC-ESTUDIO", **extra})


async def desktop_login(client, user_data):
    """Flujo completo. Devuelve (tokens de la app, access de la web)."""
    web = await register_and_login(client, user_data)
    verifier, challenge = pkce()
    r = await authorize(client, web, challenge)
    assert r.status_code == 200, r.text
    q = parse_qs(urlparse(r.json()["redirect_url"]).query)
    t = await client.post("/api/auth/desktop/token",
                          json={"code": q["code"][0], "code_verifier": verifier, "redirect_port": 53111})
    assert t.status_code == 200, t.text
    return t.json(), web


async def test_full_flow_and_beta_claim(client, user_data):
    tokens, _ = await desktop_login(client, user_data)
    assert tokens["refresh_token"] and tokens["token_type"] == "bearer"
    claims = jwt.decode(tokens["access_token"], options={"verify_signature": False})
    assert claims["beta"] is True  # el primer usuario confirmado tiene lugar (FADEX_BETA_SEATS=2)
    me = (await client.get("/api/auth/me", headers=bearer(tokens["access_token"]))).json()
    assert me["email"] == "dj@example.com" and me["beta"]


async def test_redirect_is_always_loopback(client, user_data):
    web = await register_and_login(client, user_data)
    _, challenge = pkce()
    r = await authorize(client, web, challenge, state="abcdefghijklmnop1234")
    url = urlparse(r.json()["redirect_url"])
    assert (url.scheme, url.hostname, url.port, url.path) == ("http", "127.0.0.1", 53111, "/callback")
    assert parse_qs(url.query)["state"] == ["abcdefghijklmnop1234"]
    # no hay forma de pedir otro host: campos de más se ignoran y puertos fuera de rango se rechazan
    r = await authorize(client, web, challenge, redirect_uri="https://evil.example/callback")
    assert urlparse(r.json()["redirect_url"]).hostname == "127.0.0.1"
    assert (await authorize(client, web, challenge, port=80)).status_code == 422
    assert (await authorize(client, web, challenge, port=70000)).status_code == 422


async def test_state_and_pkce_required(client, user_data):
    web = await register_and_login(client, user_data)
    _, challenge = pkce()
    assert (await authorize(client, web, challenge, state="")).status_code == 422
    assert (await authorize(client, web, challenge, state="corto")).status_code == 422
    assert (await authorize(client, web, "x" * 10)).status_code == 422
    assert (await authorize(client, web, challenge, code_challenge_method="plain")).status_code == 422
    # sin sesión de la web no se autoriza nada
    r = await client.post("/api/auth/desktop/authorize", json={
        "code_challenge": challenge, "state": "estado-de-la-app-123456", "redirect_port": 53111})
    assert r.status_code == 401


async def test_wrong_verifier_or_port_rejected(client, user_data):
    web = await register_and_login(client, user_data)
    verifier, challenge = pkce()
    code = parse_qs(urlparse((await authorize(client, web, challenge)).json()["redirect_url"]).query)["code"][0]
    other, _ = pkce()
    bad = await client.post("/api/auth/desktop/token",
                            json={"code": code, "code_verifier": other, "redirect_port": 53111})
    assert bad.status_code == 400
    # el intento fallido consumió el código: ni con el verifier correcto vale ya
    again = await client.post("/api/auth/desktop/token",
                              json={"code": code, "code_verifier": verifier, "redirect_port": 53111})
    assert again.status_code == 400

    code = parse_qs(urlparse((await authorize(client, web, challenge)).json()["redirect_url"]).query)["code"][0]
    port = await client.post("/api/auth/desktop/token",
                             json={"code": code, "code_verifier": verifier, "redirect_port": 53112})
    assert port.status_code == 400


async def test_code_single_use_and_expires(client, user_data):
    web = await register_and_login(client, user_data)
    verifier, challenge = pkce()
    code = parse_qs(urlparse((await authorize(client, web, challenge)).json()["redirect_url"]).query)["code"][0]
    body = {"code": code, "code_verifier": verifier, "redirect_port": 53111}
    assert (await client.post("/api/auth/desktop/token", json=body)).status_code == 200
    assert (await client.post("/api/auth/desktop/token", json=body)).status_code == 400  # un solo uso

    code = parse_qs(urlparse((await authorize(client, web, challenge)).json()["redirect_url"]).query)["code"][0]
    r = ratelimit.get_redis()
    keys = [k async for k in r.scan_iter("desktop:code:*")]
    assert len(keys) == 1 and 0 < await r.ttl(keys[0]) <= 120  # vence a los 2 min
    await r.delete(keys[0])  # simula el vencimiento
    body["code"] = code
    assert (await client.post("/api/auth/desktop/token", json=body)).status_code == 400


async def test_refresh_rotates_and_is_separate_from_cookie(client, user_data):
    tokens, _ = await desktop_login(client, user_data)
    r = await client.post("/api/auth/desktop/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 200
    rotated = r.json()["refresh_token"]
    assert rotated != tokens["refresh_token"]
    # reutilizar uno ya rotado (posible robo) revoca el equipo completo
    assert (await client.post("/api/auth/desktop/refresh",
                              json={"refresh_token": tokens["refresh_token"]})).status_code == 401
    assert (await client.post("/api/auth/desktop/refresh", json={"refresh_token": rotated})).status_code == 401

    # el token de la app no sirve como cookie del navegador…
    tokens, _ = await desktop_login(client, {**user_data, "email": "otro@example.com"})
    client.cookies.clear()
    client.cookies.set("fx_refresh", tokens["refresh_token"], path="/api/auth")
    assert (await client.post("/api/auth/refresh", headers=CSRF)).status_code == 401
    # …ni la cookie del navegador en el endpoint de la app
    login = await client.post("/api/auth/login", json={"email": user_data["email"], "password": user_data["password"]})
    cookie = login.cookies.get("fx_refresh")
    assert (await client.post("/api/auth/desktop/refresh", json={"refresh_token": cookie})).status_code == 401


async def test_device_listed_and_revocable_from_web(client, user_data):
    tokens, web = await desktop_login(client, user_data)
    sessions = (await client.get("/api/auth/sessions", headers=bearer(web))).json()
    device = next(s for s in sessions if s["kind"] == "desktop")
    assert device["user_agent"] == "DJ Library Upgrader · PC-ESTUDIO" and not device["current"]

    # al rotar conserva el nombre del equipo
    tokens = (await client.post("/api/auth/desktop/refresh", json={"refresh_token": tokens["refresh_token"]})).json()
    sessions = (await client.get("/api/auth/sessions", headers=bearer(web))).json()
    assert [s["user_agent"] for s in sessions if s["kind"] == "desktop"] == ["DJ Library Upgrader · PC-ESTUDIO"]

    assert (await client.delete(f"/api/auth/sessions/{device['id']}", headers=bearer(web))).status_code == 204
    r = await client.post("/api/auth/desktop/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 401


async def test_logout_from_app_revokes_device(client, user_data):
    tokens, web = await desktop_login(client, user_data)
    assert (await client.post("/api/auth/desktop/logout",
                              json={"refresh_token": tokens["refresh_token"]})).status_code == 204
    assert (await client.post("/api/auth/desktop/refresh",
                              json={"refresh_token": tokens["refresh_token"]})).status_code == 401
    sessions = (await client.get("/api/auth/sessions", headers=bearer(web))).json()
    assert not [s for s in sessions if s["kind"] == "desktop"]


async def test_no_beta_seat_claim_false(client, user_data):
    # FADEX_BETA_SEATS=2: el tercer usuario confirmado ya no tiene lugar
    for i in range(2):
        await register_and_login(client, {**user_data, "email": f"dj{i}@example.com"})
    tokens, _ = await desktop_login(client, {**user_data, "email": "tarde@example.com"})
    claims = jwt.decode(tokens["access_token"], options={"verify_signature": False})
    assert claims["beta"] is False


async def test_latest_version(client, monkeypatch):
    from app.core.config import get_settings
    assert (await client.get("/api/desktop/latest")).status_code == 404  # nada publicado todavía
    s = get_settings()
    monkeypatch.setattr(s, "desktop_version", "0.2.0")
    monkeypatch.setattr(s, "desktop_url", "https://fadexlabs.com/descargas/FADEX-Upgrader-0.2.0.exe")
    monkeypatch.setattr(s, "desktop_sha256", "AB" * 32)
    r = await client.get("/api/desktop/latest")
    assert r.status_code == 200
    assert r.json() == {"version": "0.2.0", "url": "https://fadexlabs.com/descargas/FADEX-Upgrader-0.2.0.exe",
                        "sha256": "ab" * 32, "notas": ""}


async def test_installer_served_from_data_dir(client, monkeypatch):
    from pathlib import Path

    from app.core.config import get_settings
    s = get_settings()
    folder = Path(s.data_dir) / "desktop"
    folder.mkdir(parents=True, exist_ok=True)
    exe = folder / "FADEX-Upgrader-0.3.1-setup.exe"
    exe.write_bytes(b"MZ instalador de prueba")
    assert (await client.get("/api/desktop/download")).status_code == 404  # sin publicar
    monkeypatch.setattr(s, "desktop_file", exe.name)

    r = await client.get("/api/desktop/latest")
    assert r.status_code == 200
    assert r.json() == {"version": "0.3.1", "url": "http://test/api/desktop/download",
                        "sha256": hashlib.sha256(b"MZ instalador de prueba").hexdigest(), "notas": ""}
    r = await client.get("/api/desktop/download")
    assert r.status_code == 200 and r.content == b"MZ instalador de prueba"
    assert 'filename="FADEX-Upgrader-0.3.1-setup.exe"' in r.headers["content-disposition"]

    # solo archivos .exe dentro de <data_dir>/desktop
    monkeypatch.setattr(s, "desktop_file", "../../app/main.py")
    assert (await client.get("/api/desktop/download")).status_code == 404
