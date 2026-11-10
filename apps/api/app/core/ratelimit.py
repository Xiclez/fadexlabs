"""Rate limiting de ventana fija sobre Redis."""
from fastapi import HTTPException, Request, status
from redis.asyncio import Redis

from app.core.config import get_settings

_redis: Redis | None = None


def get_redis() -> Redis:
    global _redis
    if _redis is None:
        s = get_settings()
        if s.redis_url == "memory://" and s.env in ("dev", "test"):
            # Solo para desarrollo sin Docker (fakeredis está en requirements-dev.txt)
            import fakeredis.aioredis
            _redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
        else:
            _redis = Redis.from_url(s.redis_url, decode_responses=True)
    return _redis


def set_redis(client: Redis) -> None:  # para tests
    global _redis
    _redis = client


def client_ip(request: Request) -> str:
    # Detrás de Cloudflare Tunnel + Traefik la IP real llega en CF-Connecting-IP.
    return (request.headers.get("cf-connecting-ip")
            or (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
            or (request.client.host if request.client else "unknown"))


async def hit(key: str, limit: int, window: int | None = None) -> None:
    """Cuenta un intento; lanza 429 si `key` superó `limit` en la ventana."""
    window = window or get_settings().rate_window_seconds
    r = get_redis()
    k = f"rl:{key}"
    count = await r.incr(k)
    if count == 1:
        await r.expire(k, window)
    if count > limit:
        ttl = await r.ttl(k)
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            "Demasiados intentos. Intenta más tarde.",
                            headers={"Retry-After": str(max(ttl, 1))})


async def reset(key: str) -> None:
    await get_redis().delete(f"rl:{key}")
