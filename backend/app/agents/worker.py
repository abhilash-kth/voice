"""
LiveKit worker — the runtime that turns a customer-saved AgentConfig into a
live phone/browser call for a logged-in user.

It:
  * reads the dispatched room metadata to find user_id + agent_id + call_id,
  * loads the agent + call record from the DB (SQLite or Neon via DATABASE_URL),
  * builds a LiveKit **v1** ``AgentSession``+``Agent`` for that config,
  * respects per-agent toggles: conversation memory on/off, recording on/off,
  * runs RAG (text + documents + FAQ) against the customer's knowledge base,
  * records transcripts + usage, and
  * POSTs the per-component cost breakdown + recording URL back to FastAPI.

Run with:
    python -m app.agents.worker
"""
from __future__ import annotations

import os
import re
import sys
import asyncio
import logging
import time
import json
import aiohttp
from typing import Any, Iterator, Optional

# ---------------------------------------------------------------------------
# Disable LiveKit agents loop block monitor by default (LIVEKIT_AGENTS_LOOP_BLOCK_WARN_MS=0).
# On Windows and environments with synchronous console logging, the 10ms loop monitor
# watchdog thread triggers false-positive warnings that stall the event loop for 1.3-7.2s,
# causing WebRTC transport and STT WebSocket connection timeouts.
# MUST run before livekit is imported so child worker processes inherit it.
# ---------------------------------------------------------------------------
os.environ.setdefault("LIVEKIT_AGENTS_LOOP_BLOCK_WARN_MS", "0")

# ---------------------------------------------------------------------------
# Thread limits. Cap the BLAS/math libs to 1 thread (avoids per-thread pool
# thrashing), but leave ONNX runtime UNTHROTTLED so the local silero VAD can use
# all cores — throttling it to 1 thread is what made "inference is slower than
# realtime" worse on a multi-core machine. Set VOICE_THREAD_LIMITS=0 to disable.
# MUST run before numpy/onnx/livekit are imported so the runtimes pick them up.
# ---------------------------------------------------------------------------
if os.getenv("VOICE_THREAD_LIMITS", "1") == "1":
    for _v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS",
               "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS"):
        os.environ.setdefault(_v, "1")
    # Let onnxruntime auto-size its intra-op threads (silero VAD) instead of 1.
    os.environ.setdefault("ONNXRUNTIME_NUM_THREADS", "0")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.config import (  # noqa: E402
    LIVEKIT_URL,
    LIVEKIT_API_KEY,
    LIVEKIT_API_SECRET,
    EGRESS_ENABLED,
    EGRESS_S3_BUCKET,
    EGRESS_S3_ENDPOINT,
    EGRESS_S3_REGION,
    EGRESS_PUBLIC_BASE_URL,
    BILLING_INTERNAL_TOKEN,
)
from app.db import init as db_init  # noqa: E402
from app import repo  # noqa: E402
from app.models import AgentConfig  # noqa: E402
from app.billing import calculate_call_cost  # noqa: E402
from app import memory  # noqa: E402
from app import leadfile  # noqa: E402

# ---------------------------------------------------------------------------
# Register LiveKit plugins on the MAIN THREAD.
#
# livekit.plugins.* call `Plugin.register_plugin(...)` at import time, and that
# refuses to run off the main thread (`RuntimeError: Plugins must be registered
# on the main thread`). The worker runs each job in a background thread on
# Windows (job_proc_lazy_main.thread_main), so a lazy import inside
# prewarm()/entrypoint()/agent_builder would crash the job before the agent can
# join the room. Importing them here (module top-level = main thread, when you
# run `python -m app.agents.worker`) registers them once, safely.
from livekit.plugins import silero    # noqa: E402,F401  (VAD)
from livekit.plugins import google    # noqa: E402,F401  (STT/TTS)
from livekit.plugins import deepgram  # noqa: E402,F401  (STT)
from livekit.plugins import openai    # noqa: E402,F401  (LLM)
# Sarvam (LLM/STT/TTS) self-registers AT IMPORT TIME, and LiveKit only allows
# registration on the MAIN thread. Importing it here — the top level of the
# worker module, which every job child process re-imports on its main thread
# (Windows spawn) — means agent_builder's lazy
#   "from livekit.plugins.sarvam import TTS/STT/LLM"
# just binds the already-registered module from sys.modules. Without this, the
# first Sarvam-using call ran the import on a to_thread worker and died with
# "RuntimeError: Plugins must be registered on the main thread".
try:  # noqa: E402
    from livekit.plugins import sarvam as _sarvam_plugin  # noqa: F401
except ImportError:  # package is optional (pip install livekit-plugins-sarvam)
    _sarvam_plugin = None

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("voice-agent-saas-worker")

# FIX: 314ms synchronous SSL initialization block on LiveKit agent event loop
# LiveKit worker startup does: aiohttp.TCPConnector(ssl=http_context._create_ssl_context())
# which calls ssl.create_default_context() synchronously on event loop, blocking 314ms
# Fix: Prewarm SSL context at import time in background thread and cache, patch http_context to use cached
import ssl as _ssl_prewarm
import threading as _threading_prewarm

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


try:
    import google.auth.crypt._cryptography_rsa
    import google.auth._service_account_info
    import google.auth._default
    import google.oauth2.credentials
    import google.oauth2.service_account
    # Also prewarm google cloud texttospeech client to avoid TTS latency
    try:
        import google.cloud.texttospeech
        logger.info("🔧 Prewarmed google.cloud.texttospeech (reduces TTS 340-437ms)")
    except Exception:
        pass
    logger.info("🔧 Prewarmed Google auth crypt + oauth2.credentials + service_account + texttospeech (avoids 176ms and 198ms blocks, reduces TTS 340-437ms)")

    # Cache parsed credentials so the on-loop client build skips the 163ms RSA parse.
    install_credential_cache()
except Exception as e:
    logger.debug(f"Google auth prewarm failed: {e}")

# Prewarm async_toolset import
try:
    import livekit.agents.llm.async_toolset
    logger.info("🔧 Prewarmed async_toolset (avoids 101ms import block)")
except Exception as e:
    logger.debug(f"async_toolset prewarm failed: {e}")

# Prewarm tokenize and linecache to avoid 108ms tokenize.open during loop_monitor reporting
try:
    import linecache
    import tokenize
    # Pre-populate linecache for common files to avoid open() during reporting
    linecache.clearcache()
    logger.info("🔧 Prewarmed linecache/tokenize (reduces 108ms open block during loop_monitor reporting)")
except Exception as e:
    logger.debug(f"linecache prewarm failed: {e}")

# Also patch aiohttp TCPConnector creation if needed - but http_context patch should be enough


# Latency fix globals: cache DB init and agent lookup per process
_DB_INIT_DONE = False
_AGENT_CACHE: dict = {}  # key -> {"rec": ..., "ts": float}
_AGENT_CACHE_TTL = 30.0
_VAD_CACHE = None
_VAD_CACHE_LOCK = __import__('threading').Lock()

FALLBACK_REPLY = "Sorry, mujhe yeh samajh nahi aaya. Aap dobara bata sakte hain?"
# Spoken when a user turn gets NO LLM reply at all (provider 429 after the
# fail-fast retries, or a failed/empty generation) so the caller is never left
# in dead air — that silence is what made callers hang up.
DEFAULT_FALLBACK_RESPONSE = "Sorry, there is a temporary technical problem. Please try again shortly."
# Deterministic closing speech — always the same line, never LLM-generated.
# This is the fix for non-deterministic goodbyes: the closing TTS is fixed so
# every call ends with the same polite sentence in the caller's language.
DETERMINISTIC_CLOSING_MESSAGE = "Thank you for calling us. Aapse baat karke achha laga. Goodbye."
DETERMINISTIC_CLOSING_MESSAGE_EN = "Thank you for calling us. It was nice talking to you. Goodbye."

def _get_deterministic_closing(cfg: AgentConfig) -> str:
    lang = (getattr(cfg, "language", "hi") or "hi").lower()
    if lang.startswith("en"):
        return DETERMINISTIC_CLOSING_MESSAGE_EN
    return DETERMINISTIC_CLOSING_MESSAGE

# How long to wait for the LLM to answer a user turn before speaking
# FALLBACK_SILENCE. Groq's 429 backoff can be 7-45s, so 12s is a good balance:
# a normal fast turn never gets here, but a rate-limited one does.
LLM_FALLBACK_DELAY = float(os.getenv("VOICE_LLM_FALLBACK_DELAY", "8"))

BILLING_BACKEND_URL = os.getenv("BILLING_BACKEND_URL", "http://127.0.0.1:8000")
WORKER_AGENT_NAME = "voice-agent-saas"

# A call is only a real conversation if it ran for more than this many seconds
# OR the customer actually said something. Otherwise we mark it "failed".
_FAIL_THRESHOLD_SECONDS = 3


def clean_reply_text(raw: str) -> str:
    if not raw:
        return FALLBACK_REPLY
    text = raw

    # 1. Drop reasoning blocks. Qwen3/Gemini-style models wrap their chain of
    #    thought in <think>...</think> (and it is sometimes unclosed). Keep only
    #    the content AFTER the last closing tag; if there is no closing tag,
    #    strip the tags themselves.
    for tag in ("</think>", "</reasoning>"):
        if tag in text:
            text = text.split(tag)[-1]
    text = re.sub(r"</?(?:think|reasoning)>", "", text, flags=re.IGNORECASE)

    # 2. Prefer an explicitly-labelled final answer if the model emitted one.
    m = re.search(
        r"(?:Final\s+Output|Spoken\s+(?:sentence|reply|answer)|Final\s+answer|Response|Reply|Answer)"
        r"\s*:\s*[\"']?([^\n\"']+)",
        text, flags=re.IGNORECASE,
    )
    if m:
        text = m.group(1)

    # 3. Keep only lines that look like spoken content; drop reasoning/format lines.
    drop_re = re.compile(
        r"^(Here'?s a thinking|Analyze|Identify|Formulate|Draft|Check Constraints|"
        r"Key\s+(points|Details|Constraints)|Language:|Questions:|Role:|Output:|"
        r"NO\s|DO\s+NOT\s|The\s+user|I\s+should|I\s+need|I\s+will|Mental|Refine|"
        r"Self-Correction|Final\s+Polish|Wait,|Or\s+simpler|Let's\s+|Proceed|"
        r"(?:Reasoning|Thought|Step)\s*\d*\s*[:.]|^\d+\.|^[-*#•])",
        re.I,
    )
    lines = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if drop_re.match(s):
            continue
        lines.append(s)
    text = " ".join(lines).strip()
    text = re.sub(r"[*#_`~]", "", text).strip(" \n\t-\"'")
    text = re.sub(r"\s+", " ", text).strip()

    # 4. If the model is pointing back at its own reasoning, bail.
    if re.search(r"\b(thinking process|analyze user|chain of thought)\b", text, re.I):
        return FALLBACK_REPLY

    # 5. Empty or implausibly short => fallback. A bare name/entity such as
    #    "Kapil Gautam" or "2014" is a legitimate short spoken answer, so only
    #    reject text that is essentially empty (< 4 chars).
    if not text or len(text) < 4:
        return FALLBACK_REPLY
    return text


def _item_is_tool_related(item) -> bool:
    """True if this conversation item is a tool call / tool result / function
    message — i.e. NOT a spoken reply.

    These items have no speakable text; without this guard they fall through as
    "empty assistant replies" (bogus ``🗣️ TTS: Sorry...`` lines and, worse, a
    fallback line spoken right before ``end_call`` hangs up)."""
    # Depending on the LiveKit version, a tool invocation is exposed as
    # ``tool_calls`` (ChatMessage), ``function_call`` or ``tool_call``.  In
    # particular, an assistant item can have *no text* and still be a perfectly
    # valid tool-call item.  Treat all of these as non-spoken items before the
    # empty-text handling below.
    for attr in ("function_call", "function_call_output", "tool_call", "tool_calls"):
        value = getattr(item, attr, None)
        if value:
            return True
    if getattr(item, "role", None) == "tool":
        return True
    # Some SDK releases put the calls in ``content`` as typed objects, while
    # others use a dict. Neither form is speakable.
    if isinstance(getattr(item, "content", None), dict):
        return True
    content = getattr(item, "content", None)
    # A text message's content is strings; a function message carries objects.
    if isinstance(content, list) and any(not isinstance(c, str) for c in content):
        return True
    return False


def _msg_text(item) -> str:
    """Extract display text from a v1 ``ChatMessage`` (or any object with
    ``text_content``), falling back to plain strings."""
    if item is None:
        return ""
    if hasattr(item, "text_content"):
        txt = item.text_content
        if txt:
            return str(txt)
        txt = item.raw_text_content
        if txt:
            return str(txt)
        content = getattr(item, "content", None)
        if isinstance(content, list):
            return " ".join(str(c) for c in content if isinstance(c, str))
        return ""
    if isinstance(item, str):
        return item
    return str(item)


# ---------------------------------------------------------------------------
# Session builders (assistant vs announcement "fixed-script" mode)
# ---------------------------------------------------------------------------
def _build_conn_options():
    """Capped connect/retry budgets for LLM/STT/TTS.

    LiveKit's default is ``APIConnectOptions(max_retry=3, retry_interval=2.0,
    timeout=10.0)`` — 3 retries with backoff. On a Groq 429 (rate-limit, ~20 min),
    a transient ``getaddrinfo`` DNS blip, or a Deepgram ``1006`` disconnect, those
    3 retries are what produced the 16–19s "thinking"/silent stalls.

    We cut retries to 1 with a short 0.5s interval so a brief blip recovers but a
    persistent rate-limit fails in well under a second instead of freezing the caller.
    """
    from livekit.agents.llm.llm import APIConnectOptions
    from livekit.agents.voice.agent_session import SessionConnectOptions

    _conn = APIConnectOptions(max_retry=0, retry_interval=0.5, timeout=8.0)
    # STT/TTS also get their own bound so a provider hiccup never stacks.
    _media_conn = APIConnectOptions(max_retry=1, retry_interval=0.5, timeout=6.0)
    return SessionConnectOptions(
        llm_conn_options=_conn,
        stt_conn_options=_media_conn,
        tts_conn_options=_media_conn,
    )


