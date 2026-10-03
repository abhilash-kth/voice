from __future__ import annotations

import time
import asyncio
import logging
import os
import re
from typing import Any, Optional

from ...models import AgentConfig, KnowledgeBase
from ...config import (
    GROQ_API_KEY,
    OPENAI_API_KEY,
    DEEPGRAM_API_KEY,
    GOOGLE_APPLICATION_CREDENTIALS,
    OPENROUTER_API_KEY,
    GEMINI_API_KEY,
    SARVAM_API_KEY,
    CARTESIA_API_KEY,
    ANTHROPIC_API_KEY,
    QWEN_API_KEY,
    FISH_AUDIO_API_KEY,
    MINIMAX_API_KEY,
)

logger = logging.getLogger("voice-agent-saas-agent-builder")


logger = logging.getLogger("voice-agent-saas-agent-builder")


def _provider_api_key(kind: str, slug: str, env_fallback: str) -> str:
    """Provider API key resolution: Super Admin's encrypted DB credential first,
    then the .env fallback. Sync + safe (reads the in-process snapshot)."""
    try:
        from ...services import config_store
        key = config_store.get_api_key(kind, slug)
        if key:
            return key
    except Exception:
        pass
    return env_fallback or ""


def _provider_base_url(kind: str, slug: str) -> str:
    try:
        from ...services import config_store
        return config_store.provider_base_url(kind, slug)
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Google TTS voice normalisation
# ---------------------------------------------------------------------------
# Google's streaming_synthesize endpoint rejects every Wavenet/Standard/Neural2
# voice with ``400 Currently, only Chirp 3: HD voices are supported``. Chirp 3: HD
# uses the "<locale>-Chirp3-HD-<name>" form with 8 multilingual speakers (Leda,
# Kore, Zephyr, Aoede, Charon, Fenrir, Orus, Puck) available across all supported
# locales. So any legacy voice stored in an agent config is transparently mapped
