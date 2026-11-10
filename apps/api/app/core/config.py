"""Configuración por variables de entorno (prefijo FADEX_). Ver .env.example."""
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FADEX_", env_file=".env", extra="ignore")

    env: str = "dev"  # dev | test | prod
    public_url: str = "http://localhost:3000"  # URL del sitio (enlaces de emails)
    cors_origins: list[str] = ["http://localhost:3000"]

    database_url: str = "postgresql+asyncpg://fadex:fadex@localhost:5432/fadex"
    redis_url: str = "redis://localhost:6379/0"

    # JWT Ed25519. En prod las claves vienen de un Secret de k3s (PEM).
    # En dev, si faltan, se genera un par efímero al arrancar.
    jwt_private_key: str = ""
    jwt_public_key: str = ""
    jwt_issuer: str = "https://fadexlabs.com"
    jwt_audience: str = "fadexlabs"
    access_ttl_seconds: int = 600            # 10 min
    refresh_ttl_seconds: int = 60 * 60 * 24 * 30  # 30 días
    refresh_cookie_name: str = "fx_refresh"
    refresh_cookie_path: str = "/api/auth"
    cookie_secure: bool = True

    email_token_ttl_seconds: int = 60 * 60 * 24  # verificación de email
    reset_token_ttl_seconds: int = 60 * 30        # recuperación de contraseña

    # Rate limiting (ventana fija en Redis)
    login_max_per_ip: int = 20
    login_max_per_email: int = 8
    rate_window_seconds: int = 900

    # SMTP (Telmex bloquea el 25; el dossier confirma 2525 disponible)
    smtp_host: str = ""
    smtp_port: int = 2525
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "FADEX Labs <no-reply@fadexlabs.com>"

    password_min_length: int = Field(default=10, ge=8)

    # Beta cerrada de las herramientas para DJs: los primeros N usuarios con email confirmado y WhatsApp
    beta_seats: int = 10
    phone_default_region: str = "MX"

    # Inicio de sesión con Google (OpenID Connect). Sin client_id el botón queda desactivado.
    google_client_id: str = ""
    google_client_secret: str = ""
    oauth_state_ttl_seconds: int = 600

    # ---------- Herramientas de la beta (Tracklist ID y DJ Library Upgrader) ----------
    # Carpeta compartida entre la API (subidas, resultados) y el worker (procesa). En k3s es el PVC fadex-data.
    data_dir: str = "./data"
    # Tamaño de cada parte. Cloudflare Tunnel rechaza cuerpos de más de 100 MB y el proxy de Next
    # (/api → API, en desarrollo o si se entra por la web directo) corta los de más de 10 MB.
    upload_chunk_bytes: int = 8 * 1024 * 1024
    upload_ttl_seconds: int = 60 * 60 * 24           # subidas sin completar: se borran
    result_ttl_days: int = 30                        # resultados (tracklist, informes) disponibles
    tracklist_max_bytes: int = 3 * 1024**3           # un WAV de 2 h pesa ~1.2 GB
    tracklist_min_seconds: int = 30
    tracklist_per_day: int = 5
    library_max_bytes: int = 10 * 1024**3            # zip de la librería
    library_max_files: int = 3000                    # pistas de audio por librería
    library_max_unpacked_gb: float = 40
    library_per_day: int = 2
    tools_init_per_hour: int = 30                    # rate limit de inicio/cierre de subidas por usuario

    # Worker · Tracklist ID. El token de ACRCloud llega en ACRCLOUD_TOKEN (sin prefijo; solo al worker).
    tracklist_kbps: int = 96
    acr_max_seconds: int = 60 * 60
    shazam_max_seconds: int = 15 * 60                # tope de Shazam cuando ACRCloud respondió (0 = sin Shazam)
    shazam_fallback_max_seconds: int = 60 * 60       # tope cuando Shazam es el único motor
    shazam_fail_streak: int = 4                      # fragmentos seguidos rechazados para dar a Shazam por saturado
    # Comandos alternativos (pruebas y humo sin red): reciben "<set> <salida>" como argumentos.
    acr_scan_cmd: str = ""
    shazam_scan_cmd: str = ""

    # Worker · DJ Library Upgrader: slskd (Soulseek) propio de la plataforma + entrega por Google Drive.
    slskd_url: str = "http://localhost:5030"
    slskd_api_key: str = ""
    slskd_downloads_dir: str = ""                    # vacío = <data_dir>/slskd/downloads
    upgrade_max_hours: float = 12                    # tope por librería; se entrega lo conseguido
    upgrade_search_delay: float = 3                  # pausa entre búsquedas (no saturar la red)
    upgrade_watch_seconds: int = 15                  # cada cuánto se revisan las descargas
    # Tiempos por canción: si la descarga de un candidato no arranca se prueba otro; si en total pasa el
    # tiempo de la canción sin una descarga avanzando, queda pendiente en el informe.
    upgrade_song_timeout_seconds: int = 600
    upgrade_candidate_wait_seconds: int = 120
    upgrade_stall_seconds: int = 120
    rclone_bin: str = "rclone"
    rclone_remote: str = ""                          # p. ej. "gdrive:FADEX/Entregas"; vacío = entrega pendiente (manual)

    # App de escritorio (DJ Library Upgrader para Windows): login con navegador + loopback + PKCE (RFC 8252)
    desktop_code_ttl_seconds: int = 120              # código de autorización de un solo uso
    # Última versión publicada del instalador (GET /api/desktop/latest). Sin versión: 404 (no hay descarga).
    desktop_version: str = ""
    desktop_url: str = ""                            # https://… del .exe
    desktop_sha256: str = ""
    desktop_notes: str = ""

    worker_poll_seconds: float = 5
    services_dir: str = ""                           # código vendorizado de las herramientas; vacío = <repo>/services

    @property
    def google_redirect_uri(self) -> str:
        return f"{self.public_url}/api/auth/google/callback"


@lru_cache
def get_settings() -> Settings:
    return Settings()
