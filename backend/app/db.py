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

import asyncio
import logging
import os
from typing import Optional

from .config import BASE_DIR

logger = logging.getLogger("voice-agent-saas-db")

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

# Event-loop affinity.
#
# Prisma's engine + httpx connection pool (and asyncio.Lock itself) are bound to
# the loop that created them. Connecting from a throwaway loop — e.g. the old
# `asyncio.to_thread(lambda: asyncio.new_event_loop().run_until_complete(init())`
# in the LiveKit worker — leaves a client that *reports* itself connected while
# every real query on the agent loop hangs until it times out (or raises
# "Event loop is closed"). So we remember which loop we connected on and refuse
# to reuse the client from a different one.
_connected_loop: Optional[asyncio.AbstractEventLoop] = None
_connect_lock: Optional[asyncio.Lock] = None
_connect_lock_loop: Optional[asyncio.AbstractEventLoop] = None


def get_prisma() -> Prisma:
    """Return the shared Prisma client, creating it lazily."""
    global prisma
    if prisma is None:
        prisma = Prisma()
    return prisma


def is_connected() -> bool:
    """True only when the client is connected *to the current event loop*."""
    global prisma
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return bool(prisma and prisma.is_connected())
    return bool(prisma and prisma.is_connected() and _connected_loop is loop)


def _get_connect_lock() -> asyncio.Lock:
    """asyncio.Lock binds to the loop that first awaits it (LoopBoundMixin).

    Build it per running loop instead of at import time so a process that sees
    more than one loop (LiveKit job runner, tests) never hits
    "got Future attached to a different loop".
    """
    global _connect_lock, _connect_lock_loop
    loop = asyncio.get_running_loop()
    if _connect_lock is None or _connect_lock_loop is not loop:
        _connect_lock = asyncio.Lock()
        _connect_lock_loop = loop
    return _connect_lock


async def init() -> None:
    """Connect on the *calling* event loop (FastAPI startup / worker entrypoint)."""
    global prisma, _connected_loop
    client = get_prisma()
    loop = asyncio.get_running_loop()
    if client.is_connected() and _connected_loop is loop:
        return
    # Multiple LiveKit jobs can start together. Serialize initialization so
    # concurrent Prisma engine startup does not leave one request hanging.
    async with _get_connect_lock():
        if client.is_connected() and _connected_loop is loop:
            return
        if client.is_connected():
            # Connected from another loop: unusable here. Drop it and start a
            # fresh client rather than hang every query on this loop.
            logger.warning(
                "Prisma client is connected to a different event loop — reconnecting on the "
                "current loop (a foreign-loop client makes queries hang or raise "
                "'Event loop is closed')"
            )
            try:
                await asyncio.wait_for(client.disconnect(), timeout=3)
            except Exception as e:
                logger.debug(f"Disconnecting the foreign-loop Prisma client failed: {e!r}")
                prisma = Prisma()  # abandon it; a fresh client gets a fresh engine/pool
                client = prisma
            _connected_loop = None
        await client.connect()
        _connected_loop = loop


async def shutdown() -> None:
    """Disconnect (called on FastAPI shutdown / worker exit)."""
    global prisma, _connected_loop
    if prisma and prisma.is_connected():
        await prisma.disconnect()
        _connected_loop = None
