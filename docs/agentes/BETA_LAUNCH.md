# Encargo para agente: lanzar la beta cerrada de las herramientas FADEX

> Lee este documento completo antes de escribir código. Es tu única fuente de contexto: no tienes
> acceso a la conversación que lo originó.
>
> **Versión 2 (2026-11-09).** Cambió el alcance respecto a la versión 1: la segunda herramienta ya no es
> «Library Check» (solo un informe) sino **DJ Library Upgrader**: el usuario sube su librería y la
> recibe **descargada y mejorada**, por Google Drive. La construcción de §4 **ya está hecha**; lo que
> queda por hacer es §5.

## 1. Objetivo

Dejar lista la **beta cerrada** de FADEX Labs: que los primeros 10 usuarios con lugar en la beta puedan,
**desde la web**, usar dos herramientas:

1. **Tracklist ID**: suben un DJ set (wav/mp3/flac/aiff/m4a, 2+ horas) y reciben el tracklist con
   timestamps (TXT y CSV).
2. **DJ Library Upgrader**: suben su librería en `.zip`, eligen formato (AIFF, WAV, FLAC, ALAC, MP3 320,
   AAC 256 o «lo encontrado») y reciben **su librería mejorada en una carpeta de Google Drive**: cada
   pista se busca en Soulseek, se descarga, se compara con el original (solo se entrega si es la misma
   grabación), se descartan los falsos lossless y se convierte al formato pedido, con tags y carátula.
   Un informe sin la música **no sirve**: el entregable es la librería.

## 2. Lo que ya existe

Monorepo `C:\Users\daxik\Documents\fadexlabs` (git inicializado, **sin commits**):

```
apps/api/      FastAPI + SQLAlchemy async + Alembic. Postgres en prod; SQLite + Redis en memoria en dev.
apps/worker/   Proceso aparte que toma trabajos de la base de datos y corre las herramientas.
apps/web/      Next.js 16 (App Router, cacheComponents) + Tailwind 4.
services/      Scripts de las herramientas, vendorizados (ver §3).
deploy/k3s/    Manifiestos (kustomize): postgres, redis, api, web, worker, slskd, PVC, ingress, cloudflared.
deploy/slskd/  Plantilla de configuración del slskd de la plataforma.
docker-compose.dev.yml
```

Plataforma (de antes; no la rehagas):

| Pieza | Dónde | Qué hace |
|---|---|---|
| Auth JWT | `apps/api/app/core/security.py`, `services/auth.py`, `routers/auth.py` | Access token Ed25519 (10 min, en memoria en la web) + refresh rotativo en cookie httpOnly. |
| Dependencias | `apps/api/app/core/deps.py` | `CurrentUser`, `BetaUser` (403 si no tiene lugar), `require_role`. |
| Beta | `apps/api/app/services/beta.py`, `routers/beta.py` | Lugares 1..N únicos (`users.beta_seat`). `FADEX_BETA_SEATS=10`. |
| Rate limiting | `apps/api/app/core/ratelimit.py` | `await ratelimit.hit(key, limit, window)` sobre Redis. |
| Emails | `apps/api/app/services/email.py` | `send(to, subject, text)`; en dev sin SMTP van al log; en tests a `email.outbox`. |
| Cliente web | `apps/web/src/lib/api.ts`, `lib/auth.tsx` | `api<T>()` con Bearer + reintento tras refresh; `useAuth()`. |
| UI | `apps/web/src/components/ui.tsx`, `auth-ui.tsx`, `globals.css` | Sistema de diseño FADEX (`CutCard`, `Button`, clases `fx-*`). |

Herramientas (hecho en la versión 2; detalle en §4):

| Pieza | Dónde |
|---|---|
| Modelo y migración | `apps/api/app/models/tool.py`, `alembic/versions/0003_tool_jobs.py` |
| Subida por partes, trabajos, descargas | `apps/api/app/routers/tools.py`, `services/tools.py`, `schemas/tools.py` |
| Admin mínimo | `apps/api/app/routers/admin.py`, `scripts/make_admin.py` |
| Worker | `apps/worker/worker/` (`main.py`, `jobs.py`, `proc.py`, `tracklist.py`, `library.py`) |
| Web | `apps/web/src/app/herramientas/{tracklist,library-upgrader,trabajos,trabajos/[id]}`, `components/tool-*.tsx`, `job-views.tsx`, `lib/upload.ts` |
| Pruebas | `apps/api/tests/test_tools.py` (12), `apps/worker/tests/` (12, con simuladores en `tests/fakes/`) |

