# FADEX Labs

Plataforma unificada de FADEX Labs: sitio, portafolio, servicios, tienda, marketplace, blog y herramientas para DJs.

```
fadexlabs/
├── apps/
│   ├── api/      FastAPI: autenticación JWT, beta cerrada, herramientas (subidas, trabajos, admin)
│   ├── worker/   procesa los trabajos de las herramientas (Tracklist ID y DJ Library Upgrader)
│   └── web/      Next.js 16 + Tailwind 4: sitio público, cuenta de usuario y herramientas
├── services/     scripts de las herramientas, vendorizados (ver services/README.md)
├── deploy/k3s/   manifiestos de producción (kubectl apply -k deploy/k3s)
├── deploy/slskd/ plantilla de configuración del slskd de la plataforma
├── docker-compose.dev.yml   Postgres + Redis + API + worker (+ slskd con --profile upgrader)
├── docs/agentes/ encargos para agentes (BETA_LAUNCH.md: estado y pendientes de la beta)
└── references/   dossier y catálogos de marca
```

## Desarrollo local

**Con Docker** (Postgres y Redis reales):

```bash
docker compose -f docker-compose.dev.yml up -d   # API en :8000 (corre las migraciones sola)
cd apps/web && npm install && npm run dev        # web en :3000; /api se reenvía a :8000
```

**Sin Docker** (SQLite + Redis en memoria, solo para desarrollo):

```bash
cd apps/api
python -m venv .venv && .venv/Scripts/pip install -r requirements-dev.txt
set FADEX_DATABASE_URL=sqlite+aiosqlite:///./dev.db
set FADEX_REDIS_URL=memory://
set FADEX_COOKIE_SECURE=false
.venv/Scripts/python -m alembic upgrade head
.venv/Scripts/python -m uvicorn app.main:app --port 8000
```

El worker de las herramientas, en otra terminal. Se corre **desde `apps/api`** para que use el mismo
`./dev.db` y la misma carpeta `./data` que la API:

```bash
cd apps/api
.venv/Scripts/pip install -r ../worker/requirements.txt
set PYTHONPATH=..\worker
set ACRCLOUD_TOKEN=...            &:: opcional; sin token, Tracklist ID usa solo Shazam
.venv/Scripts/python -m worker.main
```

Sin SMTP configurado, los emails (confirmación, recuperación y avisos de trabajos) se escriben en el log
de la API o del worker.

Tests: `cd apps/api && .venv/Scripts/python -m pytest` (API) y
`cd apps/worker && ../api/.venv/Scripts/python -m pytest` (worker; antes instala
`apps/worker/requirements-dev.txt`). Necesitan ffmpeg en el PATH; no usan red.

## Autenticación

| Pieza | Diseño |
|---|---|
| Access token | JWT **Ed25519**, 10 min. Claims: `sub`, `role`, `sid` (sesión), `ev` (email verificado), `pv` (versión de contraseña). Otros servicios lo verifican con la clave pública de `/api/auth/.well-known/jwks.json`. |
| Refresh token | Opaco (256 bits), cookie `httpOnly; Secure; SameSite=Strict; Path=/api/auth`, 30 días. En la base solo se guarda su SHA-256. **Rota en cada uso**; reutilizar uno viejo revoca toda la sesión. |
| CSRF | Endpoints con cookie exigen `X-Fadex-CSRF: 1` y Origin permitido. |
| Contraseñas | Argon2id, mínimo 10 caracteres. Cambiarla o restablecerla cierra todas las sesiones e invalida los access tokens emitidos. |
| Anti-abuso | Rate limiting en Redis (login por IP y por email, registro, recuperación). Respuestas genéricas: no se revela si un email existe. |
| Emails | Verificación y recuperación con tokens de un solo uso (SHA-256 en base, vencimiento). SMTP por el puerto 2525. |
| Web | El access token vive solo en memoria (nunca en localStorage); la sesión se recupera con la cookie al recargar. |

Endpoints (`/api/auth`): `register`, `login`, `refresh`, `logout`, `logout-all`, `verify-email`,
`resend-verification`, `forgot-password`, `reset-password`, `change-password`, `me`, `sessions`,
`sessions/{id}` (DELETE), `.well-known/jwks.json`.

## Herramientas para DJs (beta cerrada)

Solo para usuarios con lugar en la beta (`users.beta_seat`) y email confirmado, o administradores.

| Herramienta | Entra | Sale |
|---|---|---|
| **Tracklist ID** (`/herramientas/tracklist`) | DJ set: wav, mp3, flac, aiff, m4a | `tracklist.txt` y `tracklist.csv` con timestamps |
| **DJ Library Upgrader** (`/herramientas/library-upgrader`) | Librería en `.zip` + formato de entrega | Carpeta de Google Drive con la librería mejorada + informe por pista |

