"""Estado público de la beta cerrada (para el contador de lugares en la web)."""
from fastapi import APIRouter, Response

from app.core.config import get_settings
from app.core.deps import DB
from app.schemas.auth import BetaOut
from app.services import beta

router = APIRouter(prefix="/api/beta", tags=["beta"])


@router.get("", response_model=BetaOut)
async def beta_status(response: Response, db: DB) -> BetaOut:
    seats, n = get_settings().beta_seats, await beta.taken(db)
    response.headers["Cache-Control"] = "public, max-age=30"
    return BetaOut(seats=seats, taken=n, available=max(0, seats - n))
