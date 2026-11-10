"""Validación de números de WhatsApp. Se guardan en formato E.164 (+526141151657)."""
import phonenumbers

from app.core.config import get_settings


def normalize_whatsapp(raw: str) -> str:
    """Lanza ValueError si el número no es válido. Sin lada se asume la región por defecto (MX)."""
    text = (raw or "").strip()
    if not text or len(text) > 32:
        raise ValueError("Escribe tu número de WhatsApp")
    try:
        num = phonenumbers.parse(text, get_settings().phone_default_region)
    except phonenumbers.NumberParseException:
        raise ValueError("Número de WhatsApp inválido") from None
    if not phonenumbers.is_valid_number(num):
        raise ValueError("Número de WhatsApp inválido: revisa la lada y los 10 dígitos")
    return phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.E164)