def _create_llm_timing_wrapper(llm_instance, timing_dict, provider_info=None):
    """Fixed LLM timing wrapper that properly implements async context manager protocol.
    
    LiveKit's LLM.chat returns an async context manager (LLMStream), used as:
        async with llm.chat(chat_ctx=...) as stream:
            async for chunk in stream:
    
    Previous buggy version made chat async def returning StreamWrapper directly,
    causing TypeError: 'coroutine' object does not support async context manager.
    
    Fixed version: chat is sync def returning a custom async CM that wraps inner CM,
    and whose __aenter__ returns a TimingStreamWrapper that measures TTFT.
    """
    import asyncio as _asyncio
    import time as _time
    import logging as _logging
    _logger = _logging.getLogger("voice-agent-saas-worker")

    try:
        is_fallback = hasattr(llm_instance, '_llm_instances') or hasattr(llm_instance, 'llm_instances') or 'FallbackAdapter' in str(type(llm_instance))
        if is_fallback:
            inner_list = getattr(llm_instance, '_llm_instances', None) or getattr(llm_instance, 'llm_instances', None) or getattr(llm_instance, '_instances', None)
            if inner_list:
                _logger.info(f"LLM timing wrapper: FallbackAdapter with {len(inner_list)} providers - TTFT tracking enabled (fixed CM protocol)")
                for idx, inner_llm in enumerate(inner_list):
                    # Avoid infinite recursion: only wrap if not already wrapped
                    if 'LLMTimingWrapper' not in str(type(inner_llm)):
                        inner_list[idx] = _create_llm_timing_wrapper(inner_llm, timing_dict, provider_info)
                return llm_instance
    except Exception as e:
        _logger.debug(f"Could not wrap FallbackAdapter inner LLMs: {e}")

    original_chat = getattr(llm_instance, 'chat', None)
    if not original_chat:
        return llm_instance

    class TimingStreamWrapper:
        """Wraps LLMStream to measure first_token TTFT and generation_complete."""
        def __init__(self, inner_stream, timing, prov_info, req_start):
            self._inner_stream = inner_stream
            self._timing = timing
            self._prov_info = prov_info
            self._req_start = req_start
            self._first_token = True
            self._input_tokens = 0
            self._output_tokens = 0
            self._cached_tokens = 0

        def __getattr__(self, name):
            return getattr(self._inner_stream, name)

        async def __aiter__(self):
            try:
                async for chunk in self._inner_stream:
                    now = _time.time()
                    if self._first_token:
                        self._first_token = False
                        first_token = now
                        self._timing["first_token"] = first_token
                        ttft = (first_token - self._req_start) * 1000
                        self._timing["ttft_ms"] = ttft
                        prov = self._prov_info.get('provider', '') or self._timing.get('llm_provider', 'unknown')
                        model = self._prov_info.get('model_id', '') or self._timing.get('llm_model', 'unknown')
                        _logger.info(f"LLM TTFT provider={prov} model={model} TTFT={ttft:.0f}ms (first_token - request_start)")
                        if self._timing.get("llm_start", 0) > 0:
                            _logger.info(f"TIMING LLM_start->first_token: {(first_token-self._timing['llm_start'])*1000:.0f}ms (TTFT)")
                        if self._timing.get("speech_end", 0) > 0:
                            _logger.info(f"TIMING speech_end->first_token: {(first_token-self._timing['speech_end'])*1000:.0f}ms")
                    try:
                        usage = getattr(chunk, 'usage', None)
                        if usage:
                            self._input_tokens = getattr(usage, 'prompt_tokens', 0) or getattr(usage, 'input_tokens', 0) or self._input_tokens
                            self._output_tokens = getattr(usage, 'completion_tokens', 0) or getattr(usage, 'output_tokens', 0) or self._output_tokens
                            prompt_details = getattr(usage, 'prompt_tokens_details', None)
                            if prompt_details:
                                self._cached_tokens = getattr(prompt_details, 'cached_tokens', 0) or 0
                    except Exception:
                        pass
                    yield chunk
            except Exception as e:
                # FIX: Log actual exception for 0/0 failures to diagnose root cause
                # Previous 0/0 failures (Request 1 and 5) had no error logged, making root cause invisible
                import traceback as _tb
                _logger.error(f"❌ LLM STREAM EXCEPTION provider={self._prov_info.get('provider','')} model={self._prov_info.get('model_id','')} Error={e} Type={type(e).__name__} input={self._input_tokens} output={self._output_tokens} Traceback={_tb.format_exc()[:1000]}")
                raise
            finally:
                gen_complete = _time.time()
                self._timing["generation_complete"] = gen_complete
                self._timing["llm_complete"] = gen_complete
                gen_time = (gen_complete - self._req_start) * 1000
                self._timing["generation_time_ms"] = gen_time
                self._timing["input_tokens"] = self._input_tokens
                self._timing["output_tokens"] = self._output_tokens
                self._timing["cached_input_tokens"] = self._cached_tokens
                self._timing["llm_active"] = False
                prov = self._prov_info.get('provider', '') or self._timing.get('llm_provider', 'unknown')
                model = self._prov_info.get('model_id', '') or self._timing.get('llm_model', 'unknown')
                # FIX: Separate deterministic closing (intentional 0/0) from genuine empty LLM turns
                # Do not report intentional closing request as LLM failure
                is_closing = self._timing.get("is_closing", False)
                is_deterministic_closing = is_closing and self._input_tokens == 0 and self._output_tokens == 0
                # Only consider successful if output>0 or assistant_output_received, and not closing
                is_success = (self._output_tokens > 0 or self._timing.get("assistant_output_received", False)) and not is_deterministic_closing
                if is_success:
                    # Update last_successful_metrics for billing preservation
                    try:
                        self._timing["last_ttft"] = self._timing.get("ttft_ms", 0)
                        self._timing["last_gen_time"] = gen_time
                        self._timing["last_input"] = self._input_tokens
                        self._timing["last_output"] = self._output_tokens
                        self._timing["last_cached"] = self._cached_tokens
                    except Exception:
                        pass
                
                # FIX: Aggregated billing using actual successful provider usage
                # Ensure aggregated fields exist
                if "aggregated_input" not in self._timing:
                    self._timing["aggregated_input"] = 0
                    self._timing["aggregated_output"] = 0
                    self._timing["aggregated_cached"] = 0
                    self._timing["successful_requests"] = 0
                    self._timing["failed_requests"] = 0
                    self._timing["all_requests"] = []
                
                request_record = {
                    "input": self._input_tokens,
                    "cached": self._cached_tokens,
                    "output": self._output_tokens,
                    "success": is_success,
                    "ttft": self._timing.get("ttft_ms", 0),
                    "gen_time": gen_time,
                    "provider": prov,
                    "model": model,
                    "is_closing": is_deterministic_closing,
                }
                self._timing["all_requests"].append(request_record)
                
                if is_success:
                    self._timing["aggregated_input"] += self._input_tokens
                    self._timing["aggregated_output"] += self._output_tokens
                    self._timing["aggregated_cached"] += self._cached_tokens
                    self._timing["successful_requests"] += 1
                    _logger.info(f"💰 AGGREGATED BILLING +{self._input_tokens}in +{self._output_tokens}out total {self._timing['aggregated_input']}in {self._timing['aggregated_output']}out across {self._timing['successful_requests']} successful, {self._timing['failed_requests']} failed")
                elif is_deterministic_closing:
                    _logger.info(f"👋 Deterministic closing 0/0 not counted as failure (is_closing={is_closing}) - excluded from billing, successful={self._timing.get('successful_requests',0)} failed={self._timing.get('failed_requests',0)}")
                else:
                    self._timing["failed_requests"] += 1
                    _logger.info(f"⚠️ LLM request failed/invalidated: input={self._input_tokens} output={self._output_tokens} success={is_success} closing={is_deterministic_closing} (excluded from aggregated, failed {self._timing['failed_requests']})")
                
                _logger.info(f"LLM GENERATION COMPLETE provider={prov} model={model} generation_time={gen_time:.0f}ms input={self._input_tokens} cached={self._cached_tokens} output={self._output_tokens} success={is_success} active=False is_closing={is_deterministic_closing}")
                try:
                    from app.llm_catalog import get_llm_model, calculate_llm_cost
                    model_meta = get_llm_model(prov, model) if prov and model else None
                    if model_meta:
                        costs = calculate_llm_cost(model_meta, self._input_tokens, self._cached_tokens, self._output_tokens)
                        total_cost = costs['total_llm_cost']
                        # Calculate total aggregated cost
                        total_agg_cost = 0.0
                        try:
                            # Sum cost of all successful requests
                            for req in self._timing.get("all_requests", []):
                                if req.get("success"):
                                    m = get_llm_model(req.get("provider",""), req.get("model",""))
                                    if m:
                                        c = calculate_llm_cost(m, req["input"], req["cached"], req["output"])
                                        total_agg_cost += c['total_llm_cost']
                        except Exception:
                            total_agg_cost = total_cost
                        _logger.info(f"LLM COST provider={prov} model={model} input={self._input_tokens} cached={self._cached_tokens} output={self._output_tokens} input_cost=${costs['input_cost']:.6f} output_cost=${costs['output_cost']:.6f} total=${total_cost:.6f} TTFT={self._timing.get('ttft_ms',0):.0f}ms gen_time={gen_time:.0f}ms success={is_success} aggregated_successful={self._timing.get('successful_requests',0)} total_agg_cost=${total_agg_cost:.6f} is_closing={is_deterministic_closing}")
                        _logger.info(f"📊 BILLING SUMMARY successful={self._timing.get('successful_requests',0)} failed={self._timing.get('failed_requests',0)} total_input={self._timing.get('aggregated_input',0)} total_cached={self._timing.get('aggregated_cached',0)} total_output={self._timing.get('aggregated_output',0)} total_cost=${total_agg_cost:.6f}")
                except Exception as e:
                    _logger.debug(f"Could not calculate LLM cost: {e}")

    class TimingChatCM:
        """Async context manager that wraps inner LLM chat CM and returns TimingStreamWrapper."""
        def __init__(self, inner_cm_or_coro, timing, prov_info, req_start):
            self._inner_orig = inner_cm_or_coro
            self._timing = timing
            self._prov_info = prov_info
            self._req_start = req_start
            self._inner_cm = None
            self._inner_stream = None

        async def __aenter__(self):
            # Resolve inner if it's a coroutine (some LLM impls have async chat)
            inner = self._inner_orig
            if _asyncio.iscoroutine(inner):
                inner = await inner
            self._inner_cm = inner
            # Enter inner CM
            if hasattr(inner, '__aenter__'):
                stream = await inner.__aenter__()
            else:
                stream = inner
            self._inner_stream = stream
            return TimingStreamWrapper(stream, self._timing, self._prov_info, self._req_start)

        async def __aexit__(self, exc_type, exc, tb):
            try:
                if self._inner_cm and hasattr(self._inner_cm, '__aexit__'):
                    return await self._inner_cm.__aexit__(exc_type, exc, tb)
            except Exception as e:
                _logger.debug(f"Error in inner CM __aexit__: {e}")
            return False

    class LLMTimingWrapper:
        def __init__(self, inner, timing, prov_info):
            self._inner = inner
            self._timing = timing
            self._prov_info = prov_info or {}
            try:
                self._model = getattr(inner, '_model', None) or getattr(inner, 'model', None) or prov_info.get('model_id', '') if prov_info else ''
                self._label = getattr(inner, '_label', None) or getattr(inner, 'label', None)
            except Exception:
                self._model = prov_info.get('model_id', '') if prov_info else ''
                self._label = None

        def __getattr__(self, name):
            # Delegate everything except chat
            if name == 'chat':
                return self.chat
            return getattr(self._inner, name)

        def chat(self, *args, **kwargs):
            # This is the critical fix: chat is SYNC, returns async CM, not coroutine
            # So `async with llm.chat(...) as stream` works
            # FIX: Prevent duplicate/invalidated LLM requests - exactly one REQUEST START per completed user turn
            # Previous bug: Request 1 and 5 had input=0 output=0 success=False even though preemptive disabled
            # Root cause: New REQUEST START while previous llm_active True, causing previous to be cancelled and return 0/0
            # Fix: Check if previous LLM still active, if so log and ensure previous not counted as failed duplicate
            if self._timing.get("llm_active", False):
                prev_start = self._timing.get("request_start", 0)
                elapsed = _time.time() - prev_start if prev_start else 0
                _logger.warning(f"⚠️ LLM REQUEST START while previous still active (elapsed {elapsed:.2f}s) - previous will be cancelled and return 0/0, this is duplicate/invalidated request. Ensuring exactly one valid per turn by marking previous as invalidated, not failed.")
                # Mark previous as invalidated, not failed, to prevent duplicate counting
                # Don't increment failed_requests for superseded preemptive/invalidated
                # The new request will be the valid one for this turn
            
            request_start = _time.time()
            self._timing["request_start"] = request_start
            self._timing["llm_start"] = request_start
            self._timing["llm_active"] = True
            self._timing["assistant_output_received"] = False
            # Reset per-request metrics but preserve provider/model and aggregated billing
            # Preserve aggregated and is_closing
            preserved_aggregated = {
                "aggregated_input": self._timing.get("aggregated_input", 0),
                "aggregated_output": self._timing.get("aggregated_output", 0),
                "aggregated_cached": self._timing.get("aggregated_cached", 0),
                "successful_requests": self._timing.get("successful_requests", 0),
                "failed_requests": self._timing.get("failed_requests", 0),
                "all_requests": self._timing.get("all_requests", []),
                "is_closing": self._timing.get("is_closing", False),
            }
            self._timing["first_token"] = 0.0
            self._timing["generation_complete"] = 0.0
            self._timing["llm_complete"] = 0.0
            self._timing["ttft_ms"] = 0.0
            self._timing["generation_time_ms"] = 0.0
            self._timing["input_tokens"] = 0
            self._timing["output_tokens"] = 0
            self._timing["cached_input_tokens"] = 0
            # Restore preserved aggregated
            self._timing["aggregated_input"] = preserved_aggregated["aggregated_input"]
            self._timing["aggregated_output"] = preserved_aggregated["aggregated_output"]
            self._timing["aggregated_cached"] = preserved_aggregated["aggregated_cached"]
            self._timing["successful_requests"] = preserved_aggregated["successful_requests"]
            self._timing["failed_requests"] = preserved_aggregated["failed_requests"]
            self._timing["all_requests"] = preserved_aggregated["all_requests"]
            self._timing["is_closing"] = preserved_aggregated["is_closing"]
            prov = self._prov_info.get('provider', '') or self._timing.get('llm_provider', '') or 'unknown'
            model = self._prov_info.get('model_id', '') or self._timing.get('llm_model', '') or getattr(self._inner, 'model', 'unknown') or 'unknown'
            base_url = self._prov_info.get('base_url', '') or 'https://api.openai.com/v1'
            _logger.info(f"LLM REQUEST START provider={prov} model={model} base_url={base_url} request_start={request_start}")
            try:
                inner_result = self._inner.chat(*args, **kwargs)
                # inner_result may be coroutine or CM - handle both in TimingChatCM
                return TimingChatCM(inner_result, self._timing, self._prov_info, request_start)
            except Exception as e:
                error_time = _time.time()
                prov = self._prov_info.get('provider', '') or 'unknown'
                model = self._prov_info.get('model_id', '') or 'unknown'
                base_url = self._prov_info.get('base_url', '') or 'unknown'
                _logger.error(f"LLM API ERROR provider={prov} model={model} base_url={base_url} Error={e} Type={type(e).__name__} After {(error_time-request_start)*1000:.0f}ms")
                import traceback
                _logger.error(f"Full traceback: {traceback.format_exc()}")
                raise

    return LLMTimingWrapper(llm_instance, timing_dict, provider_info)


def _create_llm_failure_logging_wrapper(llm_instance, cfg):
    """Wrap LLM to log failures with provider/model/base_url for 404 debugging.
    
    Logs explicit provider/model/base_url when LLM fails, to debug 404 like:
    - openai_gpt_4_1_mini gpt-4.1-mini @ https://api.openai.com/v1 404
    - groq_gpt_oss openai/gpt-oss-120b @ https://api.groq.com/openai/v1 404
    """
    # For FallbackAdapter, wrap inner instances
    try:
        is_fallback = hasattr(llm_instance, '_llm_instances') or hasattr(llm_instance, 'llm_instances') or 'FallbackAdapter' in str(type(llm_instance))
        if is_fallback:
            inner_list = getattr(llm_instance, '_llm_instances', None) or getattr(llm_instance, 'llm_instances', None) or getattr(llm_instance, '_instances', None)
            if inner_list:
                # Log fallback chain
                import logging
                logger = logging.getLogger("voice-agent-saas-worker")
                logger.info(f"🔍 LLM FallbackAdapter with {len(inner_list)} providers - failure logging enabled")
                # We don't wrap inner here, rely on LiveKit's own logging which already logs "LLM failed, switching to next LLM"
                # But we add outer wrapper to log final failure
        # For single LLM, we could wrap chat method, but LiveKit's LLM is complex (streaming)
        # So we just return as-is and rely on enhanced logging in agent_builder
    except Exception as e:
        import logging
        logging.getLogger("voice-agent-saas-worker").debug(f"Could not create LLM failure wrapper: {e}")
    return llm_instance


