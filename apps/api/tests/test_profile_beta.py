import pytest

from tests.conftest import token_from_outbox

pytestmark = pytest.mark.asyncio


def bearer(token):
    return {"authorization": f"Bearer {token}"}


async def signup(client, email, verify=True, **extra):
    data = {"email": email, "password": "una-clave-segura-123", "display_name": "DJ",
            "whatsapp": "6141151657", "accept_privacy": True, **extra}
    r = await client.post("/api/auth/register", json=data)
    assert r.status_code == 202, r.text
    msg = None
    if verify:
        msg = (await client.post("/api/auth/verify-email", json={"token": token_from_outbox("verificar-email")})).json()
    r = await client.post("/api/auth/login", json={"email": email, "password": data["password"]})
    return r.json()["access_token"], msg


async def test_whatsapp_is_normalized_to_e164(client):
    access, _ = await signup(client, "a@example.com")
    me = (await client.get("/api/auth/me", headers=bearer(access))).json()
    assert me["whatsapp"] == "+526141151657"
    assert me["profile_complete"] is True and me["has_password"] is True


@pytest.mark.parametrize("bad", ["123", "abc", "", "+52 000 000 0000"])
async def test_invalid_whatsapp_rejected(client, user_data, bad):
    r = await client.post("/api/auth/register", json={**user_data, "whatsapp": bad})
    assert r.status_code == 422


async def test_privacy_consent_required(client, user_data):
    r = await client.post("/api/auth/register", json={**user_data, "accept_privacy": False})
    assert r.status_code == 422
    assert "aviso de privacidad" in r.text


async def test_beta_seats_first_n_verified_users(client):
    # FADEX_BETA_SEATS=2 en conftest
    assert (await client.get("/api/beta")).json() == {"seats": 2, "taken": 0, "available": 2}

    # un registro sin confirmar email NO ocupa lugar
    await signup(client, "sin-confirmar@example.com", verify=False)
    assert (await client.get("/api/beta")).json()["taken"] == 0

    a1, m1 = await signup(client, "uno@example.com")
    a2, _ = await signup(client, "dos@example.com")
    a3, m3 = await signup(client, "tres@example.com")
    assert "beta" in m1["detail"] and "beta" not in m3["detail"]

    seats = [(await client.get("/api/auth/me", headers=bearer(a))).json()["beta_seat"] for a in (a1, a2, a3)]
    assert seats == [1, 2, None]
    assert (await client.get("/api/beta")).json() == {"seats": 2, "taken": 2, "available": 0}


async def test_beta_claim_in_access_token(client):
    import jwt
    access, _ = await signup(client, "claim@example.com")
    assert jwt.decode(access, options={"verify_signature": False})["beta"] is True


async def test_beta_dependency_blocks_non_members(client):
    from fastapi import Depends

    from app.core.deps import beta_user
    from app.main import app

    @app.get("/api/_test/beta-only")
    async def beta_only(user=Depends(beta_user)):  # noqa: B008
        return {"ok": True}

    a1, _ = await signup(client, "b1@example.com")
    await signup(client, "b2@example.com")
    a3, _ = await signup(client, "b3@example.com")  # sin lugar (solo hay 2)
    assert (await client.get("/api/_test/beta-only", headers=bearer(a1))).status_code == 200
    r = await client.get("/api/_test/beta-only", headers=bearer(a3))
    assert r.status_code == 403 and "beta cerrada" in r.text
