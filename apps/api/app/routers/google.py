"""Inicio de sesión con Google (OpenID Connect, flujo de código con PKCE).

/api/auth/google/start     → redirige a Google con state, nonce y code_challenge
/api/auth/google/callback  → valida state, canjea el código, verifica el id_token (firma, aud, iss,
                             nonce, email verificado) y abre una sesión normal de FADEX (cookie de
                             refresh). Si falta el WhatsApp, lleva a /completar-perfil.

El state, el nonce y el code_verifier se guardan en Redis (un solo uso, 10 min) y el state
también en una cookie httpOnly: el callback solo se acepta en el mismo navegador que lo inició.
"""
import base64
import hashlib
import json
import secrets
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core import ratelimit
from app.core.config import get_settings
from app.core.deps import DB
from app.models import NO_PASSWORD, User
from app.routers.auth import _set_refresh_cookie, _ua
from app.services import auth as svc
from app.services import beta

router = APIRouter(prefix="/api/auth/google", tags=["auth"])

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
ISSUERS = ("https://accounts.google.com", "accounts.google.com")
STATE_COOKIE = "fx_oauth_state"

_jwks_client: jwt.PyJWKClient | None = None


def _safe_next(path: str | None) -> str:
    """Solo rutas internas: evita redirecciones abiertas a otros dominios."""
    if not path or not path.startswith("/") or path.startswith("//") or "\\" in path:
        return "/cuenta"
    return path


def _fail(reason: str) -> RedirectResponse:
    return RedirectResponse(f"{get_settings().public_url}/login?error={reason}", status_code=303)


# ---------- llamadas a Google (se sustituyen en los tests) ----------

async def exchange_code(code: str, verifier: str) -> dict:
    s = get_settings()
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(TOKEN_URL, data={
            "code": code, "client_id": s.google_client_id, "client_secret": s.google_client_secret,
            "redirect_uri": s.google_redirect_uri, "grant_type": "authorization_code", "code_verifier": verifier,
        })
    if r.status_code != 200:
        raise ValueError(f"Google rechazó el código ({r.status_code})")
    return r.json()


def verify_id_token(id_token: str, nonce: str) -> dict:
    global _jwks_client
    _jwks_client = _jwks_client or jwt.PyJWKClient(JWKS_URL, cache_keys=True)
    key = _jwks_client.get_signing_key_from_jwt(id_token).key
    claims = jwt.decode(id_token, key, algorithms=["RS256"], audience=get_settings().google_client_id,
                        issuer=ISSUERS, options={"require": ["exp", "iat", "sub", "aud", "iss"]})
    if claims.get("nonce") != nonce:
        raise ValueError("nonce no coincide")
    return claims


# ---------- endpoints ----------

@router.get("/start")
async def start(request: Request, next: str | None = None) -> RedirectResponse:
    s = get_settings()
    if not s.google_client_id:
        raise HTTPException(404, "Inicio de sesión con Google no configurado")
    await ratelimit.hit(f"google:ip:{ratelimit.client_ip(request)}", 30)
    state, nonce, verifier = (secrets.token_urlsafe(32) for _ in range(3))
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    await ratelimit.get_redis().set(f"oauth:{state}", json.dumps(
        {"nonce": nonce, "verifier": verifier, "next": _safe_next(next)}), ex=s.oauth_state_ttl_seconds)
    url = AUTH_URL + "?" + urlencode({
        "client_id": s.google_client_id, "redirect_uri": s.google_redirect_uri, "response_type": "code",
        "scope": "openid email profile", "state": state, "nonce": nonce, "code_challenge": challenge,
        "code_challenge_method": "S256", "prompt": "select_account",
    })
    resp = RedirectResponse(url, status_code=303)
    # SameSite=Lax: la vuelta desde Google es una navegación entre sitios y Strict no la enviaría
    resp.set_cookie(STATE_COOKIE, state, max_age=s.oauth_state_ttl_seconds, httponly=True,
                    secure=s.cookie_secure, samesite="lax", path="/api/auth/google")
    return resp


@router.get("/callback")
async def callback(request: Request, db: DB, code: str | None = None, state: str | None = None,
                   error: str | None = None) -> RedirectResponse:
    if error or not code or not state:
        return _fail("google_cancelado")
    if request.cookies.get(STATE_COOKIE) != state:
        return _fail("google_estado")
    raw = await ratelimit.get_redis().getdel(f"oauth:{state}")  # un solo uso
    if not raw:
        return _fail("google_vencido")
    saved = json.loads(raw)
    try:
        tokens = await exchange_code(code, saved["verifier"])
        claims = verify_id_token(tokens["id_token"], saved["nonce"])
    except (ValueError, KeyError, jwt.PyJWTError, httpx.HTTPError):
        return _fail("google_invalido")
    if not claims.get("email_verified") or not claims.get("email"):
        return _fail("google_email")

    sub, email_norm = str(claims["sub"]), claims["email"].lower()
    user = (await db.execute(select(User).where(User.google_sub == sub))).scalar_one_or_none()
    if user is None:
        # misma persona que ya se registró con ese email: Google ya verificó que lo controla
        user = (await db.execute(select(User).where(User.email == email_norm))).scalar_one_or_none()
        if user is not None:
            user.google_sub = sub
        else:
            name = (claims.get("name") or claims.get("given_name") or email_norm.split("@")[0])[:80]
            user = User(email=email_norm, password_hash=NO_PASSWORD, display_name=name, google_sub=sub,
                        is_active=True, role="user")
            db.add(user)
    if user.is_active is False:
        return _fail("cuenta_inactiva")
    user.email_verified_at = user.email_verified_at or svc.now()
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        return _fail("google_invalido")
    await beta.try_assign_seat(db, user)
    _, refresh = await svc.issue_session(db, user, _ua(request), ratelimit.client_ip(request))
    await db.commit()

    s = get_settings()
    dest = saved["next"] if user.profile_complete else "/completar-perfil?" + urlencode({"next": saved["next"]})
    resp = RedirectResponse(f"{s.public_url}{dest}", status_code=303)
    _set_refresh_cookie(resp, refresh)
    resp.delete_cookie(STATE_COOKIE, path="/api/auth/google")
    return resp


@router.get("/enabled")
async def enabled() -> dict:
    return {"enabled": bool(get_settings().google_client_id)}