## 3. Código de las herramientas

Los originales están fuera del monorepo y son **de solo lectura**. Sus copias viven en
`fadexlabs/services/`, cada archivo con un comentario de origen en la cabecera. El worker las ejecuta
como subprocesos, igual que se usan a mano. Si un original cambia, se vuelve a copiar.

| Carpeta | Origen | Flujo |
|---|---|---|
| `services/tracklist/` | `C:\Users\daxik\Documents\djset` | `comprimir.py` → `acr_scan.py` → `scan.py` (Shazam) → `tracklist.py` |
| `services/library_upgrade/` | `C:\Users\daxik\Documents\dj-library-upgrader\upgrader` | `biblioteca.py` → `slskd_fetch.py` → `collect.py` (+ `formats`, `authenticity`, `matching`, `normalize`) |

- `dj-library-upgrader` es un clon de `github.com/Xiclez/slskd-vpm` con mejoras locales **sin commit**
  (entrada por `.zip`, comparación por espectrograma, falsos lossless, conversión de formato). La base es
  la carpeta local, **no** el repo de GitHub, que es la versión anterior (solo lista `.txt`, MP3 320/FLAC).
- Único cambio en las copias: `tracklist/acr_scan.py` toma el token solo de `ACRCLOUD_TOKEN`.
- Fuera de la beta: verificación con Panako (`verify.py`, `deezer_previews.py`, `tools/panako*`).

⚠️ `djset/.env` contiene el token real de ACRCloud. **No lo leas, no lo imprimas, no lo copies.** El
worker lo recibe por variable de entorno; en pruebas, ACRCloud, Shazam, slskd y rclone se simulan.

## 4. Cómo está construido

### 4.1 API (`apps/api`)

**`ToolJob`** (tabla `tool_jobs`): `id`, `user_id`, `tool` (`tracklist` | `library_upgrade`), `status`
(`uploading` | `queued` | `running` | `done` | `failed` | `expired`), `input_name`, `input_bytes`,
`options` (p. ej. `{"formato": "aiff"}`), `chunk_size`, `received_parts`, `progress`, `message` (para el
usuario), `error` (interno; nunca sale por la API pública), fechas y `result`
(`{summary, files, drive_url}`).

**Subida reanudable por partes** (Cloudflare Tunnel rechaza cuerpos de más de 100 MB; el proxy `/api` de
Next corta los de más de 10 MB, por eso las partes son de **8 MB**):

```
GET    /api/tools                          límites vigentes (para validar en la web)
POST   /api/tools/uploads                  {tool, filename, size, formato?, accept_rights?} → {upload_id, chunk_size, total_parts, received_parts}
GET    /api/tools/uploads/{id}             por dónde va (para reanudar)
PUT    /api/tools/uploads/{id}/chunks/{n}  cuerpo binario; en orden; repetir una parte ya enviada es válido
POST   /api/tools/uploads/{id}/complete    valida el contenido y deja el trabajo en `queued`
DELETE /api/tools/uploads/{id}
```

- Cada parte se escribe directo a disco **en su posición** dentro de `FADEX_DATA_DIR/uploads/<id>/input.part`
  (sin memoria ni ensamblado). Iniciar otra vez con el mismo archivo devuelve la misma subida.
- `complete` valida el **contenido real**: `ffprobe` (sets) o `zipfile` (librerías: al menos una pista de
  audio, tope de pistas y de tamaño descomprimido). Nunca la extensión.
- En disco el archivo se llama `<id del trabajo>.<ext>`, nunca como lo nombró el usuario.
- Límites en `Settings` (`core/config.py`): set ≤ 3 GB; zip ≤ 10 GB y ≤ 3000 pistas; 1 trabajo activo por
  usuario y herramienta; 5 tracklists y 2 librerías por día.
- DJ Library Upgrader exige `accept_rights: true` (el usuario confirma que tiene derecho a usar esa música).
- Todo con `BetaUser` + email confirmado. Rate limit en init y complete.

**Trabajos y resultados**

```
GET /api/tools/jobs                     mis trabajos (paginado)
GET /api/tools/jobs/{id}                estado, progreso, mensaje, resumen, drive_url
GET /api/tools/jobs/{id}/files/{name}   lista blanca: tracklist.txt, tracklist.csv, informe.csv, no_encontradas.txt, revision.csv
```

Un usuario jamás ve ni descarga trabajos de otro: **404**, no 403.

**Admin** (rol `admin`): `GET /api/admin/beta/users[?all=true]`, `PUT|DELETE /api/admin/beta/users/{id}/seat`
(da el primer lugar libre, respeta el máximo), `GET /api/admin/jobs` (incluye `error`).
`python scripts/make_admin.py <email>`.

