# Encargo para agente: DJ Library Upgrader de escritorio (Windows)

> Lee este documento completo antes de escribir código. Es tu única fuente de contexto: no tienes
> acceso a la conversación que lo originó.

## 1. Objetivo

Convertir el **DJ Library Upgrader** (hoy un conjunto de scripts con Docker para usuarios técnicos) en una
**aplicación de escritorio para Windows** que cualquier DJ pueda instalar y usar sin terminal, sin Docker y sin
configurar nada técnico.

El DJ instala un `.exe`, entra con su cuenta de FADEX (debe tener lugar en la beta cerrada), elige la carpeta de
su librería y el formato deseado, y la app busca, descarga, verifica y entrega cada pista en mejor calidad,
**en su propia computadora y con su propia cuenta de Soulseek**. Los servidores de FADEX solo autentican y
publican el instalador.

Experiencia esperada:

1. **Instalar**: instalador por usuario (sin permisos de administrador), acceso directo en el menú Inicio.
2. **Entrar con FADEX**: se abre el navegador con el login de la web (incluido Google); al terminar, la app queda
   autorizada. Sin lugar en la beta, la app explica la beta cerrada y no avanza.
3. **Asistente inicial**: usuario y contraseña de Soulseek (se crean solos en el primer acceso si no existen),
   carpeta de entrega, opción de compartir (apagada) y prueba de conexión.
4. **Elegir librería**: una carpeta del disco (recursiva). La app analiza y muestra qué pistas se pueden mejorar.
5. **Elegir formato**: AIFF, WAV, FLAC, ALAC, MP3 320 o AAC 256 (o "original").
6. **Mejorar**: progreso por pista en tiempo real; se puede pausar, cerrar la app y reanudar después.
7. **Resultado**: carpeta con la misma estructura y nombres que la librería original + informe; botón "Abrir carpeta".

## 2. Lo que ya existe (reutilízalo, no lo rehagas)

### Motor: `C:\Users\daxik\Documents\dj-library-upgrader\upgrader` (SOLO LECTURA)

No modifiques ese repo. Copia lo necesario al proyecto nuevo con un comentario de origen en la cabecera.

| Archivo | Qué aporta |
|---|---|
| `normalize.py` | `parse_line()`: de "Artista - Título (Mix)" a búsquedas para Soulseek (artistas, remixer, pistas de versión). |
| `biblioteca.py` | Escaneo de librería: tags → artista/título, duración, calidad actual, `needs_upgrade()`. **Adáptalo para leer una carpeta local** (el zip ya no hace falta). |
| `slskd_fetch.py` | Cliente de la API de slskd, puntuación de resultados (`score_file`), filtro por duración, orden por formato preferido, cola, reintento con el siguiente candidato y verificación tras cada descarga (`verify_download`). |
| `formats.py` | Clasificación de formatos, preferencia de búsqueda, regla de conversión (nunca de con pérdida a sin pérdida), conversión con ffmpeg y copia de tags/carátula (ID3 v2.3 para Rekordbox). |
| `authenticity.py` | Detección de falsos lossless por espectro (numpy). |
| `matching.py` | Huella de espectrograma: confirma que la descarga es **la misma grabación** que el original. |
| `collect.py` | Entrega: copia/convierte, respeta nombre y subcarpeta del original, informe por pista. |
| `tests/test_upgrader.py` | 68 comprobaciones con audio sintético: úsalas como base de tus pruebas del motor. |
| `README.md` | Documentación del comportamiento actual (formatos, conversión, falsos lossless, coincidencias). |

El motor hoy está pensado como scripts de línea de comandos que escriben en `state.json` y en `print`. Tu trabajo
es **envolverlo** en un servicio con eventos de progreso, sin cambiar sus reglas de decisión.

### Plataforma FADEX: `C:\Users\daxik\Documents\fadexlabs`

| Pieza | Dónde |
|---|---|
| API FastAPI con JWT Ed25519, refresh rotativo, beta cerrada (`users.beta_seat`, claim `beta`), Google OIDC | `apps/api/app/…` |
| Dependencias `CurrentUser`, `BetaUser` | `apps/api/app/core/deps.py` |
| Web Next.js 16 + Tailwind 4, sistema de diseño FADEX (`fx-*`, `CutCard`, colores y tipografías) | `apps/web/src/…`, `apps/web/src/app/globals.css` |
| Tests de la API | `cd apps/api && .venv/Scripts/python -m pytest` |

La app de escritorio debe verse como FADEX: fondo `#07080d` con retícula, degradado magenta `#e040c8` → violeta
`#8b5cf6` → cian `#22d3ee`, acento lima `#c6f432`, títulos en Unbounded, texto en Manrope, etiquetas en
JetBrains Mono espaciado. Las fuentes van **empaquetadas** (sin depender de Google Fonts en tiempo de ejecución).

