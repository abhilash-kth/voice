"""In-process snapshot of the DB-backed dynamic configuration (core lifecycle).

The voice pipeline's config resolution (agent_builder, billing) is *sync* and
runs deep inside the LiveKit worker where awaiting the database is not an
option. This module keeps a process-wide ConfigSnapshot that is refreshed
asynchronously and read synchronously. Extracted from the old monolithic
config_store — behavior unchanged. The merge/getter layer lives in
``config_merge.py`` and is re-exported through ``config_store.py``.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .. import llm_catalog as code_llm
logger = logging.getLogger("voice-agent-saas-config-store")

_REFRESH_TTL = float(os.getenv("ADMIN_CONFIG_TTL_SECONDS", "60"))

# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConfigSnapshot:
    ts: float = 0.0
    source: str = "code"  # "code" | "db"
    # providers[kind][slug] -> provider dict (superset of Provider row)
    providers: Dict[str, Dict[str, Dict[str, Any]]] = field(default_factory=dict)
    # models[kind] -> list of model row dicts (DB rows merged with meta)
    models: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    # billing config
    billing: Dict[str, Any] = field(default_factory=dict)
    # credentials[(kind, slug)] -> masked-only info; secrets never here
    credentials: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    # errors from the last refresh (surfaced in /api/admin/health)
    error: str = ""


_SNAPSHOT: Optional[ConfigSnapshot] = None
_STALE = True
_LOCK: Optional[asyncio.Lock] = None


def _snapshot_lock() -> asyncio.Lock:
    global _LOCK
    if _LOCK is None:
        _LOCK = asyncio.Lock()
    return _LOCK


# ---------------------------------------------------------------------------
# Code fallback snapshot (always available, mirrors pre-existing behaviour)
# ---------------------------------------------------------------------------


def _code_fallback_snapshot() -> ConfigSnapshot:
    return ConfigSnapshot(
        ts=time.time(),
        source="code",
        providers={},
        models={},
        billing={},
        credentials={},
        error="",
    )


def get_snapshot() -> ConfigSnapshot:
    """Latest snapshot; never None (code fallback when DB not loaded yet)."""
    global _SNAPSHOT
    if _SNAPSHOT is None:
        _SNAPSHOT = _code_fallback_snapshot()
    return _SNAPSHOT


# ---------------------------------------------------------------------------
# Refresh
# ---------------------------------------------------------------------------


def invalidate() -> None:
    """Mark the snapshot stale so the next async refresh rebuilds it. Called by
    the admin service after every successful mutation."""
    global _STALE
    _STALE = True


async def refresh_if_stale(force: bool = False) -> ConfigSnapshot:
    """Rebuild the snapshot from the DB if stale/TTL-expired. Safe no-op when
    the DB is unavailable: keeps the last good snapshot (or code fallback)."""
    global _SNAPSHOT, _STALE
    snap = get_snapshot()
    if not force and not _STALE and (time.time() - snap.ts) < _REFRESH_TTL:
        return snap
    async with _snapshot_lock():
        snap = get_snapshot()
        if not force and not _STALE and (time.time() - snap.ts) < _REFRESH_TTL:
            return snap
        try:
            from . import catalog_service

            new_snap = await catalog_service.build_snapshot_from_db()
            if new_snap is not None:
                _SNAPSHOT = new_snap
                _STALE = False
                snap = new_snap
        except Exception as e:
            logger.warning(f"config snapshot refresh failed (keeping last good): {e!r}")
    return snap


async def init(db_ready_check=None) -> ConfigSnapshot:
    """Startup hook: seed the DB from code defaults on first boot, then refresh."""
    try:
        from . import catalog_service

        await catalog_service.seed_defaults_if_empty()
    except Exception as e:
        logger.warning(f"dynamic config seed skipped: {e!r}")
    return await refresh_if_stale(force=True)

# test hooks
def _reset_for_tests() -> None:
    global _SNAPSHOT, _STALE, _LOCK
    _SNAPSHOT = None
    _STALE = True
    _LOCK = None


def _now_fallback() -> str:
    """Shared UTC timestamp for service-layer writes (kept here to avoid a
    circular import between credential/catalog/admin services)."""
    from datetime import datetime

    return datetime.utcnow().isoformat(timespec="seconds")
