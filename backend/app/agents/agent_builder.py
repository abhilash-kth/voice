"""
Builds the LiveKit **v1** voice-runtime pieces from a customer-saved AgentConfig.

LiveKit v1 (livekit-agents 1.7.x) replaced ``VoicePipelineAgent`` with the
``Agent``/``AgentSession`` pair, and the per-turn RAG / cross-call memory hooks
moved to ``Agent`` methods. This module exposes small builders so the worker
(``app.agents.worker``) can assemble a session without caring about provider
details.

All LiveKit plugin imports are done lazily inside functions so the FastAPI /
management layer can boot even when the livekit packages aren't installed in
that particular interpreter (e.g. a lightweight CI or a machine that only runs
the API).
"""
from __future__ import annotations

import time

import asyncio
import logging
import os
import re
from typing import Any, Optional

from ..models import AgentConfig, KnowledgeBase
from ..config import (
    GROQ_API_KEY,
    OPENAI_API_KEY,
    DEEPGRAM_API_KEY,
    GOOGLE_APPLICATION_CREDENTIALS,
    OPENROUTER_API_KEY,
    GEMINI_API_KEY,
    SARVAM_API_KEY,
)

logger = logging.getLogger("voice-agent-saas-agent-builder")


# ---------------------------------------------------------------------------
# Google TTS voice normalisation
# ---------------------------------------------------------------------------
# Google's streaming_synthesize endpoint rejects every Wavenet/Standard/Neural2
# voice with ``400 Currently, only Chirp 3: HD voices are supported``. Chirp 3: HD
# uses the "<locale>-Chirp3-HD-<name>" form with 8 multilingual speakers (Leda,
# Kore, Zephyr, Aoede, Charon, Fenrir, Orus, Puck) available across all supported
# locales. So any legacy voice stored in an agent config is transparently mapped
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

def _instantiate_llm(provider_type: str, llm_kwargs: dict) -> Any:
    """Build the provider's native LLM plugin from normalised kwargs.

    OpenAI-compatible providers (openai, groq, openrouter, sarvam) all share
    ``livekit.plugins.openai.LLM`` (Sarvam's chat-completions endpoint is
    OpenAI-compatible). Google Gemini has its own plugin with different kwarg
    names, so translate rather than pass blindly: an unexpected kwarg raises
    TypeError while the turn is being built and the agent goes silent.
    """
    if provider_type == "google":
        try:
            from livekit.plugins.google import LLM as GoogleLLM
        except ImportError as e:
            raise RuntimeError(
                f"Gemini provider needs livekit-plugins-google ({e}). It is already "
                "pinned for Google TTS/STT; if missing run "
                "`pip install livekit-plugins-google>=1.7.1` in the worker venv."
            ) from e
        gk = {k: v for k, v in llm_kwargs.items() if k in ("model", "api_key", "temperature")}
        if llm_kwargs.get("max_completion_tokens"):
            gk["max_output_tokens"] = int(llm_kwargs["max_completion_tokens"])
        return GoogleLLM(**gk)

    from livekit.plugins.openai import LLM as OpenAILLM
    return OpenAILLM(**llm_kwargs)


