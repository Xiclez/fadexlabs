"""Lógica de sesiones: emisión, rotación y revocación de refresh tokens; tokens de un solo uso."""
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import create_access_token, hash_token, new_opaque_token
from app.models import OneTimeToken, RefreshToken, User


def utc(dt: datetime | None) -> datetime | None:
    """SQLite devuelve fechas sin zona; las tratamos siempre como UTC."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def now() -> datetime:
    return datetime.now(timezone.utc)


def password_version(user: User) -> int:
    """Milisegundos del último cambio de contraseña; va en el claim `pv` del access token."""
    return int(utc(user.password_changed_at).timestamp() * 1000)


class RefreshError(Exception):
    pass


async def issue_session(db: AsyncSession, user: User, user_agent: str, ip: str,
                        family_id: uuid.UUID | None = None, kind: str = "web") -> tuple[str, str]:
    """Crea un refresh token (nueva sesión o rotación dentro de `family_id`).
    Devuelve (access_token, refresh_token). El llamador hace commit."""
    s = get_settings()
    family_id = family_id or uuid.uuid4()
    refresh = new_opaque_token()
    db.add(RefreshToken(user_id=user.id, family_id=family_id, token_hash=hash_token(refresh),
                        expires_at=now() + timedelta(seconds=s.refresh_ttl_seconds),
                        user_agent=user_agent[:256], ip=ip[:64], kind=kind))
    access = create_access_token(user.id, user.role, family_id, user.email_verified,
                                 password_version(user), user.beta)
    return access, refresh


async def rotate(db: AsyncSession, refresh: str, user_agent: str, ip: str,
                 kind: str = "web") -> tuple[User, str, str]:
    """Canjea un refresh token por uno nuevo. Si el token ya se había usado o revocado,
    se trata como robo y se revoca toda la familia (todas las rotaciones de esa sesión).
    `kind` es el tipo de sesión del endpoint: un token de la app no vale como cookie y viceversa."""
    row = (await db.execute(select(RefreshToken).where(
        RefreshToken.token_hash == hash_token(refresh)).with_for_update())).scalar_one_or_none()
    if row is None or (row.kind or "web") != kind:
        raise RefreshError("desconocido")
    if row.used_at or row.revoked_at:
        await revoke_family(db, row.family_id)
        await db.commit()
        raise RefreshError("reutilizado")
    if utc(row.expires_at) <= now():
        raise RefreshError("expirado")
    user = await db.get(User, row.user_id)
    if not user or not user.is_active:
        raise RefreshError("usuario inactivo")
    row.used_at = now()
    # la app de escritorio conserva el nombre del equipo con que se autorizó
    ua = row.user_agent if kind == "desktop" else user_agent
    access, new_refresh = await issue_session(db, user, ua, ip, family_id=row.family_id, kind=kind)
    await db.commit()
    return user, access, new_refresh


async def revoke_family(db: AsyncSession, family_id: uuid.UUID) -> None:
    await db.execute(update(RefreshToken).where(RefreshToken.family_id == family_id,
                                                RefreshToken.revoked_at.is_(None)).values(revoked_at=now()))


async def revoke_all(db: AsyncSession, user_id: uuid.UUID) -> None:
    await db.execute(update(RefreshToken).where(RefreshToken.user_id == user_id,
                                                RefreshToken.revoked_at.is_(None)).values(revoked_at=now()))


async def family_of(db: AsyncSession, refresh: str) -> RefreshToken | None:
    return (await db.execute(select(RefreshToken).where(
        RefreshToken.token_hash == hash_token(refresh)))).scalar_one_or_none()


# ---------- tokens de un solo uso ----------

async def create_one_time(db: AsyncSession, user: User, purpose: str, ttl: int) -> str:
    # Invalida los pendientes del mismo tipo: solo vale el último enlace enviado.
    await db.execute(update(OneTimeToken).where(OneTimeToken.user_id == user.id,
                                                OneTimeToken.purpose == purpose,
                                                OneTimeToken.used_at.is_(None)).values(used_at=now()))
    token = new_opaque_token()
    db.add(OneTimeToken(user_id=user.id, purpose=purpose, token_hash=hash_token(token),
                        expires_at=now() + timedelta(seconds=ttl)))
    return token


async def consume_one_time(db: AsyncSession, token: str, purpose: str) -> User | None:
    row = (await db.execute(select(OneTimeToken).where(
        OneTimeToken.token_hash == hash_token(token), OneTimeToken.purpose == purpose
    ).with_for_update())).scalar_one_or_none()
    if row is None or row.used_at or utc(row.expires_at) <= now():
        return None
    row.used_at = now()
    return await db.get(User, row.user_id)
