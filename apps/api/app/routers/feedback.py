"""Encuesta al terminar o detener un trabajo (web y app de escritorio). Montado en /api/feedback.

Se guarda en la base (una opinión por trabajo y usuario) y se envía por EmailJS a FADEX_FEEDBACK_TO.
Si el usuario dejó comentario, la respuesta trae el Google Forms (acceso prioritario / trimestre gratis).
"""
import json
import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core import ratelimit
from app.core.config import get_settings
from app.core.deps import DB
from app.models import Feedback, ToolJob
from app.routers.tools import ToolUser
from app.schemas.tools import FeedbackIn, FeedbackOut
from app.services import email

router = APIRouter(prefix="/api/feedback", tags=["feedback"])


def _details(d: dict) -> dict:
    """Solo conteos y textos cortos del resumen (nunca rutas ni datos arbitrarios largos)."""
    out = {}
    for k, v in list(d.items())[:20]:
        if isinstance(v, bool | int | float):
            out[str(k)[:40]] = v
        elif isinstance(v, str):
            out[str(k)[:40]] = v[:80]
    return out


@router.post("", response_model=FeedbackOut, status_code=201)
async def send_feedback(body: FeedbackIn, user: ToolUser, db: DB) -> FeedbackOut:
    await ratelimit.hit(f"feedback:{user.id}", 20, 3600)
    if body.source == "web":  # en la web, el trabajo tiene que ser suyo
        try:
            job_id = uuid.UUID(body.job_ref)
        except ValueError:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No encontrado") from None
        owns = (await db.execute(select(ToolJob.id).where(ToolJob.id == job_id, ToolJob.user_id == user.id,
                                                          ToolJob.tool == body.tool))).first()
        if not owns:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No encontrado")
    details = _details(body.details)
    db.add(Feedback(user_id=user.id, source=body.source, tool=body.tool, job_ref=body.job_ref, rating=body.rating,
                    comment=body.comment, stopped=body.stopped, details=details))
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Ya nos diste tu opinión de este trabajo. ¡Gracias!") from None
    await email.send_feedback(user_email=user.email, user_name=user.display_name, source=body.source,
                              tool=body.tool, rating=body.rating, comment=body.comment, stopped=body.stopped,
                              job_ref=body.job_ref, details=json.dumps(details, ensure_ascii=False))
    form = get_settings().feedback_form_url
    return FeedbackOut(detail="¡Gracias por tu opinión!", form_url=form if body.comment and form else None)