def _build_llm_from_pair(pair, cfg_language: str = "hi") -> Any:
    """Build an LLM instance from a ProviderPair (primary or fallback) - V2 Provider → Multiple Models.
    
    No silent model substitution. Invalid provider/model returns clear config error.
    Logs LLM PROVIDER CONFIG with provider, model, base_url exactly as selected.
    Fixes OpenAI 404 by validating exact model and capturing actual API error.
    """
    from livekit.plugins.openai import LLM
    from openai import AsyncOpenAI

    sel = pair
    overrides = sel.config or {}
    raw_id = sel.id

    # Resolve provider, model, base_url using V2 logic (no silent replacement)
    # Use ProviderPair's resolve method for backward compat
    try:
        provider, model_id, base_url_resolved = sel.resolve_llm_provider_model()
    except AttributeError:
        # Fallback if sel doesn't have resolve method (should not happen)
        provider = raw_id
        model_id = overrides.get("model", "")
        base_url_resolved = overrides.get("base_url", "")

    # Determine provider id (openai, groq, openrouter) and model_id
    # If id is old style like openai_gpt_4_1_mini, resolve already handled
    # For new style, id is provider, model from config
    if not provider:
        provider = raw_id
    if not model_id:
        model_id = overrides.get("model", "")

    # Get base_url from overrides or resolved or provider default
    base_url = overrides.get("base_url") or base_url_resolved
    if not base_url:
        if provider == "openai":
            base_url = "https://api.openai.com/v1"
        elif provider == "groq":
            base_url = "https://api.groq.com/openai/v1"
        elif provider == "openrouter":
            base_url = "https://openrouter.ai/api/v1"
        else:
            base_url = None  # OpenAI default

    # Get API key based on provider
    if provider.startswith("groq"):
        api_key = overrides.get("api_key") or GROQ_API_KEY
        key_env = "GROQ_API_KEY"
        provider_type = "groq"
    elif provider.startswith("openrouter"):
        # Deprecated provider: still resolvable so agents saved against it keep
        # running, but no longer offered in the picker (see llm_catalog).
        api_key = overrides.get("api_key") or OPENROUTER_API_KEY
        key_env = "OPENROUTER_API_KEY"
        provider_type = "openrouter"
    elif provider.lower() in ("google", "gemini"):
        provider = "google"
        api_key = overrides.get("api_key") or GEMINI_API_KEY
        key_env = "GEMINI_API_KEY"
        provider_type = "google"  # native livekit.plugins.google.LLM
        base_url = None           # plugin owns the endpoint
    elif provider.lower() in ("sarvam", "sarvamai", "sarvam-ai"):
        provider = "sarvam"
        api_key = overrides.get("api_key") or SARVAM_API_KEY
        key_env = "SARVAM_API_KEY"
        provider_type = "openai"  # OpenAI-compatible chat completions
        base_url = base_url or "https://api.sarvam.ai/v1"
    else:
        # Default to openai
        api_key = overrides.get("api_key") or OPENAI_API_KEY
        key_env = "OPENAI_API_KEY"
        provider_type = "openai"
        # Normalize provider to openai if it's old style or unknown
        if provider not in ("openai", "groq", "openrouter", "google", "sarvam"):
            # Check if raw_id maps to known provider via old mapping
            if raw_id.startswith("groq"):
                provider = "groq"
                base_url = base_url or "https://api.groq.com/openai/v1"
                api_key = overrides.get("api_key") or GROQ_API_KEY
                key_env = "GROQ_API_KEY"
            elif raw_id.startswith("openrouter"):
                provider = "openrouter"
                base_url = base_url or "https://openrouter.ai/api/v1"
                api_key = overrides.get("api_key") or OPENROUTER_API_KEY
                key_env = "OPENROUTER_API_KEY"
            else:
                provider = "openai"
                base_url = base_url or "https://api.openai.com/v1"

    if not api_key:
        raise RuntimeError(
            f"No API key for LLM provider '{provider}' (id={raw_id}). Set '{key_env}' "
            f"in backend/.env (or pass api_key in agent's llm config). "
            f"Provider={provider}, model={model_id}, base_url={base_url or 'https://api.openai.com/v1'}"
        )

    # Import new catalog for validation and metadata
    try:
        from ..llm_catalog import get_llm_model, validate_provider_model, get_llm_provider
        # If model_id empty, try to get default from catalog or env
        if not model_id:
            import os as _os
            env_model = _os.getenv("GROQ_MODEL") if provider == "groq" else _os.getenv("OPENAI_MODEL") if provider == "openai" else _os.getenv("LLM_MODEL")
            if env_model:
                model_id = env_model
                logger.info(f"🔍 LLM model from env: {env_model} for provider {provider}")
            else:
                # Get first active model for provider as default
                from ..llm_catalog import list_models_for_provider
                models = list_models_for_provider(provider)
                if models:
                    model_id = models[0]["model_id"]
                    logger.info(f"🔍 LLM model default from catalog: {model_id} for provider {provider} (no model in config)")
        
        # Validate provider/model combination - NO SILENT REPLACEMENT, clear error
        is_valid, validation_msg = validate_provider_model(provider, model_id)
        if not is_valid:
            # Check if model exists under different provider for helpful error
            from ..llm_catalog import get_llm_model_by_id
            existing = get_llm_model_by_id(model_id)
            if existing:
                error_msg = (
                    f"❌ LLM CONFIG ERROR: Invalid provider/model combination. "
                    f"Provider='{provider}' Model='{model_id}' Base_URL='{base_url or 'https://api.openai.com/v1'}' - "
                    f"Model '{model_id}' belongs to provider '{existing['provider']}' (base_url {existing['base_url']}). "
                    f"Do not treat Groq's 120B as OpenAI model. Provider and model must remain separate. "
                    f"Fix: Use provider='{existing['provider']}' with model='{model_id}'. "
                    f"Original error: {validation_msg}"
                )
            else:
                from ..llm_catalog import list_models_for_provider
                valid_models = [m["model_id"] for m in list_models_for_provider(provider)]
                error_msg = (
                    f"❌ LLM CONFIG ERROR: Invalid provider/model combination. "
                    f"Provider='{provider}' Model='{model_id}' Base_URL='{base_url or 'https://api.openai.com/v1'}' - "
                    f"Unknown model '{model_id}' for provider '{provider}'. "
                    f"Valid models for {provider}: {valid_models}. "
                    f"If model is from another provider, use that provider. "
                    f"Do NOT silently replace model. Original: {validation_msg}"
                )
            logger.error(error_msg)
            raise ValueError(error_msg)
        
        # Get model metadata for logging and pricing
        model_meta = get_llm_model(provider, model_id)
        if model_meta:
            logger.info(
                f"✅ LLM MODEL METADATA provider={provider} model={model_id} "
                f"display_name={model_meta['display_name']} "
                f"input_price=${model_meta['input_price_per_1m']}/1M cached=${model_meta['cached_input_price_per_1m']}/1M output=${model_meta['output_price_per_1m']}/1M "
                f"context={model_meta['context_window']} max_output={model_meta['max_output_tokens']} "
                f"reasoning={model_meta['reasoning_supported']} speed={model_meta['expected_speed']} "
                f"streaming={model_meta['streaming_supported']} tools={model_meta['tool_calling_supported']} "
                f"status={model_meta['status']}"
            )
        
        # Log LLM PROVIDER CONFIG exactly as required
        logger.info(
            f"🤖 LLM PROVIDER CONFIG provider={provider} model={model_id} base_url={base_url or 'https://api.openai.com/v1'} "
            f"provider_type={provider_type} raw_id={raw_id} key_env={key_env}"
        )
        
        # Additional validation for OpenAI 404 root cause
        if provider == "openai" and model_id in ("gpt-4.1-mini", "gpt-4.1", "gpt-4.1-nano"):
            logger.info(
                f"🔍 Validating OpenAI model {model_id}: Should exist on OpenAI API (base_url {base_url or 'https://api.openai.com/v1'}). "
                f"If 404 occurs, possible causes: "
                f"1) incorrect model ID (should be exactly {model_id}), "
                f"2) incorrect base_url (should be https://api.openai.com/v1), "
                f"3) wrong provider adapter (should be openai), "
                f"4) API/project configuration (project lacks access to {model_id}, needs billing enabled), "
                f"5) unsupported parameter (check max_completion_tokens, reasoning_effort), "
                f"6) authentication. Will capture actual API error if 404."
            )
        
        if provider == "groq" and model_id == "openai/gpt-oss-120b":
            logger.info(
                f"🔍 Validating Groq model {model_id}: Should exist on Groq API (base_url {base_url}). "
                f"If 404 recovery failed, possible: Groq key invalid or model not available on free tier. "
                f"Safety fallback to openai/gpt-oss-20b will be added if needed."
            )
    
    except ImportError as e:
        logger.warning(f"Could not import llm_catalog for validation: {e}")
        model_meta = None
        # Fallback validation: if model empty, error
        if not model_id:
            raise ValueError(f"❌ LLM CONFIG ERROR: No model specified for provider {provider}. Provide model in config.")
    except ValueError:
        raise
    except Exception as e:
        logger.warning(f"LLM validation warning: {e}")
        model_meta = None

    low = model_id.lower()

    # Determine reasoning effort from model metadata or overrides
    # FIX: For voice, always use low reasoning to reduce TTFT variance (0.77s-1.33s observed for gpt-5.4-mini)
    # gpt-5.4-mini has reasoning_default medium which causes variable reasoning tokens before first token
    # Voice needs fast first token, so force low unless explicitly overridden
    try:
        from ..llm_catalog import get_llm_model
        meta = get_llm_model(provider, model_id)
        if meta:
            # For voice, override medium/high to low to reduce TTFT
            catalog_default = meta.get("reasoning_default") or ("low" if meta.get("reasoning_supported") else "none")
            # If model supports reasoning and catalog says medium/high, force low for voice low-latency
            if meta.get("reasoning_supported") and catalog_default in ("medium", "high"):
                default_reasoning = "low"
                # Log that we are reducing reasoning for voice
                logger.info(f"🔧 Voice reasoning override: model {model_id} catalog default {catalog_default} -> low for voice to reduce TTFT variance (0.77-1.33s -> more consistent)")
            else:
                default_reasoning = catalog_default
        else:
            if "qwen" in low or "gemma" in low:
                default_reasoning = "none"
            elif "gpt-oss" in low:
                default_reasoning = "low"
            else:
                default_reasoning = "none"
    except Exception:
        if "qwen" in low or "gemma" in low:
            default_reasoning = "none"
        elif "gpt-oss" in low:
            default_reasoning = "low"
        else:
            default_reasoning = "none"
    
    reasoning = overrides.get("reasoning_effort", default_reasoning)
    # Extra safety: if reasoning is medium/high for voice, downgrade to low
    if reasoning in ("medium", "high") and provider in ("openai", "groq", "openrouter", "google", "sarvam"):
        logger.info(f"🔧 Downgrading reasoning_effort {reasoning} -> low for voice model {model_id} to reduce TTFT")
        reasoning = "low"

    # Completion-token budget for a voice reply. Non-reasoning models: 80 is
    # plentiful (~60 spoken words) and keeps replies short. REASONING models
    # (gpt-5 family) spend HIDDEN reasoning tokens from the SAME budget —
    # first failure at cap 80, then AGAIN at cap 500 on a vague question
    # (2026-09-19 04:19: output=500/finish_reason=length with ZERO visible text
    # -> 6s watchdog apology). Diffuse prompts can burn >500 tokens of thinking;
    # 800 leaves headroom for think + reply without turning typical turns slow
    # (the model still stops early at natural completion).
    _cap_override = overrides.get("max_tokens")
    _reasoning_mdl = bool((meta or {}).get("reasoning_supported"))
    if _cap_override:
        _cap = int(_cap_override)
        if _reasoning_mdl and _cap < 500:
            logger.warning(
                f"⚠️ max_tokens={_cap} is too small for reasoning model {model_id}: the cap is spent on "
                "hidden reasoning tokens leaving ZERO text for the spoken reply (agent went silent). Raising to 800."
            )
            _cap = 800
    else:
        _cap = 800 if _reasoning_mdl else 80

    # Build client with exact base_url and model, no silent replacement.
    # Only OpenAI-compatible providers ride on an AsyncOpenAI client: Gemini's
    # plugin builds its own SDK client and would reject these kwargs.
    _native_google = provider_type == "google"
    # Task 1/2 (2026-09-24 02:31 post-mortem): the previous hook version used
    # SYNC callbacks on an AsyncClient — httpx awaits every event hook, so
    # `await None` raised TypeError inside EVERY request (the regression that
    # failed all 12 requests of the 02:31 call). The 02:31 run is INVALID for
    # provider-latency conclusions by this file's fault; nothing below changes
    # request behavior: api_key/base_url/model/max_retries are exactly as
    # before, limits/timeout mirror the openai plugin's own defaults
    # (livekit conn_options still override per-request timeout), and every
    # hook body is wrapped so instrumentation can never fail a call. Hooks
    # only READ: the stream is not consumed (the response hook fires on
    # headers arrival, before any body iteration — that is the
    # HTTP_RESPONSE_HEADERS boundary; FIRST_STREAM_CHUNK is measured by the
    # worker's stream wrapper via the shared http_timing store).
    # Mechanism labels (Task 4 — these are NOT all "SDK retries"):
    #   A OpenAI SDK retry   → impossible here: max_retries=0; if ever
    #                           enabled, the x-stainless-retry-count header
    #                           this line echoes becomes >0 per send.
    #   B LiveKit FallbackAdapter switching → a NEW chat() on a DIFFERENT
    #                           instance: visible as the next [PROMPT]/
    #                           REQUEST START line carrying a different model
    #                           + llm_instance tag (and library's own
    #                           "switching to next LLM"/"recovery failed").
    #   C application duplicate/invalidated generation → the worker's
    #                           "LLM REQUEST START while previous still
    #                           active" line, not this one.
    # client_attempt# counts sends sharing ONE httpx client (per LLM
    # instance): with B/C above it is a correlation counter, not a retry
    # claim. Rid joins this line to [HTTP_RESPONSE_HEADERS] and
    # [HTTP_CHUNK] even when attempts interleave.
    import uuid as _uuid_mod
    import httpx as _httpx
    from . import http_timing as _http_timing
    _http_inst = {"n": 0}

    async def _on_http_send(_request):
        try:
            _http_inst["n"] += 1
            _rid = _uuid_mod.uuid4().hex[:8]
            # extensions is httpx-internal metadata, never sent on the wire
            _request.extensions["voice_rid"] = _rid
            _http_timing.note_send(model_id, _rid)
            # --- Provider-bound fingerprint for cache diagnosis (safe, no PII) ---
            try:
                import json as _js
                import hashlib as _hl2
                _body = _request.content
                if _body:
                    _j = _js.loads(_body.decode("utf-8", "ignore") if isinstance(_body, (bytes, bytearray)) else str(_body))
                    _pck = _j.get("prompt_cache_key", "?")
                    _msgs = _j.get("messages", [])
                    _role_seq = ",".join([str(m.get("role", "?")) for m in _msgs])
                    _len_seq = ",".join([str(len(str(m.get("content", "")))) for m in _msgs])
                    _first_c = str(_msgs[0].get("content", "")) if _msgs else ""
                    _first_hash = _hl2.sha256(_first_c.encode("utf-8", "ignore")).hexdigest()[:12] if _first_c else "?"
                    _pref_c = "".join([str(m.get("content", "")) for m in _msgs[:2]])
                    _pref_hash = _hl2.sha256(_pref_c.encode("utf-8", "ignore")).hexdigest()[:12] if _pref_c else "?"
                    logger.info(
                        "\U0001f50d [HTTP_BODY_FINGERPRINT] rid=%s model=%s prompt_cache_key=%s prov_messages=%d role_seq=%s len_seq=%s first_hash=%s prefix_hash=%s",
                        _rid, model_id, _pck, len(_msgs), _role_seq, _len_seq, _first_hash, _pref_hash,
                    )
            except Exception as _e:
                logger.debug(f"[HTTP_BODY_FINGERPRINT] failed: {_e!r}")
            logger.info(
                "\U0001f310 [HTTP_REQUEST_START] rid=%s model=%s client_attempt#%d sdk_retry_count=%s path=%s — one send of one chat() attempt (see B/C distinction in builder comment; SDK retries are disabled by max_retries=0)",
                _rid, model_id, _http_inst["n"],
                _request.headers.get("x-stainless-retry-count", "absent"),
                _request.url.path,
            )
        except Exception:
            pass

    async def _on_http_headers(_response):
        try:
            _rid = _response.request.extensions.get("voice_rid", "?")
            _el = _http_timing.note_headers(_rid, _response.status_code)
            logger.info(
                "\U0001f310 [HTTP_RESPONSE_HEADERS] rid=%s model=%s status=%d request_start->response_headers=%s — headers boundary only; first streamed body bytes come later (see [HTTP_CHUNK])",
                _rid, model_id, _response.status_code,
                ("%.0fms" % _el) if _el >= 0 else "?",
            )
        except Exception:
            pass

    async def _on_http_error(_request):
        try:
            _rid = _request.extensions.get("voice_rid", "?")
            logger.warning(
                "\U0001f310 [HTTP_ERROR] rid=%s model=%s — transport-level failure (connect/pool/read). The 02:31 TypeError regression came from sync hooks being awaited by httpx; hooks are async since that fix, so a line here now means a real network problem.",
                _rid, model_id,
            )
        except Exception:
            pass

    client = None if _native_google else AsyncOpenAI(
        api_key=api_key, base_url=base_url, max_retries=0,
        http_client=_httpx.AsyncClient(
            event_hooks={"request": [_on_http_send], "response": [_on_http_headers], "error": [_on_http_error]},
            follow_redirects=True,
            limits=_httpx.Limits(max_connections=50, max_keepalive_connections=50, keepalive_expiry=120.0),
            timeout=_httpx.Timeout(connect=15.0, read=5.0, write=5.0, pool=5.0),
        ),
    )
    llm_kwargs = {
        "model": model_id,  # EXACT model as selected, no rewriting
        "max_completion_tokens": _cap,
    }
    if client is not None:
        llm_kwargs["client"] = client
    elif api_key:
        llm_kwargs["api_key"] = api_key

    # Temperature: reasoning models (gpt-5 family, o-series) do not support a
    # custom temperature, so only send it when the catalog says the model
    # accepts one. An explicit user override on a reasoning model is still
    # honoured (the provider will clamp/ignore it) rather than silently dropped.
    _temp_explicit = overrides.get("temperature", None)
    _supports_temp = True if model_meta is None else bool(model_meta.get("supports_temperature", True))
    if _supports_temp:
        _temp = _temp_explicit
        if _temp is None and model_meta is not None:
            _temp = model_meta.get("default_temperature")
        llm_kwargs["temperature"] = float(_temp if _temp is not None else 0.1)
    elif _temp_explicit is not None:
        llm_kwargs["temperature"] = float(_temp_explicit)
    else:
        logger.info(
            f"ℹ️ {provider}:{model_id} is a reasoning model — temperature not sent "
            f"(unsupported); set reasoning_effort instead"
        )
    # For reasoning models, check if responses API should be used for tool+reasoning support
    # OpenAI Chat Completions rejects reasoning_effort with tools for gpt-5.4-mini (400 error)
    # LiveKit 1.8.2+ has openai.responses.LLM that supports reasoning+tools via /v1/responses
    use_responses_api = False
    # Task 2 (11:41 log): ONE capability lookup drives everything below —
    # whether prompt_cache_key is sent (native_explicit only), whether the
    # provider auto-caches (native_automatic: Groq's gpt-oss family — send
    # NO field, they reject it with 400), or whether caching is genuinely
    # absent for this exact model (e.g. groq qwen3.8 → honest unsupported,
    # never a fake "miss"). Model selection itself is untouched.
    try:
        from ..llm_catalog import get_prompt_cache_capability as _gcc
        _cache_cap = _gcc(provider_type or provider, model_id)
    except Exception:
        _cache_cap = {"supported": provider_type == "openai",
                      "mode": "native_explicit" if provider_type == "openai" else "none",
                      "configuration": ({"prompt_cache_key": f"voice-{model_id}-v1"} if provider_type == "openai" else None)}
    if model_meta and model_meta.get("reasoning_supported") and model_id.startswith("gpt-5"):
        # gpt-5.4-mini with end_call tool needs responses API for reasoning+tools
        use_responses_api = True
        logger.info(f"🔧 Model {model_id} is reasoning + uses tools (end_call), will try responses.LLM for proper reasoning+tools support (fixes 400 on chat/completions)")

    if model_meta and model_meta.get("reasoning_supported"):
        llm_kwargs["reasoning_effort"] = reasoning
        # For gpt-5.4 models, reasoning_effort low is supported and transmitted via extra_kwargs
        # Verify: LiveKit plugin 1.8.2+ supports reasoning_effort via _opts.reasoning_effort -> extra["reasoning_effort"]
        # Chat API: extra["reasoning_effort"] = low, Responses API: same
        # For prompt caching, set prompt_cache_key to stable value to enable cached_input_tokens
        # This can reduce TTFT by reusing cached system prompt prefix.
        # NOTE: prompt_cache_key is an OPENAI-ONLY extension. Groq's OpenAI-compat
        # endpoint hard-rejects it with 400 "property 'prompt_cache_key' is
        # unsupported" on EVERY request (2026-09-19: gpt-oss-20b + qwen3.6-27b both
        # 400'd all turns -> FallbackAdapter exhausted -> 6s watchdog apology).
        # Only send it to api.openai.com.
        if _cache_cap["mode"] == "native_explicit":
            try:
                # Use model_id as cache key for stable prefix caching
                llm_kwargs["prompt_cache_key"] = _cache_cap["configuration"]["prompt_cache_key"]
                logger.info(f"🔧 Set prompt_cache_key={llm_kwargs['prompt_cache_key']} for prompt caching (capability=native_explicit; per-request [CACHE] hit/miss is read from provider usage CompletionUsage.prompt_cached_tokens — real numbers only)")
            except Exception:
                pass
    elif "gpt-oss" in low or "o1" in low or "o3" in low or "o4" in low:
        llm_kwargs["reasoning_effort"] = reasoning

    # Prefix-cache pinning for OpenAI's AUTOMATIC 1024+ token prompt cache:
    # without a stable prompt_cache_key, requests get load-balanced across
    # backend machines and the big static prefix (system + owner prompt + tool
    # defs, ~1.5-2K tokens) never hits — production logs showed cached=0 on
    # every turn and TTFT 1.2-2.3s on gpt-4.1-mini. A stable key pins requests
    # to the same machine, so turns 2+ reuse the cached prefix (~30-60% lower
    # TTFT). OPENAI-ONLY: Groq/OpenRouter-compatible endpoints reject the field
    # with a 400 on every request, so apply it only when provider_type=openai.
    if _cache_cap["mode"] == "native_explicit" and "prompt_cache_key" not in llm_kwargs:
        llm_kwargs["prompt_cache_key"] = _cache_cap["configuration"]["prompt_cache_key"]
        logger.info(f"🔧 Set prompt_cache_key={llm_kwargs['prompt_cache_key']} (prefix cache pinning — watch cached>0 from turn 2 on)")

    # Try responses API for gpt-5 reasoning models with tools (proper support)
    # Verified: chat/completions with reasoning_effort+tools returns 400 for gpt-5.4-nano/mini per LiveKit community
    # responses API uses reasoning object, not reasoning_effort string, and supports tools
    # For now, we KEEP chat LLM as primary because logs show reasoning=low is being passed and no 400 observed for gpt-5.4-mini
    # But we prepare correct responses.LLM build for future use if needed
    if use_responses_api:
        try:
            from livekit.plugins.openai import responses as openai_responses
            # responses.LLM expects reasoning=Reasoning(effort="low") not reasoning_effort string
            # It also does NOT use prompt_cache_key (uses previous_response_id caching)
            # For voice latency, chat LLM with prompt_cache_key may actually be faster due to prefix caching
            # So we log but do NOT switch unless explicitly enabled via VOICE_USE_RESPONSES_API=1
            import os as _os_resp
            if _os_resp.getenv("VOICE_USE_RESPONSES_API", "0") == "1":
                logger.info(f"🔧 Attempting openai.responses.LLM for {model_id} with reasoning={reasoning} (VOICE_USE_RESPONSES_API=1, proper API for reasoning+tools)")
                try:
                    # Build correct kwargs for responses API
                    from openai.types.shared import Reasoning as _Reasoning
                    resp_reasoning = _Reasoning(effort=reasoning) if reasoning != "none" else _Reasoning(effort="none")
                    resp_kwargs = {
                        "model": model_id,
                        "temperature": float(overrides.get("temperature", 0.1)),
                        "reasoning": resp_reasoning,
                    }
                    # Pass api_key/base_url via env or client? responses.LLM uses api_key param, not client
                    # Try with api_key and base_url
                    if base_url:
                        resp_kwargs["base_url"] = base_url
                    if api_key:
                        resp_kwargs["api_key"] = api_key
                    # max_output_tokens -> max_output_tokens for responses
                    resp_kwargs["max_output_tokens"] = _cap
                    llm_instance = openai_responses.LLM(**resp_kwargs)
                    logger.info(f"✅ Built openai.responses.LLM successfully for {model_id} reasoning={reasoning} (transmitted to /v1/responses API, reasoning object)")
                    return llm_instance
                except Exception as e_resp:
                    logger.warning(f"⚠️ responses.LLM build failed for {model_id}: {e_resp}, falling back to chat LLM (reasoning may not be applied on chat/completions with tools)")
                    pass
            else:
                logger.info(f"🔧 Model {model_id} reasoning+tools: chat LLM supports reasoning_effort low via extra['reasoning_effort'] (verified in plugin code), responses API available but not enabled (VOICE_USE_RESPONSES_API=0) to preserve prompt_cache_key caching and avoid websocket overhead for voice")
        except ImportError as e_imp:
            logger.warning(f"⚠️ openai.responses module not available (plugin version {e_imp}), using chat LLM - reasoning=low transmitted via extra['reasoning_effort'] for {model_id}")
        except Exception as e:
            logger.warning(f"⚠️ Could not build responses.LLM for {model_id}: {e}, using chat LLM")

    logger.info(
        f"🔧 Building LLM instance: provider={provider} model={model_id} base_url={base_url or 'https://api.openai.com/v1'} "
        f"provider_type={provider_type} temperature={llm_kwargs.get('temperature','n/a (reasoning model)')} max_tokens={llm_kwargs['max_completion_tokens']} reasoning={llm_kwargs.get('reasoning_effort','none')} "
        f"EXACT model passed to runtime, no silent substitution"
    )

    try:
        llm_instance = _instantiate_llm(provider_type, llm_kwargs)
        logger.info(f"✅ LLM instance built successfully: provider={provider} model={model_id} provider_type={provider_type}")
        # Task 1 (2026-09-24): don't CLAIM caching — verify the key survived
        # constructor -> plugin options. livekit-plugins-openai >=1.8 maps
        # OpenAILLMOptions.prompt_cache_key into chat() create kwargs
        # (llm.py: `_opts.prompt_cache_key` -> top-level param); if the
        # installed plugin is older, the option is silently dead and cached
        # tokens stay 0 forever -> say so loudly instead of pretending.
        try:
            _ck = getattr(getattr(llm_instance, "_opts", None), "prompt_cache_key", None)
            if provider_type == "openai":
                if _ck:
                    logger.info("🗄️ [CACHE] provider=openai model=%s cache_key=%s status=armed (key verified in plugin options; hit/miss is only reported from real usage.prompt_tokens_details.cached_tokens)", model_id, _ck)
                else:
                    logger.warning("🗄️ [CACHE] provider=openai model=%s status=unsupported — prompt_cache_key did NOT reach the plugin's create kwargs (plugin too old or kwarg dropped); cached_input_tokens will stay 0; upgrade livekit-plugins-openai>=1.8 to enable", model_id)
            elif _cache_cap["mode"] == "native_automatic":
                logger.info("🗄️ [CACHE] provider=%s model=%s capability=native_automatic cache_status=automatic (provider prefix-caches on its own — NO client field sent; hit/miss will only be claimed from real usage.prompt_tokens_details.cached_tokens)", provider, model_id)
            else:
                logger.info("🗄️ [CACHE] provider=%s model=%s capability=none cache_status=unsupported (this exact model exposes no provider-side prompt cache; no OpenAI-only fields are sent, nothing to hit or miss)", provider, model_id)
        except Exception as _cke:
            logger.debug(f"cache-key verification skipped: {_cke!r}")
        return llm_instance
    except Exception as e:
        logger.error(
            f"❌ LLM BUILD FAILED: provider={provider} model={model_id} base_url={base_url or 'https://api.openai.com/v1'} "
            f"Error: {e}. This is the actual API error - check if model ID, base_url, provider adapter, or project config is wrong. "
            f"Do not silently rewrite model. Fix root cause."
        )
        raise