## 3. Arquitectura

```
DJ Library Upgrader (instalado en %LOCALAPPDATA%\Programs\FADEX Upgrader)
├─ app.exe            PyInstaller (onedir). Lanza el backend local y la ventana.
├─ ui/                HTML/CSS/JS estático con el diseño FADEX, mostrado con pywebview (WebView2)
├─ backend            Python: motor del Upgrader + API local (solo 127.0.0.1) que la UI consume
├─ bin/slskd/         slskd para Windows x64, sin modificar, como proceso hijo
├─ bin/ffmpeg/        ffmpeg + ffprobe
└─ licenses/          licencias de terceros y enlaces a su código fuente
Datos del usuario: %APPDATA%\FADEX\Upgrader\  (config, estado por trabajo, logs, slskd.yml, base de slskd)
```

### 3.1 Backend local

- API HTTP en `127.0.0.1` y **puerto aleatorio libre**, protegida con un token aleatorio por sesión que solo
  conoce la ventana. Rechaza cualquier petición sin ese token y cualquier `Origin` ajeno: otra web abierta
  en el navegador del usuario no debe poder controlar la app.
- Eventos de progreso a la UI (Server-Sent Events o WebSocket): etapa, pista actual, contadores, errores.
- Estado persistente por trabajo (equivalente a `state.json` + `formato.json`) para poder cerrar y reanudar.
- Cola: búsquedas secuenciales con pausa entre ellas (como hoy), descargas en paralelo según slskd, verificación
  (falsos lossless + coincidencia por espectrograma) y entrega en cuanto cada pista termina.

### 3.2 slskd embebido

- Al arrancar: generar `slskd.yml` en `%APPDATA%\FADEX\Upgrader\slskd\` con la cuenta del usuario, API key
  aleatoria, interfaz web **solo en 127.0.0.1** y en un puerto aleatorio, carpetas de descargas/incompletas.
- **Compartir: desactivado por defecto** (sin bloque `shares`). En ajustes, un interruptor explicado
  ("Compartir tu carpeta de descargas ayuda a encontrar más fuentes, pero otros usuarios de Soulseek podrán
  descargar esos archivos de tu equipo"). Activarlo reescribe la config y reinicia slskd.
- Puerto de escucha de Soulseek configurable; la app funciona sin abrirlo en el router y lo explica.
- Ciclo de vida: arrancar con la app, esperar a que se conecte (`/api/v0/server`), detenerlo al salir. Asocia el
  proceso a un *Job Object* de Windows para que nunca quede huérfano si la app se cierra de golpe.
- Una sola instancia de la app a la vez (mutex con nombre).

### 3.3 Login de FADEX en la app (cambios en `fadexlabs/apps/api` y `apps/web`)

Patrón para apps nativas (RFC 8252): navegador del sistema + redirección a loopback + PKCE.

1. La app abre en el navegador `https://fadexlabs.com/escritorio/autorizar?code_challenge=…&state=…&redirect_port=…`
   y escucha en `http://127.0.0.1:<redirect_port>/callback`.
2. Esa página web exige sesión (login normal o Google), muestra "Autorizar DJ Library Upgrader en este equipo"
   y, al aceptar, llama a la API, que crea un código de un solo uso (2 min) y redirige al loopback con
   `code` y `state`.
3. La app canjea `code` + `code_verifier` en `POST /api/auth/desktop/token` y recibe un **refresh token de
   dispositivo** (opaco, rotativo, revocable) y un access token con el claim `beta`.
4. El refresh token se guarda en el **Administrador de credenciales de Windows** (`keyring`/DPAPI), nunca en texto plano.
5. En la web, en "Mi cuenta → Sesiones", los equipos autorizados aparecen y se pueden revocar.
6. La app verifica el claim `beta` al iniciar y al renovar; si se pierde el lugar, deja de buscar y lo explica.

Reglas: el redirect solo puede ser `http://127.0.0.1:<puerto>/callback` (nunca otro host); `state` y PKCE
obligatorios; rate limit; tests en la API como los existentes (`tests/test_google.py` es buen modelo).

### 3.4 Interfaz (pantallas)

Bienvenida/login · asistente inicial · inicio (librerías recientes + botón "Nueva mejora") · análisis de
librería (tabla: archivo, calidad actual, se mejora sí/no, motivo; filtros) · elegir formato y preferencia ·
progreso (por pista: buscando / descargando % / verificando / entregada / no encontrada / descartada con motivo:
falso lossless, otra grabación) · resultado (resumen + abrir carpeta + exportar informe) · ajustes (cuenta de
Soulseek, compartir, puerto, carpetas, cerrar sesión de FADEX) · acerca de (versión, licencias).

Todo en español, accesible (teclado, foco visible, contraste), textos sin jerga técnica.

