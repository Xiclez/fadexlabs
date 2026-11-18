# Encuesta de la beta (Google Forms)

Se ofrece a quien deja un comentario al calificar un trabajo (web o app de escritorio), a cambio de **acceso
prioritario y un trimestre gratis** cuando salga la versión oficial. La invitación dice "8 preguntas, 2 minutos":
si agregas preguntas, cambia ese texto en `apps/web/src/components/feedback-prompt.tsx` y en
`dj-library-upgrader-desktop/ui/app.js` (surveyCard).

Título: **FADEX Labs · Beta de herramientas para DJs**
Descripción: *Gracias por probar la beta. Responde y te reservamos acceso prioritario y un trimestre gratis cuando
lancemos la versión oficial. Usa el mismo email de tu cuenta de FADEX para identificarte.*

Configuración: *Recopilar direcciones de correo electrónico → Verificado* (así ligas la respuesta con su cuenta y
sabes a quién darle el beneficio) y *Limitar a 1 respuesta*.

## Preguntas

1. **¿Qué herramientas usaste?** *(casillas, obligatoria)*
   Tracklist ID (web) · DJ Library Upgrader (web) · DJ Library Upgrader para Windows

2. **¿Cómo te describes como DJ?** *(opción múltiple, obligatoria)*
   Hobby / empezando · Toco en eventos privados · Residente en un venue · Toco en giras / festivales · Productor(a) además de DJ

3. **¿Qué software usas para tocar?** *(casillas)*
   Rekordbox · Serato · Traktor · Engine DJ · VirtualDJ · Otro

4. **Del 1 al 10, ¿qué tanto te ahorró tiempo la herramienta?** *(escala lineal 1–10, obligatoria)*
   1 = nada · 10 = muchísimo

5. **¿Qué fue lo más útil?** *(párrafo, obligatoria)*

6. **¿Qué falló, te confundió o te faltó?** *(párrafo, obligatoria)*

7. **Si fuera de pago, ¿cuánto pagarías al mes por las dos herramientas?** *(opción múltiple, obligatoria)*
   No pagaría · Menos de $99 MXN · $99–$199 MXN · $200–$349 MXN · $350 MXN o más

8. **¿Qué otra herramienta para DJs te gustaría que hiciéramos?** *(párrafo)*

Pantalla final (*Configuración → Presentación → Mensaje de confirmación*):
*¡Listo! Quedaste en la lista de acceso prioritario con un trimestre gratis para el lanzamiento oficial. Te
avisaremos por email y WhatsApp.*

Cuando esté publicado, copia el enlace corto (Enviar → 🔗 → *Acortar URL*, queda como `https://forms.gle/...`) en
`FADEX_FEEDBACK_FORM_URL` del `.env` del VPS. La app de escritorio solo abre enlaces de `forms.gle`,
`docs.google.com` y `fadexlabs.com`.

**Publicado** (2026-11-18): https://forms.gle/XY6eenKfkpDmTprb7 · en Drive como "FADEX Labs · Encuesta beta".