Flujo: la web sube el archivo **por partes** → la API valida el contenido y crea un trabajo → el worker
lo procesa y publica el avance → la web lo muestra en `/herramientas/trabajos/<id>` → email al terminar.

**Subida.** Partes de 8 MB, reanudable (`POST /api/tools/uploads` con el mismo archivo devuelve por dónde
iba). Cloudflare Tunnel rechaza cuerpos de más de 100 MB y el proxy `/api` de Next los de más de 10 MB.
El contenido se valida con `ffprobe` (sets) o `zipfile` (librerías), nunca por la extensión.

**Worker.** Una tracklist y una librería a la vez. Ejecuta los scripts de `services/`:

- *Tracklist ID:* comprimir → ACRCloud y Shazam **en paralelo** → tracklist. Si un motor se satura, falla
  o se pasa de tiempo, el trabajo sigue con el otro. El CSV puntúa cada coincidencia (`confianza` 0-100
  y `nivel` alta/media/baja).
- *DJ Library Upgrader:* extracción segura del zip → búsqueda y descarga en Soulseek con el slskd de la
  plataforma → cada descarga se compara con el original (solo la misma grabación) y se descartan los
  falsos lossless; si una fuente no responde en 2 min se prueba otra, y si en 10 min ninguna está
  disponible la pista queda pendiente en el informe → conversión al formato pedido con tags y carátula → `rclone copy` + `rclone link` a
  Google Drive. Si Drive falla, el trabajo termina con la entrega pendiente en
  `data/jobs/<id>/entrega` para subirla a mano.

Al terminar se borra lo subido (set, zip, librería extraída y descargas de slskd). Los resultados
duran 30 días.

**Límites** (todos configurables):

| Variable | Por defecto | |
|---|---|---|
| `FADEX_TRACKLIST_MAX_BYTES` / `FADEX_TRACKLIST_PER_DAY` | 3 GB / 5 | tamaño del set y trabajos por usuario y día |
| `FADEX_LIBRARY_MAX_BYTES` / `FADEX_LIBRARY_PER_DAY` | 10 GB / 2 | tamaño del zip y trabajos por usuario y día |
| `FADEX_LIBRARY_MAX_FILES` / `FADEX_LIBRARY_MAX_UNPACKED_GB` | 3000 / 40 | pistas por librería y tamaño descomprimido |
| `FADEX_UPLOAD_CHUNK_BYTES` | 8 MB | tamaño de cada parte |
| `FADEX_RESULT_TTL_DAYS` / `FADEX_UPLOAD_TTL_SECONDS` | 30 / 24 h | resultados disponibles; subidas abandonadas |
| `FADEX_SHAZAM_MAX_SECONDS` / `FADEX_SHAZAM_FALLBACK_MAX_SECONDS` | 15 min / 1 h | tope de Shazam con ACRCloud / como único motor |
| `FADEX_SHAZAM_FAIL_STREAK` | 4 | fragmentos rechazados seguidos para dar a Shazam por saturado |
| `FADEX_UPGRADE_SONG_TIMEOUT_SECONDS` / `FADEX_UPGRADE_CANDIDATE_WAIT_SECONDS` | 10 min / 2 min | tiempo máximo por canción / espera por cada fuente |
| `FADEX_UPGRADE_MAX_HOURS` | 12 | tope por librería; se entrega lo conseguido |

Además, un solo trabajo activo por usuario y herramienta.

**Variables del worker:**

| Variable | |
|---|---|
| `FADEX_DATA_DIR` | carpeta compartida con la API (`uploads/`, `jobs/`, `slskd/downloads/`) |
| `ACRCLOUD_TOKEN` | token de la consola de ACRCloud (sin prefijo). Sin él, solo Shazam |
| `FADEX_SLSKD_URL`, `FADEX_SLSKD_API_KEY` | API del slskd de la plataforma |
| `FADEX_SLSKD_DOWNLOADS_DIR` | dónde ve el worker las descargas de slskd (por defecto `<data>/slskd/downloads`) |
| `FADEX_RCLONE_REMOTE`, `RCLONE_CONFIG` | destino en Drive (`gdrive:FADEX/Entregas`) y el `rclone.conf` |

**slskd.** Copia `deploy/slskd/slskd.example.yml` a `deploy/slskd/slskd.yml`, pon una cuenta de Soulseek
**solo para la plataforma** y la API key, y levántalo con
`docker compose -f docker-compose.dev.yml --profile upgrader up -d`.

**Administración** (rol `admin`; no hay pantalla, es por API):

```bash
cd apps/api && .venv/Scripts/python scripts/make_admin.py correo@ejemplo.com
```

`GET /api/admin/beta/users?all=true`, `PUT|DELETE /api/admin/beta/users/{id}/seat` (dar o quitar lugar,
respetando `FADEX_BETA_SEATS`) y `GET /api/admin/jobs` (todos los trabajos, con el detalle interno de
los errores).