### 3.5 Instalador y actualizaciones

- PyInstaller `onedir` + **Inno Setup**: instalación por usuario en `%LOCALAPPDATA%\Programs`, sin admin,
  acceso directo, desinstalador que **no borra** la librería ni las entregas del usuario (pregunta si borrar
  `%APPDATA%\FADEX\Upgrader`).
- WebView2: viene con Windows 10/11; si falta, el instalador lo indica.
- Versiones: `GET /api/desktop/latest` en la API de FADEX → `{version, url, sha256, notas}`. La app avisa
  y descarga el instalador nuevo verificando el SHA-256 antes de ejecutarlo.
- Sin firma de código en la beta: documenta el aviso de SmartScreen ("Más información → Ejecutar de todos
  modos") en la página de descarga. Deja el pipeline preparado para firmar con `signtool` cuando haya certificado.

## 4. Licencias de terceros

- **slskd: AGPL-3.0.** Se distribuye sin modificar y como proceso separado. Incluye su licencia, aviso de
  copyright y enlace al código fuente de la versión exacta empaquetada.
- **ffmpeg**: usa una build LGPL si es viable; si es GPL, incluye la licencia y el enlace al código fuente.
- Python, pywebview, PyInstaller, numpy, mutagen, requests, keyring: incluye sus licencias en `licenses/`.
- Pantalla "Acerca de" con la lista de componentes y licencias.
- Las versiones de slskd y ffmpeg se fijan (versión + SHA-256) en un archivo del proyecto; el script de build las
  descarga y **verifica el hash** antes de empaquetar.

## 5. Dónde trabajar

- Proyecto nuevo: `C:\Users\daxik\Documents\dj-library-upgrader-desktop` (crea `git init`, sin commits).
- Cambios en la plataforma (login de escritorio, `/api/desktop/latest`, página `/escritorio/autorizar`,
  página de descarga en `/herramientas`) dentro de `C:\Users\daxik\Documents\fadexlabs`.
- El repo `dj-library-upgrader` es solo lectura.

## 6. Restricciones del entorno

- **No hagas commit, push ni crees repos remotos.** No publiques ni subas el instalador a ningún lado.
- Windows con Git Bash y PowerShell 5.1. Docker normalmente apagado (no lo necesitas).
- **Descargar binarios externos** (slskd, ffmpeg, Inno Setup, WebView2) puede requerir aprobación del usuario.
  Si una descarga se deniega, no la rodees: deja el script de build listo con versiones y SHA-256 fijados,
  documenta el paso manual y sigue con lo demás.
- No tienes permiso para matar procesos por PID: los servidores que levantes como tareas en segundo plano se
  detienen con la herramienta de tareas.
- No leas ni imprimas secretos (`.env` de cualquier proyecto).
- **Next.js 16 no es el que conoces:** antes de tocar `fadexlabs/apps/web`, lee `apps/web/AGENTS.md` y la guía
  correspondiente en `apps/web/node_modules/next/dist/docs/`.
- Escribe como el código existente: comentarios y textos en español, mismos patrones de seguridad.

## 7. Pruebas exigidas

- **Motor**: adapta `test_upgrader.py` al nuevo empaquetado (conversión, tags, falsos lossless, coincidencia por
  espectrograma, escaneo de carpeta, entrega con nombres originales). Deben pasar.
- **slskd simulado**: un servidor falso que imite los endpoints usados (`/api/v0/server`, `/searches`,
  `/searches/{id}/responses`, `/transfers/downloads`) y deje archivos en la carpeta de descargas, para probar el
  flujo completo de mejora sin red: buscar → descargar → descartar un falso lossless → reintentar → entregar.
- **API local**: rechaza peticiones sin token de sesión y con `Origin` ajeno.
- **Login de escritorio** (pytest en `fadexlabs/apps/api`): PKCE, `state`, código de un solo uso y vencido,
  redirect solo a loopback, revocación del dispositivo, claim `beta`. Las pruebas existentes siguen pasando.
- **Build**: el script genera el instalador (si los binarios se pudieron obtener) o deja documentado qué falta.
- **Humo manual**: instalar, autorizar con un usuario de prueba (API en dev), analizar una carpeta de prueba y,
  con el slskd simulado, completar una mejora.

## 8. Terminado significa

1. Todas las pruebas pasan, en el proyecto nuevo y en `fadexlabs`.
2. Instalador generado, o script de build listo con los pasos manuales pendientes claramente listados.
3. `README.md` del proyecto nuevo: cómo desarrollar, probar, construir y publicar una versión; arquitectura;
   licencias.
4. Informe final breve: qué construiste, qué quedó fuera y por qué, cómo verificarlo y riesgos para el lanzamiento
   (SmartScreen sin firma, puertos, fuentes disponibles sin compartir, actualizaciones de slskd).
