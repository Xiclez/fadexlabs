FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

# ffprobe: valida por contenido los sets que se suben a las herramientas
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY alembic.ini .
COPY alembic ./alembic
COPY app ./app

# Usuario sin privilegios (k3s además fuerza runAsNonRoot)
RUN useradd --uid 10001 --no-create-home fadex
USER 10001

EXPOSE 8000
# Las migraciones las corre un initContainer / job aparte, no cada réplica
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
