"""Dependencias de autenticación y autorización para los routers."""
import uuid
from collections.abc import Callable
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_access_token
from app.db import get_db
from app.models import User
from app.services.auth import password_version

DB = Annotated[AsyncSession, Depends(get_db)]

_unauthorized = HTTPException(status.HTTP_401_UNAUTHORIZED, "No autenticado",
                              headers={"WWW-Authenticate": "Bearer"})


def access_claims(request: Request) -> dict:
    auth = request.headers.get("authorization", "")
    scheme, _, token = auth.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise _unauthorized
    try:
        return decode_access_token(token)
    except jwt.PyJWTError:
        raise _unauthorized from None


Claims = Annotated[dict, Depends(access_claims)]


async def current_user(claims: Claims, db: DB) -> User:
    user = await db.get(User, uuid.UUID(claims["sub"]))
    # Un token emitido antes del último cambio de contraseña ya no vale.
    if not user or not user.is_active or claims["pv"] != password_version(user):
        raise _unauthorized
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def require_role(*roles: str) -> Callable:
    async def dep(user: CurrentUser) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Permisos insuficientes")
        return user
    return dep


async def verified_user(user: CurrentUser) -> User:
    if not user.email_verified:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Confirma tu email para continuar")
    return user


async def beta_user(user: CurrentUser) -> User:
    """Herramientas en beta cerrada: solo usuarios con lugar asignado (o admins)."""
    if not (user.beta or user.role == "admin"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Herramienta en beta cerrada")
    return user


BetaUser = Annotated[User, Depends(beta_user)]
