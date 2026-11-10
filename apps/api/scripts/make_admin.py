"""Convierte una cuenta existente en administradora (o le quita el rol con --revoke).

Uso (desde apps/api, con las mismas variables FADEX_* que la API):
    python scripts/make_admin.py correo@ejemplo.com [--revoke]
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select  # noqa: E402

from app.db import SessionLocal, engine  # noqa: E402
from app.models import User  # noqa: E402


async def main(email: str, revoke: bool) -> int:
    async with SessionLocal() as db:
        user = (await db.execute(select(User).where(User.email == email.strip().lower()))).scalar_one_or_none()
        if not user:
            print(f"No existe una cuenta con el email {email}")
            return 1
        user.role = "user" if revoke else "admin"
        await db.commit()
        print(f"{user.email}: rol {user.role}.")
    await engine.dispose()
    return 0


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 1:
        sys.exit(__doc__)
    sys.exit(asyncio.run(main(args[0], "--revoke" in sys.argv)))
