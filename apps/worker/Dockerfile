# Worker de las herramientas (Tracklist ID y DJ Library Upgrader).
# El contexto de build es la raíz del monorepo (necesita apps/api/app y services/):
#   docker build -f apps/worker/Dockerfile -t ghcr.io/fadexlabs/worker .
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

# ffmpeg: comprimir sets, convertir formatos y analizar espectros. rclone: entrega por Google Drive.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg rclone ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
COPY apps/api/requirements.txt apps/api/requirements.txt
COPY apps/worker/requirements.txt apps/worker/requirements.txt
RUN pip install -r apps/worker/requirements.txt

# El worker reutiliza el paquete de la API (modelos, base de datos, configuración, emails)
COPY apps/api/app ./app
COPY apps/worker/worker ./worker
COPY services ./services
ENV PYTHONPATH=/srv FADEX_SERVICES_DIR=/srv/services FADEX_DATA_DIR=/data HOME=/tmp

# Mismo uid que la API: comparten el volumen de datos
RUN useradd --uid 10001 --no-create-home fadex
USER 10001

CMD ["python", "-m", "worker.main"]
