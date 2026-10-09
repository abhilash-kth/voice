from __future__ import annotations

import logging
from typing import Optional

from ...models import AgentConfig

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
    """Speed control is TTS-internal: no user/admin-facing speed is sent to
    providers (None = untouched → provider default). The config column and the
    tts_speed helpers are kept for possible future internal use but are never
    injected into provider calls.
    """
    return None


