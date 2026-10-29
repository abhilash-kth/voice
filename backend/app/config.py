"""
Central configuration for the Voice Agent SaaS backend.

Loads a `.env` file (if present) and exposes typed settings. We intentionally
avoid heavy dependencies here so this module imports cleanly everywhere.
"""
from __future__ import annotations

import os
import json
from pathlib import Path

# ---------------------------------------------------------------------------
# .env loading (no python-dotenv dependency needed)
# ---------------------------------------------------------------------------
def _load_dotenv() -> None:
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ[key.strip()] = value.strip().strip('"').strip("'")


_load_dotenv()


def _env_int(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    if raw.lower() in ("true", "yes", "on"):
        return 1
    if raw.lower() in ("false", "no", "off"):
        return 0
    try:
        return int(raw)
    except ValueError:
        return default


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent          # backend/
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# LiveKit
# ---------------------------------------------------------------------------
LIVEKIT_URL = os.getenv("LIVEKIT_URL", "ws://localhost:7880")
LIVEKIT_API_KEY = os.getenv("LIVEKIT_API_KEY", "")
LIVEKIT_API_SECRET = os.getenv("LIVEKIT_API_SECRET", "")

# ---------------------------------------------------------------------------
# Default provider credentials (used as fallbacks / examples)
# ---------------------------------------------------------------------------
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY", "")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", GOOGLE_API_KEY)
SARVAM_API_KEY = os.getenv("SARVAM_API_KEY", "")
CARTESIA_API_KEY = os.getenv("CARTESIA_API_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
# OpenRouter routes many providers through one OpenAI-compatible endpoint. Set
# OPENROUTER_API_KEY (get one at openrouter.ai/keys) and optionally LLM_MODEL to
# pick the model that `openrouter` providers use by default.
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "")
# Dynamic-catalog providers (Super Admin can also store these in ProviderCredential).
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
QWEN_API_KEY = os.getenv("QWEN_API_KEY", "")
FISH_AUDIO_API_KEY = os.getenv("FISH_AUDIO_API_KEY", "")
MINIMAX_API_KEY = os.getenv("MINIMAX_API_KEY", "")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
GOOGLE_APPLICATION_CREDENTIALS = os.getenv(
    "GOOGLE_APPLICATION_CREDENTIALS", os.path.join(str(BASE_DIR), "google-key.json")
)

# ---------------------------------------------------------------------------
# Billing / pricing defaults
# ---------------------------------------------------------------------------
# The customer is charged the *actual* provider cost (LLM + STT + TTS +
# telephony) plus a platform margin. The margin is set here in `.env` so you
# (the platform owner) control it — clients never enter a price.
PROFIT_MARGIN_PERCENT = float(os.getenv("PROFIT_MARGIN_PERCENT", "50"))
# Minimum per-call price charged to the customer (guards against a free call).
MIN_CLIENT_PRICE = float(os.getenv("MIN_CLIENT_PRICE", "1.00"))
SERVER_COST_PER_MIN = float(os.getenv("SERVER_COST_PER_MIN", "0.05"))
# Enterprise minimum billed duration per mode (seconds). 0 = bill actual time.
ASSISTANT_MIN_BILL_SECONDS = int(os.getenv("ASSISTANT_MIN_BILL_SECONDS", "0"))
ANNOUNCEMENT_MIN_BILL_SECONDS = int(os.getenv("ANNOUNCEMENT_MIN_BILL_SECONDS", "0"))
WALLET_TOPUP_AMOUNT = json.loads(
    os.getenv("WALLET_TOPUP_AMOUNTS", "[100, 250, 500, 1000]")
)

# ---------------------------------------------------------------------------
# Database (Prisma → Neon/Postgres, or local SQLite)
# ---------------------------------------------------------------------------
# Prisma reads DATABASE_URL at runtime. Use a plain postgresql:// URL (no driver
# suffix). For a local demo, set the schema datasource to "sqlite" and use:
#   DATABASE_URL=file:./data/app.db
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/neondb")

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret-change-me")
ACCESS_TOKEN_MINUTES = int(os.getenv("ACCESS_TOKEN_MINUTES", str(60 * 24 * 7)))

