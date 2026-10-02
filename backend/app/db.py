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
from typing import Dict, Optional

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

# Back-compat module attribute: the most recently created client. Kept only so
# legacy status pokes do not break; ALL real access must go through
# ``get_prisma()`` which returns the client owned by the *current* event loop.
prisma: Optional[Prisma] = None

# Event-loop affinity — per-loop client registry.
#
# A Prisma client (engine subprocess + httpx pool) is hard-bound to the asyncio
# loop it connected on: using it from any other loop hangs queries or raises
# "Event loop is closed". LiveKit's job runner executes each job on its own
# loop (jobs run in per-job threads), so one process legitimately hosts
# several loops over its lifetime.
#
# The old singleton reconnected the one shared client whenever a foreign loop
# called init() ("Prisma client is connected to a different event loop —
# reconnecting"): every job paid the ~2.5s engine startup AGAIN mid-call, and
# any queries still in flight on the previous loop were broken underneath.
#
# Instead, each loop gets its OWN client, connected lazily on first init() on
# that loop, with its own connect lock (asyncio.Lock is loop-bound, so locks
# live per loop too — reusing one across loops raises "got Future attached to
# a different loop"). Loops that go away release their client via
# ``release_current_loop()`` (the worker calls it on job shutdown); bounded
# registry, no leaks, zero cross-loop churn.
_prisma_by_loop: Dict[asyncio.AbstractEventLoop, Prisma] = {}
_locks_by_loop: Dict[asyncio.AbstractEventLoop, asyncio.Lock] = {}
# Fallback for sync / no-running-loop contexts (import-time pokes only; real
# queries always run inside a loop).
_fallback_prisma: Optional[Prisma] = None


def get_prisma() -> Prisma:
    """Return the Prisma client owned by the *current* event loop.

    Creates it lazily (unconnected; ``init()`` connects). Called from sync
    module-level code without a running loop returns a shared fallback client.
    """
    global prisma, _fallback_prisma
    try:
        loop: Optional[asyncio.AbstractEventLoop] = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is None:
        if _fallback_prisma is None:
            _fallback_prisma = Prisma()
            prisma = _fallback_prisma
        return _fallback_prisma
    client = _prisma_by_loop.get(loop)
    if client is None:
        client = Prisma()
        _prisma_by_loop[loop] = client
        prisma = client
    return client


def is_connected() -> bool:
    """True only when the client *of the current event loop* is connected."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return any(c.is_connected() for c in _prisma_by_loop.values()) or bool(
            _fallback_prisma and _fallback_prisma.is_connected()
        )
    client = _prisma_by_loop.get(loop)
    return bool(client and client.is_connected())


def _get_loop_lock(loop: asyncio.AbstractEventLoop) -> asyncio.Lock:
    lock = _locks_by_loop.get(loop)
    if lock is None:
        lock = asyncio.Lock()
        _locks_by_loop[loop] = lock
    return lock


async def init() -> None:
    """Connect this loop's client. Idempotent; safe to call from every loop."""
    loop = asyncio.get_running_loop()
    client = get_prisma()
    if client.is_connected():
        return
    # Multiple entrypoints on the same loop can race here; serialize per loop.
    async with _get_loop_lock(loop):
        if client.is_connected():
            return
        await client.connect()


async def release_current_loop() -> None:
    """Disconnect and drop the client owned by the *current* loop.

    Call this when a short-lived loop is about to close (LiveKit job thread,
    throwaway runner loops) so engine processes do not pile up in long-lived
    worker processes. Best-effort; never raises.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    client = _prisma_by_loop.pop(loop, None)
    _locks_by_loop.pop(loop, None)
    if client is not None and client.is_connected():
        try:
            await asyncio.wait_for(client.disconnect(), timeout=5)
        except Exception as e:
            logger.debug(f"Releasing this loop's Prisma client failed: {e!r}")


async def shutdown() -> None:
    """Disconnect ALL loop-bound clients (FastAPI shutdown / worker exit)."""
    global prisma
    for loop, client in list(_prisma_by_loop.items()):
        if client.is_connected():
            try:
                await asyncio.wait_for(client.disconnect(), timeout=5)
            except Exception as e:
                logger.debug(f"Disconnecting a loop-bound Prisma client failed: {e!r}")
    _prisma_by_loop.clear()
    _locks_by_loop.clear()
    if _fallback_prisma is not None and _fallback_prisma.is_connected():
        try:
            await asyncio.wait_for(_fallback_prisma.disconnect(), timeout=5)
        except Exception:
            pass
    prisma = None
