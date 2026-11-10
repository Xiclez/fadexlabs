"""Envío de emails transaccionales. Sin SMTP configurado (dev) se registran en el log."""
import logging
from email.message import EmailMessage

import aiosmtplib

from app.core.config import get_settings

log = logging.getLogger("fadex.email")
outbox: list[EmailMessage] = []  # solo se llena en env=test


async def send(to: str, subject: str, text: str) -> None:
    s = get_settings()
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = s.smtp_from, to, subject
    msg.set_content(text)
    if s.env == "test":
        outbox.append(msg)
        return
    if not s.smtp_host:
        log.warning("SMTP sin configurar; email para %s:\n%s\n%s", to, subject, text)
        return
    try:
        await aiosmtplib.send(msg, hostname=s.smtp_host, port=s.smtp_port, start_tls=True,
                              username=s.smtp_user or None, password=s.smtp_password or None, timeout=20)
    except Exception:  # un fallo de correo no debe tumbar el registro ni el login
        log.exception("No se pudo enviar el email a %s", to)


async def send_verify_email(to: str, token: str) -> None:
    url = f"{get_settings().public_url}/verificar-email?token={token}"
    await send(to, "Confirma tu email · FADEX Labs",
               f"Hola,\n\nConfirma tu cuenta de FADEX Labs abriendo este enlace:\n{url}\n\n"
               "Si no creaste esta cuenta, ignora este mensaje.\n")


async def send_reset_email(to: str, token: str) -> None:
    url = f"{get_settings().public_url}/restablecer?token={token}"
    await send(to, "Restablece tu contraseña · FADEX Labs",
               f"Hola,\n\nPara elegir una nueva contraseña abre este enlace (vence en 30 minutos):\n{url}\n\n"
               "Si no lo pediste, ignora este mensaje; tu contraseña no cambia.\n")


async def send_account_exists(to: str) -> None:
    url = f"{get_settings().public_url}/recuperar"
    await send(to, "Intento de registro · FADEX Labs",
               "Alguien intentó crear una cuenta con este email, pero ya tienes una.\n"
               f"Si olvidaste tu contraseña puedes recuperarla aquí: {url}\n")
