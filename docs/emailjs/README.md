# EmailJS para FADEX Labs

La API manda todos sus correos por EmailJS cuando está configurado (si no, usa SMTP y, sin SMTP, solo el log).
Se usan **dos plantillas**, así que alcanza el plan gratuito (200 correos al mes y 2 plantillas). Si la beta
crece, el plan de pago sube el límite sin cambiar nada del código.

| Plantilla | Para qué | Archivo |
|---|---|---|
| `fadex_generic` | Confirmar email, restablecer contraseña, "ya tienes cuenta", trabajo listo o con error | `fadex_generic.html` |
| `fadex_feedback` | Encuesta al terminar o detener un trabajo (web y app de escritorio) → a ti | `fadex_feedback.html` |

## 1. Servicio de correo

EmailJS → **Email Services → Add New Service** → Gmail (o el proveedor que uses para `no-reply`). Anota el
**Service ID** (p. ej. `service_fadex`).

## 2. Plantillas

**Email Templates → Create New Template**, una por archivo. En **Content** pulsa *Edit content*, cambia al modo
código (`<>`) y pega el HTML del archivo. Después llena los campos de la derecha:

**fadex_generic**

| Campo | Valor |
|---|---|
| Subject | `{{subject}}` |
| To Email | `{{to_email}}` |
| From Name | `FADEX Labs` |
| Reply To | tu correo de soporte |

**fadex_feedback**

| Campo | Valor |
|---|---|
| Subject | `Encuesta {{tool}}: {{stars}} · {{user_name}}` |
| To Email | `{{to_email}}` (la API manda `ibarraorvil@gmail.com`) |
| From Name | `FADEX Labs · Encuestas` |
| Reply To | `{{reply_to}}` (al responder le escribes directo al usuario) |

En `fadex_generic` el cuerpo usa `{{{message_html}}}` con **tres llaves**: es HTML que arma la API (ya escapado).
Con dos llaves EmailJS lo mostraría como texto con etiquetas.

Anota el **Template ID** de cada una.

## 3. Permitir el envío desde el servidor

**Account → Security**: activa **"Allow EmailJS API for non-browser applications"**. Sin esto EmailJS rechaza
las llamadas de la API (403). Copia también la **Public Key** y la **Private Key** (Account → General / API keys).
La Private Key es un secreto: solo va en el `.env` del VPS.

## 4. `.env` del VPS

```bash
FADEX_EMAILJS_SERVICE_ID=service_fadex
FADEX_EMAILJS_PUBLIC_KEY=...
FADEX_EMAILJS_PRIVATE_KEY=...
FADEX_EMAILJS_TEMPLATE_GENERIC=template_xxxxxxx
FADEX_EMAILJS_TEMPLATE_FEEDBACK=template_yyyyyyy
FADEX_FEEDBACK_TO=ibarraorvil@gmail.com
FADEX_FEEDBACK_FORM_URL=https://forms.gle/...    # el Google Forms de docs/encuesta-google-forms.md
```

Luego: `docker compose -f docker-compose.prod.yml up -d --force-recreate api worker` (el worker también manda
correos: "tu trabajo está listo").

## 5. Probar

Regístrate con un correo tuyo en la web: debe llegar "Confirma tu email" con el botón. Si no llega, el motivo
queda en `docker compose -f docker-compose.prod.yml logs api | grep -i emailjs` (p. ej. 403 si falta el paso 3).