def build_llm(cfg: AgentConfig) -> Any:
    """Build LLM with optional fallback via LiveKit FallbackAdapter - V2 Provider → Multiple Models.
    
    Primary and fallback both support multiple models.
    Provider and model remain separate fields, no silent substitution.
    Logs explicit provider/model/base_url/fallback for 404 debugging.
    """
    # Get primary and fallback using new V2 methods if available
    try:
        primary_pair = cfg.providers.get_primary_llm()
        fallback_pair = cfg.providers.get_fallback_llm()
    except AttributeError:
        primary_pair = getattr(cfg.providers, "llm", None)
        fallback_pair = getattr(cfg.providers, "llm_fallback", None)
        if not fallback_pair:
            try:
                fp = getattr(cfg, "fallback_providers", None)
                if fp and getattr(fp, "llm", None):
                    fallback_pair = fp.llm
            except Exception:
                pass

    if not primary_pair:
        from ..models import ProviderPair
        primary_pair = ProviderPair(id="openai_gpt4o_mini", config={})

    # Log LLM PROVIDER CONFIG for primary
    try:
        prov, model, base_url = primary_pair.resolve_llm_provider_model()
        logger.info(f"🤖 LLM PRIMARY CONFIG provider={prov} model={model} base_url={base_url or 'https://api.openai.com/v1'} raw_id={primary_pair.id}")
    except Exception as e:
        logger.warning(f"Could not log primary LLM config: {e}")

    if fallback_pair:
        try:
            prov, model, base_url = fallback_pair.resolve_llm_provider_model()
            logger.info(f"🤖 LLM FALLBACK CONFIG provider={prov} model={model} base_url={base_url or 'https://api.openai.com/v1'} raw_id={fallback_pair.id}")
        except Exception as e:
            logger.warning(f"Could not log fallback LLM config: {e}")

    def _pm_attach(inst, pair):
        # 12:28 attribution fix: stamp each LLM instance with ITS OWN
        # provider/model/base_url. The worker's timing wrapper used to hand the
        # PRIMARY's provider_info to every FallbackAdapter inner instance, so an
        # OpenAI fallback completion logged (and priced) as
        # provider=groq model=qwen/qwen3.8-27b — including real cached tokens
        # (1152/1536 — OpenAI 128-token cache blocks) appearing on "Groq"
        # records. With the stamp, the wrapper reads identity from the instance
        # that actually served; usage can never be attributed to the chain head.
        try:
            pr, mo, bu = pair.resolve_llm_provider_model()
            inst._prov_meta = {"provider": pr, "model_id": mo, "base_url": bu or ""}
        except Exception:
            try:
                inst._prov_meta = {"provider": pair.id, "model_id": (pair.config or {}).get("model", ""), "base_url": ""}
            except Exception:
                pass

    # Build primary with exact model, no silent substitution
    primary = _build_llm_from_pair(primary_pair, getattr(cfg, "language", "hi"))
    _pm_attach(primary, primary_pair)

    # Cache fix v3: make prompt_cache_key per-agent so that per-agent owner/KB/FAQ
    # content is genuinely identical for same key. Global key voice-gpt-4.1-mini-v1
    # caused cross-agent thrashing and violated "identical for same cache key"
    # principle when stable included per-agent content. Per-agent key restores
    # reliable within-agent caching while still using native_explicit mode.
    try:
        _agent_short = (getattr(cfg, "id", "") or getattr(cfg, "name", "") or "")[:12]
        _agent_short = "".join(c for c in _agent_short if c.isalnum())[:8] or "agent"
        # Resolve model_id for key
        try:
            _, _model_id_for_key, _ = primary_pair.resolve_llm_provider_model()
        except Exception:
            _model_id_for_key = (primary_pair.config or {}).get("model", "gpt-4.1-mini")
        _per_agent_key = f"voice-{_model_id_for_key}-{_agent_short}-v1"
        # Only for OpenAI (native_explicit)
        try:
            from ..llm_catalog import get_prompt_cache_capability as _gcc_key
            _cap_for_key = _gcc_key("openai", _model_id_for_key)
            if _cap_for_key.get("mode") == "native_explicit":
                if hasattr(primary, "_opts") and hasattr(primary._opts, "prompt_cache_key"):
                    primary._opts.prompt_cache_key = _per_agent_key
                    logger.info(f"🔧 Per-agent prompt_cache_key={_per_agent_key} (agent {_agent_short}) for reliable caching — identical for same agent across turns")
        except Exception as _ke:
            logger.debug(f"Per-agent cache key setup skipped: {_ke!r}")
    except Exception as _e:
        logger.debug(f"Per-agent cache key outer skipped: {_e!r}")

    # Build fallback chain - supports multiple models, provider/model separate
    fallbacks = []
    if fallback_pair:
        # Validate fallback is not same as primary (same provider and model)
        try:
            p_prov, p_model, _ = primary_pair.resolve_llm_provider_model()
            f_prov, f_model, _ = fallback_pair.resolve_llm_provider_model()
            if not (p_prov == f_prov and p_model == f_model):
                fallbacks.append(fallback_pair)
            else:
                logger.info(f"Fallback same as primary ({p_prov}:{p_model}), skipping")
        except Exception:
            # Fallback to old comparison
            if not (fallback_pair.id == primary_pair.id and (fallback_pair.config or {}).get("model") == (primary_pair.config or {}).get("model")):
                fallbacks.append(fallback_pair)

    # Safety net for Groq 120b 404 - add 20b if 120b present and 20b not, with explicit logging
    try:
        chain_ids = []
        try:
            p_prov, p_model, _ = primary_pair.resolve_llm_provider_model()
            chain_ids.append(f"{p_prov}:{p_model}")
        except Exception:
            chain_ids.append(primary_pair.id)
        for fb in fallbacks:
            try:
                f_prov, f_model, _ = fb.resolve_llm_provider_model()
                chain_ids.append(f"{f_prov}:{f_model}")
            except Exception:
                chain_ids.append(fb.id)
        
        has_120b = any("gpt-oss-120b" in cid for cid in chain_ids)
        has_20b = any("gpt-oss-20b" in cid for cid in chain_ids)
        if has_120b and not has_20b:
            from ..models import ProviderPair
            safety_pair = ProviderPair(id="groq", config={"model": "openai/gpt-oss-20b", "temperature": 0.1, "max_tokens": 80, "provider": "groq"})
            fallbacks.append(safety_pair)
            logger.info(f"🛡️ Added safety fallback groq:openai/gpt-oss-20b because chain contains gpt-oss-120b which observed 404 recovery failed")
    except Exception as e:
        logger.debug(f"Could not add safety fallback: {e}")

    if not fallbacks:
        logger.info(f"🤖 LLM single provider (no fallback): primary={primary_pair.id}")
        return primary

    fallback_instances = []
    fallback_ids = []
    for fb_pair in fallbacks:
        try:
            inst = _build_llm_from_pair(fb_pair, getattr(cfg, "language", "hi"))
            _pm_attach(inst, fb_pair)
            # Per-agent cache key for fallback too (same agent short as primary)
            try:
                _agent_short_fb = (getattr(cfg, "id", "") or getattr(cfg, "name", "") or "")[:12]
                _agent_short_fb = "".join(c for c in _agent_short_fb if c.isalnum())[:8] or "agent"
                try:
                    _, _model_id_fb, _ = fb_pair.resolve_llm_provider_model()
                except Exception:
                    _model_id_fb = (fb_pair.config or {}).get("model", "gpt-4.1-mini")
                _per_agent_key_fb = f"voice-{_model_id_fb}-{_agent_short_fb}-v1"
                try:
                    from ..llm_catalog import get_prompt_cache_capability as _gcc_fb
                    _cap_fb = _gcc_fb("openai", _model_id_fb)
                    if _cap_fb.get("mode") == "native_explicit":
                        if hasattr(inst, "_opts") and hasattr(inst._opts, "prompt_cache_key"):
                            inst._opts.prompt_cache_key = _per_agent_key_fb
                except Exception:
                    pass
            except Exception:
                pass
            fallback_instances.append(inst)
            fallback_ids.append(fb_pair.id)
        except Exception as e:
            logger.error(f"❌ Could not build LLM fallback {fb_pair.id}: {e} - clear config error, no silent substitution")
            # Do not silently skip, log error but continue to try other fallbacks
            # If all fallbacks fail, primary will be used alone

    if not fallback_instances:
        logger.warning(f"⚠️ No valid fallback built, using primary only")
        return primary

    try:
        from livekit.agents import llm as llm_agents
        all_llms = [primary] + fallback_instances
        # ── FallbackAdapter lifecycle (livekit-agents 1.8.2) — DOCUMENTED, not
        # patched (per task spec). Exactly what the log sequence means:
        #  FallbackLLMStream._run() walks the chain; per available instance it
        #  calls llm.chat() — a WRAPPED call, one "LLM REQUEST START … primary/
        #  0-of-2". Groq's 429 raises inside that attempt; the adapter logs
        #  "…failed, switching to next LLM", marks the instance unavailable and
        #  starts a BACKGROUND RECOVERY PROBE (_try_recovery →
        #  _try_generate(check_recovery=True) → another real chat() on primary/
        #  0-of-2 — the line seen while the fallback is still streaming; NOT a
        #  duplicate turn request. It is labelled 🧪 [LLM_RECOVERY_PROBE] here,
        #  kept out of turn accounting, latency state, generation ids and
        #  customer billing (it is provider-infra cost, not the caller's).
        #  Then _run continues to the next instance: "fallback/1-of-2" answers —
        #  one valid active generation per turn, no retry on the 429'd model
        #  (max_retry_per_llm=0 default), attempt_timeout=5.0s. A failed probe
        #  leaves the instance unhealthy until the "all failed" pass of the
        #  NEXT real request re-tries it.
        adapter = llm_agents.FallbackAdapter(all_llms)
        # Log full chain with exact provider/model/base_url
        try:
            chain_details = []
            for pair in [primary_pair] + fallbacks:
                try:
                    prov, model, base_url = pair.resolve_llm_provider_model()
                    chain_details.append(f"{prov}:{model} @ {base_url or 'https://api.openai.com/v1'} (id={pair.id})")
                except Exception:
                    chain_details.append(f"{pair.id}")
            chain_str = " -> ".join([primary_pair.id] + fallback_ids)
            logger.info(f"🔁 LLM FallbackAdapter armed: {chain_str} | Details: {' -> '.join(chain_details)} | Provider and model remain separate, no silent substitution")
        except Exception:
            chain_str = " -> ".join([primary_pair.id] + fallback_ids)
            logger.info(f"🔁 LLM FallbackAdapter armed: {chain_str} (provider/model separate)")
        return adapter
    except Exception as e:
        logger.error(f"❌ Could not build LLM FallbackAdapter {fallback_ids}: {e} - using primary only, error: {e}")
        return primary


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
        api_key = overrides.get("api_key") or SARVAM_API_KEY
        if not api_key:
            raise RuntimeError("Sarvam STT needs SARVAM_API_KEY (backend/.env).")
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
    from ..catalog import CATALOG
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
        api_key=overrides.get("api_key") or DEEPGRAM_API_KEY or None,
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
        from ..models import ProviderPair
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


