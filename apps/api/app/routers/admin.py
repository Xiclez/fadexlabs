"""Administración mínima de la beta (rol admin). Montado en /api/admin."""
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.core.deps import DB, require_role
from app.models import ToolJob, User
from app.schemas.tools import AdminJobOut, AdminUserOut
from app.services import tools as svc

router = APIRouter(prefix="/api/admin", tags=["admin"])
Admin = Annotated[User, Depends(require_role("admin"))]


@router.get("/beta/users", response_model=list[AdminUserOut])
async def beta_users(admin: Admin, db: DB, all: bool = False) -> list[User]:
    """Usuarios con lugar en la beta (o todos, con ?all=true, para poder dar un lugar)."""
    q = select(User).order_by(User.beta_seat.is_(None), User.beta_seat, User.created_at)
    if not all:
        q = q.where(User.beta_seat.is_not(None))
    return list((await db.execute(q.limit(500))).scalars())


@router.put("/beta/users/{user_id}/seat", response_model=AdminUserOut)
async def grant_seat(user_id: uuid.UUID, admin: Admin, db: DB) -> User:
    """Da el primer lugar libre (1..N). Nunca supera FADEX_BETA_SEATS."""
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No encontrado")
    if user.beta_seat is not None:
        return user
    taken = set((await db.execute(select(User.beta_seat).where(User.beta_seat.is_not(None)))).scalars())
    free = [n for n in range(1, get_settings().beta_seats + 1) if n not in taken]
    if not free:
        raise HTTPException(status.HTTP_409_CONFLICT, "No quedan lugares en la beta")
    user.beta_seat = free[0]
    try:
        await db.commit()
    except IntegrityError:  # otro admin tomó ese número al mismo tiempo
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Ese lugar se acaba de ocupar; intenta de nuevo") from None
    return user


@router.delete("/beta/users/{user_id}/seat", response_model=AdminUserOut)
async def revoke_seat(user_id: uuid.UUID, admin: Admin, db: DB) -> User:
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No encontrado")
    user.beta_seat = None
    await db.commit()
    return user


@router.get("/jobs", response_model=list[AdminJobOut])
async def jobs(admin: Admin, db: DB, limit: int = 50, offset: int = 0) -> list[dict]:
    rows = (await db.execute(select(ToolJob, User.email).join(User, User.id == ToolJob.user_id)
                             .order_by(ToolJob.created_at.desc())
                             .limit(max(1, min(limit, 200))).offset(max(0, offset)))).all()
    return [{**svc.job_out(j), "user_id": j.user_id, "user_email": email, "error": j.error} for j, email in rows]
