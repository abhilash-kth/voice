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
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
# OpenRouter routes many providers through one OpenAI-compatible endpoint. Set
# OPENROUTER_API_KEY (get one at openrouter.ai/keys) and optionally LLM_MODEL to
# pick the model that `openrouter` providers use by default.
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "")
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
DEFAULT_SIP_TRUNK_ID = os.getenv("SIP_TRUNK_ID", "")
# Recording (LiveKit Egress). Set these for self-hosted recording.
EGRESS_ENABLED = os.getenv("EGRESS_ENABLED", "true").lower() == "true"
EGRESS_S3_BUCKET = os.getenv("EGRESS_S3_BUCKET", "")       # e.g. voice-recordings
EGRESS_S3_ENDPOINT = os.getenv("EGRESS_S3_ENDPOINT", "")   # for MinIO/S3-compatible
EGRESS_S3_REGION = os.getenv("EGRESS_S3_REGION", "us-east-1")
EGRESS_PUBLIC_BASE_URL = os.getenv("EGRESS_PUBLIC_BASE_URL", "")  # where recordings are served from

# Shared secret the worker sends when posting billing (empty = open, demo only)
BILLING_INTERNAL_TOKEN = os.getenv("BILLING_INTERNAL_TOKEN", "")

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
def setup_logging() -> None:
    import logging
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


setup_logging()
