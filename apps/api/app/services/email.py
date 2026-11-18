"""Envío de emails transaccionales.

Orden: EmailJS (si está configurado) → SMTP (si hay host) → log (desarrollo). En env=test se guardan en `outbox`.

Con EmailJS todos los avisos usan UNA plantilla genérica (FADEX_EMAILJS_TEMPLATE_GENERIC) con estas variables:
    to_email, to_name, subject, title, message_html, button_label, button_url, footer
y la encuesta usa otra (FADEX_EMAILJS_TEMPLATE_FEEDBACK); ver send_feedback(). Las plantillas están en
docs/emailjs/.
"""
import html
import logging
from email.message import EmailMessage

import aiosmtplib
import httpx

from app.core.config import get_settings

log = logging.getLogger("fadex.email")
outbox: list[EmailMessage] = []  # solo se llena en env=test
EMAILJS_URL = "https://api.emailjs.com/api/v1.0/email/send"
FOOTER = "FADEX Labs · Chihuahua, México · fadexlabs.com"


def emailjs_enabled() -> bool:
    s = get_settings()
    return bool(s.emailjs_service_id and s.emailjs_public_key and s.emailjs_private_key)


async def post_emailjs(template_id: str, params: dict) -> None:
    """Llamada a la API REST de EmailJS (se sustituye en las pruebas)."""
    s = get_settings()
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(EMAILJS_URL, json={
            "service_id": s.emailjs_service_id, "template_id": template_id, "user_id": s.emailjs_public_key,
            "accessToken": s.emailjs_private_key, "template_params": params})
    if r.status_code != 200:
        raise RuntimeError(f"EmailJS respondió {r.status_code}: {r.text[:200]}")


def _paragraphs_html(text: str) -> str:
    return "".join(f"<p>{html.escape(p).replace(chr(10), '<br>')}</p>" for p in text.strip().split("\n\n") if p.strip())


async def send(to: str, subject: str, text: str, *, title: str = "", button: tuple[str, str] | None = None,
               to_name: str = "") -> None:
    """`text` es el cuerpo en texto plano; `button` = (texto, url) se agrega al final (y como botón en EmailJS)."""
    s = get_settings()
    plain = text.rstrip() + (f"\n\n{button[0]}: {button[1]}\n" if button else "\n")
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = s.smtp_from, to, subject
    msg.set_content(plain)
    if s.env == "test":
        outbox.append(msg)
        return
    try:
        if emailjs_enabled() and s.emailjs_template_generic:
            await post_emailjs(s.emailjs_template_generic, {
                "to_email": to, "to_name": to_name or "", "subject": subject, "title": title or subject,
                "message_html": _paragraphs_html(text), "button_label": button[0] if button else "Ir a FADEX Labs",
                "button_url": button[1] if button else s.public_url, "footer": FOOTER})
            return
        if not s.smtp_host:
            log.warning("Email sin configurar; email para %s:\n%s\n%s", to, subject, plain)
            return
        await aiosmtplib.send(msg, hostname=s.smtp_host, port=s.smtp_port, start_tls=True,
                              username=s.smtp_user or None, password=s.smtp_password or None, timeout=20)
    except Exception:  # un fallo de correo no debe tumbar el registro ni el login
        log.exception("No se pudo enviar el email a %s", to)


async def send_verify_email(to: str, token: str) -> None:
    url = f"{get_settings().public_url}/verificar-email?token={token}"
    await send(to, "Confirma tu email · FADEX Labs",
               "Hola,\n\nConfirma tu cuenta de FADEX Labs con el botón de abajo. El enlace vence en 24 horas.\n\n"
               "Si no creaste esta cuenta, ignora este mensaje.",
               title="Confirma tu email", button=("Confirmar mi email", url))


async def send_reset_email(to: str, token: str) -> None:
    url = f"{get_settings().public_url}/restablecer?token={token}"
    await send(to, "Restablece tu contraseña · FADEX Labs",
               "Hola,\n\nPara elegir una nueva contraseña usa el botón de abajo (vence en 30 minutos).\n\n"
               "Si no lo pediste, ignora este mensaje; tu contraseña no cambia.",
               title="Restablece tu contraseña", button=("Elegir nueva contraseña", url))


async def send_account_exists(to: str) -> None:
    url = f"{get_settings().public_url}/recuperar"
    await send(to, "Intento de registro · FADEX Labs",
               "Alguien intentó crear una cuenta con este email, pero ya tienes una.\n\n"
               "Si olvidaste tu contraseña puedes recuperarla desde aquí.",
               title="Ya tienes una cuenta", button=("Recuperar mi contraseña", url))


STARS = {1: "★☆☆☆☆", 2: "★★☆☆☆", 3: "★★★☆☆", 4: "★★★★☆", 5: "★★★★★"}


async def send_feedback(*, user_email: str, user_name: str, source: str, tool: str, rating: int, comment: str,
                        stopped: bool, job_ref: str, details: str) -> None:
    """Opinión de un usuario → FADEX_FEEDBACK_TO. Variables de la plantilla de encuesta:
    to_email, reply_to, user_name, user_email, tool, source, rating, stars, comment, outcome, job_ref, details."""
    s = get_settings()
    tool_name = "Tracklist ID" if tool == "tracklist" else "DJ Library Upgrader"
    where = "app de escritorio" if source == "desktop" else "web"
    outcome = "Lo detuvo antes de terminar" if stopped else "Terminó"
    params = {"to_email": s.feedback_to, "reply_to": user_email, "user_name": user_name, "user_email": user_email,
              "tool": tool_name, "source": where, "rating": str(rating), "stars": STARS.get(rating, ""),
              "comment": comment or "(sin comentario)", "outcome": outcome, "job_ref": job_ref, "details": details}
    text = "\n".join(f"{k}: {v}" for k, v in params.items() if k != "to_email")
    if s.env != "test" and emailjs_enabled() and s.emailjs_template_feedback:
        try:
            await post_emailjs(s.emailjs_template_feedback, params)
            return
        except Exception:
            log.exception("EmailJS falló con la encuesta; se intenta por la vía normal")
    await send(s.feedback_to, f"Encuesta {tool_name}: {STARS.get(rating, rating)} · {user_name}", text,
               title=f"Nueva opinión de {tool_name}")
