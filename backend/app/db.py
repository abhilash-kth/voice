"""
Prisma database singleton + connection helpers.

Replaces the earlier SQLAlchemy layer. The generated client (from
`python -m prisma generate`) exposes AsyncClient operations; all reads/writes
go through `app/repo.py`. `DATABASE_URL` (set in .env) and the datasource
`provider` in schema.prisma decide whether you hit Neon/Postgres or SQLite.

Run once after any schema change (from backend/):
    python -m prisma db push --schema schema.prisma
    python -m prisma generate --schema schema.prisma
"""
from __future__ import annotations

import os
from typing import Optional

from .config import BASE_DIR

# Make sure the generated client package is importable when running from backend/.
BACKEND_DIR = str(BASE_DIR)
if BACKEND_DIR not in os.sys.path:
    os.sys.path.insert(0, BACKEND_DIR)

# Import the generated Prisma client. This requires `prisma generate` to have
# been run; a clear error is raised otherwise.
try:
    from prisma_client import Prisma
    from prisma_client.errors import PrismaError  # noqa: F401  (re-export)
except ImportError as e:  # pragma: no cover - surface a friendly message
    raise ImportError(
        "Prisma client not generated. From backend/ run:\n"
        "    python -m prisma db push --schema schema.prisma\n"
        "    python -m prisma generate --schema schema.prisma"
    ) from e

# Singleton across the process (FastAPI + worker share this module).
prisma: Optional[Prisma] = None


def get_prisma() -> Prisma:
    """Return the shared Prisma client, creating it lazily."""
    global prisma
    if prisma is None:
        prisma = Prisma()
    return prisma


def is_connected() -> bool:
    global prisma
    return bool(prisma and prisma.is_connected())


async def init() -> None:
    """Connect (called on FastAPI startup / worker start)."""
    client = get_prisma()
    if not client.is_connected():
        await client.connect()


async def shutdown() -> None:
    """Disconnect (called on FastAPI shutdown / worker exit)."""
    global prisma
    if prisma and prisma.is_connected():
        await prisma.disconnect()