### 4.2 Worker (`apps/worker`)

- Toma el trabajo `queued` más antiguo de cada herramienta (`SELECT … FOR UPDATE SKIP LOCKED` en Postgres).
  Sin Celery ni brokers. **Una tracklist y una librería a la vez**; entre sí corren en paralelo.
- Publica `progress` y `message` en cada etapa. Un fallo nunca tumba el worker: guarda el detalle en
  `error` y deja un mensaje claro para el usuario. Al arrancar, lo que quedó `running` vuelve a la cola.
- **Tracklist ID:** comprimir → ACRCloud → Shazam (relleno con tope de 15 min; si ACRCloud falla, único
  motor con tope de 2 h) → `tracklist.py` → `tracklist.txt` + `tracklist.csv`.
- **DJ Library Upgrader:**
  1. `biblioteca.py`: extracción segura del zip y selección de lo que se puede mejorar (`revision.csv`).
  2. `slskd_fetch.py run`: busca, descarga y verifica cada descarga contra el original; si es otra
     grabación o un falso lossless, prueba el siguiente candidato. El progreso sale de su `state.json`.
     Tope de 12 h por librería: al llegar, cancela lo encolado en slskd y entrega lo conseguido.
  3. `collect.py`: arma la entrega (mismos nombres y subcarpetas que el original) + `_informe.csv`.
  4. `rclone copy` a `FADEX_RCLONE_REMOTE/<fecha>-<usuario>-<id>` y `rclone link` → `drive_url`.
     Si Drive falla, el trabajo termina igual con `delivery: pending` y la entrega queda en
     `FADEX_DATA_DIR/jobs/<id>/entrega` para subirla a mano (no se tiran horas de descarga).
  5. Limpieza: zip, librería extraída y descargas de slskd de ese trabajo.
- Al terminar (bien o mal) borra el audio subido y envía un email con el enlace
  `{public_url}/herramientas/trabajos/{id}`. Los resultados se conservan 30 días.
- Limpieza periódica: subidas sin completar en 24 h y resultados vencidos.

### 4.3 Web (`apps/web`)

- `/herramientas/tracklist` y `/herramientas/library-upgrader`: subida por partes con barra de progreso,
  reintento automático de la parte que falle y reanudación (elegir el mismo archivo continúa donde iba).
- `/herramientas/trabajos` y `/herramientas/trabajos/[id]`: lista y detalle con polling cada 4 s mientras
  esté en cola o en proceso, resumen, descargas y botón de Google Drive.
- Sin sesión → `/login`. Sin lugar → explicación de la beta + `BetaCounter`. `/herramientas` muestra el
  acceso a cada herramienta a quien tiene lugar.

### 4.4 Despliegue

- `docker-compose.dev.yml`: `worker` + carpeta `./data` compartida con la API; `slskd` con
  `--profile upgrader`.
- `deploy/k3s/`: Deployments `worker` y `slskd`, PVC `fadex-data` (RWO, `local-path`) montado en API,
  worker y slskd; Secrets `fadex-worker` (`ACRCLOUD_TOKEN`, `FADEX_SLSKD_API_KEY`, `rclone.conf`) y
  `fadex-slskd` (`slskd.yml`), documentados en `secrets.example.yaml`.

## 5. Lo que falta (tu trabajo)

Todo lo anterior pasa sus pruebas con los servicios externos **simulados**. Nada se ha probado todavía
contra los servicios reales ni se ha desplegado. En orden:

1. **Build de la web en la máquina real.** `cd apps/web && npm run build`. Se compiló y se probó en
   Chrome en un entorno sin acceso a Google Fonts (con las fuentes sustituidas); confirma que compila
   tal cual en Windows.
2. **Tracklist ID con ACRCloud y Shazam reales.** Levanta API + worker con `ACRCLOUD_TOKEN` en el entorno
   del worker y sube un set de verdad (`djset/sets/`). Compara el resultado con
   `djset/output/1109/tracklist.txt`. Revisa cuántas consultas gasta en la consola de ACRCloud.
3. **DJ Library Upgrader con slskd y rclone reales.** Con el `slskd` del compose (`--profile upgrader`,
   cuenta de Soulseek **propia de la plataforma**) y un `rclone.conf` con remoto de Drive, sube un zip
   chico (10-20 pistas MP3) y verifica: progreso, entrega en Drive, enlace compartible, informe y que
   `data/slskd/downloads` queda vacío al terminar.
