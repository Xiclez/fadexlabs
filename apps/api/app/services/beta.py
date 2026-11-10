"""Beta cerrada: los primeros N usuarios con email confirmado y WhatsApp reciben un lugar.

Cada lugar es un número 1..N con restricción UNIQUE en users.beta_seat: si dos registros
simultáneos calculan el mismo número, la base rechaza a uno y ese reintenta con el siguiente.
"""
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import User


async def taken(db: AsyncSession) -> int:
    return (await db.execute(select(func.count()).where(User.beta_seat.is_not(None)))).scalar_one()


async def try_assign_seat(db: AsyncSession, user: User) -> bool:
    """Asigna un lugar si el usuario ya califica y quedan lugares. El llamador hace commit."""
    if user.beta_seat is not None:
        return True
    if not (user.email_verified and user.profile_complete and user.is_active):
        return False
    seats = get_settings().beta_seats
    for _ in range(seats + 1):
        nxt = ((await db.execute(select(func.max(User.beta_seat)))).scalar_one() or 0) + 1
        if nxt > seats:
            return False
        try:
            async with db.begin_nested():  # SAVEPOINT: si choca, solo se deshace este intento
                user.beta_seat = nxt
                await db.flush()
            return True
        except IntegrityError:
            user.beta_seat = None  # otro registro tomó ese número: reintentar con el siguiente
    return False
