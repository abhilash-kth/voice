from __future__ import annotations

import logging
import os
from typing import Any

from ...models import AgentConfig
from ...config import(
    DEEPGRAM_API_KEY,
    GOOGLE_APPLICATION_CREDENTIALS,
    SARVAM_API_KEY,
)

logger = logging.getLogger("voice-agent-saas-agent-builder")


# cross-module imports (auto-generated)
from .ab_config_access import _provider_api_key
from .ab_voices import locale_for_language

def _build_stt_from_pair(pair, cfg: AgentConfig) -> Any:
    sel = pair
    overrides = sel.config or {}

    if sel.id.startswith("sarvam"):
        try:
            from livekit.plugins.sarvam import STT as SarvamSTT
        except ImportError as e:
            raise RuntimeError(
                f"Sarvam STT needs livekit-plugins-sarvam ({e}). Run "
                "`pip install livekit-plugins-sarvam>=1.4.1` in the worker venv."
            ) from e
        api_key = overrides.get("api_key") or _provider_api_key("stt", "sarvam", SARVAM_API_KEY)
        if not api_key:
            raise RuntimeError("Sarvam STT needs a Sarvam API key (Super Admin panel or SARVAM_API_KEY env).")
        lang = overrides.get("language") or locale_for_language(getattr(cfg, "language", "hi"))
        model = overrides.get("model", "saaras:v3")
        kwargs = dict(model=model, target_language_code=lang, api_key=api_key)
        # Code-mixed Hindi (Hinglish) benefits from codemix mode when available.
        if overrides.get("mode"):
            kwargs["mode"] = overrides["mode"]
        logger.info(f"🎧 Sarvam STT: model={model} language={lang}")
        try:
            return SarvamSTT(**kwargs)
        except TypeError as e:
            logger.warning(f"⚠️ Sarvam STT rejected {sorted(kwargs)} ({e}); retrying minimal")
            return SarvamSTT(model=model, target_language_code=lang, api_key=api_key)

    if sel.id.startswith("google"):
        from livekit.plugins.google import STT
        lang = overrides.get("language", "hi-IN")
        languages = [lang] if isinstance(lang, str) and "," not in lang else [x.strip() for x in lang.split(",")]
        return STT(
            languages=languages,
            model=overrides.get("model", "latest"),
            credentials_file=overrides.get("credentials_file") or GOOGLE_APPLICATION_CREDENTIALS or None,
        )

    from livekit.plugins.deepgram import STT
    keywords = overrides.get("keywords") or [
        ("Kriscent", 10.0),
        ("Kota", 6.0),
    ]
    # Production Deepgram tuning for 300-400ms speech_end->STT_final:
    # - endpointing_ms 200ms: Deepgram waits 200ms silence before final (was default 25ms)
    # - utterance_end_ms 1000ms: wait 1s for utterance end, allows natural pause in Hindi without premature final
    # - interim_results True: feeds RAG prefetch + lets the library accumulate
    #   continuations into one final (preemptive generation stays OFF — see the
    #   verified note in worker.build_conversational_session)
    # - vad_events True: Deepgram VAD filters non-speech, rejects noise before LLM
    # - no_delay True: send final immediately, don't buffer
    # - smart_format True: better punctuation for Hindi/Hinglish sentence completion detection
    from ...catalog import CATALOG
    cat_stt = CATALOG.get("stt", {}).get(sel.id, {})
    default_model = cat_stt.get("model") or ("nova-3" if "nova3" in sel.id or "nova-3" in sel.id else "nova-2")
    model_name = str(overrides.get("model") or default_model).strip()
    stt_kwargs = dict(
        model=model_name,
        language=overrides.get("language", "hi"),
        interim_results=bool(overrides.get("interim_results", True)),
        vad_events=bool(overrides.get("vad_events", True)),
        no_delay=bool(overrides.get("no_delay", True)),
        filler_words=bool(overrides.get("filler_words", True)),
        api_key=overrides.get("api_key") or _provider_api_key("stt", "deepgram", DEEPGRAM_API_KEY) or None,
    )
    # Deepgram API compatibility:
    # - Nova-3 models require Keyterm Prompting (list of strings via 'keyterm' parameter)
    # - Nova-2, Nova-1, Enhanced, Base models use Keywords (list of (keyword, boost) tuples via 'keywords')
    if model_name.lower().startswith("nova-3"):
        keyterms = [k[0] if isinstance(k, (tuple, list)) else str(k) for k in keywords]
        stt_kwargs["keyterm"] = keyterms
    elif "nova-2" in model_name.lower():
        stt_kwargs["keywords"] = keywords
    # Try to add production latency params with correct names, fallback gracefully if not supported
    # Correct param is endpointing_ms (not endpointing) per installed plugin 1.8.2
    # Preserve utterance_end_ms, smart_format, punctuate - don't drop all on single failure
    optional_params = {}
    # Support both endpointing_ms and legacy endpointing for backward compat
    # Deepgram's own end-of-speech detection must NOT beat the session's
    # endpointing. The session endpointing min is 0.25s and the silero VAD
    # min_silence is 0.35s, so 200ms is the largest value that still fires
    # before either layer — the final lands ~200ms after the user stops
    # talking, and the session adds its adaptive 0.25-0.75s on top. (The old
    # 300ms added a full extra 100ms of dead air to every turn.)
    # DECIDED 2026-09-23 against raising this to ~400ms despite split-turn logs
    # (23:19 + 23:36 calls): the observed splits had 1-2s pauses between
    # fragments (user composing thoughts), which endpointing cannot merge at
    # any value under a second — and >250ms here would let the session VAD
    # (min_silence 0.35s) beat Deepgram's final, committing turns with partial
    # text (more "flushing vad"). Fixed at the answer layer instead: the
    # INCOMPLETE TURNS prompt rule + acknowledgement gate above.
    _dg_endpointing_default = int(os.getenv("VOICE_STT_ENDPOINTING_MS", "200"))
    # utterance_end is the fallback final when endpointing never fires (long
    # pause): 1000ms added a full second of dead air on slow speakers — but
    # Deepgram REJECTS utterance_end_ms below 1000 (WS handshake returns 400
    # "Invalid response status", _stt_pump dies, the agent hears NOTHING — the
    # user speaks, no reply, the no-response watchdog ends the call). Floor it.
    _dg_utterance_end_default = max(1000, int(os.getenv("VOICE_STT_UTTERANCE_END_MS", "1000")))
    if "endpointing_ms" in overrides or "endpointing" in overrides:
        ep_val = overrides.get("endpointing_ms", overrides.get("endpointing", _dg_endpointing_default))
        try:
            optional_params["endpointing_ms"] = int(ep_val)
        except Exception:
            pass
    else:
        optional_params["endpointing_ms"] = _dg_endpointing_default

    if "utterance_end_ms" in overrides or True:  # always try default
        try:
            optional_params["utterance_end_ms"] = int(overrides.get("utterance_end_ms", _dg_utterance_end_default))
        except Exception:
            pass

    if "smart_format" in overrides or True:
        try:
            optional_params["smart_format"] = bool(overrides.get("smart_format", True))
        except Exception:
            pass

    if "punctuate" in overrides or True:
        try:
            optional_params["punctuate"] = bool(overrides.get("punctuate", True))
        except Exception:
            pass

    # Try with all optional params, fallback progressively keeping valid ones
    try:
        combined = {**stt_kwargs, **optional_params}
        instance = STT(**combined)
        logger.info(f"Deepgram STT configured with endpointing_ms={combined.get('endpointing_ms')} utterance_end_ms={combined.get('utterance_end_ms')} smart_format={combined.get('smart_format')} punctuate={combined.get('punctuate')}")
        return instance
    except TypeError as e:
        logger.warning(f"Deepgram STT extra params not supported ({e}), trying progressive fallback")
        # Progressive fallback: try to keep as many valid params as possible
        # First try without endpointing_ms if it failed
        for key in list(optional_params.keys()):
            test_kwargs = {**stt_kwargs}
            for k, v in optional_params.items():
                if k != key:
                    test_kwargs[k] = v
            try:
                inst = STT(**test_kwargs)
                logger.info(f"Deepgram STT fallback without {key}: using {list(test_kwargs.keys())}")
                return inst
            except TypeError:
                continue
        # If all optional fail, use basic config (preserves per-agent base config)
        logger.warning(f"Deepgram STT using basic config (base params only)")
        return STT(**stt_kwargs)