4. **Imágenes Docker.** Construye `api`, `web` y `worker` (el contexto del worker es la raíz:
   `docker build -f apps/worker/Dockerfile .`). No se han construido nunca. Comprueba que el worker
   corre con sistema de archivos de solo lectura (`/tmp` y `/data` montados) y que la imagen `slskd/slskd`
   acepta correr como uid 10001 con `/app` en el PVC.
5. **Despliegue en k3s**: crear los Secrets, aplicar, y repetir 2 y 3 detrás de Cloudflare Tunnel con un
   archivo de más de 1 GB. Mide el tiempo por parte: si la subida de los usuarios es lenta, baja
   `FADEX_UPLOAD_CHUNK_BYTES` (Cloudflare y Traefik cortan peticiones que tardan demasiado).
6. **Faltantes conocidos** (decide con el dueño si entran en la beta):
   - No hay pantalla de administración: dar/quitar lugares y ver trabajos es solo por API.
   - El usuario no puede cancelar un trabajo en curso (sí una subida).
   - Cuando Drive falla (`delivery: pending`) nadie recibe aviso: hoy hay que mirar `/api/admin/jobs`.
   - `acr_scan.py` no borra los sets del contenedor de ACRCloud tras escanearlos.
   - El aviso de privacidad (`/privacidad`) no menciona todavía que se suben sets y librerías.

## 6. Restricciones (importantes)

- **No hagas commit, push ni crees repos remotos.** Deja los cambios en el árbol de trabajo.
- **No toques** `djset/` ni `dj-library-upgrader/` (solo lectura). No despliegues nada sin que te lo pidan.
- **Secretos:** nunca los leas de `djset/.env` ni de `dj-library-upgrader/.env`; nunca los imprimas ni
  los escribas en archivos versionados. `deploy/slskd/slskd.yml` y `rclone.conf` están en `.gitignore`.
- **Soulseek:** una cuenta solo para la plataforma. Las pruebas reales, con librerías chicas.
- **Next.js 16 no es el que conoces:** lee `apps/web/AGENTS.md` y la guía correspondiente en
  `apps/web/node_modules/next/dist/docs/` antes de escribir código de Next. Con `cacheComponents`,
  cualquier lectura de la URL (`params`, `usePathname`, `useSearchParams`) va dentro de `<Suspense>`.
- **Entorno Windows:** Git Bash + PowerShell 5.1. Docker Desktop normalmente está apagado: desarrolla con
  el modo sin Docker (ver README). Si levantas servidores, hazlo como tareas en segundo plano y detenlos
  al terminar. El puerto 3000 puede estar ocupado: usa otro.
- ffmpeg está en el PATH. No descargues binarios externos.
- Escribe como el código existente: comentarios y textos de UI en español, mismos patrones de seguridad.
- Si algo resulta inviable o peligroso, no lo fuerces: documéntalo en tu informe final.

## 7. Pruebas

```bash
cd apps/api    && .venv/Scripts/python -m pytest      # 42: las 30 de antes + 12 de herramientas y admin
cd apps/worker && ../api/.venv/Scripts/python -m pytest   # 12 (instala antes apps/worker/requirements-dev.txt)
cd apps/web    && npm run build
```

Las pruebas del worker corren los scripts reales de `services/` de punta a punta (subida por la API →
worker → descarga) con audio generado por ffmpeg y estos simuladores en `apps/worker/tests/fakes/`:
`acr_scan.py` y `shazam_scan.py` (respuestas fijas con el formato real de `acr_raw.json`/`raw.jsonl`),
`slskd.py` (API v0 de slskd) y `rclone.py`. Para un humo sin red, los mismos simuladores se enchufan con
`FADEX_ACR_SCAN_CMD`, `FADEX_SHAZAM_SCAN_CMD` y `FADEX_RCLONE_BIN`.

## 8. Terminado significa

1. Las pruebas siguen verdes y la web compila en la máquina real.
2. Un set real y una librería real procesados de punta a punta, descritos en tu informe (tiempos,
   cuántas pistas se consiguieron, consumo de ACRCloud).
3. Imágenes construidas y, si se pidió, desplegado en k3s con la prueba de un archivo de más de 1 GB.
4. Informe final breve: qué hiciste, qué quedó fuera y por qué, y riesgos para el lanzamiento (cuotas de
   ACRCloud tras la prueba gratis, límites de Shazam por IP, espacio en disco, tasa de éxito en Soulseek
   sin compartir archivos, y el riesgo legal de descargar y entregar música de terceros desde el servidor
   de FADEX).
