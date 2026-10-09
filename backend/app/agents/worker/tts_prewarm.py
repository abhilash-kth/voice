from __future__ import annotations

import os
import asyncio
import logging
from typing import Any, Iterator, Optional

logger = logging.getLogger("voice-agent-saas-worker")


# cross-module imports (auto-generated)
from .gcp_env import _INNER_ATTRS, _INNER_LIST_ATTRS
from .gcp_credentials import default_credentials_path, warm_google_credentials

# ---------------------------------------------------------------------------
# TTS client loop guard
# ---------------------------------------------------------------------------
def iter_tts_instances(tts_inst: Any, _depth: int = 0) -> Iterator[Any]:
    """Yield ``tts_inst`` plus any FallbackAdapter / timing-wrapper inner instances."""
    if tts_inst is None or _depth > 4:
        return
    yield tts_inst
    for attr in _INNER_LIST_ATTRS:
        inner_list = getattr(tts_inst, attr, None)
        if inner_list:
            for inner in inner_list:
                if inner is not None and inner is not tts_inst:
                    yield from iter_tts_instances(inner, _depth + 1)
    for attr in _INNER_ATTRS:
        inner = getattr(tts_inst, attr, None)
        if inner is not None and inner is not tts_inst:
            yield from iter_tts_instances(inner, _depth + 1)


def google_tts_credentials_path(tts_inst: Any) -> Optional[str]:
    """The credentials file this (possibly wrapped) Google TTS would load lazily."""
    for inst in iter_tts_instances(tts_inst):
        path = getattr(inst, "_credentials_file", None)
        # NOT_GIVEN / None are not str; only a real path is usable.
        if isinstance(path, str) and path:
            return path
    fallback = default_credentials_path()
    if fallback and os.path.exists(fallback):
        return fallback
    return None


def client_bound_loop(client: Any) -> Optional[asyncio.AbstractEventLoop]:
    """Best-effort: the event loop a google async client's gRPC channel is on."""
    transport = getattr(client, "_transport", None)
    candidates = (
        transport,
        getattr(transport, "_channel", None),
        getattr(transport, "grpc_channel", None),
    )
    for candidate in candidates:
        if candidate is None:
            continue
        loop = getattr(candidate, "_loop", None)
        if isinstance(loop, asyncio.AbstractEventLoop):
            return loop
    return None


def guard_tts_client_loop(tts_inst: Any) -> int:
    """Drop cached async TTS clients bound to a dead or foreign event loop.

    Self-healing net for ``RuntimeError: Event loop is closed`` escaping from
    ``grpc.aio``: if a client was built on a loop other than the one now running
    (an old off-loop prewarm, or an instance reused across jobs/processes),
    reset ``_client`` so the plugin rebuilds it on the correct loop.

    Must be called from the event loop that will do the synthesis.
    Returns the number of poisoned clients that were dropped.
    """
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        return 0

    dropped = 0
    for inst in iter_tts_instances(tts_inst):
        client = getattr(inst, "_client", None)
        if client is None:
            continue
        bound = client_bound_loop(client)
        if bound is not None and (bound.is_closed() or bound is not running):
            try:
                inst._client = None
                dropped += 1
                logger.warning(
                    "🛑 Dropped a cached Google TTS async client bound to a "
                    f"{'closed' if bound.is_closed() else 'foreign'} event loop — it will be "
                    "rebuilt on the agent loop (prevents 'RuntimeError: Event loop is closed' "
                    "from silencing the whole call)"
                )
            except Exception as e:
                logger.debug(f"Could not reset poisoned TTS client: {e!r}")
    return dropped


async def warm_tts_off_loop(tts_inst: Any, timeout: float = 3.0) -> bool:
    """Awaitable warm-up for a freshly built TTS instance.

    Warms only credentials (in a thread) and then guards the instance against a
    client that is bound to the wrong loop. Never creates the async client.
    """
    warmed = False
    try:
        creds_path = google_tts_credentials_path(tts_inst)
        if creds_path:
            await asyncio.wait_for(
                asyncio.to_thread(warm_google_credentials, creds_path), timeout=timeout
            )
            warmed = True
            logger.info("🔧 TTS credentials warm off-loop completed (client is created on the agent loop)")
        else:
            logger.debug("TTS credential warm skipped: no Google credentials file on the TTS instance")
    except Exception as e:
        logger.debug(f"TTS credential prewarm skipped: {e!r}")
    guard_tts_client_loop(tts_inst)
    return warmed


# ---------------------------------------------------------------------------
# Call-failure surfacing
# ---------------------------------------------------------------------------
