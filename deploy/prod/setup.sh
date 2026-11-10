#!/usr/bin/env bash
# Prepara el servidor para docker-compose.prod.yml. Se ejecuta UNA vez, desde la raíz del repo:
#     bash deploy/prod/setup.sh
# Genera .env (contraseñas, clave JWT, API key de slskd), deploy/slskd/slskd.yml, las carpetas de datos
# y copia tu rclone.conf. Nada de eso se sube a git. Si .env ya existe, no lo toca.
set -euo pipefail
cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/../.."

ask() {  # ask VARIABLE "pregunta" [valor por defecto]; respeta la variable si ya viene del entorno
  local var="$1" prompt="$2" def="${3:-}" val="${!1:-}"
  if [[ -z "$val" ]]; then
    read -r -p "$prompt${def:+ [$def]}: " val
    val="${val:-$def}"
  fi
  printf -v "$var" '%s' "$val"
}

if [[ -f .env ]]; then
  echo ".env ya existe: no lo toco. (Bórralo si quieres generar todo de nuevo.)"
else
  command -v openssl >/dev/null || { echo "Falta openssl."; exit 1; }
  ask DOMAIN       "Dominio del sitio (sin https://)" "fadexlabs.com"
  ask SLSK_USER    "Usuario de Soulseek SOLO para FADEX (distinto al de tu otro slskd; se crea solo)"
  ask SLSK_PASS    "Contraseña de ese usuario de Soulseek"
  ask RCLONE_DEST  "Carpeta de Drive para las entregas (remoto:carpeta)" "gdrive:FADEX/Entregas"
  ask ACR_TOKEN    "Token de ACRCloud (Enter para dejarlo vacío: Tracklist ID usará solo Shazam)" ""
  [[ -n "$SLSK_USER" && -n "$SLSK_PASS" ]] || { echo "El usuario y la contraseña de Soulseek son obligatorios."; exit 1; }

  PG_PASS=$(openssl rand -hex 24)
  SLSKD_KEY=$(openssl rand -hex 24)
  JWT_KEY=$(openssl genpkey -algorithm ed25519 | awk 'BEGIN{ORS="\\n"} {print}')
  umask 077
  cat > .env <<ENV
# Generado por deploy/prod/setup.sh. Contiene secretos: no lo subas a git ni lo compartas.
POSTGRES_PASSWORD=$PG_PASS
WEB_PORT=3020
SLSK_PORT=50302

FADEX_ENV=prod
FADEX_PUBLIC_URL=https://$DOMAIN
FADEX_CORS_ORIGINS='["https://$DOMAIN","https://www.$DOMAIN"]'
FADEX_JWT_ISSUER=https://$DOMAIN
FADEX_JWT_PRIVATE_KEY='$JWT_KEY'
FADEX_DATABASE_URL=postgresql+asyncpg://fadex:$PG_PASS@postgres:5432/fadex
FADEX_REDIS_URL=redis://redis:6379/0
FADEX_BETA_SEATS=10

# Emails (confirmación de cuenta, avisos de trabajos). Sin SMTP se escriben en los logs.
FADEX_SMTP_HOST=
FADEX_SMTP_PORT=2525
FADEX_SMTP_USER=
FADEX_SMTP_PASSWORD=

# Herramientas
FADEX_DATA_DIR=/data
ACRCLOUD_TOKEN=$ACR_TOKEN
FADEX_SLSKD_URL=http://slskd:5030
FADEX_SLSKD_API_KEY=$SLSKD_KEY
FADEX_SLSKD_DOWNLOADS_DIR=/data/slskd/downloads
FADEX_RCLONE_REMOTE=$RCLONE_DEST

# Límites ajustados a un disco chico (~48 GB libres). Una librería ocupa varias veces su tamaño mientras
# se procesa: zip + extraída + descargas sin pérdida + entrega convertida. Súbelos si amplías el disco.
FADEX_LIBRARY_MAX_BYTES=2147483648
FADEX_LIBRARY_MAX_FILES=500
FADEX_LIBRARY_MAX_UNPACKED_GB=4
ENV

  mkdir -p deploy/slskd
  SLSK_USER="$SLSK_USER" SLSK_PASS="$SLSK_PASS" SLSKD_KEY="$SLSKD_KEY" WEB_PASS="$(openssl rand -hex 12)" \
  python3 - <<'PY'
import json, os
s = open("deploy/slskd/slskd.example.yml", encoding="utf-8").read()
q = json.dumps  # comillas y escapes válidos en YAML
s = s.replace("  username: CAMBIAR\n  password: CAMBIAR\n  listen_port: 50300",
              f"  username: {q(os.environ['SLSK_USER'])}\n  password: {q(os.environ['SLSK_PASS'])}\n  listen_port: 50302")
s = s.replace("    password: CAMBIAR", f"    password: {q(os.environ['WEB_PASS'])}")
s = s.replace("        key: CAMBIAR ", f"        key: {os.environ['SLSKD_KEY']} ")
assert "CAMBIAR\n" not in s and "CAMBIAR " not in s.split("api_keys")[1], "la plantilla de slskd cambió"
open("deploy/slskd/slskd.yml", "w", encoding="utf-8").write(s)
PY
  echo "✓ .env y deploy/slskd/slskd.yml generados"
fi

# Carpetas de datos con el uid de los contenedores (10001)
mkdir -p data/slskd/app data/slskd/downloads data/slskd/incomplete deploy/rclone
if [[ ! -f deploy/rclone/rclone.conf ]]; then
  src=$(rclone config file 2>/dev/null | tail -1 || true)
  if [[ -n "${src:-}" && -f "$src" ]]; then
    cp "$src" deploy/rclone/rclone.conf
    echo "✓ rclone.conf copiado de $src"
  else
    echo "! No encontré tu rclone.conf: sin él, las entregas quedan en data/jobs/<id>/entrega (pendientes)."
  fi
fi
chmod 600 deploy/slskd/slskd.yml deploy/rclone/rclone.conf 2>/dev/null || true
chown -R 10001:10001 data deploy/rclone deploy/slskd/slskd.yml 2>/dev/null \
  || echo "! No pude cambiar el dueño de data/: ejecuta este script como root."

echo
echo "Listo. Siguiente:"
echo "  docker compose -f docker-compose.prod.yml up -d --build"
echo "  docker compose -f docker-compose.prod.yml ps"
