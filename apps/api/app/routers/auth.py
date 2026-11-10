"""Endpoints de autenticación. Montados en /api/auth."""
import uuid

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.core import ratelimit
from app.core.config import get_settings
from app.core.deps import DB, Claims, CurrentUser
from app.core.security import create_access_token, hash_password, jwks, needs_rehash, verify_password
from app.models import RefreshToken, User
from app.schemas.auth import (AccessOut, ChangePasswordIn, CompleteProfileIn, EmailIn, LoginIn, MessageOut,
                              RegisterIn, ResetPasswordIn, SessionOut, TokenIn, UserOut)
from app.services import auth as svc
from app.services import beta, email

router = APIRouter(prefix="/api/auth", tags=["auth"])

GENERIC_LOGIN_ERROR = "Email o contraseña incorrectos"


# ---------- cookies y CSRF ----------

def _set_refresh_cookie(response: Response, token: str) -> None:
    s = get_settings()
    response.set_cookie(s.refresh_cookie_name, token, max_age=s.refresh_ttl_seconds,
                        httponly=True, secure=s.cookie_secure, samesite="strict",
                        path=s.refresh_cookie_path)


def _clear_refresh_cookie(response: Response) -> None:
    s = get_settings()
    response.delete_cookie(s.refresh_cookie_name, path=s.refresh_cookie_path,
                           secure=s.cookie_secure, httponly=True, samesite="strict")


def _check_origin(request: Request) -> None:
    """Defensa CSRF extra para endpoints que usan la cookie: el Origin debe ser nuestro
    y el cliente debe mandar un header que un formulario de otro sitio no puede poner."""
    s = get_settings()
    origin = request.headers.get("origin")
    if origin and origin not in s.cors_origins:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Origen no permitido")
    if request.headers.get("x-fadex-csrf") != "1":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Falta cabecera CSRF")


def _access_out(token: str) -> AccessOut:
    return AccessOut(access_token=token, expires_in=get_settings().access_ttl_seconds)


def _ua(request: Request) -> str:
    return request.headers.get("user-agent", "")


# ---------- registro, login, refresh, logout ----------

@router.post("/register", status_code=202, response_model=MessageOut)
async def register(body: RegisterIn, request: Request, db: DB) -> MessageOut:
    """Respuesta idéntica exista o no el email (no revela qué cuentas existen)."""
    ip = ratelimit.client_ip(request)
    await ratelimit.hit(f"register:ip:{ip}", 10)
    email_norm = body.email.lower()
    existing = (await db.execute(select(User).where(User.email == email_norm))).scalar_one_or_none()
    if existing:
        await email.send_account_exists(email_norm)
    else:
        user = User(email=email_norm, password_hash=hash_password(body.password),
                    display_name=body.display_name.strip(), whatsapp=body.whatsapp,
                    privacy_accepted_at=svc.now())
        db.add(user)
        try:
            await db.flush()
        except IntegrityError:  # carrera con otro registro del mismo email
            await db.rollback()
        else:
            token = await svc.create_one_time(db, user, "verify_email",
                                              get_settings().email_token_ttl_seconds)
            await db.commit()
            await email.send_verify_email(email_norm, token)
    return MessageOut(detail="Revisa tu correo para confirmar la cuenta.")


@router.post("/login", response_model=AccessOut)
async def login(body: LoginIn, request: Request, response: Response, db: DB) -> AccessOut:
    s = get_settings()
    ip, email_norm = ratelimit.client_ip(request), body.email.lower()
    await ratelimit.hit(f"login:ip:{ip}", s.login_max_per_ip)
    await ratelimit.hit(f"login:email:{email_norm}", s.login_max_per_email)

    user = (await db.execute(select(User).where(User.email == email_norm))).scalar_one_or_none()
    # verify_password se ejecuta aunque el usuario no exista (mismo tiempo de respuesta)
    if not verify_password(body.password, user.password_hash if user else None) or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, GENERIC_LOGIN_ERROR)
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)
    await ratelimit.reset(f"login:email:{email_norm}")

    access, refresh = await svc.issue_session(db, user, _ua(request), ip)
    await db.commit()
    _set_refresh_cookie(response, refresh)
    return _access_out(access)


@router.post("/refresh", response_model=AccessOut)
async def refresh(request: Request, response: Response, db: DB) -> AccessOut:
    _check_origin(request)
    token = request.cookies.get(get_settings().refresh_cookie_name)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sesión no encontrada")
    await ratelimit.hit(f"refresh:ip:{ratelimit.client_ip(request)}", 120)
    try:
        _, access, new_refresh = await svc.rotate(db, token, _ua(request), ratelimit.client_ip(request))
    except svc.RefreshError:
        _clear_refresh_cookie(response)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sesión expirada") from None
    _set_refresh_cookie(response, new_refresh)
    return _access_out(access)


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response, db: DB) -> None:
    _check_origin(request)
    token = request.cookies.get(get_settings().refresh_cookie_name)
    if token and (row := await svc.family_of(db, token)):
        await svc.revoke_family(db, row.family_id)
        await db.commit()
    _clear_refresh_cookie(response)


@router.post("/logout-all", status_code=204)
async def logout_all(user: CurrentUser, response: Response, db: DB) -> None:
    await svc.revoke_all(db, user.id)
    await db.commit()
    _clear_refresh_cookie(response)


# ---------- email y contraseña ----------

