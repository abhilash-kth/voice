"""Event-loop safety helpers for provider clients used by the LiveKit worker.

Why this module exists
----------------------
The worker goes to a lot of trouble to move blocking startup work (SSL context
creation, service-account parsing, VAD model load, ...) off the agent event
loop, because a 150-400ms synchronous block delays audio and turn handling.
Two of those "optimisations" were loop-*hostile* rather than loop-friendly and
broke live calls:

1. Google TTS was "prewarmed" by calling ``_ensure_client()`` inside
   ``asyncio.new_event_loop()`` on a worker thread, then closing that loop.
   ``_ensure_client()`` caches a ``texttospeech.TextToSpeechAsyncClient`` whose
   ``grpc.aio`` channel remembers the loop it was created on, so every later
   ``streaming_synthesize()`` on the real agent loop died with::

       RuntimeError: Event loop is closed   (grpc/aio/_call.py -> loop.create_task)

   i.e. the agent joined the room, transcribed fine, and then never spoke.

2. Prisma was connected the same way (``to_thread`` + ``new_event_loop()``),
   binding the process-wide client/pool to a throwaway loop, so the first real
   query hung until its 3s timeout.

Rule of thumb enforced here: **only loop-independent work may be prewarmed off
the loop.** For Google that means the credentials (JSON + RSA parse); the async
gRPC client must always be created by the plugin on the loop that uses it.

The helpers are dependency-free (google/auth imports are lazy) so they can be
unit-tested without the LiveKit runtime installed.
"""
from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from typing import Any, Iterator, Optional

logger = logging.getLogger("voice-agent-saas-worker")

CLOUD_PLATFORM_SCOPE = "https://www.googleapis.com/auth/cloud-platform"

# Cache of parsed service-account credentials: key -> (credentials, project_id).
# Populated off-loop by warm_google_credentials() and read by the patched
# google.auth.load_credentials_from_file() so the on-loop client build is cheap.
CREDS_CACHE: dict = {}
CREDS_LOCK = threading.Lock()

# The unpatched loader, kept so warming works whether or not the patch installed.
_ORIG_LOAD_CREDS = None

# Attribute names used by livekit's FallbackAdapter / our timing wrapper to hold
# the real TTS instances.
_INNER_LIST_ATTRS = ("_tts_instances", "tts_instances", "_instances")
_INNER_ATTRS = ("_tts", "_inner")


# ---------------------------------------------------------------------------
# Credentials cache
# ---------------------------------------------------------------------------
def creds_cache_key(args: tuple, kwargs: dict) -> str:
    """Stable cache key for ``load_credentials_from_file(*args, **kwargs)``.

    Keyed per (file, scopes) because one deployment can serve several agents,
    potentially with different key files — a single global entry would hand the
    wrong credentials to the second one.
    """
    try:
        return repr((args, sorted((k, repr(v)) for k, v in kwargs.items())))
    except Exception:
        return "default"


def default_credentials_path() -> Optional[str]:
    """GOOGLE_APPLICATION_CREDENTIALS env var, else the repo's google-key.json."""
    env_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if env_path:
        return env_path
    try:
        from app.config import GOOGLE_APPLICATION_CREDENTIALS as cfg_path
        return cfg_path or None
    except Exception:
        return None


def install_credential_cache() -> bool:
    """Patch ``google.auth.load_credentials_from_file`` to use CREDS_CACHE.

    Returns True when the patch is in place. Safe to call once at import time;
    a failure (google-auth not installed) is logged at debug level because the
    API-only environment doesn't need it.
    """
    global _ORIG_LOAD_CREDS
    try:
        import google.auth as _ga
    except Exception as e:  # pragma: no cover - depends on installed extras
        logger.debug(f"google.auth unavailable, credential cache not installed: {e!r}")
        return False

    if getattr(_ga.load_credentials_from_file, "_voice_cached", False):
        return True  # idempotent

    try:
        _ORIG_LOAD_CREDS = _ga.load_credentials_from_file

        def _patched_load_creds(*args, **kwargs):
            key = creds_cache_key(args, kwargs)
            with CREDS_LOCK:
                hit = CREDS_CACHE.get(key)
            if hit is not None:
                return hit
            creds = _ORIG_LOAD_CREDS(*args, **kwargs)
            with CREDS_LOCK:
                CREDS_CACHE[key] = creds
            return creds

        _patched_load_creds._voice_cached = True
        _ga.load_credentials_from_file = _patched_load_creds

        # google.auth re-exports the same function, but patch _default too: some
        # SDK versions call it through the private module.
        import google.auth._default as _ga_default

        _orig_default_load = _ga_default.load_credentials_from_file

        def _patched_default_load(*args, **kwargs):
            key = creds_cache_key(args, kwargs)
            with CREDS_LOCK:
                hit = CREDS_CACHE.get(key)
            if hit is not None:
                return hit
            creds = _orig_default_load(*args, **kwargs)
            with CREDS_LOCK:
                CREDS_CACHE[key] = creds
            return creds

        _patched_default_load._voice_cached = True
        _ga_default.load_credentials_from_file = _patched_default_load
        logger.info(
            "🔧 Patched google.auth.load_credentials_from_file to use cached credentials (fixes 163ms RSA init block)"
        )
        return True
    except Exception as e:
        logger.debug(f"Could not patch google auth credential cache: {e!r}")
        return False


def warm_google_credentials(path: Optional[str] = None) -> bool:
    """Parse + cache a service-account key file **in the calling thread**.

    This is the blocking, loop-independent half of Google TTS startup (~163ms of
    JSON + RSA work). Call it from ``asyncio.to_thread(...)`` or a prewarm
    thread; the async gRPC client is still built lazily by the plugin on the
    loop that actually synthesizes audio.

    Returns True when credentials for ``path`` are now cached.
    """
    path = path or default_credentials_path()
    if not path or not os.path.exists(path):
        return False

    # Exactly the call shape the Google plugin uses inside _ensure_client(), so
    # the key matches and the later on-loop build is a cache hit.
    args: tuple = (path,)
    kwargs: dict = {"scopes": [CLOUD_PLATFORM_SCOPE]}
    key = creds_cache_key(args, kwargs)
    with CREDS_LOCK:
        if key in CREDS_CACHE:
            return True

    loader = _ORIG_LOAD_CREDS
    if loader is None:
        try:
            import google.auth as _ga
            loader = _ga.load_credentials_from_file
        except Exception as e:
            logger.debug(f"Google credential warm unavailable: {e!r}")
            return False

    t0 = time.time()
    try:
        creds = loader(*args, **kwargs)
        with CREDS_LOCK:
            CREDS_CACHE[key] = creds
        logger.info(
            f"🔧 Google credentials warm off-loop in {(time.time() - t0) * 1000:.0f}ms "
            f"({os.path.basename(path)}) — async TTS client stays on the agent loop"
        )
        return True
    except Exception as e:
        logger.warning(f"⚠️ Google credential warm failed for {path}: {e!r}")
        return False


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