def build_stt(cfg: AgentConfig) -> Any:
    primary_pair = getattr(cfg.providers, "stt", None) if hasattr(cfg, "providers") else None
    if not primary_pair:
        from ...models import ProviderPair
        primary_pair = ProviderPair(id="deepgram_nova2", config={})
    primary = _build_stt_from_pair(primary_pair, cfg)

    fallback_pair = getattr(cfg.providers, "stt_fallback", None)
    if not fallback_pair:
        try:
            fp = getattr(cfg, "fallback_providers", None)
            if fp and getattr(fp, "stt", None):
                fallback_pair = fp.stt
        except Exception:
            pass

    if not fallback_pair:
        return primary
    if fallback_pair.id == primary_pair.id and (fallback_pair.config or {}) == (primary_pair.config or {}):
        return primary

    try:
        fallback = _build_stt_from_pair(fallback_pair, cfg)
        from livekit.agents import stt as stt_agents
        adapter = stt_agents.FallbackAdapter([primary, fallback])
        logger.info(f"🔁 STT FallbackAdapter armed: primary={primary_pair.id} -> fallback={fallback_pair.id}")
        return adapter
    except Exception as e:
        logger.warning(f"⚠️ Could not build STT fallback {fallback_pair.id}: {e} — using primary only")
        return primary


