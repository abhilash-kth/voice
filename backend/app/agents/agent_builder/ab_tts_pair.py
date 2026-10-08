from __future__ import annotations

import logging
from typing import Any

from ...models import AgentConfig
from ...config import (
    GROQ_API_KEY,
    OPENAI_API_KEY,
    GOOGLE_APPLICATION_CREDENTIALS,
    OPENROUTER_API_KEY,
    SARVAM_API_KEY,
    CARTESIA_API_KEY,
    FISH_AUDIO_API_KEY,
    MINIMAX_API_KEY,
)

logger = logging.getLogger("voice-agent-saas-agent-builder")


# cross-module imports (auto-generated)
from .ab_config_access import _provider_api_key, _provider_base_url
from .ab_tts_select import _normalized_voice_speed, _tts_adapter_for_pair
from .ab_voices import _resolve_tts_voice, locale_for_language

def _build_tts_from_pair(pair, cfg: AgentConfig) -> Any:
    sel = pair
    overrides = sel.config or {}
    _adapter = _tts_adapter_for_pair(pair)
    try:
        from ...services import tts_speed as _tts_speed_mod
        overrides = _tts_speed_mod.apply_voice_speed(overrides, _adapter, _normalized_voice_speed(cfg))
    except Exception:
        pass

    if _adapter == "openai_compat_tts":
        # DB-driven OpenAI-compatible TTS providers (OpenAI, Fish Voice, MiniMax,
        # and any future such adapter added from the Super Admin panel). Model,
        # voice and base_url come from provider config / DB row metadata.
        from livekit.plugins.openai import TTS as _CompatTTS
        from ...services import config_store as _cs
        rows = [m for m in (_cs.get_snapshot().models.get("tts") or [])
                if m.get("catalogId") == sel.id]
        row_meta = (rows[0].get("_meta") or {}) if rows else {}
        slug = rows[0].get("providerSlug") if rows else ""
        model = overrides.get("model") or (rows[0].get("modelId") if rows else "") or "tts-1"
        voice = overrides.get("voice") or row_meta.get("voice") or ""
        if not voice:
            raise RuntimeError(
                f"TTS provider '{sel.id}' needs a voice (set `voice` in the agent's tts config)."
            )
        key_map = {"fish": FISH_AUDIO_API_KEY, "minimax": MINIMAX_API_KEY, "openai": OPENAI_API_KEY}
        env_default = key_map.get((slug or ""), OPENAI_API_KEY)
        api_key = overrides.get("api_key") or _provider_api_key("tts", slug or sel.id, env_default)
        if not api_key:
            raise RuntimeError(
                f"TTS provider '{sel.id}' needs an API key (Super Admin panel or the provider's env var)."
            )
        base_url = overrides.get("base_url") or _provider_base_url("tts", slug or sel.id) or None
        kwargs: dict = dict(model=model, voice=voice, api_key=api_key)
        if base_url:
            kwargs["base_url"] = base_url
        for opt in ("speed", "instructions"):
            if overrides.get(opt) is not None:
                kwargs[opt] = overrides[opt]
        logger.info(f"🎙️ OpenAI-compatible TTS: provider={slug or sel.id} model={model} base_url={base_url}")
        return _CompatTTS(**kwargs)

    if sel.id.startswith("google"):
        from livekit.plugins.google import TTS
        configured_language = (getattr(cfg, "language", "hi") or "hi").lower()
        # Honour the agent's language for every Indic locale we support (was
        # hard-coded to hi-IN/en-IN, so a Tamil agent would have spoken Hindi).
        default_language = locale_for_language(configured_language)
        language = overrides.get("language", default_language)
        gender = (getattr(cfg, "gender", "") or overrides.get("gender") or "female").lower()
        voice = _resolve_tts_voice(language, overrides.get("voice"), gender)
        kwargs = dict(
            voice_name=voice,
            language=language,
            credentials_file=overrides.get("credentials_file") or GOOGLE_APPLICATION_CREDENTIALS or None,
        )
        if overrides.get("speaking_rate") is not None:
            # normalized user voice_speed mapped per-provider (services/tts_speed.py)
            kwargs["speaking_rate"] = float(overrides["speaking_rate"])
        logger.info(f"🎙️ Google TTS: voice={voice} language={language} gender={gender}")
        try:
            return TTS(**kwargs)
        except TypeError as e:
            logger.warning(f"⚠️ Google TTS rejected {sorted(kwargs)} ({e}); retrying minimal")
            return TTS(
                voice_name=voice,
                language=language,
                credentials_file=overrides.get("credentials_file") or GOOGLE_APPLICATION_CREDENTIALS or None,
            )

    if sel.id.startswith("sarvam"):
        try:
            from livekit.plugins.sarvam import TTS as SarvamTTS
        except ImportError as e:
            raise RuntimeError(
                f"Sarvam TTS needs livekit-plugins-sarvam ({e}). Run "
                "`pip install livekit-plugins-sarvam>=1.4.1` in the worker venv and "
                "set SARVAM_API_KEY in backend/.env."
            ) from e
        api_key = overrides.get("api_key") or _provider_api_key("tts", "sarvam", SARVAM_API_KEY)
        if not api_key:
            raise RuntimeError(
                "Sarvam TTS needs a Sarvam API key (Super Admin panel or SARVAM_API_KEY env)."
            )
        configured_language = (getattr(cfg, "language", "hi") or "hi").lower()
        target_language = overrides.get("language") or locale_for_language(configured_language)
        # Gender selects the speaker unless one was chosen explicitly.
        gender = (getattr(cfg, "gender", "") or overrides.get("gender") or "female").lower()
        model = overrides.get("model", "bulbul:v3")
        # Sarvam retired bulbul:v2 SERVER-SIDE (every request now errors with
        # "400: Model 'bulbul:v2' has been deprecated. Please use 'bulbul:v3'
        # instead."). Saved v2 configs must keep speaking — upgrade loudly and
        # remap v2-only speakers to their closest bulbul:v3 counterparts.
        if model == "bulbul:v2":
            logger.warning(
                "⚠️ Sarvam bulbul:v2 is RETIRED server-side (API returns 400 'deprecated'). "
                "Upgrading this agent's TTS to bulbul:v3 with the closest v3 speaker. "
                "Open the agent and pick 'Sarvam Bulbul v3' to silence this warning."
            )
            model = "bulbul:v3"
        _v2_to_v3_speaker = {
            "anushka": "priya", "vidya": "kavya", "manisha": "ritu",
            "abhilash": "shubh", "hitesh": "ratan", "karun": "aditya", "arya": "rohan",
        }
        default_speakers = {"female": "priya", "male": "shubh", "neutral": "priya"}
        speaker = overrides.get("voice") or overrides.get("speaker") or default_speakers.get(gender, "priya")
        if speaker and speaker.lower() in _v2_to_v3_speaker:
            speaker = _v2_to_v3_speaker[speaker.lower()]
        kwargs = dict(
            model=model,
            target_language_code=target_language,
            speaker=speaker,
            speech_sample_rate=int(overrides.get("speech_sample_rate", 22050)),
            api_key=api_key,
        )
        if overrides.get("pace") is not None:
            kwargs["pace"] = float(overrides["pace"])
        if overrides.get("pitch") is not None:
            kwargs["pitch"] = float(overrides["pitch"])
        logger.info(
            f"🎙️ Sarvam TTS: model={model} speaker={speaker} "
            f"target_language_code={target_language} gender={gender}"
        )
        try:
            return SarvamTTS(**kwargs)
        except TypeError as e:
            # Plugin version skew: retry with the minimal documented signature.
            logger.warning(f"⚠️ Sarvam TTS rejected {sorted(kwargs)} ({e}); retrying minimal")
            return SarvamTTS(
                model=model,
                target_language_code=target_language,
                speaker=speaker,
                api_key=api_key,
            )

    if sel.id.startswith("cartesia"):
        try:
            from livekit.plugins.cartesia import TTS as CartesiaTTS
        except ImportError as e:
            raise RuntimeError(
                f"Cartesia TTS needs livekit-plugins-cartesia ({e}). Run "
                "`pip install livekit-plugins-cartesia>=1.7.1` in the worker venv and "
                "set CARTESIA_API_KEY in backend/.env."
            ) from e
        api_key = overrides.get("api_key") or _provider_api_key("tts", "cartesia", CARTESIA_API_KEY)
        if not api_key:
            raise RuntimeError(
                "Cartesia TTS needs a Cartesia API key (Super Admin panel or CARTESIA_API_KEY env)."
            )
        model = overrides.get("model", "sonic-3")
        configured_language = (getattr(cfg, "language", "hi") or "hi").lower()
        # Cartesia takes bare ISO-639-1 codes ("hi", "en"), not BCP-47 locales, so
        # strip the region from the shared locale map: "hi-IN"→"hi", "en-US"→"en",
        # "multi"→"hi" (Sonic 3 is natively code-mixed, so Hinglish is fine).
        target_language = overrides.get("language") or locale_for_language(configured_language).split("-")[0]
        # Gender selects the voice unless one was chosen explicitly. Cartesia voice
        # ids are account-specific UUIDs; the defaults below are the operator's
        # Indian-accent voices (add more in backend/app/catalog.py options.voice).
        # An explicit `voice` in the agent's tts config always wins.
        gender = (getattr(cfg, "gender", "") or overrides.get("gender") or "female").lower()
        _default_voices = {
            "female": "4459a9a5-69d6-4680-b970-e13dc51845b6",
            "male": "cb9c954d-bcaa-43ed-82bf-aeb5e88a3cb5",
            "neutral": "4459a9a5-69d6-4680-b970-e13dc51845b6",
        }
        voice = overrides.get("voice") or _default_voices.get(gender, _default_voices["female"])
        kwargs = dict(
            model=model,
            language=target_language,
            voice=voice,
            api_key=api_key,
        )
        if overrides.get("speed") is not None:
            # sonic-3 accepts a float 0.6–2.0 or the preset words
            speed = overrides["speed"]
            kwargs["speed"] = speed if isinstance(speed, str) else float(speed)
        if overrides.get("emotion"):
            kwargs["emotion"] = overrides["emotion"]
        logger.info(
            f"🎙️ Cartesia TTS: model={model} voice={str(voice)[:8]}… "
            f"language={target_language} gender={gender}"
        )
        try:
            return CartesiaTTS(**kwargs)
        except TypeError as e:
            # Plugin version skew: retry with the minimal documented signature.
            logger.warning(f"⚠️ Cartesia TTS rejected {sorted(kwargs)} ({e}); retrying minimal")
            return CartesiaTTS(model=model, language=target_language, voice=voice, api_key=api_key)

    if sel.id.startswith("elevenlabs"):
        from ...config import ELEVENLABS_API_KEY as _EL_ENV
        from livekit.plugins.elevenlabs import TTS
        kwargs = dict(
            voice_id=overrides.get("voice", "pNInz6obpgDQGcFmaJgB"),
            model=overrides.get("model", "eleven_multilingual_v2"),
            language=overrides.get("language", "en" if (getattr(cfg, "language", "hi") or "hi").lower().startswith("en") else "hi"),
        )
        _el_key = overrides.get("api_key") or _provider_api_key("tts", "elevenlabs", _EL_ENV)
        if _el_key:
            kwargs["api_key"] = _el_key
        return TTS(**kwargs)

    if sel.id.startswith("openrouter"):
        import os as _os
        from livekit.plugins.openai import TTS
        from ...catalog import get_provider
        cat = get_provider("tts", sel.id) or {}
        model = (
            overrides.get("model")
            or _os.getenv("LLM_TTS_MODEL", "")
            or cat.get("model")
            or "deepgram/flux-tts:free"
        )
        api_key = overrides.get("api_key") or _provider_api_key("tts", "openrouter", OPENROUTER_API_KEY)
        if not api_key:
            raise RuntimeError(
                "OpenRouter TTS needs an OpenRouter API key (Super Admin panel or OPENROUTER_API_KEY env)."
            )
        default_voices = {
            "deepgram/flux-tts:free": "flux-bree-en",
            "hexgrad/kokoro-82m": "af_bella",
            "microsoft/mai-voice-2-flash": "en-US-Harper:MAI-Voice-2",
            "qwen/qwen-audio-3.0-tts-flash": "loongjohn",
        }
        voice = overrides.get("voice") or cat.get("voice") or default_voices.get(model)
        if not voice:
            logger.warning(
                f"⚠️ OpenRouter TTS model '{model}' has no preset voice (it is "
                "voice-cloning only) and no `voice` was set. Falling back to "
                "'deepgram/flux-tts:free' (English) so the call does not fail. "
                "Fix the agent's TTS config with a valid `voice` or pick another "
                "TTS provider."
            )
            model = "deepgram/flux-tts:free"
            voice = "flux-bree-en"
        return TTS(
            model=model,
            voice=voice,
            api_key=api_key,
            base_url=overrides.get("base_url") or "https://openrouter.ai/api/v1",
            response_format=overrides.get("response_format", "mp3"),
        )

    raise ValueError(f"Unsupported TTS provider: {sel.id}")


