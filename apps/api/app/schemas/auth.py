import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.core.config import get_settings
from app.core.phone import normalize_whatsapp


def _check_whatsapp(v: str) -> str:
    return normalize_whatsapp(v)


def _check_privacy(v: bool) -> bool:
    if v is not True:
        raise ValueError("Debes aceptar el aviso de privacidad")
    return v


def _check_password(v: str) -> str:
    s = get_settings()
    if len(v) < s.password_min_length:
        raise ValueError(f"La contraseña debe tener al menos {s.password_min_length} caracteres")
    if len(v) > 256:
        raise ValueError("La contraseña es demasiado larga")
    if v.strip() != v or len(set(v)) < 4:
        raise ValueError("La contraseña es demasiado débil")
    return v


class RegisterIn(BaseModel):
    email: EmailStr
    password: str
    display_name: str = Field(min_length=2, max_length=80)
    whatsapp: str
    accept_privacy: bool = False

    _pw = field_validator("password")(_check_password)
    _wa = field_validator("whatsapp")(_check_whatsapp)
    _pv = field_validator("accept_privacy")(_check_privacy)


class CompleteProfileIn(BaseModel):
    """Lo que falta tras entrar con Google: WhatsApp y aceptación del aviso de privacidad."""
    whatsapp: str
    accept_privacy: bool = False
    display_name: str | None = Field(default=None, min_length=2, max_length=80)

    _wa = field_validator("whatsapp")(_check_whatsapp)
    _pv = field_validator("accept_privacy")(_check_privacy)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(max_length=256)


class EmailIn(BaseModel):
    email: EmailStr


class TokenIn(BaseModel):
    token: str = Field(min_length=20, max_length=128)


class ResetPasswordIn(TokenIn):
    password: str

    _pw = field_validator("password")(_check_password)


class ChangePasswordIn(BaseModel):
    current_password: str = Field(max_length=256)
    new_password: str

    _pw = field_validator("new_password")(_check_password)


class AccessOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserOut(BaseModel):
    id: uuid.UUID
    email: EmailStr
    display_name: str
    role: str
    email_verified: bool
    whatsapp: str | None
    profile_complete: bool
    has_password: bool
    google_linked: bool
    beta: bool
    beta_seat: int | None
    created_at: datetime

    model_config = {"from_attributes": True}


class BetaOut(BaseModel):
    seats: int
    taken: int
    available: int


class SessionOut(BaseModel):
    id: uuid.UUID  # family_id
    created_at: datetime
    last_used_at: datetime
    user_agent: str
    ip: str
    current: bool


class MessageOut(BaseModel):
    detail: str
