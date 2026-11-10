from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.core.config import get_settings
from app.core.ratelimit import get_redis
from app.db import engine
from app.routers import admin, auth, beta, desktop, google, tools

settings = get_settings()
app = FastAPI(
    title="FADEX Labs API",
    version="0.1.0",
    # La documentación interactiva solo en desarrollo
    docs_url="/api/docs" if settings.env != "prod" else None,
    redoc_url=None,
    openapi_url="/api/openapi.json" if settings.env != "prod" else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,  # necesario para la cookie de refresh
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["authorization", "content-type", "x-fadex-csrf"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    h = response.headers
    h.setdefault("X-Content-Type-Options", "nosniff")
    h.setdefault("X-Frame-Options", "DENY")
    h.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    h.setdefault("Cache-Control", "no-store")  # respuestas de API con datos de cuenta
    if settings.env == "prod":
        h.setdefault("Strict-Transport-Security", "max-age=63072000; includeSubDomains; preload")
    return response


app.include_router(auth.router)
app.include_router(google.router)
app.include_router(desktop.router)
app.include_router(beta.router)
app.include_router(tools.router)
app.include_router(admin.router)


@app.get("/api/health", tags=["health"])
async def health() -> dict:
    """Liveness/readiness para k3s: comprueba Postgres y Redis."""
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    await get_redis().ping()
    return {"status": "ok"}