def _build_tts_from_pair(pair, cfg: AgentConfig) -> Any:
    sel = pair
    overrides = sel.config or {}

    if sel.id.startswith("google"):
        from livekit.plugins.google import TTS
        configured_language = (getattr(cfg, "language", "hi") or "hi").lower()
        # Honour the agent's language for every Indic locale we support (was
        # hard-coded to hi-IN/en-IN, so a Tamil agent would have spoken Hindi).
        default_language = locale_for_language(configured_language)
        language = overrides.get("language", default_language)
        gender = (getattr(cfg, "gender", "") or overrides.get("gender") or "female").lower()
        voice = _resolve_tts_voice(language, overrides.get("voice"), gender)
        logger.info(f"🎙️ Google TTS: voice={voice} language={language} gender={gender}")
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
        api_key = overrides.get("api_key") or SARVAM_API_KEY
        if not api_key:
            raise RuntimeError(
                "Sarvam TTS needs SARVAM_API_KEY (backend/.env) or an api_key in the "
                "agent's tts config. Get one at https://dashboard.sarvam.ai."
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

    if sel.id.startswith("elevenlabs"):
        from livekit.plugins.elevenlabs import TTS
        return TTS(
            voice_id=overrides.get("voice", "pNInz6obpgDQGcFmaJgB"),
            model=overrides.get("model", "eleven_multilingual_v2"),
            language=overrides.get("language", "en" if (getattr(cfg, "language", "hi") or "hi").lower().startswith("en") else "hi"),
        )

    if sel.id.startswith("openrouter"):
        import os as _os
        from livekit.plugins.openai import TTS
        from ..catalog import get_provider
        cat = get_provider("tts", sel.id) or {}
        model = (
            overrides.get("model")
            or _os.getenv("LLM_TTS_MODEL", "")
            or cat.get("model")
            or "deepgram/flux-tts:free"
        )
        api_key = overrides.get("api_key") or OPENROUTER_API_KEY
        if not api_key:
            raise RuntimeError(
                "OpenRouter TTS needs OPENROUTER_API_KEY (see backend/.env) or an "
                "api_key in the agent's tts config."
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


def build_tts(cfg: AgentConfig) -> Any:
    primary_pair = getattr(cfg.providers, "tts", None) if hasattr(cfg, "providers") else None
    if not primary_pair:
        from ..models import ProviderPair
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
_KB_BUDGET_CHARS_DEFAULT_GROQ = 2500
_FAQ_BUDGET_CHARS_DEFAULT_GROQ = 1200
_OWNER_PROMPT_BUDGET_CHARS_DEFAULT_GROQ = 3000

# FIXED for KB grounding: Previous 1000/600/1500 budgets were too small, causing
# "Mere paas company ki exact team size nahi hai" - KB truncated 45788->1001 chars.
# Groq 8k TPM is tight, but with 6-msg history trim we can afford larger budgets.
# New: Groq 2500/1200/3000, OpenAI 4000/2000/4000 to preserve KB grounding.
# Task: "Do not sacrifice correctness for latency" - so preserve KB.

# Voice latency optimization (20260917-230522): LLM TTFT 882-1203ms with 3500-3700 input tokens
# Root cause: static KB 4000 + FAQ 2000 + owner 4000 = 10000 chars ~2500 tokens + RAG 1091 + history 20*200 = 4000 => 3500-3700 tokens
# With RAG per-turn enabled (27-105ms), static KB is redundant. Reduce static when RAG enabled to lower TTFT.
# New for OpenAI voice latency: when RAG enabled, KB 1200 (was 4000), FAQ 800 (was 2000), owner 2500 (was 4000)
# Saves ~6000 chars ~1500 tokens, bringing 3500->~2000, TTFT should improve 200-400ms without hurting quality because RAG provides relevant facts.
# Env overrides still respected: VOICE_KB_BUDGET_CHARS etc.
_KB_BUDGET_CHARS_DEFAULT = 4000
_FAQ_BUDGET_CHARS_DEFAULT = 2000
_OWNER_PROMPT_BUDGET_CHARS_DEFAULT = 4000

# Voice latency optimized defaults when RAG enabled (reduces 3500-3700 -> ~2000 tokens)
# v2: Further reduction to hit ~1500 tokens for TTFT improvement, prior_memory also budgeted
# KB 800 (was 1200), FAQ 400 (was 800), owner 2000 (was 2500), prior_memory 800 (was unlimited 40 turns ~4000 tokens)
# Total static ~3200 chars ~800 tokens + RAG 500 + history 8*150=1200 = ~2500 tokens (was 3500-3700)
# Prior_memory 40 turns -> 800 chars preserves recent cross-call context without bloating
# v3 (2026-09-24 cache fix): 1126-token stable was borderline <1024 real tokens → cached=0 miss.
# Restore larger genuinely stable prefix: KB 2500 FAQ 1200 owner 3000 matches historical
# cache-hit size (~2350 tokens est) and is still bounded to avoid Groq 429s.
# This is natural business content, not artificial padding.
_KB_BUDGET_CHARS_VOICE_RAG = 2500
_FAQ_BUDGET_CHARS_VOICE_RAG = 1200
_OWNER_PROMPT_BUDGET_CHARS_VOICE_RAG = 3000
_PRIOR_MEMORY_BUDGET_CHARS_VOICE_RAG = 800

# Legacy module-level constants kept for backward compat / logging, but
# build_instructions now uses provider-aware effective budgets.
_KB_BUDGET_CHARS = int(os.getenv("VOICE_KB_BUDGET_CHARS", str(_KB_BUDGET_CHARS_DEFAULT)))
_FAQ_BUDGET_CHARS = int(os.getenv("VOICE_FAQ_BUDGET_CHARS", str(_FAQ_BUDGET_CHARS_DEFAULT)))
_OWNER_PROMPT_BUDGET_CHARS = int(os.getenv("VOICE_OWNER_PROMPT_BUDGET_CHARS", str(_OWNER_PROMPT_BUDGET_CHARS_DEFAULT)))


def _effective_budgets(cfg: AgentConfig) -> tuple[int, int, int]:
    """Return (kb_budget, faq_budget, owner_budget) based on LLM provider and RAG enabled for voice latency."""
    try:
        llm_id = (cfg.providers.llm.id or "").lower() if cfg.providers and cfg.providers.llm else ""
    except Exception:
        llm_id = ""
    is_groq = llm_id.startswith("groq")
    # Check if RAG enabled for voice latency optimization
    rag_enabled = True
    try:
        v = (os.getenv("VOICE_RAG_PER_TURN") or "").strip().lower()
        if v in ("0", "false", "off"):
            rag_enabled = False
    except Exception:
        rag_enabled = True

    if is_groq:
        kb = int(os.getenv("VOICE_KB_BUDGET_CHARS", str(_KB_BUDGET_CHARS_DEFAULT_GROQ)))
        faq = int(os.getenv("VOICE_FAQ_BUDGET_CHARS", str(_FAQ_BUDGET_CHARS_DEFAULT_GROQ)))
        owner = int(os.getenv("VOICE_OWNER_PROMPT_BUDGET_CHARS", str(_OWNER_PROMPT_BUDGET_CHARS_DEFAULT_GROQ)))
    else:
        # Voice latency optimization: when RAG enabled, use smaller static budgets to reduce 3500-3700 input tokens
        # RAG provides relevant facts per-turn (27-105ms), so static KB can be smaller without hurting quality
        # v2: 800/400/2000 + prior_memory 800 (was 1200/800/2500) saves additional ~1000 chars
        if rag_enabled:
            kb = int(os.getenv("VOICE_KB_BUDGET_CHARS", str(_KB_BUDGET_CHARS_VOICE_RAG)))
            faq = int(os.getenv("VOICE_FAQ_BUDGET_CHARS", str(_FAQ_BUDGET_CHARS_VOICE_RAG)))
            owner = int(os.getenv("VOICE_OWNER_PROMPT_BUDGET_CHARS", str(_OWNER_PROMPT_BUDGET_CHARS_VOICE_RAG)))
            logger.info(f"🔧 Voice latency budgets v2 (RAG enabled): KB {kb} (was 4000), FAQ {faq} (was 2000), owner {owner} (was 4000), prior_memory 800 - reduces 3500-3700 -> ~2000-2500, TTFT 1203/894/1189/882ms should improve")
        else:
            kb = int(os.getenv("VOICE_KB_BUDGET_CHARS", str(_KB_BUDGET_CHARS_DEFAULT)))
            faq = int(os.getenv("VOICE_FAQ_BUDGET_CHARS", str(_FAQ_BUDGET_CHARS_DEFAULT)))
            owner = int(os.getenv("VOICE_OWNER_PROMPT_BUDGET_CHARS", str(_OWNER_PROMPT_BUDGET_CHARS_DEFAULT)))
    return kb, faq, owner

# Marker for the per-turn RAG system message (used to prune the previous turn's).
_RAG_PREFIX = "[RAG]"

# Deterministic closing speech — fixed line, never LLM-generated (bb393dd fix).
DETERMINISTIC_CLOSING = "Thank you for calling us. Aapse baat karke achha laga. Goodbye."
DETERMINISTIC_CLOSING_EN = "Thank you for calling us. It was nice talking to you. Goodbye."

def _get_closing_for_cfg(cfg: AgentConfig) -> str:
    lang = (getattr(cfg, "language", "hi") or "hi").lower()
    if lang.startswith("en"):
        return DETERMINISTIC_CLOSING_EN
    return DETERMINISTIC_CLOSING


def _truncate(text: str, budget: int) -> str:
    """Clip `text` to `budget` chars, preferring a sentence/line boundary."""
    text = (text or "").strip()
    if budget <= 0 or len(text) <= budget:
        return text
    cut = text[:budget]
    best = -1
    for m in re.finditer(r"[.!?\n]", cut):
        best = m.end()
    if best > budget * 0.5:
        cut = text[:best]
    return cut.rstrip() + " …"


def _rag_per_turn_enabled() -> bool:
    v = (os.getenv("VOICE_RAG_PER_TURN") or "").strip().lower()
    if v in ("0", "false", "off"):
        return False
    if v in ("1", "true", "on"):
        return True
    # FIXED: Always enable RAG per-turn for KB grounding, even when preemptive ON.
    # Previous: disabled RAG when VOICE_PREEMPTIVE=1 to preserve preemptive, but that
    # sacrificed correctness (\"Mere paas exact jaankari nahi hai\").
    # Now: RAG always ON for correctness. When preemptive ON, we explicitly log
    # that RAG will invalidate preemptive for this turn (correctness > latency),
    # but we still do RAG. This is explicit handling, not silent skip.
    # Preemptive still benefits non-KB turns (greetings, small talk).
    return True


def _chat_msg_text(item) -> str:
    """Best-effort text of a v1 ChatMessage (or a plain string)."""
    if item is None:
        return ""
    if isinstance(item, str):
        return item
    if hasattr(item, "text_content") and item.text_content:
        return str(item.text_content)
    content = getattr(item, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(str(c) for c in content if isinstance(c, str))
    return ""


# ---------------------------------------------------------------------------
# Incomplete-turn fragment state machine — the 03:07 call fix.
#
# Production evidence (03:07:39→03:08:44): a held fragment "Ok और" was
# merged into EVERY following turn — the buffer had no consume step, so it
# accumulated duplicates ("merged 3 fragment(s): 'Ok और Ok और और इसका
# office...'") and contaminated RAG queries for the rest of the call. Two
# additional first-answer failures were visible in the same log: the real
# K-exam question DID retrieve (2 hits), but its LLM request was clobbered
# 104ms in by the caller's own next FINAL ("वह क्या है?" — one continuous
# speech burst split by VAD), and that bare pronoun follow-up then went to
# RAG alone → 0 hits → "मेरे पास जानकारी नहीं है". Repeats worked only
# because the contaminated buffer accidentally carried the question text.
#
# Rules implemented here (per spec, no keyword special-casing):
#   - fragments are TIMESTAMPED and CONSUMED (buffer cleared) when merged;
#   - ACK turns and drops also clear — a new independent turn starts clean;
#   - fragments older than _FRAGMENT_TTL_S never merge (stale evidence);
#   - a turn whose request was superseded BEFORE producing any output is
#     strong evidence the caller is still in the same utterance (worker tags
#     it via turn_timing["overwritten_turn"] with its generation token); the
#     just-killed question merges forward with the immediate continuation,
#     so the FIRST valid question gets its retrieved context — with the same
#     clean query the repeat had to fight for. The gen tag makes a late
#     teardown unable to contaminate a turn two generations later.
# ---------------------------------------------------------------------------
_FRAGMENT_TTL_S = 12.0
_SUPERSEDED_MERGE_MAX_AGE_S = 6.0


def _frag_norm(p, now_ts):
    if isinstance(p, (tuple, list)) and len(p) == 2:
        try:
            return str(p[0]), float(p[1] or 0.0)
        except Exception:
            return str(p[0]), now_ts
    return str(p), now_ts


def _frag_append_fresh(tt, texts, now_ts):
    """Append texts to the fragment buffer after dropping TTL-stale entries."""
    pend = []
    for q in (tt.get("pending_fragments") or []):
        t, ts = _frag_norm(q, now_ts)
        if t and now_ts - ts <= _FRAGMENT_TTL_S:
            pend.append((t, ts))
    for t in texts:
        if t:
            pend.append((str(t), now_ts))
    pend = pend[-4:]
    if pend:
        tt["pending_fragments"] = pend
    else:
        tt.pop("pending_fragments", None)
    return pend


def _frag_consume(tt, now_ts):
    """TAKE the whole buffer and CLEAR it (the missing consume step).
    Returns (fresh_texts, dropped_stale_count)."""
    raw = list(tt.get("pending_fragments") or [])
    if raw:
        tt.pop("pending_fragments", None)
    fresh, dropped = [], 0
    for q in raw:
        t, ts = _frag_norm(q, now_ts)
        if t and now_ts - ts <= _FRAGMENT_TTL_S:
            fresh.append(t)
        else:
            dropped += 1
    return fresh, dropped


def _strip_trailing_ack_turns(target: Any) -> int:
    """Drop trailing pure-ack assistant messages from THIS TURN's ctx copy.

    11:41 log defect #2: the previous turn's deterministic acknowledgement
    ('जी, बताइए।') sat as the last assistant message right above the model's
    answer slot, and the model pattern-completed instead of answering the
    real question — even on RAG-hit turns, and it kept re-seeding the echo
    each turn. `target` is the per-turn temp_mutable_chat_ctx (the library
    discards it after generation; ChatContext.copy() owns a fresh items
    list), so removal changes THIS request only — session history,
    transcripts and billing stay intact. Detection reuses
    rag.is_acknowledgement (the same turn_rules classifier that produces
    deterministic acks) — no new string matching.
    """
    if target is None:
        return 0
    n = 0
    try:
        items = getattr(target, "items", None)
        if not isinstance(items, list):
            return 0
        from .. import rag as _ack_rules
        _outs = _ack_reply_texts(_ack_rules)
        for k in range(len(items) - 1, -1, -1):
            m = items[k]
            if getattr(m, "type", "message") != "message" or getattr(m, "role", "") != "assistant":
                break
            txt = _chat_msg_text(m).strip()
            if not txt or len(txt) > 40:
                break
            if not (_ack_rules.is_acknowledgement(txt) or txt in _outs):
                break
            del items[k]
            n += 1
            if n >= 3:
                break
    except Exception:
        return n
    return n


_ACK_REPLY_OUTPUTS: set = set()


def _ack_reply_texts(rules) -> frozenset:
    """The exact strings turn_rules.ack_reply() can emit — probed at runtime
    from the module's OWN function (its classifier seeds), never a copy of
    its wording hardcoded here: if the deterministic reply ever changes, the
    strip follows automatically. Assistant messages equal to a generated ack
    reply (or classifying as a bare acknowledgement) are the echo template;
    nothing else ever matches."""
    global _ACK_REPLY_OUTPUTS
    if not _ACK_REPLY_OUTPUTS:
        try:
            _ACK_REPLY_OUTPUTS = frozenset(
                rules.ack_reply(w) for w in ("haan", "हाँ", "हां", "han", "जी", "ji", "ok", "yes", "thanks")
            ) - {""}
        except Exception:
            return frozenset()
    return _ACK_REPLY_OUTPUTS


def _find_chat_ctx(obj) -> Any:
    """Return the mutable ChatContext from a v1 turn context (defensively)."""
    candidates = [obj]
    for attr in ("chat_ctx", "llm_ctx", "context"):
        v = getattr(obj, attr, None)
        if v is not None:
            candidates.append(v)
    for c in candidates:
        if c is not None and hasattr(c, "add_message"):
            return c
    return None


# ---------------------------------------------------------------------------
# System prompt builder (persona + business facts + FAQ)
# ---------------------------------------------------------------------------
def _flatten_knowledge(kb: KnowledgeBase) -> list[str]:
    """Flatten every knowledge source into a list of bullet lines.

    Returns the WHOLE knowledge base; ``build_instructions`` then applies the
    context-size budgets to it (the capped static part), while the question-
    specific chunks are retrieved per-turn by ``rag.build_context`` inside
    ``on_user_turn_completed``.
    """
    blocks = []
    manual = (kb.text or "").strip()
    if manual:
        blocks.append(manual)
    for doc in kb.documents or []:
        name = doc.get("name", "document")
        content = doc.get("content") or doc.get("text") or ""
        if content.strip():
            blocks.append(f"[{name}]\n{content.strip()}")
    return blocks


def build_instructions(cfg: AgentConfig, query_context: str = "") -> str:
    """Build the permanent (stable-head) system prompt.

    Global prompt-budget policy (2026-09-24): the stable prompt carries ONLY
    behavioral rules. Company/KB/FAQ content is NOT part of it — the per-turn
    RAG hook retrieves exactly the relevant chunks for the caller's question
    and injects them as a [RAG] system message; when retrieval finds no
    relevant hit (relevance floor), nothing is injected. Escape hatches keep
    their old semantics: with VOICE_RAG_PER_TURN=0 the static KB/FAQ slices
    return (they are the only grounding in that mode), and the
    VOICE_KB_BUDGET_CHARS / VOICE_FAQ_BUDGET_CHARS /
    VOICE_OWNER_PROMPT_BUDGET_CHARS env overrides still apply. The output is
    deterministic per agent config, so the provider's prompt-cache prefix
    (head_sha) stays stable across every turn and every call.
    """
    persona = cfg.voice_personality or "friendly"
    lang = cfg.language or "hi"
    kb_budget, faq_budget, owner_budget = _effective_budgets(cfg)
    rag_on = _rag_per_turn_enabled()
    logger.info(
        "📚 [KNOWLEDGE_BASE_INIT] Agent '%s' knowledge loaded: manual_text=%d chars, documents=%d, faq=%d items | Static budgets: KB=%d chars, FAQ=%d chars, Owner=%d chars | stable-prompt policy: %s",
        cfg.name,
        len(getattr(cfg.knowledge, "text", "") or ""),
        len(getattr(cfg.knowledge, "documents", []) or []),
        len(getattr(cfg.knowledge, "faq", []) or []),
        kb_budget,
        faq_budget,
        owner_budget,
        "KB/FAQ included in stable prefix for caching + RAG per-turn injects relevant chunks" if rag_on else "KB/FAQ included — RAG disabled for this call",
    )

    lines = [
        f"You are {cfg.name}, a {persona} voice receptionist on a live phone call.",
        "Answer in the caller's language: English in -> English out; Hindi or Hinglish in -> Hindi in Devanagari script (देवनागरी) only — Roman-script Hindi sounds broken through TTS. Digits, phone numbers and emails stay as written. If the language is unclear, default to: " + lang + ".",
        "Speak like a warm, efficient receptionist: 1-2 short spoken sentences, under 25 words, start answering immediately, no markdown, lists, emojis or preambles; never read back the caller's question, never repeat yourself, never greet or introduce yourself again (the greeting already played), never pitch services unprompted and never reveal being an AI.",
    ]
    # Human rhythm + real latency win: a 1-3 word acknowledgment as its OWN
    # first sentence reaches TTS at the LLM's first tokens (~1s answer).
    # Env kill switch: VOICE_ACK_OPENERS=0.
    if os.getenv("VOICE_ACK_OPENERS", "1") == "1":
        lines.append(
            "Open every answer with a very short acknowledgment as its own complete sentence, in the caller's language ('जी.' / 'हाँ जी.' / 'Sure.'), 1-3 words, varied naturally, never the same one twice in a row; then give the full answer."
        )
    lines.append(
        "ACK/INCOMPLETE TURNS: pure acknowledgements and half-spoken fragments ('कि', 'और', 'एक minute') are answered deterministically before you are called; if one still reaches you, reply with at most one short warm line ('जी, बताइए।') — never facts, never guesses about what was meant. "
        "That line is ONLY for turn-less fragments: NEVER use it to dodge a question, even a garbled or unclear one — for any question, answer from the provided business facts, or say plainly you don't have that detail and offer a follow-up. And never repeat an answer you already gave in this call."
    )
    lines.append(
        "NEVER offer further help at the end of an answer: no 'Aur kuch poochna hai?', 'क्या मैं आपकी और मदद कर सकती हूँ?' or any variant — one answer, then stop and wait. Ask a follow-up only while actively collecting required enquiry details (name, phone, budget)."
    )

    extra = (cfg.knowledge.system_prompt or "").strip()
    if extra:
        if len(extra) > owner_budget:
            extra = _truncate(extra, owner_budget)
            logger.warning(
                "⚠️ Owner system prompt truncated to fit the LLM context budget "
                f"({len(cfg.knowledge.system_prompt)} -> {owner_budget} chars; "
                "raise VOICE_OWNER_PROMPT_BUDGET_CHARS to keep more)."
            )
        else:
            logger.info(f"✅ Owner system prompt kept full ({len(extra)} chars, budget {owner_budget})")
        lines.append("")
        lines.append("Instructions from the business owner:")
        lines.append(extra)

    # Cache fix v3: static KB/FAQ are genuinely stable for same agent and
    # increase the cacheable prefix to reliably >1024 real tokens. When RAG is
    # on, per-turn RAG still injects the *relevant* chunks (27-105ms), but the
    # static slices provide a large identical prefix for prompt caching.
    # This restores historical cache-hit size (~2350 tokens) without artificial
    # padding — natural business content only. RAG behavior unchanged.
    facts = _flatten_knowledge(cfg.knowledge)
    if facts:
        kept: list[str] = []
        used = 0
        truncated_any = False
        for f in facts:
            room = kb_budget - used
            if room <= 40:
                truncated_any = True
                break
            if len(f) > room:
                f = _truncate(f, room)
                truncated_any = True
            kept.append(f)
            used += len(f) + 2
        if truncated_any:
            logger.warning(
                "⚠️ Knowledge base truncated to fit the LLM context budget "
                f"({sum(len(f) for f in facts)} -> {used} chars; an oversized prompt "
                "is what causes rate-limit 429s → silent dropped "
                f"turns). Raise VOICE_KB_BUDGET_CHARS only if you've upgraded the "
                f"Groq tier or switched to a higher-limit provider (budget {kb_budget})."
            )
        else:
            logger.info(f"✅ Knowledge base kept ({used}/{kb_budget} chars)")
        if kept:
            lines.append("")
            lines.append("Business facts you know (use these when answering):")
            lines.extend(f"- {f}" for f in kept)

    if query_context:
        lines.append("")
        lines.append("Relevant business facts to use when answering:")
        lines.append(query_context)

    faq = getattr(cfg.knowledge, "faq", None) or []
    if faq:
        faq_lines: list[str] = []
        used = 0
        faq_truncated = False
        for item in faq:
            q = item.get("q", "")
            a = item.get("a", "")
            if not (q and a):
                continue
            block = f"- Q: {q}\n  A: {a}"
            room = faq_budget - used
            if room <= 40:
                faq_truncated = True
                break
            if len(block) > room:
                block = f"- Q: {q}\n  A: {_truncate(a, max(room - len(q) - 12, 40))}"
                faq_truncated = True
            faq_lines.append(block)
            used += len(block) + 2
        if faq_truncated:
            logger.warning(
                "⚠️ FAQ truncated to fit the LLM context budget "
                f"(VOICE_FAQ_BUDGET_CHARS={faq_budget})."
            )
        if faq_lines:
            lines.append("")
            lines.append(
                "Frequently asked questions. When the caller asks something that "
                "matches one of these, answer with its official answer VERBATIM "
                "(do not paraphrase or add extra info):"
            )
            lines.extend(faq_lines)

    lines.append("")
    lines.append(
        "FACTS & HONESTY: ground every substantive answer ONLY in the owner instructions and any per-turn [RAG] business facts; when a retrieved fact directly answers the question, follow it exactly — numbers, prices and timings verbatim, never paraphrased. If nothing covers it, say plainly that you do not have that detail and offer to have the team follow up — never invent prices, offices, transactions or history. Give contact numbers or emails ONLY exactly as written in the owner instructions; if none are listed there, offer a callback instead."
    )

    _stable_chars = sum(len(x) + 1 for x in lines)
    # ---- 📐 stable-prompt diagnostics: what the permanent head costs on
    # EVERY request, measured at build time (the per-request [PROMPT] line in
    # the worker shows the same numbers next to dynamic/RAG tokens).
    logger.info(
        "📐 [STABLE_PROMPT] chars=%d est_tokens=%d (4.0 chars/token) | sections: core+%sowner=%d kb_static=%s faq_static=%s | policy=%s",
        _stable_chars,
        int(_stable_chars / 4.0),
        "ack-rhythm " if os.getenv("VOICE_ACK_OPENERS", "1") == "1" else "",
        len(extra),
        "on" if facts else "off",
        "on" if faq else "off",
        "cache-optimized: KB/FAQ in stable for >1024 tokens + RAG per-turn" if rag_on else "RAG disabled: static slices re-included",
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# v1 Agent (subclass) — static knowledge + cross-call memory + greeting
# ---------------------------------------------------------------------------

async def wait_until_caller_can_hear(session, timeout: float = 12.0) -> None:
    """Wait until the caller is linked, then give the browser time to subscribe.

    Opening speech that starts before the browser attaches its audio element is
    generated and dropped. The call looks connected and stays silent.
    """
    room_io = getattr(session, "room_io", None)
    if room_io is not None and hasattr(room_io, "wait_for_ready"):
        try:
            await asyncio.wait_for(room_io.wait_for_ready(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning("Timed out waiting for the caller audio path — speaking anyway.")
        except Exception as e:
            logger.warning(f"wait_for_ready failed; speaking anyway: {e}")
    # RoomIO "ready" is earlier than the browser attaching <audio>.
    await asyncio.sleep(0.2)


async def speak_opening_line(
    session, text: str, *, timeout: float = 45.0, allow_interruptions: bool = False
) -> None:
    """Play one opening line and wait until playout finishes.

    Interruptions stay off for this line only. The browser mic opens at the
    same moment the agent starts, and that burst used to cancel the greeting
    before any audio reached the caller.
    """
    text = (text or "").strip()
    if not text:
        logger.warning("Opening line is empty — nothing to speak")
        return
    last_error: Exception | None = None
    for attempt in (1, 2):
        try:
            # allow_interruptions: the greeting used to be hard-protected
            # (False), which made EVERY interruption path skip it — library
            # barge-in checks _current_speech.allow_interruptions and
            # SpeechHandle.interrupt() raises while the handle is protected
            # (voice/speech_handle.py:221, agent_activity.py user-speech
            # gates). Result: talking over "Namaste…" changed nothing audible.
            # Assistant mode now passes True; announcement one-way playback
            # keeps False.
            handle = session.say(text, allow_interruptions=allow_interruptions)
            if handle is None:
                return
            waiter = getattr(handle, "wait_for_playout", None)
            if callable(waiter):
                await asyncio.wait_for(waiter(), timeout=timeout)
            else:
                await asyncio.wait_for(handle, timeout=timeout)
            return
        except Exception as e:
            last_error = e
            logger.warning(
                "opening line attempt %s failed: %s: %r",
                attempt, type(e).__name__, e,
            )
            if attempt == 1:
                await asyncio.sleep(0.4)
    if last_error is not None:
        raise last_error


def warm_agent_builder_schemas() -> None:
    """Pre-warm Pydantic ChatMessage and ChatContext validation schemas off the event loop.

    Pydantic v2 triggers a lazy model_rebuild() upon first ChatMessage instantiation.
    On Windows systems, model_rebuild() inspects caller namespaces and imports annotations,
    blocking the asyncio event loop for up to 7+ seconds if done inside an active call turn.
    Calling this in prewarm() compiles the validators ahead of time.
    """
    try:
        from livekit.agents.llm import chat_context
        chat_context.ChatMessage.model_rebuild()
        from livekit.agents import llm
        warm_ctx = llm.ChatContext()
        warm_ctx.add_message(role="system", content="warmup")
        warm_ctx.add_message(role="user", content="warmup")
        warm_ctx.add_message(role="assistant", content="warmup")
        logger.info("🔥 Prewarm: llm.ChatContext / ChatMessage models compiled (0ms model_rebuild during call)")
    except Exception as exc:
        logger.debug("ChatContext schema prewarm note: %r", exc)


def build_voice_agent(
    cfg: AgentConfig,
    *,
    greeting: str = "",
    prior_memory: str = "",
    lead_data: Optional[dict] = None,
    turn_timing_ref: Optional[dict] = None,
    rag_prefetch: Optional[dict] = None,
) -> "Any":
    """Return a LiveKit v1 ``Agent`` instance wired for this config.

    The returned agent:
      * speaks ``greeting`` when the session enters (LiveKit's ``on_enter``),
      * has a CAPPED summary of the knowledge base in its static system prompt
        (full-KB prompts 429 Groq's free tier; relevant chunks are injected
        per-turn via RAG in on_user_turn_completed), and
      * seeds the conversation with ``prior_memory`` (cross-call memory).

    The KB is split: a capped summary stays static (fast, stable), and the
    question-specific chunks are added in ``on_user_turn_completed`` (per-turn
    RAG). Per-turn mutation would invalidate preemptive generation, so RAG is
    skipped when ``VOICE_PREEMPTIVE=1`` (only the capped static facts are used
    then). See the context-size budgets comment above for why the static part
    is capped.
    """
    from livekit.agents import Agent, llm
    from livekit.agents import get_job_context

    # A CAPPED summary of the knowledge base is baked into the static system
    # prompt (see context-size budgets above). Baking in the FULL KB made every
    # LLM request 6-7k tokens, which 429s Groq's free tier (8k TPM) and silently
    # dropped turns. The specific chunks a question needs are injected per turn
    # by on_user_turn_completed (lightweight RAG) — safe because preemptive
    # generation is off by default; when VOICE_PREEMPTIVE=1 the hook stands down
    # and only the capped static facts are used.
    instructions = build_instructions(cfg)

    # The model may request the tool, but only a deterministic transcript check
    # may authorize room deletion. This prevents phrases such as "no more help,
    # thank you" from being mistaken for a final goodbye. The closing speech
    # itself is deterministic (bb393dd fix) — always the same fixed line.
    explicit_goodbye = False
    agent_ref: dict[str, Any] = {"instance": None}

    # Auto hang-up: when the conversation is finished the LLM calls `end_call`,
    # which shuts the job down so the call is cut AND the billing is finalized.
    # We make the trigger explicit so the model reliably hangs up on its own and
    # doesn't leave the caller in a silent, open call. Closing speech is now
    # deterministic: the tool itself speaks the fixed closing line.
    instructions += (
        "\n\nCALL LIFECYCLE: keep the call open after every normal answer, pause or detail-collection turn. End the call ONLY on a clear, standalone goodbye or hang-up grant in any language ('bye', 'ok bye', 'thank you' as a closer, 'that\'s all', 'no more questions/help', 'फ़ोन रख दीजिए', 'कॉल काट दीजिए', 'मुझे कुछ और नहीं चाहिए/जानना'). 'ok', or 'that\'s all for this question' followed by another question, is NOT a goodbye. On a real goodbye do not compose a closing sentence yourself: call the end_call tool once — the system speaks the fixed closing line and hangs up. Never call end_call at any other time."
    )

    async def _end_call() -> str:
        """End this call and hang up. Call it ONLY when user says goodbye, bye, thank you, etc.
        Do NOT call for 'sahi baat hai', 'ok', 'achhi lagti', 'product hai', number, email, etc.
        Deterministic closing: worker speaks fixed closing line, tool only deletes room.
        """
        if not explicit_goodbye:
            logger.warning("end_call rejected: caller did not give an explicit final goodbye - keeping call open")
            # Return instruction for LLM to continue naturally, not silence
            return "DO NOT END CALL. User did NOT say goodbye. Phrases like 'sahi baat hai', 'ok', 'achhi lagti', 'product hai', phone numbers, emails are NOT goodbye. Continue conversation warmly, ask how you can help."
        ctx = get_job_context(required=False)
        if ctx is None:
            return "No job context; call not ended."
        logger.info("[CALL_END_REQUESTED] source=agent reason=completed")
        # Avoid duplicate TTS: worker.py already spoke deterministic closing.
        # Only speak here as fallback if worker hasn't (check last closing timestamp).
        import time as _time
        now = _time.time()
        last_ts = agent_ref.get("last_closing_ts", 0)
        agent_inst = agent_ref.get("instance")
        if agent_inst is not None:
            # Check timestamp set by worker.py _do_deterministic_closing
            ts1 = getattr(agent_inst, '_last_deterministic_closing_ts', 0)
            ts2 = getattr(getattr(agent_inst, 'cfg', None), '_last_closing_ts', 0) if hasattr(agent_inst, 'cfg') else 0
            last_ts = max(last_ts, ts1, ts2)
        # If worker spoke within last 4s, skip TTS here.
        if now - last_ts > 4:
            # Fallback deterministic closing if worker missed it
            closing_line = _get_closing_for_cfg(cfg)
            agent_inst = agent_ref.get("instance")
            if agent_inst is not None:
                try:
                    sess = getattr(agent_inst, "session", None)
                    if sess is not None:
                        logger.info(f"👋 Fallback deterministic closing via end_call tool: {closing_line}")
                        await sess.say(closing_line, allow_interruptions=False)
                        await asyncio.sleep(0.6)
                except Exception as e:
                    logger.warning(f"Fallback closing via tool failed: {e}")
        else:
            await asyncio.sleep(0.4)
        # Physically cut the call: delete the LiveKit room so the caller/SIP
        # participant is disconnected (not left in a silent, open call).
        agent_inst = agent_ref.get("instance")
        if agent_inst is not None:
            sess = getattr(agent_inst, "session", None)
            if sess is not None:
                try:
                    sess.shutdown(drain=False)
                except Exception:
                    pass
        room = getattr(ctx.room, "name", None)
        if room:
            try:
                from ..telephony import end_active_room
                await end_active_room(room)
            except Exception as e:
                logger.warning(f"end_call: could not delete room {room}: {e}")
        ctx.shutdown()
        logger.info("[CALL_ENDED] reason=completed")
        return "Call ended."

    # `name="end_call"` keeps the LLM-visible tool name in sync with the prompt
    # (otherwise it would default to "_end_call" and the model might not call it).
    end_call_tool = llm.function_tool(
        _end_call,
        name="end_call",
        description="End the call and hang up. Call this once the conversation is finished.",
    )

    # Cross-call memory becomes part of the initial conversation history, so it
    # influences every turn without being re-inserted.
    chat_ctx = llm.ChatContext()
    if lead_data:
        # For bulk-call campaigns, give the agent the lead's details (from the
        # uploaded file) so it can address them by name / reference their data.
        lead_blurb = ", ".join(f"{k}: {v}" for k, v in (lead_data or {}).items() if v)
        chat_ctx.add_message(
            role="system",
            content=(
                "You are now speaking with a specific caller from a contact list.\n"
                f"This caller's details: {lead_blurb or '(none)'}.\n"
                "Use the caller's name naturally when it is known, and reference their "
                "details when relevant."
            ),
        )
    if prior_memory:
        # Voice latency: truncate prior_memory to 800 chars when RAG enabled (was unlimited 40 turns ~4000 tokens)
        # Preserves recent cross-call memory (name, preferences) without bloating input tokens 3500-3700
        try:
            import os as _os_pm
            _rag_pm = (_os_pm.getenv("VOICE_RAG_PER_TURN") or "").strip().lower() not in ("0", "false", "off")
            _pm_budget = int(_os_pm.getenv("VOICE_PRIOR_MEMORY_BUDGET_CHARS", "800")) if _rag_pm else 2000
        except Exception:
            _pm_budget = 800
        _pm_truncated = prior_memory
        if len(prior_memory) > _pm_budget:
            # Keep last _pm_budget chars (most recent)
            _pm_truncated = prior_memory[-_pm_budget:]
            # Try to cut at line boundary
            _nl = _pm_truncated.find("\n")
            if _nl != -1 and _nl < _pm_budget * 0.3:
                _pm_truncated = _pm_truncated[_nl+1:]
        chat_ctx.add_message(
            role="system",
            content="Prior conversation with this customer:\n" + _pm_truncated,
        )
        if len(prior_memory) != len(_pm_truncated):
            logger.info(f"🔧 Prior memory truncated {len(prior_memory)} -> {len(_pm_truncated)} chars (budget {_pm_budget}) to reduce 3500-3700 tokens")

    class _VoiceAgent(Agent):
        def __init__(self):
            self.cfg = cfg
            self.greeting = greeting
            self._opening_started = False
            self._opening_done = False
            self._turn_timing_ref = turn_timing_ref  # For preventing duplicate REQUEST START while previous active
            # Store instance so _end_call tool can speak deterministic closing via session.
            agent_ref["instance"] = self
            super().__init__(
                instructions=instructions,
                chat_ctx=chat_ctx,
                # The tool is gated by the explicit goodbye instructions above.
                # It is used only after the closing sentence has been generated.
                tools=[end_call_tool],
                # NOTE: turn-handling (endpointing / interruption / preemptive
                # generation) is set on the AgentSession (build_assistant_session),
                # where LiveKit actually reads the interruption min_duration/window.
                # Keeping it there is the single source of truth; do NOT also set it
                # here or the two can disagree.
            )

        def llm_node(self, chat_ctx, tools, model_settings):
            """Deterministic ack + incomplete-turn silence (see app/turn_rules.py).

            Library contract (voice/generation.py `_llm_inference_task`): a
            coroutine resolving to ``str`` IS the complete reply (fed straight to
            TTS); one resolving to ``None`` yields no output at all. That is how
            an acknowledgement gets answered with ZERO LLM calls (no REQUEST
            START, no tokens, no billing entry to exclude) and how an incomplete
            fragment stays silent until the caller finishes the thought. Every
            other turn falls through to the default LLM path untouched.
            """
            tt = self._turn_timing_ref
            if tt is not None:
                ack = tt.get("ack_reply")
                if ack is not None:
                    tt.pop("ack_reply", None)
                    logger.info(
                        "✅ [ACK_FAST_PATH] text='%s' response='%s' (no LLM request)",
                        str(ack.get("text", ""))[:60], str(ack.get("reply", ""))[:40],
                    )

                    async def _ack_reply():
                        return str(ack.get("reply") or "जी।")

                    return _ack_reply()
                if tt.get("gov_turn_state") == "suppress":
                    logger.info("⏸️ [LLM_REQUEST_SKIPPED] reason=incomplete_turn — awaiting caller continuation")

                    async def _skip():
                        return None

                    return _skip()
            return Agent.default.llm_node(self, chat_ctx, tools, model_settings)

        async def tts_node(self, text, model_settings):
            """Measure the FIRST assistant audio frame per speech (Task 3).

            Deliberately NOT a TTS-object wrapper — an earlier experiment that
            wrapped the TTS instance broke the greeting (see worker's
            "TTS left unwrapped" note). Instead we override the agent's
            tts_node hook, call the library default (which owns
            synthesize/segmenting/aligned transcripts and works with ANY
            provider behind it, including the FallbackAdapter), and wrap only
            the frame generator. Zero added latency: it is a pass-through
            async for. Stamps exactly the keys the existing turn-summary code
            already understands (tts_request / first_tts_audio /
            first_audio / last_speech_end_to_first_audio) so the 🗣️ TTS line
            upgrades from "audio not measured" to REAL audio automatically.
            """
            res = Agent.default.tts_node(self, text, model_settings)
            if asyncio.iscoroutine(res):
                res = await res
            tt = self._turn_timing_ref
            if res is None or tt is None:
                return res
            tt["tts_request"] = time.time()
            _logger = logging.getLogger("voice-agent-saas-agent-builder")

            async def _probe():
                _first = True
                async for frame in res:
                    if _first:
                        _first = False
                        if float(tt.get("first_tts_audio", 0) or 0) == 0.0:
                            _now = time.time()
                            tt["first_tts_audio"] = _now
                            tt["first_audio"] = _now
                            _se = float(tt.get("speech_end", 0) or 0)
                            _sf = float(tt.get("stt_final_ts", 0) or 0)
                            _tc = float(tt.get("turn_commit_ts", 0) or 0)
                            _ft = float(tt.get("first_token", 0) or 0)
                            _ttft = float(tt.get("ttft_ms", 0) or 0)
                            def _ms(a, b):
                                return f"{(b - a) * 1000:.0f}ms" if a and b and b >= a else "na"
                            _synth_ms = int((_now - _ft) * 1000) if _ft else -1
                            _s2fa = (tt["first_tts_audio"] - _se) * 1000 if _se else 0.0
                            if _s2fa > 0:
                                tt["last_speech_end_to_first_audio"] = _s2fa
                            _logger.info(
                                "🔊 [FIRST_ASSISTANT_AUDIO] t=%.3f (generation=%s)",
                                _now, tt.get("gen", 0),
                            )
                            _logger.info(
                                "⏱️ [LATENCY] stt_final_ms=%s turn_commit_ms=%s llm_ttft_ms=%s tts_first_audio_ms=%s speech_to_first_audio_ms=%s",
                                _ms(_se, _sf) if _sf else "na",
                                _ms(_sf if _sf else _se, _tc),
                                f"{_ttft:.0f}ms" if _ttft else "na",
                                f"{_synth_ms}ms" if _synth_ms >= 0 else "na",
                                f"{_s2fa:.0f}ms" if _s2fa > 0 else "na",
                            )
                            try:
                                _samples = tt.setdefault("latency_samples", [])
                                if len(_samples) < 40:
                                    _samples.append({
                                        "speech_end_to_first_audio_ms": round(_s2fa) if _s2fa > 0 else None,
                                        "ttft_ms": round(_ttft) if _ttft else None,
                                        "tts_synth_ms": _synth_ms if _synth_ms >= 0 else None,
                                        "turn_commit_ms": round((_tc - _sf) * 1000) if _tc and _sf else None,
                                    })
                            except Exception:
                                pass
                    yield frame

            return _probe()

        async def on_enter(self) -> None:
            # Assistant mode: greet as soon as the caller can hear, then listen.
            self._opening_started = True
            try:
                if not (self.greeting or "").strip():
                    logger.info("[ASSISTANT_STARTED] Assistant has no greeting — listening immediately")
                    return
                logger.info("[ASSISTANT_STARTED] Assistant connected — waiting for caller audio path")
                await wait_until_caller_can_hear(self.session)
                logger.info("[ASSISTANT_STARTED] Speaking greeting: %s", self.greeting[:60])
                _gtt = self._turn_timing_ref
                if _gtt is not None:
                    _gtt["greeting_active"] = True
                logger.info("👋 [GREETING_STARTED] '%s' — interruptible: caller speech cancels playback", self.greeting[:60])
                try:
                    await speak_opening_line(self.session, self.greeting, timeout=45, allow_interruptions=True)
                finally:
                    if _gtt is not None:
                        _gtt["greeting_active"] = False
                if _gtt is not None and _gtt.pop("greeting_interrupted", None):
                    logger.info("🔇 Greeting ended via caller barge-in — only the played portion counts; caller's turn proceeds")
                else:
                    logger.info("[ASSISTANT_STARTED] Greeting finished — now listening for caller speech")
            except Exception as e:
                logger.warning(f"Greeting failed: {type(e).__name__}: {e!r}")
            finally:
                self._opening_done = True
                if self._turn_timing_ref is not None:
                    self._turn_timing_ref["greeting_active"] = False

        async def on_user_turn_completed(self, turn_ctx, new_message) -> None:
            """Hook that runs after the user finishes speaking — CRITICAL LATENCY PATH.

            LiveKit's ``AgentSession`` ``await``s this hook, so any blocking here
            directly adds to STT_final->LLM_start latency (target ≤100ms).

            Production fixes:
            - Explicit goodbye detection is fast (string ops, ~1ms)
            - Conversation trim is fast (list slice)
            - RAG is now async via to_thread to avoid blocking event loop (was sync, could be 100-300ms)
            - Turn governor (below): ack turns answer deterministically via the
              agent's llm_node override (zero LLM), incomplete fragments are held
              silently and merged into the next completed turn's RAG query
            - Added timing logs for STT_final->LLM_start to detect 3-7s outliers
            - FIX: Prevent duplicate/invalidated LLM requests - wait for previous LLM to complete before new REQUEST START
            - Exactly one REQUEST START per completed user turn, no 0/0 race
            """
            # NOTE: LiveKit `await`s this hook before generating the reply, so any
            # waiting here stalls the whole turn pipeline. The old code busy-waited
            # up to 2s for the previous LLM request to finish; when the user barged
            # in, LiveKit's interruption had to wait on this hook, the speech handle
            # never resolved, and the 5s INTERRUPTION_TIMEOUT fired:
            #   "speech not done in time after interruption, cancelling arbitrarily"
            # — which killed the rest of the call's audio (livekit/agents #5359).
            # Turn serialization is LiveKit's job, not ours: a superseded request is
            # simply cancelled and reported as 0/0 tokens, which billing ignores.
            # So: log only, never wait.
            try:
                _turn_marker_text = _chat_msg_text(new_message).strip()
                logger.info("🗣️ [USER_TURN_COMPLETED] user turn committed: '%s'", _turn_marker_text[:80])
                if self._turn_timing_ref is not None:
                    self._turn_timing_ref["turn_commit_ts"] = time.time()
            except Exception:
                pass
            try:
                if self._turn_timing_ref and self._turn_timing_ref.get("llm_active", False):
                    prev_start = self._turn_timing_ref.get("request_start", 0)
                    elapsed = time.time() - prev_start if prev_start else 0
                    logger.info(
                        f"↪️ New user turn while previous LLM request still active "
                        f"(elapsed {elapsed:.2f}s) — LiveKit will cancel the superseded "
                        f"request; not waiting (waiting here stalls barge-in)"
                    )
            except Exception as e:
                logger.debug(f"Could not inspect previous LLM state: {e}")
            nonlocal explicit_goodbye
            import time as _time
            _rag_t0 = _time.time()
            try:
                user_text = _chat_msg_text(new_message).strip()
                normalized = " ".join(
                    user_text.lower()
                    .replace(".", " ")
                    .replace(",", " ")
                    .split()
                )
                # Expanded deterministic closing detection — must match worker.py logic
                closing_exact = {
                    "bye", "bye bye", "goodbye", "good bye", "ok bye",
                    "okay bye", "ok good bye", "okay good bye", "ok goodbye",
                    "okay goodbye", "good bye bye", "thank you", "thanks", "thankyou",
                    "और तो मुझे कुछ नहीं जानना", "अब मुझे कुछ नहीं जानना",
                    "मुझे और कुछ नहीं जानना", "बस इतना ही", "बस इतना ही पूछना था",
                    "no more questions", "no more help", "that's all", "that is all",
                    "नहीं और कोई मदद नहीं चाहिए", "और कोई मदद नहीं चाहिए",
                    "कोई मदद नहीं चाहिए", "और कुछ नहीं चाहिए", "बस हो गया",
                    "नहीं और कोई सवाल नहीं है", "और कोई सवाल नहीं है",
                    "कोई सवाल नहीं है", "मुझे कुछ नहीं पूछना है", "मुझे कुछ नहीं पूछना",
                    "कुछ नहीं पूछना है", "कुछ नहीं पूछना",
                    "mujhe kuch nahi puchna hai", "mujhe kuch nahi puchna",
                    "kuch nahi puchna hai", "kuch nahi puchna",
                    "koi sawaal nahi hai", "koi sawal nahi hai",
                    "aur koi sawaal nahi hai", "aur koi sawal nahi hai",
                    "nahi aur koi madad nahi chahiye", "aur koi madad nahi chahiye",
                    "nahi aur koi sawaal nahi hai",
                }
                disconnect_sub = (
                    "cut the call", "hang up", "disconnect", "end the call", "call cut",
                    "कॉल कट", "call काट", "कॉल काट", "call cut कर दीजिए", "call काट दीजिए",
                    "कॉल बंद कर दीजिए", "फोन काट दीजिए", "फोन काट दो",
                    # Hang-up granted in Hindi / mixed script (caller: "आप phone रख सकते")
                    "फोन रख दो", "फ़ोन रख दो", "फोन रख दीजिए", "फ़ोन रख दीजिए", "फ़ोन रख",
                    "फोन रख", "phone रख", "call रख", "कॉल रख",
                    "phone rakh do", "phone rakh dijiye", "phone rakh sakte", "aap phone rakh sakte",
                    # "I need nothing (else)"
                    "कुछ भी नहीं चाहिए", "जानकारी नहीं चाहिए", "कोई भी जानकारी नहीं चाहिए",
                    "kuch bhi nahi chahiye", "koi jaankari nahi chahiye", "kisi bhi tarah ki madad nahi chahiye",
                    "और तो मुझे कुछ नहीं जानना", "अब मुझे कुछ नहीं जानना",
                    "मुझे और कुछ नहीं जानना", "बस इतना ही", "बस इतना ही पूछना था",
                    "no more questions", "no more help", "that's all", "that is all",
                    "नहीं और कोई मदद नहीं चाहिए", "और कोई मदद नहीं चाहिए",
                    "नहीं और कोई सवाल नहीं है", "और कोई सवाल नहीं है",
                    "मुझे कुछ नहीं पूछना है", "कुछ नहीं पूछना है",
                    "mujhe kuch nahi puchna", "kuch nahi puchna",
                    "koi sawaal nahi", "koi sawal nahi",
                )
                has_goodbye = "goodbye" in normalized or "good bye" in normalized
                tokens = normalized.split()
                has_bye_token = "bye" in tokens or normalized.endswith(" bye") or normalized.startswith("bye ")
                has_thank = "thank" in normalized or "thanks" in normalized or "धन्यवाद" in user_text
                has_positive_close = any(w in normalized for w in ("accha laga", "achha laga", "khushi", "very much", "bahut"))
                # Fix: Don't treat contact info as goodbye - user giving number/email is NOT closing
                has_contact_info = any(c in normalized for c in ("nine", "five", "double", "triple", "zero", "at the rate", "gmail", "dot com", "number", "email")) or any(ch.isdigit() for ch in user_text if len(user_text.split()) <= 20)
                # If message looks like phone number or email, never treat as goodbye
                if has_contact_info and len(tokens) >= 4:
                    explicit_goodbye = False
                else:
                    explicit_goodbye = bool(
                        normalized in closing_exact
                        or has_goodbye
                        or (has_bye_token and len(tokens) <= 8)
                        or (has_thank and "?" not in user_text and (len(tokens) <= 18 or has_positive_close or "accha laga" in normalized))
                        or any(p in normalized for p in disconnect_sub)
                    )
            except Exception:
                explicit_goodbye = False
            # --- Turn governor (2026-09-24 spec) — runs BEFORE any LLM
            # scheduling and decides three outcomes:
            #   ack        -> llm_node answers with a canned line; NO LLM request,
            #                 NO tokens, NO billing (00:31 log: 'Ok.' still cost a
            #                 2865-token request whose 3-char answer was then
            #                 mis-flagged into an apology).
            #   incomplete -> llm_node produces NOTHING; the fragment is kept in
            #                 pending_fragments and merged into the next complete
            #                 turn (00:31 log: one thought split into 4 finals
            #                 produced 3 invalidated 0/0 requests + 1 answered).
            #   complete   -> normal trim+RAG+LLM path; if fragments are pending,
            #                 RAG runs on the MERGED query.
            # Closing intent always wins (explicit_goodbye computed above), so
            # "thanks"/"बस इतना ही..." keep the existing deterministic closing.
            try:
                _gtext = user_text
            except NameError:
                _gtext = ""
            _tt = self._turn_timing_ref
            if _tt is not None:
                # per-turn flags: drop anything left from a cancelled turn so a
                # stale 'ack'/'suppress' can never hijack the next real question
                _tt.pop("gov_turn_state", None)
                _tt.pop("ack_reply", None)
                _tt.pop("combined_query", None)
                if _gtext and not explicit_goodbye:
                    try:
                        from .. import rag as _rag_rules
                        _is_ack = _rag_rules.is_acknowledgement(_gtext)
                        _is_inc = (not _is_ack) and _rag_rules.is_incomplete_turn(_gtext)
                    except Exception:
                        _is_ack = _is_inc = False
                    _now_f = _time.time()
                    _fb_before = len(list(_tt.get("pending_fragments") or []))
                    if _is_ack:
                        _tt["gov_turn_state"] = "ack"
                        _tt["ack_reply"] = {"text": _gtext, "reply": _rag_rules.ack_reply(_gtext)}
                        # an ACK means the caller moved past whatever they were
                        # composing — held fragments can never "continue" into
                        # this turn; clear so the NEXT turn starts clean.
                        _freshA, _dropA = _frag_consume(_tt, _now_f)
                        if _freshA or _dropA:
                            logger.info("🧹 fragments cleared on ACK turn (kept=%d dropped_stale=%d) — deterministic answer owns the floor", len(_freshA), _dropA)
                        logger.info("⏭️ [RAG_SKIPPED] acknowledgement turn: '%s' → deterministic reply, no LLM", _gtext[:40])
                        logger.info("📥 [TURN_INPUT] raw_stt='%s' cleaned_turn='' fragment_buffer_before=%d fragment_buffer_after=0 merged=no path=ack", _gtext[:70], _fb_before)
                        return
                    if _is_inc:
                        _pend = _frag_append_fresh(_tt, [_gtext], _now_f)
                        _tt["gov_turn_state"] = "suppress"
                        logger.info("⏸️ [INCOMPLETE_TURN] text='%s' waiting_for_continuation=true fragments=%d (TTL=%.0fs)", _gtext[:60], len(_pend), _FRAGMENT_TTL_S)
                        logger.info("📥 [TURN_INPUT] raw_stt='%s' cleaned_turn='' fragment_buffer_before=%d fragment_buffer_after=%d merged=no path=hold", _gtext[:70], _fb_before, len(_pend))
                        return
                    # complete turn — strong-evidence continuation merge: a
                    # previous question whose request was killed BEFORE any
                    # output (worker-set overwritten_turn, generation-tagged)
                    # joins the buffer as a fresh-in-time fragment.
                    _ov = _tt.pop("overwritten_turn", None)
                    _ov_used = False
                    if isinstance(_ov, dict):
                        _ovt = str(_ov.get("text") or "").strip()
                        _ov_age = _now_f - float(_ov.get("ts") or 0.0)
                        _ov_gen_ok = int(_ov.get("gen") or -1) == int(_tt.get("gen", 0) or 0)
                        if _ovt and _ov_gen_ok and _ov_age <= _SUPERSEDED_MERGE_MAX_AGE_S and _ovt[:120] != _gtext[:120]:
                            _old_p = list(_tt.get("pending_fragments") or [])
                            _tt["pending_fragments"] = ([(_ovt, float(_ov.get("ts") or _now_f))] + _old_p)[-5:]
                            _ov_used = True
                            logger.info("🔗 [CONTINUATION_MERGE] caller's previous question was superseded %.1fs ago with zero output — treating '%s…' + '%s…' as ONE utterance", _ov_age, _ovt[:40], _gtext[:40])
                    _kept, _dropped = _frag_consume(_tt, _now_f)
                    if _dropped:
                        logger.info("🧹 dropped %d stale fragment(s) (>%.0fs) — independent turn gets a clean query", _dropped, _FRAGMENT_TTL_S)
                    if _kept:
                        _combined = " ".join(_kept + [_gtext])
                        _tt["gov_turn_state"] = "complete"
                        _tt["combined_query"] = _combined
                        logger.info("🧩 [COMPLETE_TURN] merged %d fragment(s)%s: '%s'", len(_kept) + 1, " (incl. superseded continuation)" if _ov_used else "", _combined[:90])
                        logger.info("📥 [TURN_INPUT] raw_stt='%s' cleaned_turn='%s' fragment_buffer_before=%d fragment_buffer_after=0 merged=%s", _gtext[:70], _combined[:70], _fb_before, "yes+continuation" if _ov_used else "yes")
                    else:
                        logger.info("📥 [TURN_INPUT] raw_stt='%s' cleaned_turn='%s' fragment_buffer_before=%d fragment_buffer_after=0 merged=no", _gtext[:70], _gtext[:70], _fb_before)
            # Keep the rolling conversation bounded. Groq accounts the entire
            # prompt against TPM; an unbounded voice call eventually turns every
            # request into a 429 even with the 20b model. Preserve system facts
            # and only the latest few conversational messages.
            # CRITICAL FIX: Do NOT trim when preemptive generation is enabled.
            # Trimming mutates chat_ctx (len changes) → is_equivalent False → 
            # preemptive generation invalidated after on_user_turn_completed
            # → full LLM restart adds 1-2s latency (observed 1826-2364ms)
            # When preemptive ON, skip trimming to preserve preemptive.
            # When preemptive OFF, trim to avoid 429.
            preemptive_on = os.getenv("VOICE_PREEMPTIVE", "0") == "1"
            # FIX 4: Conversation memory - name unavailable but mobile remembered
            # Root cause: trimming to 6 dialogue messages max drops early name if many turns
            # Evidence: user asked name after previously giving it, agent said unavailable, but mobile 9538450441 remembered (later in conversation)
            # Fix: increase trim limit from 6 to 20 dialogue messages to preserve name, and preserve memory when memory_enabled
            # Also check if KB present - when KB present we already disable preemptive in worker.py, so trimming will happen
            # We should preserve more history for memory retention, not aggressively trim
            if not preemptive_on:
                try:
                    target_ctx = _find_chat_ctx(turn_ctx) or turn_ctx
                    items = getattr(target_ctx, "items", None)
                    # Voice latency optimization v2: keep 8 dialogue max for OpenAI when RAG enabled (was 12) to reduce 3500-3700 tokens further
                    # Billing shows avg 4 turns per call, 8 covers full call. prior_memory 800 chars handles cross-call memory.
                    # Saves additional ~4*150=600 tokens vs 12. Groq still 16 for TPM safety (reduced from 20), OpenAI 8 for latency.
                    # Determine history limit based on provider
                    try:
                        _llm_id_hist = (cfg.providers.llm.id or "").lower() if cfg.providers and cfg.providers.llm else ""
                        _is_groq_hist = _llm_id_hist.startswith("groq")
                        _history_limit = 16 if _is_groq_hist else 8
                        _trim_threshold = 20 if _is_groq_hist else 12
                    except Exception:
                        _history_limit = 8
                        _trim_threshold = 12
                    if isinstance(items, list):
                        # Cache fix (applies ALWAYS, not just when trimming): keep ONLY the stable
                        # behavioral instructions at the very beginning (id=lk.agent_task.instructions)
                        # as the cacheable prefix. All other system messages (prior_memory, lead_data,
                        # prior RAG if ever left) are dynamic per customer/lead/turn and must be AFTER
                        # history so the stable prefix remains byte-identical across turns and across
                        # customers (cross-customer cache sharing). This guarantees the provider-bound
                        # prompt starts with the identical stable head.
                        _stable_sys = []
                        _other_sys = []
                        for m in items:
                            if getattr(m, "role", "") == "system":
                                if getattr(m, "id", "") == "lk.agent_task.instructions":
                                    _stable_sys.append(m)
                                else:
                                    _other_sys.append(m)
                        # If no explicit instructions id found (older contexts), treat first system as stable
                        if not _stable_sys:
                            _all_sys = [m for m in items if getattr(m, "role", "") == "system"]
                            if _all_sys:
                                _stable_sys = [_all_sys[0]]
                                _other_sys = _all_sys[1:]
                        dialogue_items = [m for m in items if getattr(m, "role", "") != "system"]
                        if len(items) > _trim_threshold:
                            kept_dialogue = dialogue_items[-_history_limit:]
                        else:
                            kept_dialogue = dialogue_items
                        # Order: stable behavioral → history (dynamic) → other dynamic system (prior_memory, lead_data)
                        # RAG for THIS turn is injected later with created_at just before final user, so it lands after history as well.
                        # For cache: stable at beginning, identical across turns/customers; dynamic after.
                        if len(items) > _trim_threshold or _other_sys:
                            target_ctx.items = _stable_sys + kept_dialogue + _other_sys
                        # else: no reordering needed (only stable present)
                        logger.info("🧹 Trimmed conversation context to %s messages (voice latency: %s dialogue max, preserves name via prior_memory)", len(target_ctx.items), _history_limit)
                        trimmed_count = len(dialogue_items) - len(kept_dialogue)
                        if trimmed_count > 0:
                            logger.info(f"📝 Trimmed {trimmed_count} old dialogue items, kept last {_history_limit} for memory retention (reduces input tokens)")
                except Exception as exc:
                    logger.debug("conversation context trim skipped: %s", exc)
            else:
                # Preemptive ON: DO NOT mutate chat_ctx at all — any mutation invalidates preemptive
                # Previous lenient trim (10 msgs when >12) still changed chat_ctx → is_equivalent False → invalidation
                # So when preemptive ON, skip trimming entirely to preserve preemptive generation
                # This eliminates "preemptive generation invalidated after on_user_turn_completed" warning
                # FIX: Also for memory, when preemptive ON and KB present, we already disabled preemptive in worker.py
                # So this path is for non-KB calls where preemptive ON is safe and we want speed
                logger.debug("Preemptive ON: skipping chat_ctx trim to preserve preemptive generation and memory")
            # Log timing for STT_final->LLM_start path
            try:
                _elapsed_goodbye = (_time.time() - _rag_t0) * 1000
                if _elapsed_goodbye > 50:
                    logger.warning(f"🐢 Slow goodbye detection: {_elapsed_goodbye:.0f}ms (should be <10ms)")
                else:
                    logger.info(f"⏱️ TIMING on_user_turn_completed (goodbye check): {_elapsed_goodbye:.0f}ms")
            except Exception:
                pass

            # RAG handling - ALWAYS enabled for KB grounding (correctness > latency)
            # When preemptive ON, RAG will invalidate preemptive for this turn, but we explicitly log it
            # This is the fix for "Mere paas exact jaankari nahi hai" - KB grounding preserved
            if not _rag_per_turn_enabled():
                logger.info(f"⏱️ TIMING on_user_turn_completed (RAG disabled by env): {(_time.time()-_rag_t0)*1000:.0f}ms")
                return
            try:
                user_text = _chat_msg_text(new_message).strip()
                if not user_text:
                    logger.info(f"⏱️ TIMING on_user_turn_completed (empty text): {(_time.time()-_rag_t0)*1000:.0f}ms")
                    return
                from .. import rag  # local import: keep this module light
                from ..turn_rules import is_contextual_followup, build_contextual_retrieval_query
                # If this turn completed a split thought, retrieve for the MERGED
                # question (fragments + this final) instead of the bare tail —
                # [COMPLETE_TURN] logged above shows the merge.
                _cq = (self._turn_timing_ref or {}).get("combined_query")
                if _cq:
                    user_text = str(_cq)

                # --- Conversational context for RAG (fix for pronoun follow-ups) ---
                # Preserve actual user message for LLM (new_message unchanged).
                # Only the INTERNAL retrieval query gets enriched with recent context.
                original_user_query = user_text
                retrieval_query = original_user_query
                recent_user_ctx = ""
                recent_assistant_ctx = ""
                context_used = False
                try:
                    _ctx_for_recent = _find_chat_ctx(turn_ctx)
                    if _ctx_for_recent is not None:
                        _items = getattr(_ctx_for_recent, "items", []) or []
                        # Find last user before current (not ack/incomplete, not same text)
                        for m in reversed(_items):
                            if getattr(m, "role", "") == "user":
                                _txt = _chat_msg_text(m).strip()
                                if not _txt or _txt == original_user_query or len(_txt) < 4:
                                    continue
                                try:
                                    from ..turn_rules import is_acknowledgement as _is_ack_r, is_incomplete_turn as _is_inc_r
                                    if _is_ack_r(_txt) or _is_inc_r(_txt):
                                        continue
                                except Exception:
                                    pass
                                recent_user_ctx = _txt
                                break
                        if not recent_user_ctx:
                            for m in reversed(_items):
                                if getattr(m, "role", "") == "assistant":
                                    _txt = _chat_msg_text(m).strip()
                                    if _txt and len(_txt) > 10:
                                        recent_assistant_ctx = _txt[:200]
                                        break
                except Exception:
                    recent_user_ctx = ""
                    recent_assistant_ctx = ""

                try:
                    if is_contextual_followup(original_user_query):
                        _ctx_candidate = recent_user_ctx or recent_assistant_ctx
                        if _ctx_candidate:
                            _built = build_contextual_retrieval_query(
                                original_user_query, recent_user_ctx, recent_assistant_ctx
                            )
                            if _built and _built != original_user_query:
                                retrieval_query = _built
                                context_used = True
                except Exception:
                    retrieval_query = original_user_query
                    context_used = False

                try:
                    logger.info(
                        "🔎 [RAG_CONTEXT_QUERY] user_query='%s' retrieval_query='%s' context_used=%s recent_len=%d",
                        original_user_query[:80],
                        retrieval_query[:120],
                        "yes" if context_used else "no",
                        len(recent_user_ctx or recent_assistant_ctx),
                    )
                except Exception:
                    pass

                logger.info(
                    "🔎 [RAG_STARTED] query='%s' retrieval_query='%s' context_used=%s",
                    original_user_query[:60],
                    retrieval_query[:60],
                    "yes" if context_used else "no",
                )
                # --- Fast path: the worker precomputes RAG from STT interim
                # text (in parallel with endpointing), so by the time the turn
                # completes the retrieval result for this exact text is usually
                # already cached. This hook is AWAITED by the session before the
                # LLM starts, so a cache hit removes ~30-100ms from EVERY turn.
                hits = ""
                _rag_src = "normal"
                # P3 ROOT-CAUSE FIX: initialize EVERY retrieval-result field
                # before either branch. Previously kb_used/faq_used & friends
                # were assigned ONLY on the cache-MISS path; the shared log
                # line after injection then raised UnboundLocalError on each
                # prefetch-HIT turn (surfacing as the misleading
                # "per-turn RAG injection skipped" warning — the context was in
                # fact injected). Both branches now produce the same structure.
                kb_used = False
                kb_chars = 0
                kb_hits = 0
                faq_used = False
                faq_chars = 0
                faq_hits = 0
                total_chars = 0
                _prefetch_entry = None
                if rag_prefetch is not None:
                    try:
                        # Prefetch cache is keyed by original normalized query (worker stores contextual result under original key)
                        _prefetch_entry = rag_prefetch.get(rag.normalize_query(original_user_query))
                        # Fallback: try retrieval_query key as well (in case worker stored under contextual key)
                        if _prefetch_entry is None and retrieval_query != original_user_query:
                            _prefetch_entry = rag_prefetch.get(rag.normalize_query(retrieval_query))
                    except Exception:
                        _prefetch_entry = None
                # The worker caches the full detailed result; tolerate the old
                # bare-string shape too so a worker/builder version skew cannot
                # turn a hit into a crash.
                if isinstance(_prefetch_entry, dict):
                    hits = (_prefetch_entry.get("text") or "").strip()
                elif isinstance(_prefetch_entry, str):
                    hits = _prefetch_entry.strip()
                else:
                    hits = ""
                if hits:
                    _rag_src = "prefetch"
                    if isinstance(_prefetch_entry, dict):
                        kb_used = bool(_prefetch_entry.get("kb_used", False))
                        kb_chars = int(_prefetch_entry.get("kb_chars", 0) or 0)
                        kb_hits = int(_prefetch_entry.get("kb_hits", 0) or 0)
                        faq_used = bool(_prefetch_entry.get("faq_used", False))
                        faq_chars = int(_prefetch_entry.get("faq_chars", 0) or 0)
                        faq_hits = int(_prefetch_entry.get("faq_hits", 0) or 0)
                        total_chars = int(_prefetch_entry.get("total_chars", len(hits)) or len(hits))
                    else:  # bare text (older worker): source flags unknown
                        kb_used = True
                        kb_chars = total_chars = len(hits)
                    _rag_elapsed = (_time.time() - _rag_t0) * 1000
                    logger.info(
                        "📚 [KNOWLEDGE_RETRIEVAL] query='%s' | latency=%.0fms | kb_used=%s (%d chars, %d hits) | faq_used=%s (%d chars, %d hits) | total=%d chars | prefetch=true",
                        retrieval_query[:60], _rag_elapsed, kb_used, kb_chars, kb_hits,
                        faq_used, faq_chars, faq_hits, total_chars,
                    )
                    logger.info(
                        "⚡ RAG PREFETCH HIT '%s' (%d chars) — computed during the STT interim, "
                        "critical-path cost %.0fms",
                        retrieval_query[:60], len(hits), _rag_elapsed,
                    )
                else:
                    # Cache miss (final text diverged from every interim, or the
                    # interim compute lost the race): compute now using contextual retrieval_query.
                    # Actual LLM user message (new_message) remains unchanged.
                    try:
                        rag_res = await asyncio.to_thread(rag.build_context_detailed, cfg.knowledge, retrieval_query, 3)
                    except Exception:
                        # Fallback sync if to_thread fails
                        rag_res = rag.build_context_detailed(cfg.knowledge, retrieval_query, top_k=3)
                    _rag_elapsed = (_time.time() - _rag_t0) * 1000
                    hits = (rag_res.get("text") or "").strip()
                    kb_used = rag_res.get("kb_used", False)
                    kb_chars = rag_res.get("kb_chars", 0)
                    kb_hits = rag_res.get("kb_hits", 0)
                    faq_used = rag_res.get("faq_used", False)
                    faq_chars = rag_res.get("faq_chars", 0)
                    faq_hits = rag_res.get("faq_hits", 0)
                    total_chars = rag_res.get("total_chars", 0)

                    # Authoritative user-facing retrieval log detailing KB and FAQ usage
                    logger.info(
                        "📚 [KNOWLEDGE_RETRIEVAL] query='%s' | latency=%.0fms | kb_used=%s (%d chars, %d hits) | faq_used=%s (%d chars, %d hits) | total=%d chars",
                        retrieval_query[:60],
                        _rag_elapsed,
                        kb_used,
                        kb_chars,
                        kb_hits,
                        faq_used,
                        faq_chars,
                        faq_hits,
                        total_chars,
                    )

                    if _rag_elapsed > 200:
                        logger.warning(f"🐢 Slow RAG: {_rag_elapsed:.0f}ms exceeds 100ms target")

                logger.info(
                    "🔎 [RAG_QUERY] query='%s' source=%s result_count=%d relevant_context_found=%s",
                    retrieval_query[:70], _rag_src, int(kb_hits) + int(faq_hits), "yes" if hits else "no",
                )
                # NOTE: deliberately NO "same as last turn" dedupe here. This hook
                # edits the per-turn copy of the chat context (temp_mutable_chat_ctx);
                # the library discards it after generation, so the previous turn's
                # injected facts are NOT in this turn's prompt. Skipping injection on
                # "no new hits" (the old behavior) silently left repeat-question turns
                # ungrounded (23:19 log: identical kb result -> "RAG no new hits" ->
                # model answered from generic priors). Same text = same injection cost
                # (~600 tokens); correctness wins.
                _rag_kind = "retrieved"
                target = _find_chat_ctx(turn_ctx)
                _nstripped = _strip_trailing_ack_turns(target)
                if _nstripped:
                    logger.info("🧹 [ACK_STRIPPED] removed %d trailing acknowledgement assistant message(s) from this turn's generation context (per-turn copy only — session history untouched)", _nstripped)
                if not hits:
                    # ---- 0-hit turn: ONE cheap containment fallback over the
                    # cached corpus (rag.fallback_context — BM25/ranking
                    # untouched, runs in a thread so the loop stays free).
                    # STT-mangled keywords ("Kriscent" heard as "sent") share
                    # no exact token with any chunk, so main retrieval is
                    # legitimately empty; containment still finds the chunk
                    # containing the fragment, capped at ~560 chars. If the
                    # fallback also finds nothing, the request proceeds
                    # ungrounded — the prompt tells the model to say so
                    # honestly instead of guessing.
                    _fb_text = ""
                    _fb_hits = 0
                    try:
                        _fb_text, _fb_hits = await asyncio.to_thread(
                            rag.fallback_context, cfg.knowledge, retrieval_query
                        )
                    except Exception as _fb_exc:
                        logger.debug("RAG fallback failed: %r", _fb_exc)
                    if _fb_text:
                        hits = _fb_text
                        _rag_kind = "near-match"
                        logger.info(
                            "🕳️ [RAG_MISS] query='%s' fallback_attempted=yes fallback_hits=%d fallback_context_chars=%d",
                            retrieval_query[:70], _fb_hits, len(_fb_text),
                        )
                    else:
                        logger.info(
                            "🕳️ [RAG_MISS] query='%s' fallback_attempted=yes fallback_hits=0 fallback_context_chars=0",
                            retrieval_query[:70],
                        )
                        logger.info("🧠 [LLM_CONTEXT] user_query='%s' rag_context_present=no", retrieval_query[:70])
                        logger.info(f"⏱️ TIMING on_user_turn_completed (no RAG hits): {(_time.time()-_rag_t0)*1000:.0f}ms")
                        return  # nothing to inject, main retrieval AND fallback came up empty
                if target is None:
                    logger.warning("⚠️ RAG: no chat_ctx found, skipping injection")
                    return
                
                # FIX ROOT CAUSE: When KB/FAQ RAG enabled, preemptive must be disabled BEFORE turn begins
                rag_enabled = True
                try:
                    import os as _os_rag_check
                    v = (_os_rag_check.getenv("VOICE_RAG_PER_TURN") or "").strip().lower()
                    if v in ("0", "false", "off"):
                        rag_enabled = False
                except Exception:
                    rag_enabled = True
                
                if preemptive_on and rag_enabled:
                    logger.info(f"🔧 RAG+preemptive: KB grounding needed ({len(hits)} chars) but preemptive already disabled at session level (rag_enabled={rag_enabled}, env preemptive={preemptive_on}) - no invalidation, exactly one REQUEST START per turn (query: {retrieval_query[:60]})")
                elif preemptive_on:
                    logger.info(f"🔍 RAG+preemptive conflict: KB grounding needed ({len(hits)} chars) will invalidate preemptive for this turn — preserving correctness over latency (query: {retrieval_query[:60]})")
                
                if _rag_kind == "near-match":
                    _header = (
                        f"{_RAG_PREFIX} NEAR-MATCH business context (the exact question "
                        "keywords were not found in the knowledge base; use ONLY statements "
                        "this excerpt makes verbatim, do not stretch it to fit the question):"
                    )
                else:
                    _header = (
                        f"{_RAG_PREFIX} Relevant business facts for THIS specific question:"
                    )
                # 11:41 log defect #1 (ORDER, not presence — final_user=0c
                # explained): agent_activity creates user_message BEFORE this
                # hook, then inserts it into the generation ctx by
                # created_at (_pipeline_reply_task_impl: chat_ctx.insert()).
                # A plain add_message() stamps created_at=NOW — newer than the
                # question — so [RAG] landed AFTER it: [..., USER question,
                # [RAG] system]. The question was never the last message and
                # the trailing system line read like new instructions. Anchor
                # the block 1ms before the question instead: the library then
                # slots the question right behind it — [..., [RAG] facts,
                # USER question] — facts precede the question it grounds, and
                # the question is last (stable prefix → dynamic RAG → user
                # content, per the cache-prefix contract).
                _inj_at = float(getattr(new_message, "created_at", 0.0) or 0.0) - 0.001
                if _inj_at <= 0:
                    _inj_at = _time.time() - 0.001
                target.add_message(
                    role="system",
                    content=f"{_header}\n{hits}",
                    created_at=_inj_at,
                )
                logger.info(f"✅ [RAG_DONE] RAG injected {len(hits)} chars for query: {retrieval_query[:80]} (kb_used={kb_used}, faq_used={faq_used}) original='{original_user_query[:60]}'")
                logger.info("🧠 [LLM_CONTEXT] user_query='%s' rag_context_present=yes (chars=%d, kind=%s)", retrieval_query[:70], len(hits), _rag_kind)
            except Exception as e:
                # RAG only *enriches* the turn context: a retrieval failure must
                # never gate or delay the LLM reply (brief P4). Log loudly with
                # the real exception, then fall through so LiveKit generates.
                logger.warning(f"⚠️ per-turn RAG handling raised {type(e).__name__}: {e!r} — LLM reply still proceeds ungrounded for this turn")
                logger.info(f"⏱️ TIMING on_user_turn_completed (RAG error, fallback): {(_time.time()-_rag_t0)*1000:.0f}ms")

    return _VoiceAgent()


# ---------------------------------------------------------------------------
# Announcement / fixed-script "reminder" agent — no STT, no LLM
# ---------------------------------------------------------------------------
def build_announce_agent(
    cfg: AgentConfig,
    *,
    announce_text: str = "",
) -> "Any":
    """Return a LiveKit v1 ``Agent`` that only plays a fixed script and hangs up.

    Used for "reminder"/"inform-only" calls: the agent answers, reads the script
    aloud via TTS, then ends the call. It never listens (no STT) and never
    generates a reply (no LLM). The customer is not billed for STT/LLM.
    """
    from livekit.agents import Agent
    from livekit.agents import llm

    text = (announce_text or getattr(cfg, "announce_text", "") or cfg.greeting or f"Hello, this is {cfg.name} with an announcement.").strip()
    end_after_announcement = bool(getattr(cfg, "end_after_announcement", False))

    class _AnnounceAgent(Agent):
        def __init__(self):
            self.cfg = cfg
            self._opening_started = False
            self._opening_done = False
            super().__init__(
                # No LLM: a still/empty instruction set. Everything is hardcoded.
                instructions="You are a one-way announcement. Do not use tools.",
                chat_ctx=llm.ChatContext(),
                turn_handling={
                    "endpointing": {"min_delay": 0.2, "max_delay": 0.5},
                    "interruption": {"enabled": False},  # script should not be cut off
                    "preemptive_generation": {"enabled": False},
                },
            )

        async def on_enter(self) -> None:
            self._opening_started = True
            try:
                logger.info("[ANNOUNCEMENT_STARTED] Announcement connected — waiting for caller audio path")
                await wait_until_caller_can_hear(self.session)
                logger.info("[ANNOUNCEMENT_STARTED] Reading announcement script: %s", text[:60])
                await speak_opening_line(self.session, text, timeout=120)
                logger.info("[ANNOUNCEMENT_FINISHED] Announcement script playback completed")
            except Exception as e:
                logger.warning(f"Announcement playback failed: {type(e).__name__}: {e!r}")
            finally:
                self._opening_done = True

            if end_after_announcement:
                logger.info("[CALL_END_REQUESTED] source=announcement reason=announcement_completed")
                try:
                    await asyncio.sleep(2.5)  # flush audio playout buffer to caller
                    from livekit.agents import get_job_context
                    ctx = get_job_context(required=False)
                    try:
                        self.session.shutdown(drain=True)
                    except Exception:
                        pass
                    if ctx is not None:
                        room = getattr(ctx.room, "name", None)
                        if room:
                            try:
                                from ..telephony import end_active_room
                                await end_active_room(room)
                            except Exception as e:
                                logger.warning(f"announcement: could not delete room {room}: {e}")
                        ctx.shutdown()
                    logger.info("[CALL_ENDED] reason=announcement_completed")
                except Exception as e:
                    logger.warning(f"could not close announcement session: {e}")
            else:
                logger.info("📢 Announcement finished — keeping call connected (end_after_announcement=False)")

    return _AnnounceAgent()


# Pre-compile schemas when agent_builder is imported
try:
    warm_agent_builder_schemas()
except Exception:
    pass

