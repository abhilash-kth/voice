from __future__ import annotations

import logging
from typing import Any

from ...models import AgentConfig
from ...config import (
    GROQ_API_KEY,
)

logger = logging.getLogger("voice-agent-saas-agent-builder")


# cross-module imports (auto-generated)
from .ab_tts_pair import _build_tts_from_pair

def build_tts(cfg: AgentConfig) -> Any:
    primary_pair = getattr(cfg.providers, "tts", None) if hasattr(cfg, "providers") else None
    if not primary_pair:
        from ...models import ProviderPair
        primary_pair = ProviderPair(id="google_wavenet_hi", config={})
    primary = _build_tts_from_pair(primary_pair, cfg)

    fallback_pair = getattr(cfg.providers, "tts_fallback", None)
    if not fallback_pair:
        try:
            fp = getattr(cfg, "fallback_providers", None)
            if fp and getattr(fp, "tts", None):
                fallback_pair = fp.tts
        except Exception:
            pass

    if not fallback_pair:
        return primary
    if fallback_pair.id == primary_pair.id and (fallback_pair.config or {}) == (primary_pair.config or {}):
        return primary

    try:
        fallback = _build_tts_from_pair(fallback_pair, cfg)
        from livekit.agents import tts as tts_agents
        adapter = tts_agents.FallbackAdapter([primary, fallback])
        logger.info(f"🔁 TTS FallbackAdapter armed: primary={primary_pair.id} -> fallback={fallback_pair.id}")
        return adapter
    except Exception as e:
        logger.warning(f"⚠️ Could not build TTS fallback {fallback_pair.id}: {e} — using primary only")
        return primary


