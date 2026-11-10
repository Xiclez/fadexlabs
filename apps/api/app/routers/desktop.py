"""Inicio de sesión de la app de escritorio (DJ Library Upgrader para Windows) y su versión publicada.

Patrón para apps nativas (RFC 8252): navegador del sistema + redirección a loopback + PKCE.

1. La app abre /escritorio/autorizar?code_challenge=…&state=…&redirect_port=… en el navegador y
   escucha en http://127.0.0.1:<puerto>/callback.
2. La página exige sesión normal (contraseña o Google) y, si el usuario acepta, llama a
   POST /api/auth/desktop/authorize: se crea un código de un solo uso (2 min) atado al challenge y
   al puerto, y se devuelve la URL de loopback a la que la página redirige.
3. La app canjea code + code_verifier en POST /api/auth/desktop/token y recibe un refresh token de
   dispositivo (opaco, rotativo, revocable desde "Mi cuenta → Sesiones") y un access token con el claim
   `beta`. La app guarda el refresh en el Administrador de credenciales de Windows.

La redirección la arma la API con el puerto: nunca puede apuntar a otro host. Los refresh de la app
viajan en el cuerpo (no hay cookie fuera del navegador) y solo valen en /api/auth/desktop/refresh.
"""
import base64
import hashlib
import hmac
import asyncio
import json
import os
import re
import uuid
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import FileResponse

from app.core import ratelimit
from app.core.config import get_settings
from app.core.deps import DB, CurrentUser
from app.core.security import hash_token, new_opaque_token
from app.models import User
from app.schemas.auth import (DesktopAuthorizeIn, DesktopAuthorizeOut, DesktopLatestOut, DesktopRefreshIn,
                              DesktopTokenIn, DesktopTokenOut)
from app.services import auth as svc

router = APIRouter(tags=["desktop"])

APP_NAME = "DJ Library Upgrader"
_bad_code = HTTPException(status.HTTP_400_BAD_REQUEST, "Código inválido o vencido. Vuelve a autorizar desde la app.")


def _device_label(name: str) -> str:
    """'DJ Library Upgrader · PC-ESTUDIO' (va en la columna user_agent de la sesión)."""
    clean = re.sub(r"[^\w .\-()]", "", name, flags=re.U).strip()[:60]
    return f"{APP_NAME} · {clean}" if clean else APP_NAME


def _s256(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


def _tokens(access: str, refresh: str) -> DesktopTokenOut:
    return DesktopTokenOut(access_token=access, refresh_token=refresh, expires_in=get_settings().access_ttl_seconds)


@router.post("/api/auth/desktop/authorize", response_model=DesktopAuthorizeOut)
async def authorize(body: DesktopAuthorizeIn, user: CurrentUser) -> DesktopAuthorizeOut:
    """La llama la página web con la sesión del usuario (Bearer). El código queda en Redis, de un solo uso."""
    await ratelimit.hit(f"desktop-auth:{user.id}", 20)
    code = new_opaque_token()
    await ratelimit.get_redis().set(f"desktop:code:{hash_token(code)}", json.dumps({
        "user_id": str(user.id), "challenge": body.code_challenge, "port": body.redirect_port,
        "device": _device_label(body.device_name),
    }), ex=get_settings().desktop_code_ttl_seconds)
    query = urlencode({"code": code, "state": body.state})
    return DesktopAuthorizeOut(redirect_url=f"http://127.0.0.1:{body.redirect_port}/callback?{query}")


@router.post("/api/auth/desktop/token", response_model=DesktopTokenOut)
async def token(body: DesktopTokenIn, request: Request, db: DB) -> DesktopTokenOut:
    ip = ratelimit.client_ip(request)
    await ratelimit.hit(f"desktop-token:ip:{ip}", 30)
    raw = await ratelimit.get_redis().getdel(f"desktop:code:{hash_token(body.code)}")  # un solo uso
    if not raw:
        raise _bad_code
    saved = json.loads(raw)
    # PKCE: solo quien generó el challenge (la app que abrió el navegador) conoce el verifier
    if saved["port"] != body.redirect_port or not hmac.compare_digest(_s256(body.code_verifier), saved["challenge"]):
        raise _bad_code
    user = await db.get(User, uuid.UUID(saved["user_id"]))
    if not user or not user.is_active:
        raise _bad_code
    access, refresh = await svc.issue_session(db, user, saved["device"], ip, kind="desktop")
    await db.commit()
    return _tokens(access, refresh)


@router.post("/api/auth/desktop/refresh", response_model=DesktopTokenOut)
async def refresh(body: DesktopRefreshIn, request: Request, db: DB) -> DesktopTokenOut:
    ip = ratelimit.client_ip(request)
    await ratelimit.hit(f"desktop-refresh:ip:{ip}", 120)
    try:
        _, access, new_refresh = await svc.rotate(db, body.refresh_token, "", ip, kind="desktop")
    except svc.RefreshError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sesión del equipo vencida o revocada") from None
    return _tokens(access, new_refresh)


@router.post("/api/auth/desktop/logout", status_code=204)
async def logout(body: DesktopRefreshIn, db: DB) -> None:
    """Cerrar sesión desde la app: revoca el equipo (todas las rotaciones de su refresh)."""
    row = await svc.family_of(db, body.refresh_token)
    if row and row.kind == "desktop":
        await svc.revoke_family(db, row.family_id)
        await db.commit()


# ---------- instalador ----------

_VERSION_RE = re.compile(r"(\d+\.\d+\.\d+)")
_sha_cache: dict[tuple, str] = {}


def _installer() -> Path | None:
    """El .exe publicado en <data_dir>/desktop/ (solo el nombre: nunca una ruta fuera de esa carpeta)."""
    name = os.path.basename(get_settings().desktop_file.strip())
    if not name.lower().endswith(".exe"):
        return None
    path = Path(get_settings().data_dir) / "desktop" / name
    return path if path.is_file() else None


def _sha256(path: Path) -> str:
    st = path.stat()
    key = (str(path), st.st_size, st.st_mtime_ns)  # se recalcula solo si el archivo cambia
    if key not in _sha_cache:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        _sha_cache.clear()
        _sha_cache[key] = h.hexdigest()
    return _sha_cache[key]


@router.get("/api/desktop/latest", response_model=DesktopLatestOut)
async def latest() -> DesktopLatestOut:
    """Última versión del instalador. La app compara versiones y verifica el SHA-256 antes de ejecutarlo."""
    s = get_settings()
    path = _installer()
    version = s.desktop_version or (m.group(1) if path and (m := _VERSION_RE.search(path.name)) else "")
    url = s.desktop_url or (f"{s.public_url}/api/desktop/download" if path else "")
    sha = s.desktop_sha256 or (await asyncio.to_thread(_sha256, path) if path else "")
    if not (version and url and sha):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Todavía no hay una versión publicada")
    return DesktopLatestOut(version=version, url=url, sha256=sha.lower(), notas=s.desktop_notes)


@router.get("/api/desktop/download")
async def download(request: Request) -> FileResponse:
    """Descarga directa del instalador (el botón de /herramientas y las actualizaciones de la app)."""
    path = _installer()
    if not path:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Todavía no hay una versión publicada")
    await ratelimit.hit(f"desktop-download:ip:{ratelimit.client_ip(request)}", 30, 3600)
    return FileResponse(path, media_type="application/vnd.microsoft.portable-executable", filename=path.name,
                        headers={"Cache-Control": "public, max-age=3600"})