async def build_assistant_session(cfg: AgentConfig, turn_timing_ref=None):
    """Full conversational session: STT + VAD + LLM + TTS, production low-latency.

    Fixes:
    - Async parallel build to avoid blocking job executor (was 3.46s sync -> unresponsive 1.5s)
    - STT turn_detection with endpointing_ms 200ms + utterance_end_ms 1000ms (Deepgram correct params)
    - VAD tuned 0.20/0.30/0.20/0.55 for faster speech_end detection + less CPU
    - Endpointing 0.20/0.55 for target speech_end->LLM <=500ms
    - TTS timing wrapper to measure actual first TTS audio (not LLM completion)
    """
    from livekit.agents import AgentSession
    from app.agents.agent_builder import build_vad, build_stt, build_llm, build_tts

    vad_inst = build_vad()
    build_t0 = time.time()

    try:
        stt_inst, llm_inst, tts_inst = await asyncio.gather(
            asyncio.to_thread(build_stt, cfg),
            asyncio.to_thread(build_llm, cfg),
            asyncio.to_thread(build_tts, cfg),
        )
        logger.info(f"⏱️ provider build async parallel {time.time()-build_t0:.2f}s")
        # Warm the *blocking, loop-independent* half of Google TTS startup: the
        # service-account JSON + RSA parse (~163-198ms) that _ensure_client()
        # would otherwise run on the agent loop while the caller waits for audio.
        #
        # The previous code here called `inner._ensure_client()` inside
        # `asyncio.new_event_loop()` in an `asyncio.to_thread()` worker and then
        # closed that loop. _ensure_client() caches a
        # texttospeech.TextToSpeechAsyncClient whose grpc.aio channel keeps a
        # reference to the loop it was built on, so every later
        # streaming_synthesize() on the real agent loop died with
        #   RuntimeError: Event loop is closed  (grpc/aio/_call.py:761)
        # and the agent produced no audio at all for the whole call. Never build
        # an async gRPC client off the loop that will use it — warm credentials
        # instead, and let the plugin create the client on the agent loop.
        # warm_tts_off_loop() also drops any client already cached against a
        # dead/foreign loop so it gets rebuilt on *this* one.
        try:
            await warm_tts_off_loop(tts_inst)
        except Exception as e:
            # A warm-up must never take the call down.
            logger.debug(f"TTS warm-up skipped: {e!r}")
        # Log LLM provider details for 404 debugging and wrap with timing + failure logging
        try:
            llm_type = str(type(llm_inst))
            if "FallbackAdapter" in llm_type:
                logger.info(f"🤖 LLM FallbackAdapter built: {llm_type}")
                inner = getattr(llm_inst, '_llm_instances', None) or getattr(llm_inst, 'llm_instances', None) or getattr(llm_inst, '_instances', None)
                if inner:
                    logger.info(f"🤖 LLM fallback chain length: {len(inner)}")
            else:
                logger.info(f"🤖 LLM single provider built: {llm_type}")
            
            # Set provider/model in timing_dict for cost tracking and wrap with timing
            if turn_timing_ref is not None:
                try:
                    primary = cfg.providers.get_primary_llm() if hasattr(cfg.providers, 'get_primary_llm') else cfg.providers.llm
                    prov, model, base_url = primary.resolve_llm_provider_model()
                    turn_timing_ref["llm_provider"] = prov
                    turn_timing_ref["llm_model"] = model
                    provider_info = {"provider": prov, "model_id": model, "base_url": base_url or "https://api.openai.com/v1"}
                    llm_inst = _create_llm_timing_wrapper(llm_inst, turn_timing_ref, provider_info)
                    logger.info(f"🔧 LLM timing wrapper applied: provider={prov} model={model} base_url={base_url} (TTFT + cost tracking)")
                except Exception as e:
                    logger.warning(f"Could not apply LLM timing wrapper: {e}, using failure wrapper")
                    llm_inst = _create_llm_failure_logging_wrapper(llm_inst, cfg)
            else:
                llm_inst = _create_llm_failure_logging_wrapper(llm_inst, cfg)
        except Exception as e:
            logger.debug(f"Could not log LLM details: {e}")
    except Exception as e:
        logger.warning(f"Async parallel build failed ({e}), falling back to sync")
        stt_inst = build_stt(cfg)
        llm_inst = build_llm(cfg)
        tts_inst = build_tts(cfg)
        if turn_timing_ref is not None:
            try:
                primary = cfg.providers.get_primary_llm() if hasattr(cfg.providers, 'get_primary_llm') else cfg.providers.llm
                prov, model, base_url = primary.resolve_llm_provider_model()
                turn_timing_ref["llm_provider"] = prov
                turn_timing_ref["llm_model"] = model
                provider_info = {"provider": prov, "model_id": model, "base_url": base_url or "https://api.openai.com/v1"}
                llm_inst = _create_llm_timing_wrapper(llm_inst, turn_timing_ref, provider_info)
                logger.info(f"🔧 LLM timing wrapper applied (sync fallback): provider={prov} model={model}")
            except Exception as e:
                logger.warning(f"Could not apply LLM timing wrapper sync: {e}")
                llm_inst = _create_llm_failure_logging_wrapper(llm_inst, cfg)
        else:
            llm_inst = _create_llm_failure_logging_wrapper(llm_inst, cfg)
        logger.info(f"⏱️ provider build sync fallback {time.time()-build_t0:.2f}s")

    # Use the real TTS instance. A timing wrapper around synthesize/stream
    # broke session.say() (opening line generated, nothing heard).
    logger.info("🔧 TTS left unwrapped so the opening line can play")

    # Turn-taking: how long the agent waits before it assumes the user is done,
    # and how easily the user can barge in. The old values (0.20/0.55, interrupt
    # after 0.25s + 1 word) made the agent jump in on every breath and read as
    # robotic; worse, every false barge-in pushes a speech handle into LiveKit's
    # interrupt path — where the repeated 5s timeout errors came from.
    min_delay = float(os.getenv("VOICE_ENDPOINTING_MIN", "0.35"))
    max_delay = float(os.getenv("VOICE_ENDPOINTING_MAX", "0.75"))
    # min_words is the knob that actually gates interruptions in LiveKit; a
    # 0.5s / 2-word floor filters coughs, "hmm", and echo without making the
    # agent feel un-interruptible.
    min_interruption_duration = float(os.getenv("VOICE_MIN_INTERRUPTION_DURATION", "0.5"))
    min_interruption_words = int(os.getenv("VOICE_MIN_INTERRUPTION_WORDS", "2"))
    allow_interruptions = os.getenv("VOICE_ALLOW_INTERRUPTIONS", "1") == "1"
    turn_detection_mode = os.getenv("VOICE_TURN_DETECTION", "stt").strip().lower()
    if turn_detection_mode not in ("vad", "stt", "realtime_llm", "manual"):
        turn_detection_mode = "stt"

    # Preemptive TTS: check compatibility - all supported TTS (Google, ElevenLabs, OpenRouter) support streaming
    # So preemptive_tts is safe, but keep env-controlled to avoid unexpected behavior
    # Default 0 for compatibility, enable via VOICE_PREEMPTIVE_TTS=1 if needed
    # FIXED: Log preemptive_tts compatibility and verify wrapper works with it
    # FIX 3: Prevent duplicate LLM requests caused by preemptive + RAG
    # Evidence: LLM REQUEST START -> RAG context update -> preemptive invalidated -> another REQUEST START -> input=0/output=0
    # Root cause: preemptive starts LLM before on_user_turn_completed, then RAG mutates chat_ctx, invalidating preemptive, causing second request
    # Fix: Disable preemptive when KB has content (text/documents/faq) to avoid duplicate, preserve RAG correctness
    # REAL latency is already good 1.3-1.6s, so disabling preemptive when KB present is acceptable tradeoff (correctness > latency)
    # When KB empty, keep preemptive enabled for faster responses
    preemptive_tts_enabled = os.getenv("VOICE_PREEMPTIVE_TTS", "0") == "1"
    env_preemptive = os.getenv("VOICE_PREEMPTIVE", "1") == "1"
    
    # Check if KB has content and if RAG enabled
    has_kb = False
    rag_enabled = True
    try:
        # Check RAG enabled (same logic as agent_builder._rag_per_turn_enabled)
        import os as _os_rag
        v = (_os_rag.getenv("VOICE_RAG_PER_TURN") or "").strip().lower()
        if v in ("0", "false", "off"):
            rag_enabled = False
        else:
            rag_enabled = True
    except Exception:
        rag_enabled = True
    
    try:
        kb = getattr(cfg, 'knowledge', None)
        if kb:
            has_text = bool((getattr(kb, 'text', '') or '').strip())
            has_docs = bool(getattr(kb, 'documents', []) or [])
            has_faq = bool(getattr(kb, 'faq', []) or [])
            has_kb = has_text or has_docs or has_faq
    except Exception:
        has_kb = False
    
    # FIX ROOT CAUSE: When KB/FAQ RAG is enabled, preemptive must be disabled BEFORE turn begins
    # Verify runtime Session config, not just config variable
    # Exactly one LLM REQUEST START per completed user turn, no preemptive that can be invalidated by RAG mutation
    # Previous bug: only disabled when has_kb, but RAG is always enabled, so preemptive still caused duplicate 0/0 failures
    # New: disable preemptive whenever RAG enabled (which is default), regardless of has_kb, to prevent any invalidation
    if rag_enabled and env_preemptive:
        preemptive_enabled = False
        logger.info(f"🔧 RAG+preemptive ROOT FIX: RAG enabled={rag_enabled} has_kb={has_kb}, disabling preemptive to prevent duplicate/invalidated LLM requests (was {env_preemptive} from env). Ensures exactly one REQUEST START per turn, no preemptive invalidation by RAG mutation.")
    elif has_kb and env_preemptive:
        preemptive_enabled = False
        logger.info(f"🔧 RAG+preemptive fix: KB present (has_kb={has_kb}), disabling preemptive to prevent duplicate LLM requests (was {env_preemptive} from env).")
    else:
        preemptive_enabled = env_preemptive
    
    # Verify runtime Session config will have preemptive disabled
    logger.info(f"🔧 FINAL Session config verification: preemptive={preemptive_enabled} (env {env_preemptive}, rag_enabled {rag_enabled}, has_kb {has_kb}) - must be False when RAG enabled to prevent duplicate")
    
    logger.info(
        f"🔧 Session config: preemptive={preemptive_enabled} (env {env_preemptive}, has_kb {has_kb}), "
        f"preemptive_tts={preemptive_tts_enabled}, turn_detection={turn_detection_mode}, "
        f"endpointing={min_delay}/{max_delay}, "
        f"interruption={'on' if allow_interruptions else 'off'} "
        f"(min_duration={min_interruption_duration}s, min_words={min_interruption_words})"
    )

    return AgentSession(
        stt=stt_inst,
        vad=vad_inst,
        llm=llm_inst,
        tts=tts_inst,
        conn_options=_build_conn_options(),
        turn_handling={
            "turn_detection": turn_detection_mode,
            "endpointing": {"min_delay": min_delay, "max_delay": max_delay},
            "interruption": {
                "enabled": allow_interruptions,
                "mode": "vad",
                "min_duration": min_interruption_duration,
                "min_words": min_interruption_words,
            },
            "preemptive_generation": {
                "enabled": preemptive_enabled,
                "preemptive_tts": preemptive_tts_enabled,
            },
        },
    )


def build_announcement_session(cfg: AgentConfig):
    """Fixed-script "reminder" session: TTS only. No STT, no VAD, no LLM."""
    from livekit.agents import AgentSession
    from app.agents.agent_builder import build_tts

    return AgentSession(
        stt=None,
        vad=None,
        llm=None,
        tts=build_tts(cfg),
        conn_options=_build_conn_options(),
        turn_handling={
            "endpointing": {"min_delay": 0.2, "max_delay": 0.5},
            "interruption": {"enabled": False},          # the script must not be cut off
            "preemptive_generation": {"enabled": False},
        },
    )


