from __future__ import annotations

import logging
import os
from typing import Any

from ...config import (
    GROQ_API_KEY
)

logger = logging.getLogger("voice-agent-saas-agent-builder")


_VAD_CACHE_AGENT = None
_VAD_CACHE_LOCK_AGENT = __import__('threading').Lock()

def _vad_tuning() -> dict:
    """Silero VAD knobs (env-overridable), aligned with the session endpointing
    (VOICE_ENDPOINTING_MIN=0.35). VAD needing MORE silence than the endpointer
    is what produced "stt end of speech received while vad is still in a speech
    segment, flushing vad" — keep them in lock-step here."""
    return {
        # ignore <200ms blips (lip noise, clicks) but keep "haan"/"ok"
        "min_speech_duration": float(os.getenv("VOICE_VAD_MIN_SPEECH", "0.20")),
        # aligned with VOICE_ENDPOINTING_MIN so STT and VAD agree on turn end
        "min_silence_duration": float(os.getenv("VOICE_VAD_MIN_SILENCE", "0.35")),
        "prefix_padding_duration": float(os.getenv("VOICE_VAD_PREFIX_PADDING", "0.20")),
        "activation_threshold": float(os.getenv("VOICE_VAD_THRESHOLD", "0.55")),
    }


def build_vad() -> Any:
    global _VAD_CACHE_AGENT
    # Use cached VAD if available to avoid 406ms onnxruntime block
    try:
        with _VAD_CACHE_LOCK_AGENT:
            if _VAD_CACHE_AGENT is not None:
                logger.info("🔧 VAD cache hit in agent_builder (avoids 406ms onnxruntime block)")
                return _VAD_CACHE_AGENT
    except Exception:
        pass
    from livekit.plugins import silero
    # Production latency fix (eliminate 3-7s outliers):
    # Root cause of outliers: VAD inference slower than realtime 0.4s + job executor unresponsive 1.5s
    # due to CPU overload from silero with low min_speech + high sensitivity + blocking provider build.
    # Also endpointing 0.35/0.7 caused total speech_end->LLM 0.75s min, exceeding 500ms target.
    #
    # Production latency fix (eliminate 3-7s outliers):
    # Root cause: VAD inference slower than realtime 0.407s + job executor unresponsive 1.5s
    # due to CPU overload from blocking provider build + low min_speech causing many wake-ups.
    #
    # New production-tuned VAD (balanced for CPU + latency):
    # - min_speech 0.20s (was 0.12): ignore blips, reduce CPU wake-ups by ~30%, avoid "slower than realtime"
    #   Still catches "haan/ok" (0.3-0.5s) but ignores <200ms noise
    # - min_silence 0.30s (was 0.4): faster speech end detection, target speech_end->STT_final 300-400ms
    #   0.30s is enough for natural Hindi pause (0.3-0.5s mid-sentence) but not too slow
    # - prefix 0.20s (was 0.2): keep context for STT, allows "haan" to be captured fully
    # - threshold 0.55 (was 0.6): slightly more sensitive for soft Hindi, but not too sensitive for noise
    # Combined with STT turn_detection and endpointing 0.20/0.55, total speech_end->LLM ~400-500ms
    # For short "haan/ok" (1-2 words): VAD 0.30s + STT final 200ms + endpointing 0.20 = 0.5s total -> fast
    # For natural pause in Hindi: Deepgram utterance_end 1000ms prevents premature final, endpointing max 0.55 caps
    vad = silero.VAD.load(**_vad_tuning())
    try:
        with _VAD_CACHE_LOCK_AGENT:
            _VAD_CACHE_AGENT = vad
    except Exception:
        pass
    return vad


# ---------------------------------------------------------------------------
# Context-size budgets
#
# Groq's free ("on_demand") tier caps each model at ~8k tokens/minute, and every
# voice turn re-sends the ENTIRE system prompt + chat history. Baking the whole
# knowledge base into the static prompt (the old behaviour) made each LLM request
# 6-7k tokens, so a single turn used most of the minute's budget and back-to-back
# turns / concurrent calls got HTTP 429 — which, with fail-fast retries, silently
# dropped the reply (the caller heard dead air). These char budgets keep the
# static prompt small (~1-2k tokens), and per-turn RAG (see
# on_user_turn_completed) pulls in the specific chunks a question needs.
# Raise the budgets only if you've upgraded the Groq tier or moved to a
# higher-limit provider.
#
# FIX: Budgets are now provider-aware. Groq keeps tiny defaults (to avoid 429s),
# but OpenAI/OpenRouter/etc get large defaults so full system prompt (contact
# numbers, etc) is preserved. User's log showed 5187->1000 truncation dropping
# contact info, causing "Mere paas exact phone numbers nahi hain".
# ---------------------------------------------------------------------------
