from __future__ import annotations

import logging
from typing import Optional


logger = logging.getLogger("voice-agent-saas-agent-builder")


# to a Chirp 3: HD voice for the same locale.
_CHIRP3_VOICES = {
    "female": "Leda",       # alternates: Kore, Zephyr, Aoede
    "male": "Charon",       # alternates: Fenrir, Orus, Puck
    "neutral": "Zephyr",
}

# Agent "language" (dashboard value) -> full BCP-47 locale spoken by Google /
# Sarvam TTS and expected by their STT. Anything unknown falls back to hi-IN so
# legacy two-letter values keep working.
_AGENT_LOCALES = {
    "hi": "hi-IN", "hi-in": "hi-IN", "hi-latn": "hi-IN", "hinglish": "hi-IN",
    "en": "en-IN", "en-in": "en-IN", "en-us": "en-US", "en-gb": "en-GB",
    "mr": "mr-IN", "bn": "bn-IN", "ta": "ta-IN", "te": "te-IN", "kn": "kn-IN",
    "gu": "gu-IN", "ml": "ml-IN", "pa": "pa-IN", "or": "or-IN", "od": "od-IN",
    "ur": "ur-IN", "as": "as-IN",
}


def locale_for_language(agent_language: Optional[str]) -> str:
    """Map the agent's configured language to a locale the TTS engines accept."""
    lang = (agent_language or "hi").strip().lower()
    if lang in _AGENT_LOCALES:
        return _AGENT_LOCALES[lang]
    if lang.startswith("en"):
        return "en-IN"
    if "-" in lang:  # already a full tag like "ta-IN"
        return agent_language  # type: ignore[return-value]
    if lang in ("multi", "multi-lingual", ""):
        return "hi-IN"  # code-mix: speak Hindi, STT still handles mixing
    return "hi-IN"


def _resolve_tts_voice(language: str, raw_voice: Optional[str], gender: str = "female") -> str:
    """Return a voice name that Google's streaming endpoint accepts.

    A voice already set to a Chirp 3 or Gemini name is passed through unchanged.
    An empty value defaults to Chirp 3: HD with the speaker matching the agent's
    gender. Any legacy Wavenet/Standard/Neural2 voice is remapped to a Chirp 3:
    HD voice for the same locale.
    """
    v = (raw_voice or "").strip()
    if v and ("chirp" in v.lower() or "gemini" in v.lower()):
        return v
    speaker = _CHIRP3_VOICES.get((gender or "female").lower(), "Leda")
    if not v:
        return f"{language or 'hi-IN'}-Chirp3-HD-{speaker}"
    # Derive the locale from a legacy voice name like "hi-IN-Wavenet-A"
    parts = v.split("-")
    if len(parts) >= 2 and parts[0] and parts[1]:
        locale = f"{parts[0]}-{parts[1]}"
    else:
        locale = language or "hi-IN"
    return f"{locale}-Chirp3-HD-{speaker}"


# ---------------------------------------------------------------------------
# Provider → plugin construction
# ---------------------------------------------------------------------------
