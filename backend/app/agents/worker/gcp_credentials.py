from __future__ import annotations

import os
import logging
import time
from typing import Optional
logger = logging.getLogger("voice-agent-saas-worker")


# cross-module imports (auto-generated)
from .gcp_env import CLOUD_PLATFORM_SCOPE, CREDS_CACHE, CREDS_LOCK, _ORIG_LOAD_CREDS

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
