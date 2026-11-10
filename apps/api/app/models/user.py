import uuid
from datetime import datetime, timezone
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


NO_PASSWORD = "!"  # no es un hash Argon2 válido: verify_password siempre falla


class Role(StrEnum):
    user = "user"
    creator = "creator"  # vende en el marketplace
    admin = "admin"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)  # siempre en minúsculas
    # NO_PASSWORD: cuentas creadas con Google que aún no eligieron contraseña (nunca valida)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(80))
    role: Mapped[str] = mapped_column(String(16), default=Role.user)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    password_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    whatsapp: Mapped[str | None] = mapped_column(String(20))              # E.164: +526141151657
    privacy_accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    google_sub: Mapped[str | None] = mapped_column(String(64), unique=True)
    # Lugar 1..N de la beta cerrada (único: dos usuarios nunca comparten lugar)
    beta_seat: Mapped[int | None] = mapped_column(unique=True)

    sessions: Mapped[list["RefreshToken"]] = relationship(back_populates="user", cascade="all, delete-orphan")

    @property
    def email_verified(self) -> bool:
        return self.email_verified_at is not None

    @property
    def profile_complete(self) -> bool:
        return bool(self.whatsapp and self.privacy_accepted_at)

    @property
    def beta(self) -> bool:
        return self.beta_seat is not None

    @property
    def has_password(self) -> bool:
        return self.password_hash != NO_PASSWORD

    @property
    def google_linked(self) -> bool:
        return self.google_sub is not None


class RefreshToken(Base):
    """Un refresh token rotativo. Todos los de una misma sesión comparten `family_id`;
    si se reutiliza uno ya rotado (posible robo) se revoca la familia completa."""
    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    family_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))   # rotado
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str] = mapped_column(String(256), default="")
    ip: Mapped[str] = mapped_column(String(64), default="")
    # web: cookie httpOnly del navegador · desktop: app de escritorio (token en el cuerpo, ver routers/desktop.py).
    # Un token solo se canjea por el endpoint de su tipo.
    kind: Mapped[str] = mapped_column(String(16), default="web", server_default="web")

    user: Mapped[User] = relationship(back_populates="sessions")


class OneTimeToken(Base):
    """Tokens de un solo uso: verificación de email y recuperación de contraseña."""
    __tablename__ = "one_time_tokens"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    purpose: Mapped[str] = mapped_column(String(16))  # verify_email | reset_password
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