## Producción (k3s)

1. Construye y publica las imágenes `api`, `web` y `worker` en tu registry (por defecto `ghcr.io/fadexlabs/*`).
   El worker se construye desde la raíz: `docker build -f apps/worker/Dockerfile -t ghcr.io/fadexlabs/worker .`
2. Crea los Secrets como indica `deploy/k3s/secrets.example.yaml` (nunca los subas a git).
3. `kubectl apply -k deploy/k3s`
4. En Cloudflare Zero Trust, apunta el hostname del tunnel a `http://traefik.kube-system.svc.cluster.local:80`.

## Producción en un solo servidor (Docker Compose)

Para un VPS sin Kubernetes, o donde los puertos 80/443 ya son de otro proxy. `docker-compose.prod.yml`
levanta Postgres, Redis, API, worker, web y slskd, y publica solo la web en `127.0.0.1:3020`; Next
reenvía `/api` a la API. El dominio llega por un Cloudflare Tunnel apuntado a `http://localhost:3020`.

```bash
bash deploy/prod/setup.sh        # una vez: genera .env, deploy/slskd/slskd.yml, carpetas y copia rclone.conf
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs -f worker
```

- `setup.sh` pide el dominio, una cuenta de Soulseek **solo para FADEX**, la carpeta de Drive y el token
  de ACRCloud. Todo lo que genera está en `.gitignore`.
- Los límites de librería en `.env` vienen reducidos (zip de 2 GB, 500 pistas) para un disco chico.
- Actualizar: `git pull && docker compose -f docker-compose.prod.yml up -d --build`.
- Dar rol de administrador:
  `docker compose -f docker-compose.prod.yml exec api python scripts/make_admin.py correo@ejemplo.com`

## Clúster local de pruebas (k3d)

`deploy/k3s-local` levanta lo mismo que producción en un k3s dentro de Docker: imágenes construidas en
tu máquina, sin dominio ni Cloudflare, en `http://localhost:8080`. Requiere Docker Desktop encendido,
[k3d](https://k3d.io) (`winget install k3d`) y `kubectl`.

```bash
k3d cluster create fadex -p "8080:80@loadbalancer"

docker build -t fadex/api:dev apps/api
docker build -t fadex/web:dev apps/web
docker build -t fadex/worker:dev -f apps/worker/Dockerfile .
k3d image import fadex/api:dev fadex/web:dev fadex/worker:dev -c fadex

kubectl apply -k deploy/k3s-local
kubectl -n fadexlabs get pods -w        # espera a que api, web, worker, postgres y redis estén Running
```

- **Confirmar email:** el enlace sale en `kubectl -n fadexlabs logs deploy/api`.
- **Avance de un trabajo:** `kubectl -n fadexlabs logs -f deploy/worker`.
- **ACRCloud** (sin token se usa solo Shazam):
  ```bash
  kubectl -n fadexlabs create secret generic fadex-worker --from-literal=ACRCLOUD_TOKEN=... \
    --from-literal=FADEX_SLSKD_API_KEY=fadex-local-key --dry-run=client -o yaml | kubectl apply -f -
  kubectl -n fadexlabs rollout restart deploy/worker
  ```
- **slskd** (hasta crear este Secret su pod queda en espera; lo demás funciona): copia
  `deploy/slskd/slskd.example.yml` a `deploy/slskd/slskd.yml`, pon la cuenta de Soulseek y la API key
  `fadex-local-key`, y:
  ```bash
  kubectl -n fadexlabs create secret generic fadex-slskd --from-file=slskd.yml=deploy/slskd/slskd.yml
  ```
- **Entrega sin Drive:** la librería mejorada queda dentro del worker, en `/data/jobs/<id>/entrega`
  (`kubectl -n fadexlabs exec deploy/worker -- ls -R /data/jobs`).
- **Tras cambiar código:** reconstruye la imagen, vuelve a importarla y `kubectl -n fadexlabs rollout restart deploy/<api|web|worker>`.
- **Borrar todo:** `k3d cluster delete fadex`.

## Contenido y licencias

La tienda vende solo contenido propio o con licencia (loops visuales, librerías de iluminación, guías, cursos).
DJ Library Upgrader se ofrece como herramienta que el DJ usa sobre fuentes que tiene derecho a usar:
al subir su librería confirma que tiene derecho a usar esa música, y solo se le entrega la misma
grabación que ya tenía, en mejor calidad.

> Ojo: desde que el Upgrader corre en la plataforma, es el servidor de FADEX el que descarga de Soulseek
> y entrega los archivos por Drive. Eso ya no encaja con «FADEX Labs no distribuye música de terceros»
> y conviene revisarlo con un abogado antes de abrir la beta.