@router.post("/verify-email", response_model=MessageOut)
async def verify_email(body: TokenIn, db: DB) -> MessageOut:
    user = await svc.consume_one_time(db, body.token, "verify_email")
    if not user:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Enlace inválido o vencido")
    user.email_verified_at = user.email_verified_at or svc.now()
    seat = await beta.try_assign_seat(db, user)  # los primeros N confirmados entran a la beta
    await db.commit()
    return MessageOut(detail="Email confirmado." + (" ¡Tienes acceso a la beta de las herramientas!" if seat else ""))


@router.post("/resend-verification", status_code=202, response_model=MessageOut)
async def resend_verification(user: CurrentUser, db: DB) -> MessageOut:
    await ratelimit.hit(f"resend:{user.id}", 3, 3600)
    if not user.email_verified:
        token = await svc.create_one_time(db, user, "verify_email", get_settings().email_token_ttl_seconds)
        await db.commit()
        await email.send_verify_email(user.email, token)
    return MessageOut(detail="Si tu email no estaba confirmado, te enviamos un nuevo enlace.")


@router.post("/forgot-password", status_code=202, response_model=MessageOut)
async def forgot_password(body: EmailIn, request: Request, db: DB) -> MessageOut:
    email_norm = body.email.lower()
    await ratelimit.hit(f"forgot:ip:{ratelimit.client_ip(request)}", 10)
    await ratelimit.hit(f"forgot:email:{email_norm}", 3, 3600)
    user = (await db.execute(select(User).where(User.email == email_norm))).scalar_one_or_none()
    if user and user.is_active:
        token = await svc.create_one_time(db, user, "reset_password", get_settings().reset_token_ttl_seconds)
        await db.commit()
        await email.send_reset_email(email_norm, token)
    return MessageOut(detail="Si existe una cuenta con ese email, te enviamos un enlace.")


@router.post("/reset-password", response_model=MessageOut)
async def reset_password(body: ResetPasswordIn, request: Request, db: DB) -> MessageOut:
    await ratelimit.hit(f"reset:ip:{ratelimit.client_ip(request)}", 10)
    user = await svc.consume_one_time(db, body.token, "reset_password")
    if not user:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Enlace inválido o vencido")
    user.password_hash = hash_password(body.password)
    user.password_changed_at = svc.now()
    user.email_verified_at = user.email_verified_at or svc.now()  # demostró controlar el email
    await beta.try_assign_seat(db, user)
    await svc.revoke_all(db, user.id)  # cierra todas las sesiones abiertas
    await db.commit()
    return MessageOut(detail="Contraseña actualizada. Inicia sesión de nuevo.")


@router.post("/change-password", response_model=AccessOut)
async def change_password(body: ChangePasswordIn, request: Request, response: Response,
                          user: CurrentUser, db: DB) -> AccessOut:
    await ratelimit.hit(f"change:{user.id}", 5)
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "La contraseña actual no es correcta")
    user.password_hash = hash_password(body.new_password)
    user.password_changed_at = svc.now()
    await svc.revoke_all(db, user.id)
    access, refresh = await svc.issue_session(db, user, _ua(request), ratelimit.client_ip(request))
    await db.commit()
    _set_refresh_cookie(response, refresh)
    return _access_out(access)


# ---------- cuenta y sesiones ----------

@router.post("/complete-profile", response_model=AccessOut)
async def complete_profile(body: CompleteProfileIn, user: CurrentUser, claims: Claims, db: DB) -> AccessOut:
    """Tras entrar con Google: WhatsApp + aviso de privacidad. Devuelve un access token nuevo
    (puede traer el acceso a la beta recién asignado)."""
    await ratelimit.hit(f"profile:{user.id}", 10)
    user.whatsapp = body.whatsapp
    user.privacy_accepted_at = user.privacy_accepted_at or svc.now()
    if body.display_name:
        user.display_name = body.display_name.strip()
    await beta.try_assign_seat(db, user)
    await db.commit()
    token = create_access_token(user.id, user.role, uuid.UUID(claims["sid"]), user.email_verified,
                                svc.password_version(user), user.beta)
    return _access_out(token)


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> User:
    return user


@router.get("/sessions", response_model=list[SessionOut])
async def sessions(user: CurrentUser, claims: Claims, db: DB) -> list[SessionOut]:
    """Sesiones activas (una por familia de refresh tokens)."""
    rows = (await db.execute(
        select(RefreshToken.family_id, func.min(RefreshToken.created_at), func.max(RefreshToken.created_at))
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        .group_by(RefreshToken.family_id)
        .having(func.max(RefreshToken.expires_at) > svc.now()))).all()
    out = []
    for family_id, first, last in rows:
        latest = (await db.execute(select(RefreshToken).where(
            RefreshToken.family_id == family_id).order_by(RefreshToken.created_at.desc()).limit(1))).scalar_one()
        out.append(SessionOut(id=family_id, created_at=svc.utc(first), last_used_at=svc.utc(last),
                              user_agent=latest.user_agent, ip=latest.ip,
                              current=str(family_id) == claims["sid"], kind=latest.kind or "web"))
    return sorted(out, key=lambda s: s.last_used_at, reverse=True)


@router.delete("/sessions/{session_id}", status_code=204)
async def revoke_session(session_id: str, user: CurrentUser, db: DB) -> None:
    try:
        fid = uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Sesión no encontrada") from None
    owns = (await db.execute(select(RefreshToken.id).where(
        RefreshToken.family_id == fid, RefreshToken.user_id == user.id).limit(1))).first()
    if not owns:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Sesión no encontrada")
    await svc.revoke_family(db, fid)
    await db.commit()


@router.get("/.well-known/jwks.json")
async def public_keys() -> dict:
    return jwks()
