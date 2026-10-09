from __future__ import annotations

import os
import re
import sys
import asyncio
import logging
import time
import uuid
import json
import traceback
import hashlib as _hl
from typing import Any, Iterator, Optional

logger = logging.getLogger("voice-agent-saas-worker")


# cross-module imports (auto-generated)
from .dep_imports import _ssl_prewarm
from .ssl_cert_patch import _ssl_context_cache, _ssl_context_lock

try:
    from livekit.agents.utils import http_context as _http_context
    _original_create_ssl = _http_context._create_ssl_context
    def _patched_create_ssl_context(*args, **kwargs):
        global _ssl_context_cache
        # Fast path: return cached context if available (no load_verify_locations)
        with _ssl_context_lock:
            if _ssl_context_cache is not None:
                return _ssl_context_cache
        # Fallback: if not cached yet (very early), create but log
        logger.info("🔧 SSL cache miss, creating context (should be prewarmed)")
        try:
            ctx = _ssl_prewarm.create_default_context(*args, **kwargs)
            with _ssl_context_lock:
                _ssl_context_cache = ctx
            return ctx
        except Exception:
            return _original_create_ssl(*args, **kwargs)
    _http_context._create_ssl_context = _patched_create_ssl_context
    logger.info("🔧 Patched http_context._create_ssl_context to use cached SSL (fixes 314ms event loop block at ssl.py:717)")
except Exception as e:
    logger.debug(f"Could not patch http_context for SSL fix: {e}")

# Also patch httpx SSL context to fix the multi-second ssl.create_default_context
# block during prisma/httpx DB init (observed at 1359ms, then 1377ms even WITH
# this patch — see below why it needed two bites).
try:
    import httpx._config as _httpx_config
    _original_httpx_ssl = _httpx_config.create_ssl_context

    def _patched_httpx_ssl(verify=True, cert=None, trust_env=True, *args, **kwargs):
        """Cached SSL context for httpx — but only for the default case.

        `verify=False` or a client certificate must NOT be served the shared
        default context (that would verify when the caller asked not to, or drop
        the client cert), so anything non-default falls through to httpx's own
        implementation.
        """
        global _ssl_context_cache
        non_default = (verify is not True) or cert is not None or args or kwargs
        if not non_default:
            with _ssl_context_lock:
                if _ssl_context_cache is not None:
                    return _ssl_context_cache
        return _original_httpx_ssl(verify=verify, cert=cert, trust_env=trust_env,
                                   *args, **kwargs)

    _httpx_config.create_ssl_context = _patched_httpx_ssl
    # httpx/_transports/default.py does `from .._config import create_ssl_context`,
    # i.e. the transport holds its OWN reference bound at import time. Patching
    # httpx._config alone therefore changed nothing for AsyncHTTPTransport — which
    # is why the 1377ms ssl.py:717 stall was still in the log after the first
    # version of this patch. Patch every module that imported the name.
    _patched_httpx_modules = []
    for _mod_name in ("httpx._transports.default", "httpx._client", "httpx"):
        try:
            _mod = __import__(_mod_name, fromlist=["create_ssl_context"])
        except Exception:
            continue
        if getattr(_mod, "create_ssl_context", None) is _original_httpx_ssl:
            _mod.create_ssl_context = _patched_httpx_ssl
            _patched_httpx_modules.append(_mod_name)
    logger.info(
        "🔧 Patched httpx create_ssl_context to use cached SSL in "
        f"{', '.join(['httpx._config'] + _patched_httpx_modules)} (fixes ssl block during DB init)"
    )
except Exception as e:
    logger.debug(f"Could not patch httpx SSL: {e}")

# Prewarm hyphenator off loop to avoid 256ms/391ms re.split block
try:
    from livekit.agents.tokenize._basic_hyphenator import Hyphenator as _Hyph, PATTERNS as _Pat, EXCEPTIONS as _Exc
    _hyph_cache = _Hyph(_Pat, _Exc)
    # Patch _get_hyphenator to return cached
    import livekit.agents.tokenize._basic_hyphenator as _hyph_module
    _orig_get_hyph = _hyph_module._get_hyphenator
    def _patched_get_hyph():
        return _hyph_cache
    _hyph_module._get_hyphenator = _patched_get_hyph
    logger.info("🔧 Patched hyphenator to use cached (fixes 256ms/391ms re.split block)")
except Exception as e:
    logger.debug(f"Could not patch hyphenator: {e}")

# ---------------------------------------------------------------------------
# Google credentials cache + TTS event-loop guard.
# ---------------------------------------------------------------------------
# Bringing up Google TTS has two very different costs:
#   1. reading the service-account JSON + parsing the RSA private key
#      (`google.auth.load_credentials_from_file`, ~163-198ms of blocking CPU), and
#   2. constructing `texttospeech.TextToSpeechAsyncClient`, which opens a
#      **grpc.aio** channel bound to whatever event loop is running at that
#      moment.
#
# (1) is loop-independent: it is done in a worker thread and cached (see
# right below). (2) MUST happen on the agent's own event loop — a
# channel keeps `self._loop` from construction time, so a client built on a
# temporary loop that is later closed makes every `streaming_synthesize()` fail
# with `RuntimeError: Event loop is closed` (grpc/aio/_call.py -> create_task ->
# _check_closed) and the agent produces no audio at all for the whole call.
# Loop-safety helpers (inlined — no extra module).
import threading

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
