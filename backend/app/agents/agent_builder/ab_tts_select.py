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


def _tts_adapter_for_pair(pair) -> str:
    """Resolve the plugin adapter for a TTS pair: DB provider's adapter field
    first (Super Admin can re-map adapters), then the legacy id-prefix mapping."""
    try:
        from ...services import config_store as _cs
        rows = [m for m in (_cs.get_snapshot().models.get("tts") or [])
                if m.get("catalogId") == pair.id]
        if rows:
            slug = rows[0].get("providerSlug") or ""
            prov = (_cs.get_snapshot().providers.get("tts") or {}).get(slug)
            adapter = (prov or {}).get("providerType") or ""
            if adapter:
                return adapter
    except Exception:
        pass
    pid = pair.id or ""
    if pid.startswith("google"):
        return "google"
    if pid.startswith("sarvam"):
        return "sarvam"
    if pid.startswith("cartesia"):
        return "cartesia"
    if pid.startswith("elevenlabs"):
        return "elevenlabs"
    if pid.startswith("openrouter"):
        return "openrouter"
    if pid.startswith(("openai", "fish", "minimax")):
        return "openai_compat_tts"
    return pid.split("_")[0]


def _normalized_voice_speed(cfg: AgentConfig) -> Optional[float]:
    """User voice_speed normalized to the Super Admin's configured range; None
    means 'untouched' (no provider param is sent)."""
    raw = getattr(cfg, "voice_speed", None)
    try:
        from ...services import config_store as _cs, tts_speed
        b = _cs.get_billing()
        return tts_speed.normalize_user_speed(raw, b["voice_speed_min"], b["voice_speed_max"], b["voice_speed_default"])
    except Exception:
        return raw