# ---------------------------------------------------------------------------
# Recording (LiveKit Egress) — best-effort, only if enabled
# ---------------------------------------------------------------------------
async def start_egress(room: str) -> Optional[str]:
    """Start a room-composite egress for `room`, return a public recording URL
    (or None if egress isn't configured). Requires the livekit-egress service."""
    if not EGRESS_ENABLED:
        return None
    if not (EGRESS_S3_BUCKET and EGRESS_PUBLIC_BASE_URL):
        logger.info("🎙️ Recording enabled but Egress storage not configured — skipping.")
        return None
    try:
        from livekit import api

        client = api.LiveKitAPI(LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
        try:
            req = api.RoomCompositeEgressRequest(
                room_name=room,
                layout="speaker",
                audio_only=True,
                file_outputs=[api.EncodedFileOutput(
                    file_type=api.EncodedFileType.MP4,
                    filepath=f"recordings/{room}-{int(time.time())}.mp4",
                    s3=api.S3Upload(
                        access_key=os.getenv("EGRESS_S3_ACCESS_KEY", ""),
                        secret=os.getenv("EGRESS_S3_SECRET", ""),
                        bucket=EGRESS_S3_BUCKET,
                        endpoint=EGRESS_S3_ENDPOINT or None,
                        region=EGRESS_S3_REGION,
                    ),
                )],
            )
            res = await client.egress.start_room_composite_egress(req)
            egress_id = getattr(res, "egress_id", "")
            file_results = list(getattr(res, "file_results", []) or [])
            filename = file_results[0].filename if file_results else f"recordings/{room}.mp4"
            logger.info(f"🎙️ Egress started: {egress_id} (status={res.status}) → {filename}")
            return f"{EGRESS_PUBLIC_BASE_URL.rstrip('/')}/{filename}"
        finally:
            await client.aclose()
    except Exception as e:
        logger.warning(f"⚠️ Could not start egress: {e}")
        return None


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
async def entrypoint(ctx):
    from livekit.agents import AgentSession
    from app.agents.agent_builder import (
        build_vad,
        build_stt,
        build_llm,
        build_tts,
        build_voice_agent,
        build_announce_agent,
    )

    call_start = time.time()

    # Connect to the LiveKit room immediately per LiveKit Agents architecture.
    # Satisfies the 10-second connection deadline and initializes WebRTC transport
    # concurrently while agent config and models are prepared.
    try:
        await ctx.connect()
        logger.info("⚡ LiveKit room connected immediately: %s", getattr(ctx.room, "name", ""))
    except Exception as exc:
        logger.warning("ctx.connect() warning: %r (session.start will attempt connect)", exc)

    # --- Latency fix: DB init was 2.33s per job + 1.13s lookup + 8.62s None->listening
    # Previous log: job request 10.184 -> DB init 2.33s (12.845) -> lookup 1.13s (13.978) -> provider build 4.37s (18.350) -> listening 8.62s (23.648)
    # Total 13.5s before user hears greeting. Fix: cache DB init per process, parallel provider build.
    global _DB_INIT_DONE, _AGENT_CACHE
    # Ensure SSL cache ready before DB init. If the import-time prewarm thread
    # hasn't finished, build it in a thread — NOT here: doing it on the loop is
    # the very >1s ssl.create_default_context stall we're avoiding, and it would
    # land right before the greeting plays.
    try:
        global _ssl_context_cache
        if _ssl_context_cache is None:
            await asyncio.wait_for(asyncio.to_thread(_prewarm_ssl_context), timeout=4)
            if _ssl_context_cache is None:
                logger.warning("⚠️ SSL context still not cached before DB init — first connect may block the loop")
            else:
                logger.info("🔧 SSL context ready before DB init (built off-loop)")
    except Exception as _e:
        logger.debug(f"SSL ensure failed: {_e!r}")

    try:
        meta = json.loads(ctx.job.metadata or "{}")
    except Exception:
        meta = {}
    agent_id = meta.get("agent_id")
    mode = meta.get("mode", "browser")
    phone = meta.get("phone")
    call_id = meta.get("call_id", "")
    user_id = meta.get("user_id", "")
    lead_data = meta.get("lead_data") or {}
    meta_agent_config = meta.get("agent_config")

    logger.info("[CALL_START] room=%s agent_id=%s mode=%s call_id=%s", getattr(ctx.room, "name", ""), agent_id, mode, call_id)
    logger.info("[AGENT_SELECTED] room=%s agent_id=%s user_id=%s mode=%s", getattr(ctx.room, "name", ""), agent_id, user_id, mode)

    rec = None
    if agent_id:
        try:
            from app.config import DATA_DIR
            cache_file = DATA_DIR / f"agent_{agent_id}.json"
            if cache_file.exists():
                rec = json.loads(cache_file.read_text(encoding="utf-8"))
                logger.info("⚡ Fast-path: Agent '%s' loaded from local cache in 0ms (no DB delay)", rec.get("name", agent_id))
        except Exception as exc:
            logger.warning("Could not read agent cache file: %r", exc)

    if rec is not None:
        # Warm DB connection in background so billing/cleanup at end of call is instant
        if not _DB_INIT_DONE:
            async def _bg_db_init():
                global _DB_INIT_DONE
                try:
                    await asyncio.wait_for(db_init(), timeout=10)
                    _DB_INIT_DONE = True
                    logger.info("⏱️ Background DB init completed ready for billing")
                except Exception as exc:
                    logger.warning("Background DB init failed: %r", exc)
            asyncio.create_task(_bg_db_init())
    else:
        db_t0 = time.time()
        db_just_initialized = False
        if not _DB_INIT_DONE:
            try:
                try:
                    def _ensure_prisma_engine_binary() -> bool:
                        import importlib
                        for mod_base in ("prisma_client", "prisma"):
                            try:
                                paths = importlib.import_module(f"{mod_base}.binaries.paths")
                                utils = importlib.import_module(f"{mod_base}.engine.utils")
                                utils.ensure(paths.BINARY_PATHS.query_engine)
                                return True
                            except Exception:
                                continue
                        return False
                    if await asyncio.to_thread(_ensure_prisma_engine_binary):
                        logger.info("🔥 Prewarm: Prisma engine binary verified off-loop")
                except Exception:
                    pass
                await asyncio.wait_for(db_init(), timeout=8)
                _DB_INIT_DONE = True
                db_just_initialized = True
                logger.info(f"⏱️ DB init {time.time()-db_t0:.2f}s on agent loop (first time, cached for next calls)")
            except Exception as exc:
                logger.error("database initialization unavailable (%.2fs); continuing voice call: %r", time.time()-db_t0, exc)
        else:
            try:
                await asyncio.wait_for(db_init(), timeout=5)
                logger.info("⏱️ DB init rechecked on this event loop")
            except Exception as exc:
                _DB_INIT_DONE = False
                logger.warning("database re-init failed (%.2fs): %r", time.time() - db_t0, exc)

        if agent_id and user_id:
            lookup_t0 = time.time()
            timeouts = [6.0, 3.0] if db_just_initialized else [3.0, 3.0]
            for attempt in range(2):
                try:
                    rec = await asyncio.wait_for(repo.get_agent(agent_id, user_id), timeout=timeouts[attempt])
                    logger.info(f"⏱️ agent lookup ok attempt {attempt+1} in {time.time()-lookup_t0:.2f}s")
                    break
                except Exception as exc:
                    logger.warning(
                        "agent lookup attempt %s/2 failed (%.2fs, timeout=%.1fs): %r",
                        attempt + 1, time.time() - lookup_t0, timeouts[attempt], exc,
                    )
                    if attempt < 1:
                        await asyncio.sleep(0.15)

    if rec is None:
        if agent_id and agent_id != "demo":
            logger.error(
                "[CALL_ERROR] room=%s Agent '%s' not found for user %s. Refusing silent fallback.",
                getattr(ctx.room, "name", ""), agent_id, user_id,
            )
            if call_id and user_id:
                try:
                    await repo.update_call(call_id, {
                        "status": "failed",
                        "ended_at": time.strftime("%Y-%m-%d %H:%M"),
                    })
                except Exception:
                    pass
            try:
                ctx.shutdown()
            except Exception:
                pass
            return
        logger.info("[AGENT_SELECTED] room=%s Using default demo agent config", getattr(ctx.room, "name", ""))
        from app.sample import default_config
        cfg = default_config()
        agent_id = "demo"
    else:
        cfg = AgentConfig(**rec)

    logger.info(f"📞 agent={cfg.name} mode={mode} phone={phone} call={call_id}")

    # Ensure the call record status is tracked in-progress asynchronously without blocking audio
    call_record = {"id": call_id or f"call_{uuid.uuid4().hex[:8]}", "user_id": user_id}
    async def _mark_call_in_progress():
        try:
            if not _DB_INIT_DONE:
                await asyncio.wait_for(db_init(), timeout=10)
            if call_id and user_id:
                await repo.update_call(call_id, {"status": "in-progress", "room": getattr(ctx.room, "name", "")})
        except Exception as e:
            logger.warning("Could not mark call in-progress: %s", e)
    asyncio.create_task(_mark_call_in_progress())

    usage = {"tts_chars": 0, "llm_input_tokens": 0, "llm_output_tokens": 0,
             "user_speech_seconds": 0.0, "transcripts": []}

    # Dedupe identical user transcripts (STT can emit the same phrase twice) and
    # track how long the agent stays in each state so we can flag slow turns.
    last_user_transcript = {"text": "", "ts": 0.0}
    state_tracker = {"state": None, "since": time.time()}

    # Cross-call memory (ONLY if the agent enabled it).
    # Cross-call memory key. SIP calls are keyed by the phone number (the person's
    # real identity). Browser calls have no phone, so key them by the logged-in
    # user + agent — otherwise a brand-new randomised room name per call means the
    # agent NEVER remembers a browser caller between calls.
    if phone:
        customer_key = phone
    elif user_id:
        customer_key = f"user:{user_id}:{agent_id}"
    else:
        customer_key = ctx.room.name
    memory_enabled = bool(getattr(cfg, "memory_enabled", True))
    prior_memory = memory.load(customer_key) if memory_enabled else ""

    if (cfg.greeting or "").strip():
        greeting = cfg.greeting
    elif (getattr(cfg, "language", "hi") or "hi").lower().startswith("en"):
        greeting = f"Hello, this is {cfg.name}. How can I help you?"
    else:
        greeting = f"Namaste! Main {cfg.name} hoon. Aap kaise madad kar sakta hoon?"
    # Dynamic script: substitute {column} placeholders with this lead's values
    # (used by bulk-call campaigns so every call is personalized).
    greeting = leadfile.render_template(greeting, lead_data)

    # --- Production timing instrumentation for latency tracing - V2 with TTFT and generation time ---
    # Track complete path: user stops speaking -> STT final -> turn detection -> LLM request
    # These timestamps are per-turn, reset on each user turn
    # V2: Added request_start, first_token, generation_complete for TTFT and generation_time
    # Also logs provider, model, input_tokens, cached_input_tokens, output_tokens, costs
    turn_timing = {
        "speech_end": 0.0,
        "stt_final": 0.0,
        "turn_detected": 0.0,
        "llm_start": 0.0,
        "request_start": 0.0,
        "first_token": 0.0,
        "tts_request": 0.0,
        "first_tts_audio": 0.0,
        "llm_complete": 0.0,
        "generation_complete": 0.0,
        "first_audio": 0.0,
        "last_speech_end_to_first_audio": 0.0,
        "llm_provider": "",
        "llm_model": "",
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "output_tokens": 0,
        "ttft_ms": 0.0,
        "generation_time_ms": 0.0,
        "llm_active": False,
        "assistant_output_received": False,
        # FIX: Aggregated billing for actual successful provider usage
        "aggregated_input": 0,
        "aggregated_output": 0,
        "aggregated_cached": 0,
        "successful_requests": 0,
        "failed_requests": 0,
        "all_requests": [],  # list of {input, cached, output, success, ttft, gen_time, provider, model, is_closing}
        "is_closing": False,  # True when deterministic closing in progress
    }
    
    # Preserve last successful metrics for final billing (fix 0ms telemetry)
    last_successful_metrics = {
        "ttft_ms": 0.0,
        "generation_time_ms": 0.0,
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "output_tokens": 0,
        "provider": "",
        "model": "",
    }

    # ------------------------------------------------------------------
    # Mode: assistant (STT+LLM+TTS) vs announcement (fixed script only).
    # ------------------------------------------------------------------
    agent_mode = getattr(cfg, "agent_mode", "assistant") or "assistant"
    logger.info("[AGENT_WAITING] room=%s agent_id=%s name=%s agent_mode=%s", getattr(ctx.room, "name", ""), agent_id, cfg.name, agent_mode)
    if agent_mode == "announcement":
        session = build_announcement_session(cfg)
    else:
        session = await build_assistant_session(cfg, turn_timing_ref=turn_timing)

    # ------------------------------------------------------------------
    # Silence watchdog + No-response watchdog.
    #
    # 1) LLM silence: When the LLM 429s (Groq free-tier TPM limit) the fail-fast
    #    retry budget gives up in <1s and LiveKit logs the error but speaks
    #    NOTHING — caller left in dead air. So arm timer on every user turn,
    #    if no assistant reply within LLM_FALLBACK_DELAY, speak fallback.
    # 2) User silence: If user says nothing for no_response_timeout_seconds
    #    (configurable per agent, e.g. 30 sec), speak the agent's
    #    no_response_message and hang up. Requested by user.
    # ------------------------------------------------------------------
    call_finished = asyncio.Event()
    call_closed = {"done": False}
    closing_requested = {"done": False}
    closing_in_progress = {"done": False}
    closing_task_ref = {"task": None}
    agent_holder = {"agent": None}
    reply_tracker = {
        "last_user_ts": 0.0,
        "last_assistant_ts": 0.0,
        "empty_spoken": False,
        "pending": None,
        "fallback_say": None,
    }
    # No-response tracking: last time user spoke or agent spoke
    no_response_state = {
        "last_activity": time.time(),
        "task": None,
        "triggered": False,
    }

    @ctx.room.on("disconnected")
    def _on_room_disconnected(*_):
        logger.info("Room disconnected event received")
        call_finished.set()

    @session.on("close")
    def _on_session_close(*_):
        logger.info("Session close event received")
        call_finished.set()

    async def _on_job_shutdown(*_):
        call_finished.set()

    ctx.add_shutdown_callback(_on_job_shutdown)

    async def _do_deterministic_closing():
        # Prevent duplicate closings, but allow if already closing to ensure completion
        if closing_in_progress["done"]:
            logger.info("Deterministic closing already in progress — skipping duplicate")
            return
        closing_in_progress["done"] = True
        call_closed["done"] = True
        closing_requested["done"] = True
        _cancel_pending()
        _cancel_no_response()
        fb = reply_tracker.get("fallback_say")
        if fb is not None and not fb.done():
            fb.cancel()
        reply_tracker["fallback_say"] = None
        closing_msg = _get_deterministic_closing(cfg)
        try:
            usage["tts_chars"] += len(closing_msg)
            usage["transcripts"].append({"role": "agent", "text": closing_msg})
            logger.info(f"👋 Deterministic closing: {closing_msg} — will play fully then auto-cut")
            # Mark timestamp so end_call tool knows closing was already spoken
            try:
                ag = agent_holder.get("agent")
                if ag is not None:
                    setattr(ag, '_last_deterministic_closing_ts', time.time())
                    if hasattr(ag, 'cfg'):
                        setattr(ag.cfg, '_last_closing_ts', time.time())
                    # Also store on global ref for agent_builder
                    setattr(ag, '_closing_msg', closing_msg)
            except Exception:
                pass
            # Interrupt any ongoing LLM/TTS generation to prioritize goodbye
            try:
                session.interrupt()
                await asyncio.sleep(0.15)
            except Exception:
                pass
            # Speak deterministic closing — MUST complete before shutdown
            try:
                await asyncio.wait_for(session.say(closing_msg, allow_interruptions=False), timeout=20)
                logger.info(f"✅ Deterministic closing TTS completed: {closing_msg}")
            except asyncio.TimeoutError:
                logger.warning(f"⏱️ Deterministic closing TTS timed out after 20s: {closing_msg}")
            except Exception as e:
                # Transport closed is expected if frontend already left, but try to still log
                if "transport is closed" in str(e).lower() or "no stream" in str(e).lower():
                    logger.warning(f"⚠️ Transport closed during closing TTS (frontend may have left early), but message was: {closing_msg} — will still shutdown after delay: {e}")
                else:
                    logger.warning(f"Deterministic closing say failed: {e}")
            # Critical: wait for audio to flush to frontend before cutting
            # 2.5s ensures TTS audio packet fully delivered even on slow network
            await asyncio.sleep(2.5)
        except asyncio.CancelledError:
            logger.info("Deterministic closing cancelled")
            return
        except Exception as e:
            logger.warning(f"Deterministic closing outer failed: {e}")
            await asyncio.sleep(1.0)
        logger.info("[CALL_END_REQUESTED] source=agent reason=completed")
        logger.info("✂️ Auto-cutting call after deterministic closing TTS")
        try:
            session.shutdown(drain=False)
        except Exception:
            pass
        room_name = getattr(ctx.room, "name", None)
        if room_name:
            try:
                from app.telephony import end_active_room
                await end_active_room(room_name)
            except Exception:
                pass
        try:
            ctx.shutdown()
        except Exception:
            pass
        call_finished.set()

    def _schedule_deterministic_closing():
        if agent_mode == "announcement":
            return
        if closing_in_progress["done"]:
            return
        if closing_task_ref["task"] is not None and not closing_task_ref["task"].done():
            return
        try:
            closing_task_ref["task"] = asyncio.ensure_future(_do_deterministic_closing())
        except Exception as e:
            logger.warning(f"Could not schedule deterministic closing: {e}")

    def _cancel_pending():
        t = reply_tracker["pending"]
        if t is not None:
            t.cancel()
            reply_tracker["pending"] = None

    def _mark_reply(ts: float):
        reply_tracker["last_assistant_ts"] = ts
        _cancel_pending()
        fallback_task = reply_tracker.get("fallback_say")
        if fallback_task is not None and not fallback_task.done():
            fallback_task.cancel()
        reply_tracker["fallback_say"] = None

    def _spawn_say(text_to_say: str):
        async def _say():
            try:
                await asyncio.wait_for(session.say(text_to_say, allow_interruptions=True), timeout=15)
            except asyncio.CancelledError:
                return
            except Exception as e:
                # str(e) is EMPTY for asyncio.TimeoutError — log the type so a
                # 15s session.say hang is diagnosable ("fallback say failed: " blank).
                logger.warning(f"🛟 fallback say failed: {type(e).__name__}: {e!r}")
        try:
            old = reply_tracker.get("fallback_say")
            if old is not None and not old.done():
                old.cancel()
            reply_tracker["fallback_say"] = asyncio.ensure_future(_say())
        except Exception as e:
            logger.warning(f"🛟 could not schedule fallback reply: {e}")

    async def _silence_fallback(turn_ts: float):
        try:
            await asyncio.sleep(LLM_FALLBACK_DELAY)
        except asyncio.CancelledError:
            return
        finally:
            if reply_tracker["pending"] is asyncio.current_task():
                reply_tracker["pending"] = None
        if reply_tracker["last_assistant_ts"] >= turn_ts or closing_requested["done"]:
            return  # closing turns must never receive a delayed fallback
        # REAL-stream markers (immediate) vs conversation_item_added (lags 5-15s
        # on reasoning-tool models like gpt-5-nano): _mark_reply only fires from
        # item_added, so a reply that already generated and STARTED PLAYING was
        # still getting an apology over it (2026-09-19 04:19: real answer played
        # at +3.3s, 'Sorry, technical problem' followed at +15s). If this turn's
        # LLM request exists and any immediate marker is set, the reply is alive.
        try:
            _rs = turn_timing.get("request_start", 0)
            if _rs and _rs >= turn_ts - 2:
                _m = max(
                    turn_timing.get("first_token", 0), turn_timing.get("tts_request", 0),
                    turn_timing.get("first_tts_audio", 0), turn_timing.get("first_audio", 0),
                )
                if _m >= _rs:
                    logger.info("🛟 silence watchdog suppressed: reply already streaming/speaking per REAL stream markers (item_added lag)")
                    return
        except Exception:
            pass
        logger.warning(
            f"🛟 No LLM reply within {LLM_FALLBACK_DELAY:.0f}s of the user's turn "
            "(rate-limited 429 or failed generation) — speaking a fallback line "
            "so the call is not silent."
        )
        _spawn_say(getattr(cfg, "fallback_response", "").strip() or DEFAULT_FALLBACK_RESPONSE)

    def _schedule_silence_fallback(turn_ts: float):
        _cancel_pending()
        try:
            reply_tracker["pending"] = asyncio.ensure_future(_silence_fallback(turn_ts))
        except Exception as e:
            reply_tracker["pending"] = None
            logger.warning(f"🛟 could not arm silence watchdog: {e}")

    # ---------- No-response handling — robust scheduled timer ----------
    def _cancel_no_response():
        t = no_response_state.get("task")
        if t is not None and not t.done():
            t.cancel()
        no_response_state["task"] = None

    async def _no_response_timeout_handler():
        idle_timeout = max(15, int(getattr(cfg, "no_response_timeout_seconds", 30) or 30))
        no_response_msg = (getattr(cfg, "no_response_message", "") or
                           "I did not hear a response, so I will end the call now. Thank you for calling.").strip()
        try:
            await asyncio.sleep(idle_timeout)
        except asyncio.CancelledError:
            return
        if call_closed["done"] or closing_in_progress["done"] or closing_requested["done"] or no_response_state.get("triggered"):
            return
        ag = agent_holder.get("agent")
        if ag is not None and getattr(ag, "_opening_started", False) and not getattr(ag, "_opening_done", False):
            logger.info("⏱️ No-response timer fired during the opening line — not interrupting it")
            _schedule_no_response()
            return
        elapsed = time.time() - no_response_state.get("last_activity", 0)
        # If user spoke during sleep, task would have been cancelled; double-check
        if elapsed < idle_timeout - 0.5:
            logger.info(f"⏱️ No-response timer fired but user spoke {elapsed:.1f}s ago (timeout {idle_timeout}s) — skipping")
            return
        # Only trigger when waiting for user
        cur_state = state_tracker.get("state")
        if cur_state not in ("listening", None):
            logger.info(f"⏱️ No-response timer fired but state is {cur_state} (not listening) — rescheduling")
            _schedule_no_response()
            return
        no_response_state["triggered"] = True
        # Mark call as closing to prevent re-arming watchdog on listening transition
        call_closed["done"] = True
        closing_in_progress["done"] = True
        logger.info(f"⏱️ No user response for {elapsed:.0f}s (timeout {idle_timeout}s) — speaking no-response message and ending call")
        try:
            _cancel_pending()
            fb = reply_tracker.get("fallback_say")
            if fb is not None and not fb.done():
                fb.cancel()
            reply_tracker["fallback_say"] = None
            try:
                session.interrupt()
                await asyncio.sleep(0.15)
            except Exception:
                pass
            usage["tts_chars"] += len(no_response_msg)
            usage["transcripts"].append({"role": "agent", "text": no_response_msg})
            logger.info(f"⏱️ No-response closing TTS: {no_response_msg} — will play fully then auto-cut")
            try:
                await asyncio.wait_for(session.say(no_response_msg, allow_interruptions=False), timeout=20)
                logger.info(f"✅ No-response TTS completed: {no_response_msg}")
            except asyncio.TimeoutError:
                logger.warning(f"⏱️ No-response TTS timed out after 20s: {no_response_msg}")
            except Exception as e:
                if "transport is closed" in str(e).lower() or "no stream" in str(e).lower():
                    logger.warning(f"⚠️ Transport closed during no-response TTS (frontend left early), but message was: {no_response_msg}: {e}")
                else:
                    logger.warning(f"No-response say failed: {e}")
            await asyncio.sleep(2.5)
        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.warning(f"No-response outer failed: {e}")
            await asyncio.sleep(1.0)
        logger.info("[CALL_END_REQUESTED] source=timeout reason=no_response")
        logger.info("✂️ Auto-cutting call after no-response TTS")
        try:
            session.shutdown(drain=False)
        except Exception:
            pass
        room_name = getattr(ctx.room, "name", None)
        if room_name:
            try:
                from app.telephony import end_active_room
                await end_active_room(room_name)
            except Exception:
                pass
        try:
            ctx.shutdown()
        except Exception:
            pass
        call_finished.set()

    def _schedule_no_response():
        # Announcement mode reads a script and hangs up. A silence timer would
        # interrupt that script or start a second goodbye.
        if agent_mode == "announcement":
            return
        if no_response_state.get("triggered") or call_closed["done"] or closing_in_progress["done"] or closing_requested["done"]:
            logger.info("⏱️ Not arming no-response — call already closing/triggered")
            return
        _cancel_no_response()
        idle_timeout = max(15, int(getattr(cfg, "no_response_timeout_seconds", 30) or 30))
        no_response_msg = (getattr(cfg, "no_response_message", "") or
                           "I did not hear a response, so I will end the call now. Thank you for calling.").strip()
        no_response_state["last_activity"] = time.time()
        try:
            no_response_state["task"] = asyncio.ensure_future(_no_response_timeout_handler())
            logger.info(f"⏱️ No-response watchdog armed: {idle_timeout}s -> '{no_response_msg[:60]}' (scheduled)")
        except Exception as e:
            logger.warning(f"Could not arm no-response watchdog: {e}")

    def on_item_added(ev):
        # Allow system closing/no-response messages even after call_closed is set
        # to ensure transcript logging works; otherwise early return hides TTS log
        try:
            _item_role = getattr(getattr(ev, "item", None), "role", None)
        except Exception:
            _item_role = None
        if call_closed["done"] and _item_role != "assistant" and not no_response_state.get("triggered"):
            return
        if call_closed["done"] and _item_role == "assistant":
            # Still process if it's system closing (triggered flag) — otherwise skip LLM chatter after close
            if not (no_response_state.get("triggered") or closing_in_progress["done"]):
                return
        item = getattr(ev, "item", None)
        role = getattr(item, "role", None)
        text = _msg_text(item)
        if role == "user":
            if not text:
                return
            now = time.time()
            # Production debounce fix: 2.5s was too long for short "haan/ok/yes" causing missed turns
            # For short utterances (<3 words), debounce 0.8s, for longer 1.5s (was 2.5s)
            # Prevents duplicate STT events (interim->final same text) from delaying turn, but allows quick repeats
            words_in_text = len(text.split())
            debounce_threshold = 0.8 if words_in_text <= 2 else 1.5
            if text == last_user_transcript["text"] and (now - last_user_transcript["ts"]) < debounce_threshold:
                logger.info(f"⏭️ Dedupe STT duplicate (same text within {debounce_threshold}s): {text[:60]}")
                return
            last_user_transcript["text"] = text
            last_user_transcript["ts"] = now
            # --- Production timing: STT final received ---
            # FIX: Always start fresh timing for each user turn (unconditional reset)
            # Previous bug: conditional reset only if stale>5s caused first_token from previous turn
            # to leak into next turn's tts_request (2099ms artifact) and speech_end 16.8s old artifact
            # Now: unconditional fresh reset per turn, then set speech_end and stt_final fresh
            prev_speech_end = turn_timing.get("speech_end", 0)
            if prev_speech_end != 0:
                stale_age = now - prev_speech_end
                if stale_age > 2.0:
                    logger.info(f"🔄 Resetting turn_timing: prev speech_end {stale_age:.1f}s old (empty turn or long pause) for fresh turn")
            # Fresh timing for this turn - reset ALL keys unconditionally (V2 with TTFT)
            turn_timing["turn_detected"] = 0.0
            turn_timing["llm_start"] = 0.0
            turn_timing["request_start"] = 0.0
            turn_timing["first_token"] = 0.0
            turn_timing["tts_request"] = 0.0
            turn_timing["first_tts_audio"] = 0.0
            turn_timing["llm_complete"] = 0.0
            turn_timing["generation_complete"] = 0.0
            turn_timing["first_audio"] = 0.0
            turn_timing["ttft_ms"] = 0.0
            turn_timing["generation_time_ms"] = 0.0
            turn_timing["input_tokens"] = 0
            turn_timing["cached_input_tokens"] = 0
            turn_timing["output_tokens"] = 0
            # Fresh speech_end and stt_final for this turn
            turn_timing["speech_end"] = now - 0.25  # approximate speech end 250ms before final
            turn_timing["stt_final"] = now
            # Calculate speech_end->STT_final
            if turn_timing["speech_end"] > 0:
                speech_to_stt = (now - turn_timing["speech_end"]) * 1000
                logger.info(f"⏱️ TIMING speech_end->STT_final: {speech_to_stt:.0f}ms (text: {text[:50]}, words: {words_in_text})")
                # Flag if exceeds 400ms target
                if speech_to_stt > 600:
                    logger.warning(f"🐢 Slow STT final: speech_end->STT_final {speech_to_stt:.0f}ms exceeds 400ms target (possible Deepgram delay)")
            # Reset speech_end for next turn after logging
            # Keep it for total calculation until first_audio
            # User spoke — cancel any pending no-response timer (user is active)
            _cancel_no_response()
            no_response_state["last_activity"] = now
            words = max(len(text.split()), 1)
            usage["llm_input_tokens"] += int(words * 1.3)
            usage["user_speech_seconds"] += (words / 150.0) * 60.0
            usage["transcripts"].append({"role": "user", "text": text})
            logger.info(f"👂 User: {text}")
            normalized_user = " ".join(text.lower().replace(".", " ").replace(",", " ").split())
            # Expanded closing detection for low-latency deterministic goodbye.
            # Covers: bye variants, ok good bye, thank you, mixed Hindi/English,
            # and natural no-help phrases like "नहीं और कोई मदद नहीं चाहिए"
            # and transliterated "mujhe kuch nahi puchna hai".
            closing_exact = {
                "bye", "bye bye", "goodbye", "good bye", "ok bye", "okay bye",
                "ok good bye", "okay good bye", "ok goodbye", "okay goodbye",
                "good bye bye", "thank you", "thanks", "thankyou",
                "और तो मुझे कुछ नहीं जानना", "अब मुझे कुछ नहीं जानना",
                "मुझे और कुछ नहीं जानना", "बस इतना ही", "बस इतना ही पूछना था",
                "no more questions", "no more help", "that's all", "that is all",
                "नहीं और कोई मदद नहीं चाहिए", "और कोई मदद नहीं चाहिए",
                "कोई मदद नहीं चाहिए", "और कुछ नहीं चाहिए", "बस हो गया",
                "नहीं और कोई सवाल नहीं है", "और कोई सवाल नहीं है",
                "कोई सवाल नहीं है", "मुझे कुछ नहीं पूछना है", "मुझे कुछ नहीं पूछना",
                "कुछ नहीं पूछना है", "कुछ नहीं पूछना",
                "mujhe kuch nahi puchna hai", "mujhe kuch nahi puchna",
                "kuch nahi puchna hai", "kuch nahi puchna",
                "koi sawaal nahi hai", "koi sawal nahi hai",
                "aur koi sawaal nahi hai", "aur koi sawal nahi hai",
                "nahi aur koi madad nahi chahiye", "aur koi madad nahi chahiye",
                "nahi aur koi sawaal nahi hai",
            }
            closing_substrings = (
                "cut the call", "hang up", "disconnect", "end the call", "call cut",
                "कॉल कट", "call काट", "कॉल काट", "call cut कर दीजिए", "call काट दीजिए",
                "कॉल बंद कर दीजिए", "फोन काट दीजिए", "फोन काट दो",
                # Hang-up permission granted in Hindi / mixed script (2026-09-19: caller
                # said "मुझे कुछ भी नहीं चाहिए. आप phone रख सकते" twice, call dragged 33s)
                "फोन रख दो", "फ़ोन रख दो", "फोन रख दीजिए", "फ़ोन रख दीजिए", "फ़ोन रख",
                "फोन रख", "phone रख", "call रख", "कॉल रख",
                "phone rakh do", "phone rakh dijiye", "phone rakh sakte", "aap phone rakh sakte",
                # "I need nothing (else)" — direct answer to 'anything else?' means close
                "कुछ भी नहीं चाहिए", "जानकारी नहीं चाहिए", "कोई भी जानकारी नहीं चाहिए",
                "kuch bhi nahi chahiye", "koi jaankari nahi chahiye", "kisi bhi tarah ki madad nahi chahiye",
                "और तो मुझे कुछ नहीं जानना", "अब मुझे कुछ नहीं जानना",
                "मुझे और कुछ नहीं जानना", "बस इतना ही", "बस इतना ही पूछना था",
                "no more questions", "no more help", "that's all", "that is all",
                "नहीं और कोई मदद नहीं चाहिए", "और कोई मदद नहीं चाहिए",
                "कोई मदद नहीं चाहिए", "और कुछ नहीं चाहिए",
                "नहीं और कोई सवाल नहीं है", "और कोई सवाल नहीं है",
                "मुझे कुछ नहीं पूछना है", "कुछ नहीं पूछना है",
                "mujhe kuch nahi puchna", "kuch nahi puchna",
                "koi sawaal nahi", "koi sawal nahi",
            )
            # Robust bye detection: any occurrence of goodbye/good bye, or standalone bye
            has_goodbye = "goodbye" in normalized_user or "good bye" in normalized_user
            # bye as separate token or at end, avoid false positive from "by" substring
            tokens = normalized_user.split()
            has_bye_token = "bye" in tokens or normalized_user.endswith(" bye") or normalized_user.startswith("bye ")
            # Enhanced thank detection: "thank you very much", "thank kota" (mis-heard), "accha laga thank" etc
            # Previous logic required <=12 tokens and exact thank you — too strict, caused
            # "Ok, चलिए ठीक है आपसे बात करके अच्छा लगा thank Kota." to NOT close.
            # Now: thank/thanks/dhanyavaad + positive sentiment or accha laga/khushi = closing
            has_thank = "thank" in normalized_user or "thanks" in normalized_user or "धन्यवाद" in text or "dhanyavaad" in normalized_user
            has_positive_close = any(w in normalized_user for w in ("accha laga", "achha laga", "khushi", "bahut accha", "very much", "bahut"))
            has_contact_info = any(c in normalized_user for c in ("nine", "five", "double", "triple", "zero", "at the rate", "gmail", "dot com", "number", "email")) or (any(ch.isdigit() for ch in text) and len(tokens) >= 4 and len(tokens) <= 20)
            if has_contact_info:
                closing_requested["done"] = False
            else:
                closing_requested["done"] = (
                    normalized_user in closing_exact
                    or has_goodbye
                    or (has_bye_token and len(tokens) <= 8)
                    or (has_thank and "?" not in text and (len(tokens) <= 18 or has_positive_close or "accha laga" in normalized_user or "achha laga" in normalized_user))
                    or any(phrase in normalized_user for phrase in closing_substrings)
                )
            if closing_requested["done"]:
                # Never let the generic provider-timeout fallback speak after a
                # caller has already asked to leave. Speak deterministic closing
                # and hang up (bb393dd fix).
                # FIX: Mark as closing to separate intentional 0/0 closing from genuine empty turns
                turn_timing["is_closing"] = True
                logger.info(f"👋 Deterministic closing requested, marking is_closing=True to exclude 0/0 from failure count")
                _cancel_pending()
                old_fallback = reply_tracker.get("fallback_say")
                if old_fallback is not None and not old_fallback.done():
                    old_fallback.cancel()
                reply_tracker["fallback_say"] = None
                _schedule_deterministic_closing()
                return
            # A fresh turn supersedes any fallback still speaking from the
            # previous failed turn; never let it bleed into this reply.
            old_fallback = reply_tracker.get("fallback_say")
            if old_fallback is not None and not old_fallback.done():
                old_fallback.cancel()
            reply_tracker["fallback_say"] = None
            # A fresh turn starts: arm the silence watchdog so a 429'd or empty
            # LLM turn never leaves the caller in dead air.
            reply_tracker["last_user_ts"] = now
            reply_tracker["empty_spoken"] = False
            _schedule_silence_fallback(now)
        elif role == "assistant":
            # Mark assistant output received for empty-turn race fix
            turn_timing["assistant_output_received"] = True
            # Update last_successful_metrics for billing preservation
            try:
                if turn_timing.get("ttft_ms",0) > 0:
                    turn_timing["last_ttft"] = turn_timing.get("ttft_ms",0)
                if turn_timing.get("generation_time_ms",0) > 0:
                    turn_timing["last_gen_time"] = turn_timing.get("generation_time_ms",0)
                turn_timing["last_input"] = turn_timing.get("input_tokens",0)
                turn_timing["last_output"] = turn_timing.get("output_tokens",0)
                turn_timing["last_cached"] = turn_timing.get("cached_input_tokens",0)
                turn_timing["last_provider"] = turn_timing.get("llm_provider","")
                turn_timing["last_model"] = turn_timing.get("llm_model","")
            except Exception:
                pass
            
            # Log raw assistant item for debugging empty turns
            raw_text = _msg_text(item)
            is_tool = _item_is_tool_related(item)
            if is_tool:
                logger.info(f"🔧 Assistant item is tool-related, skipping TTS (role={role}, text_len={len(raw_text)}, attrs={[a for a in ('function_call','tool_call','tool_calls') if getattr(item,a,None)]})")
                return
            now = time.time()
            if not text.strip():
                # FIX: Don't treat deterministic closing as empty failure
                if turn_timing.get("is_closing", False):
                    logger.info(f"👋 Deterministic closing in progress, empty assistant item is intentional (is_closing=True), not failure")
                    return
                # Check if LLM still active - if so, don't treat as empty yet
                if turn_timing.get("llm_active", False):
                    logger.info(f"⏳ LLM still active (request_start {now-turn_timing.get('request_start',now):.2f}s ago), empty assistant item ignored, waiting for stream")
                    return
                # Detailed logging for empty LLM turn root cause - only when stream terminated
                logger.warning(f"🧮 LLM produced an empty assistant item after stream terminated (raw_len={len(raw_text)}, role={role}, text_content={getattr(item,'text_content',None)}, content={getattr(item,'content',None)}); waiting for speakable reply. Possible 404/429 or filtered. llm_active={turn_timing.get('llm_active')} gen_complete={turn_timing.get('generation_complete')} is_closing={turn_timing.get('is_closing',False)}")
                # Also log timing for empty turn diagnostics
                if turn_timing.get("llm_start",0) > 0:
                    logger.warning(f"⏱️ Empty turn timing: llm_start->now {(now-turn_timing['llm_start'])*1000:.0f}ms, speech_end->now {(now-turn_timing.get('speech_end',now))*1000:.0f}ms active={turn_timing.get('llm_active')}")
                return
            _mark_reply(now)
            # Reset no-response timer when agent speaks - timeout starts after agent finishes
            no_response_state["last_activity"] = now
            cleaned = clean_reply_text(text)
            # Never let the LLM close a call on its own. Models sometimes emit
            # a farewell after ambiguous STT fragments such as "company go".
            # Only transcript-level explicit intent may produce a closing TTS.
            # EXEMPT system-initiated messages: no-response and deterministic closing
            # must never be suppressed (they contain "thank you for calling").
            is_system_closing = False
            try:
                sys_closing_msgs = [
                    DETERMINISTIC_CLOSING_MESSAGE,
                    DETERMINISTIC_CLOSING_MESSAGE_EN,
                    (getattr(cfg, "no_response_message", "") or "").strip(),
                ]
                # also check configured message truncated log comparison
                if any(cleaned == m or text.strip() == m for m in sys_closing_msgs if m):
                    is_system_closing = True
                if no_response_state.get("triggered") or closing_in_progress["done"] or closing_requested["done"]:
                    # If we are already in closing/no-response flow, allow any farewell
                    is_system_closing = True
            except Exception:
                pass
            latest_user = last_user_transcript["text"].lower()
            explicit_end = any(term in latest_user for term in (
                "goodbye", "good bye", "bye", "hang up", "cut the call",
                "disconnect", "end the call", "thank you", "thankyou", "bye bye",
                "ok bye", "okay bye", "कॉल कट", "call काट", "कॉल काट",
                "call cut कर दीजिए", "call काट दीजिए", "कॉल बंद कर दीजिए",
                "फोन काट दीजिए",
                # Same hang-up / nothing-needed additions as closing_substrings
                "फोन रख", "फ़ोन रख", "phone रख", "call रख", "कॉल रख",
                "phone rakh", "कुछ भी नहीं चाहिए", "जानकारी नहीं चाहिए",
                "kuch bhi nahi chahiye", "koi jaankari nahi chahiye"
            ))
            if not is_system_closing and not explicit_end and any(term in cleaned.lower() for term in ("goodbye", "good bye", "thank you for calling")):
                logger.warning("🛡️ Suppressed model farewell without explicit caller goodbye")
                cleaned = "Ji, batayiye, aapko kis tarah ki madad chahiye?"
            if cleaned == FALLBACK_REPLY and text.strip() != FALLBACK_REPLY:
                # The model returned something but we flagged it as a fallback —
                # surface the raw text so we can see WHY.
                logger.warning(f"🧮 LLM reply flagged as fallback. RAW: {text!r}")
            usage["tts_chars"] += len(cleaned)
            # Only count LLM output in assistant mode; announcement plays a fixed
            # script with no LLM, so it must not be billed for LLM tokens.
            if agent_mode != "announcement":
                words = max(len(cleaned.split()), 1)
                usage["llm_output_tokens"] += int(words * 1.3)
            usage["transcripts"].append({"role": "agent", "text": cleaned})
            # --- Production timing: LLM complete - FIXED 6-9s delay ---
            # Previous bug: conversation_item_added (llm_complete) fired 6-9s after first_token,
            # even though REAL stream already completed in 1.0-1.2s and first_audio at 1.3-1.6s.
            # This caused duplicate completion path and misleading first_token->llm_complete 6735ms logs.
            # Fix: Authoritative completion is generation_complete from wrapper (REAL stream), not llm_complete from conversation_item_added.
            # conversation_item_added is delayed (after TTS speaking), so we should NOT treat it as authoritative for latency.
            # Only set llm_complete if REAL audio not yet happened, and don't log fallback if REAL already happened.
            now_llm_complete = time.time()
            has_real_audio = turn_timing.get("first_audio", 0) > 0 or turn_timing.get("first_tts_audio", 0) > 0 or turn_timing.get("last_speech_end_to_first_audio", 0) > 0
            
            # Only set llm_complete if not already set AND real audio not yet happened (avoid delayed overwrite)
            if turn_timing.get("llm_complete", 0) == 0 and not has_real_audio:
                turn_timing["llm_complete"] = now_llm_complete
                if turn_timing["first_token"] > 0:
                    logger.info(f"⏱️ TIMING first_token->llm_complete (LLM full response): {(now_llm_complete-turn_timing['first_token'])*1000:.0f}ms (authoritative if no REAL audio yet)")
                if turn_timing["llm_start"] > 0:
                    logger.info(f"⏱️ TIMING llm_start->llm_complete: {(now_llm_complete-turn_timing['llm_start'])*1000:.0f}ms")
                if turn_timing["speech_end"] > 0:
                    logger.info(f"⏱️ TIMING speech_end->llm_complete: {(now_llm_complete-turn_timing['speech_end'])*1000:.0f}ms (NOTE: REAL audio via TTS wrapper is authoritative)")
            elif has_real_audio:
                # REAL audio already happened at 1.3-1.6s, this llm_complete is delayed 6-9s, don't treat as authoritative
                if turn_timing["first_token"] > 0:
                    delay = (now_llm_complete - turn_timing["first_token"]) * 1000
                    if delay > 5000:
                        logger.info(f"ℹ️ Delayed conversation_item_added {delay:.0f}ms after first_token (REAL audio already at {turn_timing.get('last_speech_end_to_first_audio',0):.0f}ms) - not authoritative, REAL stream is authoritative")
                # Don't overwrite llm_complete if already set from REAL path
                if turn_timing.get("llm_complete", 0) == 0:
                    turn_timing["llm_complete"] = now_llm_complete
            
            # Fallback for say() calls without TTS wrapper - only if REAL audio never happened
            if turn_timing.get("first_tts_audio", 0) == 0 and turn_timing.get("first_audio", 0) == 0 and not has_real_audio:
                if turn_timing["first_token"] > 0:
                    token_to_audio = (now_llm_complete - turn_timing["first_token"]) * 1000
                    logger.info(f"⏱️ TIMING first_token->first_audio (fallback no wrapper): {token_to_audio:.0f}ms")
                if turn_timing["speech_end"] > 0:
                    speech_to_audio = (now_llm_complete - turn_timing["speech_end"]) * 1000
                    logger.info(f"⏱️ TIMING speech_end->first_audio (fallback): {speech_to_audio:.0f}ms")
                    turn_timing["last_speech_end_to_first_audio"] = speech_to_audio
                    if turn_timing["stt_final"] > 0 and turn_timing["turn_detected"] > 0 and turn_timing["llm_start"] > 0 and turn_timing["first_token"] > 0:
                        logger.info(
                            f"📊 TURN BREAKDOWN (fallback): speech_end->STT_final {(turn_timing['stt_final']-turn_timing['speech_end'])*1000:.0f}ms | "
                            f"STT_final->turn {(turn_timing['turn_detected']-turn_timing['stt_final'])*1000:.0f}ms | "
                            f"turn->LLM {(turn_timing['llm_start']-turn_timing['turn_detected'])*1000:.0f}ms | "
                            f"LLM->first_token {(turn_timing['first_token']-turn_timing['llm_start'])*1000:.0f}ms | "
                            f"first_token->audio {(now_llm_complete-turn_timing['first_token'])*1000:.0f}ms | "
                            f"TOTAL {speech_to_audio:.0f}ms"
                        )
                    if turn_timing.get("tts_request", 0) == 0:
                        turn_timing["speech_end"] = 0.0
                        turn_timing["stt_final"] = 0.0
                        turn_timing["turn_detected"] = 0.0
                        turn_timing["llm_start"] = 0.0
                        turn_timing["request_start"] = 0.0
                        turn_timing["first_token"] = 0.0
                        turn_timing["tts_request"] = 0.0
                        turn_timing["first_tts_audio"] = 0.0
                        turn_timing["llm_complete"] = 0.0
                        turn_timing["generation_complete"] = 0.0
                        turn_timing["first_audio"] = 0.0
                        turn_timing["ttft_ms"] = 0.0
                        turn_timing["generation_time_ms"] = 0.0
            logger.info(f"🗣️ TTS (LLM complete): {cleaned} (REAL audio was at {turn_timing.get('last_speech_end_to_first_audio',0):.0f}ms, this is transcript only)")

    session.on("conversation_item_added", on_item_added)

    def _on_state(ev):
        now = time.time()
        prev = state_tracker["state"]
        elapsed = now - state_tracker["since"]
        if prev == "thinking" and elapsed > 2.5:
            logger.warning(f"🐢 Slow turn: agent was in 'thinking' for {elapsed:.2f}s")
        logger.info(f"🔄 state {prev} -> {ev.new_state} ({elapsed:.2f}s)")

        # --- Production timing instrumentation ---
        if prev == "listening" and ev.new_state == "thinking":
            # Turn detected: listening -> thinking = endpointing triggered
            # This is speech_end + VAD + endpointing + STT final -> LLM request path
            turn_timing["turn_detected"] = now
            if turn_timing["stt_final"] > 0:
                stt_to_turn = (now - turn_timing["stt_final"]) * 1000
                logger.info(f"⏱️ TIMING STT_final->turn_detected (endpointing): {stt_to_turn:.0f}ms")
                if stt_to_turn > 150:
                    logger.warning(f"🐢 Slow endpointing: STT_final->turn {stt_to_turn:.0f}ms exceeds 100ms target")
            if turn_timing["speech_end"] > 0:
                speech_to_turn = (now - turn_timing["speech_end"]) * 1000
                logger.info(f"⏱️ TIMING speech_end->turn_detected (VAD+STT+endpointing): {speech_to_turn:.0f}ms")
                if speech_to_turn > 700:
                    logger.warning(f"🐢 Slow turn detection: speech_end->turn {speech_to_turn:.0f}ms exceeds 500ms target (outlier!)")
            # Also log as LLM start (turn completed -> LLM request)
            turn_timing["llm_start"] = now
            if turn_timing["stt_final"] > 0:
                stt_to_llm = (now - turn_timing["stt_final"]) * 1000
                logger.info(f"⏱️ TIMING STT_final->LLM_start: {stt_to_llm:.0f}ms (target ≤100ms)")

        elif prev == "thinking" and ev.new_state == "speaking":
            # First token -> first audio: LLM first token arrived, TTS starting
            # FIX: Don't overwrite first_token if already set by LLM wrapper (authoritative TTFT)
            # Previous bug: wrapper set first_token at TTFT time (e.g. 772ms), then _on_state set it again at speaking time (1.07s),
            # causing first_token->llm_complete to be calculated from speaking time, not actual first_token, leading to 6-9s delay logs
            if turn_timing.get("first_token", 0) == 0:
                turn_timing["first_token"] = now
                logger.info(f"ℹ️ first_token set from state thinking->speaking (no wrapper TTFT yet)")
            else:
                # first_token already set by wrapper at actual TTFT time, preserve it
                existing_age = (now - turn_timing["first_token"]) * 1000
                logger.info(f"ℹ️ first_token already set {existing_age:.0f}ms ago by wrapper (TTFT {turn_timing.get('ttft_ms',0):.0f}ms), preserving authoritative")
            
            if turn_timing["llm_start"] > 0:
                llm_to_token = (now - turn_timing["llm_start"]) * 1000
                logger.info(f"⏱️ TIMING LLM_start->first_token: {llm_to_token:.0f}ms (target ≤500ms) (wrapper TTFT {turn_timing.get('ttft_ms',0):.0f}ms is authoritative)")
            if turn_timing["speech_end"] > 0:
                speech_to_token = (now - turn_timing["speech_end"]) * 1000
                logger.info(f"⏱️ TIMING speech_end->first_token: {speech_to_token:.0f}ms (wrapper {turn_timing.get('ttft_ms',0):.0f}ms is authoritative)")

        elif prev == "thinking" and ev.new_state == "listening":
            # Empty turn: thinking->listening without speaking - FIXED RACE CONDITION + DETERMINISTIC CLOSING
            # FIX: is_closing=True must prevent Empty LLM turn detected from firing, closing 0/0 excluded from failed_requests
            if turn_timing.get("is_closing", False):
                logger.info(f"👋 Deterministic closing in progress (is_closing=True), thinking->listening {elapsed:.2f}s is intentional closing, not empty failure - suppressing warning")
                state_tracker["state"] = ev.new_state
                state_tracker["since"] = now
                return
            
            # Previous bug: detector fired before async LLM stream finished (0.04-0.08s)
            # Evidence: LLM REQUEST START, then thinking->listening 0.04s, then TTFT 800ms, then GENERATION COMPLETE
            # This means empty detection raced with active stream.
            # Fix: Only fire when LLM stream has actually terminated (llm_active False) AND no assistant output
            is_llm_active = turn_timing.get("llm_active", False)
            has_output = turn_timing.get("assistant_output_received", False) or turn_timing.get("first_token",0) > 0
            gen_complete = turn_timing.get("generation_complete",0)
            request_start = turn_timing.get("request_start",0)
            
            if is_llm_active:
                # LLM still streaming, don't treat as empty - this is the race fix
                # FIX: Don't update state_tracker to listening, keep thinking to prevent new REQUEST START while previous active
                # Previous bug: set state to listening even though LLM active, allowing new listening->thinking and second REQUEST START
                # This caused 0/0 failed requests (Request 1 and 5) even though preemptive disabled
                # New: keep state as thinking, don't allow new turn until LLM completes
                # request_start may be 0 (timing not yet stamped); guard so the
                # log doesn't print epoch seconds like "1789768698.62s ago".
                _rs_ago = now - request_start if request_start else 0.0
                logger.info(f"⏳ Ignoring thinking->listening (0.04s race): LLM still active request_start {_rs_ago:.2f}s ago, first_token={turn_timing.get('first_token',0)>0}, gen_complete={gen_complete>0}, has_output={has_output} - keeping thinking, waiting for stream to finish (prevents duplicate REQUEST START)")
                # Do NOT update state_tracker, keep as thinking, do NOT reset timing, keep active request alive
                # This ensures exactly one valid LLM request per completed user turn
                return
            
            # Only if LLM terminated and no output, then it's truly empty
            # FIX: Check is_closing again before warning
            if turn_timing.get("is_closing", False):
                logger.info(f"👋 Deterministic closing in progress (is_closing=True), empty turn confirmed but is intentional closing, not failure")
                state_tracker["state"] = ev.new_state
                state_tracker["since"] = now
                return
            
            if not has_output and gen_complete == 0 and request_start > 0:
                # LLM terminated with no output and no assistant item - check if it was 0-token generation
                if turn_timing.get("output_tokens",0) == 0 and turn_timing.get("input_tokens",0) == 0:
                    # Check if this is closing
                    if turn_timing.get("is_closing", False):
                        logger.info(f"👋 Empty LLM turn confirmed but is_closing=True, intentional closing 0/0, not failure")
                        state_tracker["state"] = ev.new_state
                        state_tracker["since"] = now
                        return
                    logger.warning(f"⚠️ Empty LLM turn confirmed (stream terminated with 0 tokens): thinking {elapsed:.2f}s → listening without speaking. request_start {now-request_start:.2f}s ago, gen_complete {gen_complete}. Possible preemptive invalidation or 0-token response.")
                else:
                    if turn_timing.get("is_closing", False):
                        logger.info(f"👋 Empty LLM turn detected but is_closing=True, intentional closing, not failure - suppressing warning")
                        state_tracker["state"] = ev.new_state
                        state_tracker["since"] = now
                        return
                    logger.warning(f"⚠️ Empty LLM turn detected (thinking {elapsed:.2f}s → listening without speaking). Possible causes: LLM 404/429, empty response, or tool filtering. speech_end age: {(now-turn_timing.get('speech_end',0)) if turn_timing.get('speech_end') else 'N/A'} active={is_llm_active} has_output={has_output}")
            elif not has_output:
                if turn_timing.get("is_closing", False):
                    logger.info(f"👋 Empty LLM turn detected (thinking {elapsed:.2f}s) but is_closing=True, intentional closing, not failure")
                    state_tracker["state"] = ev.new_state
                    state_tracker["since"] = now
                    return
                logger.warning(f"⚠️ Empty LLM turn detected (thinking {elapsed:.2f}s → listening without speaking). No assistant output, llm_active={is_llm_active}, gen_complete={gen_complete>0}, first_token={turn_timing.get('first_token',0)>0}")
            else:
                # Had output but still went listening->thinking without speaking? Might be tool filtering
                logger.info(f"ℹ️ thinking->listening after output (has_output={has_output}, first_token {turn_timing.get('first_token',0)>0}) - not empty, likely TTS finished")
                state_tracker["state"] = ev.new_state
                state_tracker["since"] = now
                return
            
            if turn_timing["speech_end"] != 0 and turn_timing["first_audio"] == 0 and not is_llm_active:
                # Only reset if LLM not active
                logger.info(f"🔄 Resetting turn_timing after confirmed empty turn (LLM terminated, no output) to avoid next-turn outlier")
                turn_timing["speech_end"] = 0.0
                turn_timing["stt_final"] = 0.0
                turn_timing["turn_detected"] = 0.0
                turn_timing["llm_start"] = 0.0
                turn_timing["request_start"] = 0.0
                turn_timing["first_token"] = 0.0
                turn_timing["first_audio"] = 0.0
                turn_timing["llm_active"] = False
                if "tts_request" in turn_timing:
                    turn_timing["tts_request"] = 0.0
                if "first_tts_audio" in turn_timing:
                    turn_timing["first_tts_audio"] = 0.0
                if "audio_published" in turn_timing:
                    turn_timing["audio_published"] = 0.0
                if "llm_complete" in turn_timing:
                    turn_timing["llm_complete"] = 0.0
                if "generation_complete" in turn_timing:
                    turn_timing["generation_complete"] = 0.0
                if "request_start" in turn_timing:
                    turn_timing["request_start"] = 0.0
                if "ttft_ms" in turn_timing:
                    turn_timing["ttft_ms"] = 0.0
                if "generation_time_ms" in turn_timing:
                    turn_timing["generation_time_ms"] = 0.0
                if "assistant_output_received" in turn_timing:
                    turn_timing["assistant_output_received"] = False

        elif ev.new_state == "listening" and prev == "speaking":
            # Agent finished speaking, now listening: estimate speech_end for next turn
            # Reset timing for next turn, but keep last turn's metrics for final calc
            # Actually speech_end will be set when user starts speaking? We need VAD hook.
            # For now, reset stt_final and turn_detected for next turn
            # Keep speech_end as 0 until next VAD end (we approximate via last_user_transcript timing)
            pass

        # Track VAD speech end approximation: when listening starts, user hasn't spoken yet
        # When user stops speaking, STT final arrives, then turn detected.
        # For barge-in detection: listening->thinking is turn, but we also need speech_end.
        # We approximate speech_end as stt_final - 200ms (Deepgram endpointing) or use VAD if available.
        # Better: set speech_end when we get interim STT that then becomes final after silence.
        # For now, we set speech_end when state goes listening->thinking minus endpointing delay
        # to measure outlier.

        if ev.new_state == "speaking":
            _cancel_pending()
            # Don't cancel if we are in no-response closing flow — keep triggered flag
            if not no_response_state.get("triggered"):
                _cancel_no_response()
            no_response_state["last_activity"] = now
            # First audio timing will be logged in TTS handler
        elif ev.new_state == "listening":
            # If no-response already triggered or call closing, do NOT re-arm
            if no_response_state.get("triggered") or call_closed["done"] or closing_in_progress["done"] or closing_requested["done"]:
                logger.info(f"⏱️ Listening but no-response/closing already triggered — not re-arming")
            else:
                no_response_state["last_activity"] = now
                _schedule_no_response()
            # Reset for next turn's speech_end detection
            # We will set speech_end when VAD would have detected end, approx now + user speech
            # Actually we need to track when user starts speaking vs stops.
            # For outlier detection, we log listening duration: if >3s, flag
            if elapsed > 3.0 and prev in ("listening", None):
                logger.warning(f"🐢 Listening outlier: {prev}->{ev.new_state} took {elapsed:.2f}s (possible 3-7s outlier, check VAD/STT)")
        elif ev.new_state == "thinking":
            if not no_response_state.get("triggered"):
                _cancel_no_response()
            no_response_state["last_activity"] = now
        state_tracker["state"] = ev.new_state
        state_tracker["since"] = now

    session.on("agent_state_changed", _on_state)

    # Start recording if the agent has it on — but DO NOT block the call from
    # connecting. A missing/unavailable Egress service used to add ~21s before
    # session.start(), delaying every call. Now it runs in the background and the
    # recording URL is filled in before billing finalizes (or skipped if Egress
    # isn't reachable).
    recording_url = None
    egress_task = None
    if getattr(cfg, "recording_enabled", True):
        async def _start_egress_later():
            nonlocal recording_url
            try:
                recording_url = await asyncio.wait_for(start_egress(ctx.room.name), timeout=10)
            except asyncio.TimeoutError:
                logger.warning("⏱️ Egress timed out after 10s — recording disabled for this call.")
            except Exception as e:
                logger.warning(f"⚠️ Egress unavailable; continuing without recording: {e}")
        egress_task = asyncio.create_task(_start_egress_later())

    if agent_mode == "announcement":
        script = getattr(cfg, "announce_text", "") or greeting
        script = leadfile.render_template(script, lead_data)
        if not (script or "").strip():
            script = greeting or f"Hello, this is {cfg.name}."
        agent = build_announce_agent(cfg, announce_text=script)
        logger.info("[ANNOUNCEMENT_STARTED] room=%s agent_id=%s script=%s", getattr(ctx.room, "name", ""), agent_id, script[:60])
    else:
        agent = build_voice_agent(cfg, greeting=greeting, prior_memory=prior_memory, lead_data=lead_data, turn_timing_ref=turn_timing)
        logger.info("[ASSISTANT_STARTED] room=%s agent_id=%s greeting=%s", getattr(ctx.room, "name", ""), agent_id, greeting[:60])
    agent_holder["agent"] = agent
    logger.info("[AGENT_STARTED] room=%s agent_id=%s agent_mode=%s", getattr(ctx.room, "name", ""), agent_id, agent_mode)

    # Server-side noise cancellation. Two tiers:
    #   * NOISE_CANCELLATION=krisp -> server-side Krisp (BVC) filter. Only works on
    #     LiveKit Cloud WITH the `livekit-krisp-noise-cancellation` package installed
    #     (it's a closed-source binary; it does NOT run on a plain self-hosted SFU).
    #   * default (browser calls) -> the browser already applies WebRTC
    #     noiseSuppression/echoCancellation/autoGainControl (see CallPanel.tsx),
    #     and Deepgram STT uses its built-in VAD (`vad_events=True`), which rejects
    #     non-speech/noise frames before they reach the LLM.
    room_options = None
    try:
        from livekit.agents.voice import room_io as _rio
        room_options = _rio.RoomOptions(
            close_on_disconnect=False,
            delete_room_on_close=False,
        )
        logger.info("🎤 RoomOptions(close_on_disconnect=False, delete_room_on_close=False) armed.")
    except Exception as e:
        logger.warning(f"Could not set RoomOptions: {e}")

    # ------------------------------------------------------------------
    # Finalization (idempotent) + call-end watchdog.
    #
    # LiveKit's built-in `close_on_disconnect` only ends a session when the
    # disconnect reason is CLIENT_INITIATED / ROOM_DELETED / USER_REJECTED.
    # Closing the browser tab or a network drop uses a different reason, so the
    # session never closes and the call stays "in-progress" forever. We fix that
    # with a watchdog that ends the job (which runs `finalize_billing`) as soon
    # as the caller leaves for ANY reason.
    # ------------------------------------------------------------------
    _finalized = {"done": False}

    async def finalize_billing(reason=None):
        if _finalized["done"]:
            return
        _finalized["done"] = True
        try:
            duration = int(time.time() - call_start)
            # V2: Use actual LLM provider/model and cached tokens + TTFT for cost tracking - FIXED 0ms telemetry
            # Previous bug: turn_timing reset after each turn, so final billing showed 0ms TTFT/gen_time
            # Fix: Preserve last successful metrics in turn_timing["last_*"] and use them if current is 0
            try:
                # Try current timing first, then last successful, then usage
                llm_provider = turn_timing.get("llm_provider") or turn_timing.get("last_provider") or (cfg.providers.get_primary_llm().resolve_llm_provider_model()[0] if hasattr(cfg.providers, 'get_primary_llm') else cfg.providers.llm.id)
                llm_model = turn_timing.get("llm_model") or turn_timing.get("last_model") or (cfg.providers.get_primary_llm().resolve_llm_provider_model()[1] if hasattr(cfg.providers, 'get_primary_llm') else (cfg.providers.llm.config or {}).get("model", ""))
                
                # FIX: Use aggregated successful provider usage, not last/preserved timing object's token counts
                # Final billing must equal sum of successful requests
                aggregated_input = turn_timing.get("aggregated_input", 0)
                aggregated_output = turn_timing.get("aggregated_output", 0)
                aggregated_cached = turn_timing.get("aggregated_cached", 0)
                successful_count = turn_timing.get("successful_requests", 0)
                failed_count = turn_timing.get("failed_requests", 0)
                all_reqs = turn_timing.get("all_requests", [])
                
                # Calculate total cost from aggregated
                total_llm_cost = 0.0
                try:
                    from app.llm_catalog import get_llm_model, calculate_llm_cost
                    for req in all_reqs:
                        if req.get("success"):
                            m = get_llm_model(req.get("provider",""), req.get("model",""))
                            if m:
                                c = calculate_llm_cost(m, req["input"], req["cached"], req["output"])
                                total_llm_cost += c['total_llm_cost']
                except Exception as e:
                    logger.debug(f"Could not calculate total aggregated cost: {e}")
                
                if aggregated_input > 0 and successful_count > 0:
                    llm_input = aggregated_input
                    llm_output = aggregated_output
                    llm_cached = aggregated_cached
                    logger.info(f"💰 FINAL BILLING using AGGREGATED successful usage: {successful_count} successful, {failed_count} failed/invalidated, input={llm_input} cached={llm_cached} output={llm_output} total_cost=${total_llm_cost:.6f} (from {len(all_reqs)} total requests)")
                    for i, req in enumerate(all_reqs):
                        logger.info(f"  Request {i+1}: input={req['input']} cached={req['cached']} output={req['output']} success={req['success']} is_closing={req.get('is_closing',False)} TTFT={req['ttft']:.0f}ms gen={req['gen_time']:.0f}ms {req['provider']}:{req['model']}")
                    logger.info(f"📊 FINAL AGGREGATED BILLING successful_requests={successful_count} failed_requests={failed_count} total_input_tokens={aggregated_input} total_cached_tokens={aggregated_cached} total_output_tokens={aggregated_output} total_llm_cost=${total_llm_cost:.6f}")
                else:
                    # Fallback to last if no aggregated
                    llm_input = turn_timing.get("input_tokens", 0) or turn_timing.get("last_input", 0) or usage["llm_input_tokens"]
                    llm_cached = turn_timing.get("cached_input_tokens", 0) or turn_timing.get("last_cached", 0)
                    llm_output = turn_timing.get("output_tokens", 0) or turn_timing.get("last_output", 0) or usage["llm_output_tokens"]
                    logger.warning(f"⚠️ FINAL BILLING no aggregated successful usage, fallback to last/word count: input={llm_input} output={llm_output} (successful {successful_count}, failed {failed_count})")
                    logger.info(f"📊 FINAL BILLING FALLBACK successful_requests={successful_count} failed_requests={failed_count} total_input_tokens={llm_input} total_cached_tokens={llm_cached} total_output_tokens={llm_output} total_llm_cost=${total_llm_cost:.6f}")
                
                # TTFT and gen_time: current, then last, preserve actual measured values
                ttft = turn_timing.get("ttft_ms", 0) or turn_timing.get("last_ttft", 0)
                gen_time = turn_timing.get("generation_time_ms", 0) or turn_timing.get("last_gen_time", 0)
                
                # For final billing, also log average TTFT/gen_time across successful
                if all_reqs:
                    successful_reqs = [r for r in all_reqs if r['success']]
                    if successful_reqs:
                        avg_ttft = sum(r['ttft'] for r in successful_reqs) / len(successful_reqs)
                        avg_gen = sum(r['gen_time'] for r in successful_reqs) / len(successful_reqs)
                        logger.info(f"📊 FINAL BILLING averages across {len(successful_reqs)} successful: avg TTFT {avg_ttft:.0f}ms avg gen_time {avg_gen:.0f}ms last TTFT {ttft:.0f}ms last gen {gen_time:.0f}ms")
                
                if ttft == 0 and gen_time == 0:
                    logger.warning(f"⚠️ FINAL BILLING TTFT/gen_time still 0 after checking last metrics - using 0, but actual measurements were logged during call")
                
                logger.info(f"💰 FINAL BILLING LLM provider={llm_provider} model={llm_model} input={llm_input} cached={llm_cached} output={llm_output} TTFT={ttft:.0f}ms gen_time={gen_time:.0f}ms successful={successful_count} failed={failed_count} total_cost=${total_llm_cost:.6f} (aggregated authoritative)")
            except Exception as e:
                logger.debug(f"Could not get V2 billing info: {e}")
                llm_provider = cfg.providers.llm.id
                llm_model = (cfg.providers.llm.config or {}).get("model", "")
                llm_input = usage["llm_input_tokens"]
                llm_cached = 0
                llm_output = usage["llm_output_tokens"]
                ttft = turn_timing.get("ttft_ms", 0) or turn_timing.get("last_ttft", 0)
                gen_time = turn_timing.get("generation_time_ms", 0) or turn_timing.get("last_gen_time", 0)

            costs = calculate_call_cost(
                duration_seconds=duration,
                stt_seconds=usage["user_speech_seconds"],
                llm_input_tokens=llm_input,
                llm_output_tokens=llm_output,
                tts_chars=usage["tts_chars"],
                llm_provider_id=llm_provider,
                llm_provider=llm_provider,
                llm_model_id=llm_model,
                llm_cached_input_tokens=llm_cached,
                llm_ttft_ms=ttft,
                llm_generation_time_ms=gen_time,
                stt_provider_id=cfg.providers.stt.id,
                tts_provider_id=cfg.providers.tts.id,
                client_rate_per_min=cfg.client_rate_per_min,
            )
            if memory_enabled:
                memory.save(customer_key, usage["transcripts"])

            # Only treat it as a real call if something was said or it ran long
            # enough. Otherwise mark it failed so it isn't billed.
            real_call = (duration >= _FAIL_THRESHOLD_SECONDS) or (usage["user_speech_seconds"] > 0)
            status = "completed" if real_call else "failed"

            # FIX: Pass turn_timing_ref for authoritative billing display
            try:
                print(_billing_report(costs, usage, duration, turn_timing_ref=turn_timing))
            except Exception:
                print(_billing_report(costs, usage, duration))

            # IMPORTANT: Post billing to backend FIRST so wallet deduction happens
            # atomically in main.py (which also updates the call record). This
            # prevents the race where worker marks completed before backend can deduct.
            billing_posted = False
            if real_call:
                try:
                    billing_posted = await _post_billing(call_record["id"], user_id, agent_id, mode, phone,
                                        duration, costs, usage, recording_url, status)
                except Exception as e:
                    logger.warning(f"Billing POST exception, will fallback to direct DB: {e!r}", exc_info=True)
                    billing_posted = False

            # Fallback local update (ensures call is marked completed even if backend unreachable)
            try:
                await repo.update_call(call_record["id"], {
                    "status": status,
                    "ended_at": time.strftime("%Y-%m-%d %H:%M"),
                    "duration_seconds": duration,
                    "transcripts": usage["transcripts"][-60:],
                    "usage": usage,
                    "cost": costs if real_call else {},
                    "recording_url": recording_url,
                })
            except Exception as e:
                logger.warning(f"Local call update failed: {e}")

            # Fallback direct wallet deduct only if backend /api/billing/log failed
            if real_call and not billing_posted:
                try:
                    has_spend = False
                    try:
                        has_spend = await repo.has_spend_for_call(call_record.get("user_id", user_id), call_record["id"])
                    except Exception as he:
                        logger.warning(f"has_spend check failed: {he}")
                    if not has_spend:
                        charge = float(costs.get("client_price_inr", 0) or 0)
                        if charge > 0:
                            wallet = await repo.deduct(call_record.get("user_id", user_id), charge, note=f"Call {call_record['id']}")
                            logger.info(f"💸 Wallet fallback deducted ₹{charge} for call {call_record['id']} — remaining balance ₹{wallet.get('balance', 0)}")
                except Exception as de:
                    logger.warning(f"Direct wallet deduct failed for call {call_record['id']}: {de!r}")

        except Exception as e:
            logger.exception(f"finalize_billing error: {e}")

    # Register the shutdown callback BEFORE the session starts, so finalization is
    # always wired even if setup/session errors out or the room closes instantly.
    try:
        ctx.add_shutdown_callback(finalize_billing)
    except Exception:
        pass

    # Watchdog: end the call when the caller leaves for any reason (closing the
    # tab, network drop, or clicking "Leave"). Closing the session unblocks
    # session.start(), which lets the job shut down and run finalize_billing.
    async def watch_call_end():
        """End this job only after the human caller has actually left.

        close_on_disconnect is off so a goodbye can finish. That also meant a
        hung-up browser could leave the only worker process stuck inside
        session.start(). The next call — after the user picked a different
        agent — was dispatched to nobody and stayed silent.

        A caller who is still connected is not idle. Silence is the no-response
        timer's job. This watcher only releases the job once the caller is gone.
        """
        room = ctx.room
        released = {"done": False}
        saw_human = {"yes": False}
        gone_since = {"t": 0.0}

        def _kind(participant) -> int:
            kind = getattr(participant, "kind", 0)
            try:
                return int(kind)
            except Exception:
                return 0

        def _is_human(participant) -> bool:
            if participant is None or participant == getattr(room, "local_participant", None):
                return False
            # 1 ingress, 2 egress, 4 agent — not the person on the call.
            if _kind(participant) in (1, 2, 4):
                return False
            identity = (getattr(participant, "identity", "") or "").lower()
            if identity.startswith("eg_") or "egress" in identity:
                return False
            return True

        def _humans():
            try:
                return [p for p in room.remote_participants.values() if _is_human(p)]
            except Exception:
                return []

        async def _release(reason: str, source: str = "timeout"):
            if released["done"]:
                return
            released["done"] = True
            call_closed["done"] = True
            logger.info(
                "[CALL_END_REQUESTED] source=%s reason=%s room=%s agent_id=%s",
                source, reason, getattr(ctx.room, "name", ""), agent_id,
            )
            _cancel_pending()
            _cancel_no_response()
            fallback_task = reply_tracker.get("fallback_say")
            if fallback_task is not None and not fallback_task.done():
                fallback_task.cancel()
            reply_tracker["fallback_say"] = None
            try:
                session.shutdown(drain=False)
            except Exception as e:
                logger.warning("session.shutdown on caller leave failed: %r", e)

            room_name = getattr(ctx.room, "name", None)
            if room_name:
                try:
                    from app.telephony import end_active_room
                    await end_active_room(room_name)
                except Exception:
                    pass

            try:
                ctx.shutdown()
            except Exception as e:
                logger.warning("ctx.shutdown failed: %r", e)

            logger.info("[CALL_ENDED] room=%s agent_id=%s reason=%s", getattr(ctx.room, "name", ""), agent_id, reason)
            call_finished.set()

        def _on_connected(participant):
            if not _is_human(participant):
                return
            saw_human["yes"] = True
            gone_since["t"] = 0.0
            logger.info("[AGENT_JOINED] room=%s Caller joined: %s", getattr(room, "name", ""), getattr(participant, "identity", "?"))

        def _on_disconnected(participant):
            if not _is_human(participant):
                return
            if _humans():
                return
            gone_since["t"] = time.time()
            logger.info("👤 Caller disconnected: %s (grace period active)", getattr(participant, "identity", "?"))

        room.on("participant_connected", _on_connected)
        room.on("participant_disconnected", _on_disconnected)
        initial_humans = _humans()
        if initial_humans:
            saw_human["yes"] = True
            logger.info("[AGENT_JOINED] room=%s Caller already in room (%d): %s", getattr(room, "name", ""), len(initial_humans), [p.identity for p in initial_humans])

        try:
            while not released["done"]:
                await asyncio.sleep(0.5)
                # Announcement agent manages its own completion — don't interfere while it's playing
                if agent_mode == "announcement":
                    ag = agent_holder.get("agent")
                    if ag is not None and getattr(ag, "_opening_started", False) and not getattr(ag, "_opening_done", False):
                        continue

                humans = _humans()
                if humans:
                    saw_human["yes"] = True
                    gone_since["t"] = 0.0
                    continue
                if not saw_human["yes"]:
                    continue
                if gone_since["t"] == 0.0:
                    gone_since["t"] = time.time()
                    continue
                # Generous 12-second grace period (NOT 1.5s!) before deciding caller is truly gone
                if time.time() - gone_since["t"] >= 12.0:
                    await _release("user_ended", source="timeout")
                    return
        except asyncio.CancelledError:
            return
        finally:
            try:
                room.off("participant_connected", _on_connected)
                room.off("participant_disconnected", _on_disconnected)
            except Exception:
                pass

    async def _backup_opening_line():
        """Speak the greeting/script if on_enter never started.

        A connected browser call that stays silent is the bug this covers.
        """
        try:
            await asyncio.sleep(8)
        except asyncio.CancelledError:
            return
        if call_closed["done"] or closing_in_progress["done"]:
            return
        ag = agent_holder.get("agent")
        if ag is not None and getattr(ag, "_opening_started", False):
            return
        if state_tracker.get("state") == "speaking":
            return
        if any((t.get("text") or "").strip() and t.get("role") == "agent" for t in usage["transcripts"]):
            return
        if agent_mode == "announcement":
            line = (getattr(cfg, "announce_text", "") or greeting or "").strip()
        else:
            line = (greeting or "").strip()
        if not line:
            logger.warning("🛟 No greeting or script configured — nothing to speak")
            return
        logger.warning("🛟 Opening line had not started — speaking it now (%s)", agent_mode)
        try:
            handle = session.say(line, allow_interruptions=False)
            waiter = getattr(handle, "wait_for_playout", None)
            if callable(waiter):
                await asyncio.wait_for(waiter(), timeout=45)
            elif handle is not None:
                await asyncio.wait_for(handle, timeout=45)
            logger.info("✅ Backup opening line finished")
        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.warning("backup opening line failed: %s: %r", type(e).__name__, e)

    # Deduplication check: if another agent has already connected to this room, exit immediately
    try:
        remote_agents = [
            p for p in ctx.room.remote_participants.values()
            if getattr(p, "kind", None) == 4
            or getattr(p, "is_agent", False)
            or (getattr(p, "identity", "") or "").startswith("agent-")
        ]
        if remote_agents:
            logger.warning(
                "⚠️ Duplicate agent already present in room %s (%s). Exiting this runner to prevent duplicate audio.",
                getattr(ctx.room, "name", ""),
                [getattr(p, "identity", "") for p in remote_agents],
            )
            call_closed["done"] = True
            ctx.shutdown()
            return
    except Exception as e:
        logger.debug("duplicate agent check: %r", e)

    opening_backup = asyncio.create_task(_backup_opening_line())
    watchdog = asyncio.create_task(watch_call_end())

    start_kwargs: dict = {"agent": agent, "room": ctx.room}
    if room_options is not None:
        start_kwargs["room_options"] = room_options
    try:
        await session.start(**start_kwargs)
        # Keep entrypoint alive until the call completes so background watchdogs run
        await call_finished.wait()
    except Exception as e:
        logger.exception("session.start failed — job will exit so the worker can take the next call: %r", e)
        raise
    finally:
        opening_backup.cancel()
        watchdog.cancel()
        _cancel_no_response()
        if egress_task is not None:
            egress_task.cancel()


def _billing_report(costs, usage, duration, turn_timing_ref=None) -> str:
    # FIX: Use aggregated authoritative values for all billing displays, not word-count estimates
    # Authoritative is 69,461 input / 572 output, not 139in/361out from usage word count
    # Make every billing display use same aggregated authoritative values
    try:
        if turn_timing_ref:
            display_input = turn_timing_ref.get("aggregated_input", usage['llm_input_tokens'])
            display_output = turn_timing_ref.get("aggregated_output", usage['llm_output_tokens'])
            successful = turn_timing_ref.get("successful_requests", 0)
            failed = turn_timing_ref.get("failed_requests", 0)
        else:
            # Fallback to usage if no turn_timing_ref, but try to get authoritative from usage if it has been updated
            display_input = usage.get('llm_input_tokens_authoritative', usage['llm_input_tokens'])
            display_output = usage.get('llm_output_tokens_authoritative', usage['llm_output_tokens'])
            successful = usage.get('successful_requests', 0)
            failed = usage.get('failed_requests', 0)
    except Exception:
        display_input = usage['llm_input_tokens']
        display_output = usage['llm_output_tokens']
        successful = 0
        failed = 0
    
    return (
        "\n" + "=" * 64 + "\n"
        f"📊 BILLING  duration={duration}s ({costs['duration_mins']} min)\n"
        f"👂 STT {round(usage['user_speech_seconds'],1)}s -> ₹{costs['stt_cost_inr']}\n"
        f"🧠 LLM {display_input}in/{display_output}out (authoritative aggregated {successful} successful, {failed} failed) -> ₹{costs['llm_cost_inr']}\n"
        f"🗣️ TTS {usage['tts_chars']} chars -> ₹{costs['tts_cost_inr']}\n"
        f"🖥️ Server -> ₹{costs['server_cost_inr']}\n"
        f"💸 YOUR COST ₹{costs['total_cost_inr']} (₹{costs['your_cost_per_min']}/min)\n"
        f"💳 CUSTOMER BILL ₹{costs['client_price_inr']} (₹{costs['client_bill_per_min']}/min)\n"
        f"🤑 PROFIT ₹{costs['your_profit_inr']} [{'PROFIT ✅' if costs['is_profit'] else 'LOSS ⚠️'}]\n"
        + "=" * 64
    )


async def _post_billing(call_id, user_id, agent_id, mode, phone, duration, costs, usage,
                       recording_url, status="completed", turn_timing_ref=None) -> bool:
    # FIX: Use authoritative aggregated billing values, not undefined llm_input variable
    # Authoritative is from turn_timing_ref aggregated_input/output or usage authoritative
    try:
        if turn_timing_ref:
            auth_input = turn_timing_ref.get("aggregated_input", usage.get("llm_input_tokens", 0))
            auth_output = turn_timing_ref.get("aggregated_output", usage.get("llm_output_tokens", 0))
            auth_cached = turn_timing_ref.get("aggregated_cached", 0)
            successful = turn_timing_ref.get("successful_requests", 0)
            failed = turn_timing_ref.get("failed_requests", 0)
        else:
            auth_input = usage.get("llm_input_tokens_authoritative", usage.get("llm_input_tokens", 0))
            auth_output = usage.get("llm_output_tokens_authoritative", usage.get("llm_output_tokens", 0))
            auth_cached = usage.get("llm_cached_input_tokens", 0)
            successful = usage.get("successful_requests", 0)
            failed = usage.get("failed_requests", 0)
    except Exception:
        auth_input = usage.get("llm_input_tokens", 0)
        auth_output = usage.get("llm_output_tokens", 0)
        auth_cached = 0
        successful = 0
        failed = 0
    headers = {"Content-Type": "application/json"}
    if BILLING_INTERNAL_TOKEN:
        headers["X-Internal-Token"] = BILLING_INTERNAL_TOKEN
    payload = {
        "callId": call_id,
        "userId": user_id,
        "agentId": agent_id,
        "mode": mode,
        "phone": phone,
        "duration": duration,
        "costs": costs,
        "usage": {
            "sttSeconds": round(usage["user_speech_seconds"], 1),
            "ttsChars": usage["tts_chars"],
            "llmInputTokens": auth_input,
            "llmOutputTokens": auth_output,
            "llmInputTokensAuthoritative": auth_input,
            "llmOutputTokensAuthoritative": auth_output,
            "llmCachedTokens": auth_cached,
            "successfulRequests": successful,
            "failedRequests": failed,
            "totalInputTokens": auth_input,
            "totalCachedTokens": auth_cached,
            "totalOutputTokens": auth_output,
            "totalLlmCost": costs.get("total_cost", 0) if isinstance(costs, dict) else 0,
        },
        "recordingUrl": recording_url,
        "status": status,
        "transcripts": usage["transcripts"][-30:],
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{BILLING_BACKEND_URL}/api/billing/log",
                                    json=payload, headers=headers, timeout=8) as resp:
                body = await resp.text()
                logger.info(f"✅ Billing posted HTTP {resp.status} for call {call_id} — billed ₹{costs['client_price_inr']} — backend will deduct wallet")
                if resp.status >= 400:
                    logger.warning(f"⚠️ Billing POST returned {resp.status}: {body[:500]}")
                    return False
                return True
    except Exception as e:
        logger.warning(f"⚠️ Billing POST failed for call {call_id} to {BILLING_BACKEND_URL}: {e!r} — will fallback to direct DB deduct", exc_info=True)
        return False


def prewarm(proc):
    os.environ["LIVEKIT_AGENTS_LOOP_BLOCK_WARN_MS"] = "0"
    # Silence loop_monitor telemetry in runner processes to avoid slow synchronous console writes
    try:
        logging.getLogger("livekit.agents.telemetry").setLevel(logging.ERROR)
        logging.getLogger("livekit.agents.telemetry.loop_monitor").setLevel(logging.ERROR)
    except Exception:
        pass

    # Production prewarm: VAD + Google auth + hyphenator + async_toolset off loop
    # Fixes: 406ms onnxruntime VAD, 176ms Google auth crypt, 256ms hyphenation re.split, 101ms async_toolset import
    # VAD 0.20/0.30/0.20/0.55 production-tuned for 300-400ms speech_end->STT_final + less CPU
    # VAD tuning comes from agent_builder._vad_tuning() (env-driven) so the
    # prewarmed model and the one build_vad() would create are identical — this
    # cache IS what build_vad() returns, so a hardcoded copy here would silently
    # override any VOICE_VAD_* / VOICE_ENDPOINTING_* tuning.
    global _VAD_CACHE
    try:
        from app.agents.agent_builder import _vad_tuning as _vad_params
        vad = silero.VAD.load(**_vad_params())
        with _VAD_CACHE_LOCK:
            _VAD_CACHE = vad
        # Also set agent_builder cache to avoid 406ms block in build_vad
        try:
            from app.agents import agent_builder as _ab
            with _ab._VAD_CACHE_LOCK_AGENT:
                _ab._VAD_CACHE_AGENT = vad
            logger.info("🔥 Prewarm: VAD hot cached in both worker and agent_builder (avoids 406ms onnxruntime block)")
        except Exception as _e:
            logger.info(f"🔥 Prewarm: VAD hot (production 0.20/0.30/0.20/0.55) - cached in worker, agent_builder cache set failed: {_e}")
    except Exception as e:
        logger.warning(f"VAD prewarm failed: {e}")
    
    # Prewarm Google auth crypt off loop to avoid 176ms and 198ms blocks
    try:
        import google.auth.crypt._cryptography_rsa as _crypt_rsa
        import google.auth._service_account_info as _sa_info
        import google.auth._default as _auth_default
        import google.oauth2.credentials as _oauth2_creds
        import google.oauth2.service_account as _oauth2_sa
        logger.info("🔥 Prewarm: Google auth crypt + oauth2.credentials imported (avoids 176ms and 198ms blocks during TTS)")
    except Exception as e:
        logger.debug(f"Google auth prewarm failed: {e}")
    
    # Prewarm hyphenator off loop to avoid 256ms/391ms block at re.split in _basic_hyphenator
    try:
        from livekit.agents.tokenize._basic_hyphenator import Hyphenator, PATTERNS, EXCEPTIONS
        Hyphenator(PATTERNS, EXCEPTIONS)
        logger.info("🔥 Prewarm: Hyphenator hot (avoids 256ms/391ms re.split block in transcription synchronizer)")
    except Exception as e:
        logger.debug(f"Hyphenator prewarm failed: {e}")
    
    # Prewarm async_toolset import off loop to avoid 101ms block
    try:
        import livekit.agents.llm.async_toolset as _async_toolset
        logger.info("🔥 Prewarm: async_toolset imported (avoids 101ms import block)")
    except Exception as e:
        logger.debug(f"async_toolset prewarm failed: {e}")

    # Prewarm Pydantic ChatMessage and ChatContext validation schemas off the agent loop.
    # In Pydantic v2, ChatMessage.__init__ triggers model_rebuild() upon first invocation.
    # On Windows, this took 7259ms inside entrypoint. Prewarming here compiles it off-loop.
    try:
        from app.agents.agent_builder import warm_agent_builder_schemas
        warm_agent_builder_schemas()
    except Exception as e:
        logger.debug(f"ChatMessage prewarm failed: {e}")

    try:
        from livekit.agents.voice import Agent as _VoiceAgent, room_io as _room_io
        _ = _room_io.RoomOptions(close_on_disconnect=False, delete_room_on_close=False)
        logger.info("🔥 Prewarm: Voice Agent & RoomOptions imported")
    except Exception as e:
        logger.debug(f"Voice Agent prewarm failed: {e}")

    # Warm the Google TTS *credentials* before the first customer response so the
    # ~163-198ms JSON/RSA parse never lands on the agent event loop.
    #
    # This deliberately does NOT build a TextToSpeechAsyncClient any more. The old
    # version created a throwaway TTS and called _ensure_client() inside
    # asyncio.new_event_loop() + loop.close(); a grpc.aio channel remembers the
    # loop it was created on, so any client warmed that way is bound to a dead
    # loop and later synthesize() calls fail with
    # `RuntimeError: Event loop is closed`. The async client must be created on
    # the loop that uses it (the plugin does that lazily in _ensure_client()).
    # Everything that IS loop-independent — credential parsing and the grpc/google
    # module imports — is warmed here instead, in a thread so prewarm() itself
    # never blocks.
    try:
        import os as _os_tts
        from app.config import GOOGLE_APPLICATION_CREDENTIALS as _gac_default
        creds = _os_tts.getenv("GOOGLE_APPLICATION_CREDENTIALS") or _gac_default

        def _prewarm_google_tts():
            try:
                warmed = warm_google_credentials(creds)
                # Import the transport machinery so the on-loop client build is
                # just channel creation (module import cost paid off loop).
                try:
                    import grpc.aio  # noqa: F401
                    import google.api_core.grpc_helpers_async  # noqa: F401
                    from google.cloud import texttospeech  # noqa: F401
                except Exception:
                    pass
                if warmed:
                    logger.info(
                        "🔥 Prewarm: Google TTS credentials + grpc.aio/texttospeech imports warm "
                        "(async client is built on the agent loop — never off-loop)"
                    )
            except Exception as _e:
                logger.debug(f"Google TTS credential prewarm thread failed: {_e!r}")

        if creds and _os_tts.path.exists(creds):
            import threading as _thr
            t = _thr.Thread(target=_prewarm_google_tts, daemon=True)
            t.start()
            t.join(timeout=3)  # Wait up to 3s for prewarm
            logger.info("🔥 Prewarm: Google TTS credential prewarm attempted (off loop, thread)")
        else:
            logger.info("🔥 Prewarm: no Google credentials file found, skipping TTS credential prewarm")
    except Exception as e:
        logger.debug(f"Google TTS prewarm failed: {e!r}")
    
    # NOTE: DB prewarm removed - it used asyncio.run() which closes event loop, causing
    # "Event loop is closed" on next Prisma call -> 1.73s retry. DB is cached per process
    # via the _DB_INIT_DONE global and connected ON the agent loop in entrypoint() (the
    # 1359ms SSL block that pushed it off-loop is fixed by the cached SSL context patch).


def _worker_load(worker) -> float:
    """Calculate load based on actual active jobs rather than Windows event-loop jitter.

    Default CPU-sampling load_fnc in livekit-agents spikes to 1.0 on Windows due to
    asyncio IOCP polling (GetQueuedCompletionStatus) and synchronous console I/O,
    falsely marking the worker as 'at full capacity, marking as unavailable' and
    dropping incoming calls.
    """
    try:
        active = len(getattr(worker, "active_jobs", []) or [])
        max_jobs = int(os.getenv("MAX_CONCURRENT_CALLS", "10"))
        return min(float(active) / float(max_jobs), 1.0)
    except Exception:
        return 0.0


if __name__ == "__main__":
    os.environ["LIVEKIT_AGENTS_LOOP_BLOCK_WARN_MS"] = "0"
    from livekit.agents import WorkerOptions, cli

    # Silence runaway loop_monitor telemetry warnings that trigger synchronous console writes
    logging.getLogger("livekit.agents.telemetry").setLevel(logging.ERROR)
    logging.getLogger("livekit.agents.telemetry.loop_monitor").setLevel(logging.ERROR)

    # livekit-agents v1 ships a Typer CLI that requires a subcommand
    # (start / dev / console). Default to `start` so that
    # `python -m app.agents.worker` boots a production worker out of the box.
    if len(sys.argv) == 1:
        sys.argv.append("start")

    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            prewarm_fnc=prewarm,
            # Two idle processes so a call that is still winding down cannot
            # block the next one. One stuck job used to make "change agent and
            # call again" look like the worker had silently stopped.
            num_idle_processes=int(os.getenv("NUM_IDLE_PROCESSES", "2")),
            shutdown_process_timeout=float(os.getenv("SHUTDOWN_PROCESS_TIMEOUT", "12")),
            agent_name=WORKER_AGENT_NAME,
            # Windows doesn't support the default "forkserver" context; "spawn"
            # is portable and works on Windows/macOS/Linux alike.
            multiprocessing_context="spawn",
            load_fnc=_worker_load,
            load_threshold=float(os.getenv("WORKER_LOAD_THRESHOLD", "0.95")),
        )
    )
