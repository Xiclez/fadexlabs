"""Hash de contraseñas (Argon2id), JWT de acceso (Ed25519) y tokens opacos."""
import base64
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.core.config import get_settings

_hasher = PasswordHasher()  # Argon2id con parámetros recomendados por argon2-cffi
# Hash fijo para gastar el mismo tiempo cuando el usuario no existe (evita enumeración por tiempo)
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


# ---------- Tokens opacos (refresh, verificación, reset) ----------

def new_opaque_token() -> str:
    return secrets.token_urlsafe(32)  # 256 bits


def hash_token(token: str) -> str:
    """En la base de datos solo se guarda el SHA-256 del token, nunca el token."""
    return hashlib.sha256(token.encode()).hexdigest()


# ---------- JWT de acceso ----------

class _Keys:
    private = None
    public = None
    kid = ""


def _load_keys() -> _Keys:
    if _Keys.private is not None:
        return _Keys
    s = get_settings()
    if s.jwt_private_key:
        priv = serialization.load_pem_private_key(s.jwt_private_key.encode(), password=None)
    elif s.env in ("dev", "test"):
        priv = Ed25519PrivateKey.generate()  # efímera: los tokens no sobreviven a un reinicio
    else:
        raise RuntimeError("FADEX_JWT_PRIVATE_KEY es obligatoria en producción")
    pub = priv.public_key()
    raw = pub.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    _Keys.private, _Keys.public = priv, pub
    _Keys.kid = hashlib.sha256(raw).hexdigest()[:16]
    return _Keys


def create_access_token(user_id: uuid.UUID, role: str, session_id: uuid.UUID,
                        email_verified: bool, password_version: int, beta: bool = False) -> str:
    s, k = get_settings(), _load_keys()
    now = datetime.now(timezone.utc)
    claims = {
        "iss": s.jwt_issuer, "aud": s.jwt_audience, "sub": str(user_id),
        "iat": now, "nbf": now, "exp": now + timedelta(seconds=s.access_ttl_seconds),
        "jti": uuid.uuid4().hex, "sid": str(session_id), "role": role,
        "ev": email_verified, "pv": password_version, "beta": beta, "typ": "access",
    }
    return jwt.encode(claims, k.private, algorithm="EdDSA", headers={"kid": k.kid})


def decode_access_token(token: str) -> dict:
    """Lanza jwt.PyJWTError si el token no es válido."""
    s, k = get_settings(), _load_keys()
    claims = jwt.decode(token, k.public, algorithms=["EdDSA"], audience=s.jwt_audience,
                        issuer=s.jwt_issuer, options={"require": ["exp", "iat", "sub", "sid", "pv"]})
    if claims.get("typ") != "access":
        raise jwt.InvalidTokenError("tipo de token incorrecto")
    return claims


def jwks() -> dict:
    """Clave pública para que otros servicios (descargas, tracklist, vpm) verifiquen tokens."""
    k = _load_keys()
    raw = k.public.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    x = base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
    return {"keys": [{"kty": "OKP", "crv": "Ed25519", "x": x, "kid": k.kid, "alg": "EdDSA", "use": "sig"}]}