# ---------------------------------------------------------------------------
# Agent behaviour
# ---------------------------------------------------------------------------
ALLOW_BROWSER_CALL = os.getenv("ALLOW_BROWSER_CALL", "true").lower() == "true"
# Seed/fallback only; runtime reads TelephonyConfig.defaultSipTrunkId.
DEFAULT_SIP_TRUNK_ID = os.getenv("SIP_TRUNK_ID", "")

# ---------------------------------------------------------------------------
# Self-service telephony marketplace (VoiceLink reseller API + LiveKit SIP)
# ---------------------------------------------------------------------------
# PANEL-MANAGED AT RUNTIME: services/telephony_settings.py reads the
# TelephonyConfig DB row managed from Super Admin -> Telephony -> Settings.
# The env values below only seed that row on first use (and act as an
# emergency fallback if the row is unavailable). Once the panel row exists,
# changing these env values has no effect on the marketplace.
# Reseller API. Prefer a long-lived Sanctum token; username/password login is
# the fallback. These credentials are operator-only and never leave the API.
VOICELINK_API_BASE_URL = os.getenv(
    "VOICELINK_API_BASE_URL", "https://app.voicelink.co.in/api/v1").rstrip("/")
VOICELINK_API_TOKEN = (
    os.getenv("VOICELINK_API_TOKEN", "") or os.getenv("VOICELINK_AUTH_TOKEN", "")
).strip()
VOICELINK_USERNAME = os.getenv("VOICELINK_USERNAME", "")
VOICELINK_PASSWORD = os.getenv("VOICELINK_PASSWORD", "")
VOICELINK_SIP_HOST = os.getenv("VOICELINK_SIP_HOST", "sip.voicelink.co.in")
VOICELINK_SIP_PORT = _env_int("VOICELINK_SIP_PORT", 3300)
# Carrier tech prefix prepended to the dialled digits on this reseller
# account (proven format: <prefix><91><10-digit>). Stored per number too.
VOICELINK_TECH_PREFIX = os.getenv("VOICELINK_TECH_PREFIX", "45454")
VOICELINK_TRANSPORT_TYPE = _env_int("VOICELINK_TRANSPORT_TYPE", 1)  # 1=UDP
VOICELINK_AUDIO_FORMATS = [
    f.strip() for f in os.getenv("VOICELINK_AUDIO_FORMATS", "alaw,ulaw").split(",") if f.strip()
]
VOICELINK_WALLET_BYPASS = _env_int("VOICELINK_WALLET_BYPASS", 0)
VOICELINK_KYC_TERMS_URL = os.getenv("VOICELINK_KYC_TERMS_URL", "")
VOICELINK_KYC_REDIRECT_HOSTS = [
    h.strip().lower()
    for h in os.getenv("VOICELINK_KYC_REDIRECT_HOSTS", "").split(",") if h.strip()
]
# VoiceLink's documented final-submit lists no client_id parameter. Keep this
# OFF until VoiceLink confirms in writing that final-submit acts only on the
# supplied client_id; earlier KYC steps are explicitly client-scoped.
VOICELINK_CLIENT_KYC_FINALIZE_VERIFIED = (
    os.getenv("VOICELINK_CLIENT_KYC_FINALIZE_VERIFIED", "0") == "1"
)
# Public SIP destination VoiceLink trunks point at (our LiveKit SIP service).
LIVEKIT_SIP_HOST = os.getenv("LIVEKIT_SIP_HOST", "kvoice.duckdns.org")
LIVEKIT_SIP_PORT = _env_int("LIVEKIT_SIP_PORT", 5060)
# Browser-facing URLs used for the DigiLocker return redirect.
FRONTEND_URL = (
    os.getenv("FRONTEND_URL", "") or os.getenv("APP_PUBLIC_URL", "")
    or "http://localhost:3000"
).rstrip("/")
PUBLIC_API_URL = os.getenv("PUBLIC_API_URL", "").rstrip("/")
# Recording (LiveKit Egress). Set these for self-hosted recording.
EGRESS_ENABLED = os.getenv("EGRESS_ENABLED", "true").lower() == "true"
EGRESS_S3_BUCKET = os.getenv("EGRESS_S3_BUCKET", "")       # e.g. voice-recordings
EGRESS_S3_ENDPOINT = os.getenv("EGRESS_S3_ENDPOINT", "")   # for MinIO/S3-compatible
EGRESS_S3_REGION = os.getenv("EGRESS_S3_REGION", "us-east-1")
EGRESS_PUBLIC_BASE_URL = os.getenv("EGRESS_PUBLIC_BASE_URL", "")  # where recordings are served from

