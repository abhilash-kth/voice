from __future__ import annotations

import os
import asyncio
import logging
import hashlib as _hl
from typing import Any

logger = logging.getLogger("voice-agent-saas-worker")


# cross-module imports (auto-generated)
from .dep_imports import _ssl_prewarm, _threading_prewarm

_ssl_context_cache = None
_ssl_context_lock = _threading_prewarm.Lock()

def _build_ssl_context():
    """Build the default SSL context the same way httpx does.

    httpx (trust_env=True) honours SSL_CERT_FILE / SSL_CERT_DIR, and on Windows
    parsing that CA bundle inside `ssl.create_default_context()` is what blocked
    the agent loop for >1s during Prisma's connect. The cached context must be
    built with the same cafile/capath, otherwise handing it to httpx would
    silently change which CAs are trusted.
    """
    _cafile = os.environ.get("SSL_CERT_FILE")
    _capath = os.environ.get("SSL_CERT_DIR")
    if _cafile and os.path.exists(_cafile):
        return _ssl_prewarm.create_default_context(cafile=_cafile)
    if _capath and os.path.isdir(_capath):
        return _ssl_prewarm.create_default_context(capath=_capath)
    return _ssl_prewarm.create_default_context()


def _prewarm_ssl_context():
    global _ssl_context_cache
    try:
        ctx = _build_ssl_context()
        with _ssl_context_lock:
            _ssl_context_cache = ctx
        logger.info("🔧 SSL context prewarmed at import time in background thread (fixes 314ms event loop block)")
    except Exception as e:
        logger.debug(f"SSL prewarm failed: {e}")

# Start prewarm immediately in daemon thread
_threading_prewarm.Thread(target=_prewarm_ssl_context, daemon=True).start()

# Patch LiveKit http_context and httpx to use cached SSL context - fixes 314ms and 1359ms blocks


async def ensure_ssl_before_db_init() -> None:
    """Ensure the SSL context cache exists before DB init. If the import-time
    prewarm thread has not finished, build it off-loop in a thread (never on the
    loop — that is the >1s ssl.create_default_context stall right before the
    greeting). Extracted verbatim from `_entrypoint_body`."""
    try:
        if _ssl_context_cache is None:
            await asyncio.wait_for(asyncio.to_thread(_prewarm_ssl_context), timeout=4)
            if _ssl_context_cache is None:
                logger.warning("⚠️ SSL context still not cached before DB init — first connect may block the loop")
            else:
                logger.info("🔧 SSL context ready before DB init (built off-loop)")
    except Exception as _e:
        logger.debug(f"SSL ensure failed: {_e!r}")