# Shared secret the worker sends when posting billing (empty = open, demo only)
BILLING_INTERNAL_TOKEN = os.getenv("BILLING_INTERNAL_TOKEN", "")

# ---------------------------------------------------------------------------
# Logging (Non-blocking QueueHandler + QueueListener)
# ---------------------------------------------------------------------------
_log_listener = None
_log_queue = None


def purge_sync_root_handlers(job_proc: bool = False) -> None:
    """Keep exactly ONE non-blocking root handler.

    LiveKit's CLI adds its own synchronous JSON ``StreamHandler`` to the root
    logger AFTER our setup (supervisor process), and every spawned job process
    adds LiveKit's IPC ``LogQueueHandler`` next to ours. Without this purge
    every record is printed 2–3 times (one JSON line + one plain line), and
    the synchronous Windows-console ``stream.write`` blocks the asyncio loop
    for 150–350ms+ — the ``event loop blocked ... in emit`` warnings that
    starve audio/turn handling.

    ``job_proc=True`` (called from the worker's ``prewarm``): keep ONLY
    LiveKit's IPC forwarder so job logs travel to the supervisor and are
    printed there exactly once. Anywhere else: keep our async QueueHandler.
    """
    import logging
    from logging.handlers import QueueHandler

    if _log_queue is None:
        return
    root = logging.getLogger()
    if job_proc:
        ipc = [h for h in root.handlers if type(h).__name__ == "LogQueueHandler"]
        if ipc:
            if len(root.handlers) != len(ipc):
                root.handlers = ipc
            return
    keep = [h for h in root.handlers if isinstance(h, QueueHandler)]
    if not keep:
        root.handlers = [QueueHandler(_log_queue)]
    elif len(root.handlers) != len(keep):
        root.handlers = keep[:1]


def setup_logging() -> None:
    """Configure non-blocking asynchronous logging using QueueHandler and QueueListener.

    Synchronous StreamHandler.emit calls (stream.write) can block the asyncio event
    loop for 200ms–1300ms on Windows console, triggering severe WebRTC and IPC watchdog
    starvation. Using QueueHandler places log records into an in-memory queue in microseconds,
    while a dedicated background thread (QueueListener) performs the actual I/O writes.

    Safe to call repeatedly: later calls only purge duplicate root handlers.
    """
    global _log_listener, _log_queue
    import logging
    import queue
    import atexit
    import sys
    from logging.handlers import QueueHandler, QueueListener

    if _log_listener is not None:
        purge_sync_root_handlers()
        return

    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    root = logging.getLogger()
    root.setLevel(level)

    _log_queue = queue.SimpleQueue()
    stream_handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    stream_handler.setFormatter(formatter)
    stream_handler.setLevel(level)

    _log_listener = QueueListener(_log_queue, stream_handler, respect_handler_level=True)
    _log_listener.start()
    atexit.register(_log_listener.stop)

    # Route root logger to the non-blocking QueueHandler
    root.handlers = [QueueHandler(_log_queue)]


setup_logging()
