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


# cross-module imports (auto-generated)
from .ab_config_access import _provider_api_key, _provider_base_url
from .ab_llm_instantiate import _instantiate_llm

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

    # Get API key based on provider (DB credential → .env fallback chain)
    if provider.startswith("groq"):
        api_key = overrides.get("api_key") or _provider_api_key("llm", "groq", GROQ_API_KEY)
        key_env = "GROQ_API_KEY"
        provider_type = "groq"
    elif provider.startswith("openrouter"):
        # Deprecated provider: still resolvable so agents saved against it keep
        # running, but no longer offered in the picker (see llm_catalog).
        api_key = overrides.get("api_key") or _provider_api_key("llm", "openrouter", OPENROUTER_API_KEY)
        key_env = "OPENROUTER_API_KEY"
        provider_type = "openrouter"
    elif provider.lower() in ("google", "gemini"):
        provider = "google"
        api_key = overrides.get("api_key") or _provider_api_key("llm", "google", GEMINI_API_KEY)
        key_env = "GEMINI_API_KEY"
        provider_type = "google"  # native livekit.plugins.google.LLM
        base_url = None           # plugin owns the endpoint
    elif provider.lower() in ("sarvam", "sarvamai", "sarvam-ai"):
        provider = "sarvam"
        api_key = overrides.get("api_key") or _provider_api_key("llm", "sarvam", SARVAM_API_KEY)
        key_env = "SARVAM_API_KEY"
        provider_type = "openai"  # OpenAI-compatible chat completions
        base_url = base_url or _provider_base_url("llm", "sarvam") or "https://api.sarvam.ai/v1"
    elif provider.lower() in ("qwen", "dashscope", "alibaba", "aliyun"):
        # Dynamic-catalog provider (Super Admin controlled): Alibaba Qwen via
        # the OpenAI-compatible DashScope endpoint.
        provider = "qwen"
        api_key = overrides.get("api_key") or _provider_api_key("llm", "qwen", QWEN_API_KEY)
        key_env = "QWEN_API_KEY"
        provider_type = "openai"  # OpenAI-compatible chat completions
        base_url = base_url or _provider_base_url("llm", "qwen") or "https://dashscope.aliyuncs.com/compatible-mode/v1"
    elif provider.lower() in ("anthropic", "claude"):
        # Dynamic-catalog provider (Super Admin controlled): Anthropic Claude
        # via the native LiveKit Anthropic plugin.
        provider = "anthropic"
        api_key = overrides.get("api_key") or _provider_api_key("llm", "anthropic", ANTHROPIC_API_KEY)
        key_env = "ANTHROPIC_API_KEY"
        provider_type = "anthropic"  # native livekit.plugins.anthropic.LLM
        base_url = None             # plugin owns the endpoint
    else:
        # Default to openai
        api_key = overrides.get("api_key") or _provider_api_key("llm", "openai", OPENAI_API_KEY)
        key_env = "OPENAI_API_KEY"
        provider_type = "openai"
        # Normalize provider to openai if it's old style or unknown
        if provider not in ("openai", "groq", "openrouter", "google", "sarvam", "qwen", "anthropic"):
            # Check if raw_id maps to known provider via old mapping
            if raw_id.startswith("groq"):
                provider = "groq"
                base_url = base_url or "https://api.groq.com/openai/v1"
                api_key = overrides.get("api_key") or _provider_api_key("llm", "groq", GROQ_API_KEY)
                key_env = "GROQ_API_KEY"
            elif raw_id.startswith("openrouter"):
                provider = "openrouter"
                base_url = base_url or "https://openrouter.ai/api/v1"
                api_key = overrides.get("api_key") or _provider_api_key("llm", "openrouter", OPENROUTER_API_KEY)
                key_env = "OPENROUTER_API_KEY"
            else:
                provider = "openai"
                base_url = base_url or "https://api.openai.com/v1"

    if not api_key:
        raise RuntimeError(
            f"No API key for LLM provider '{provider}' (id={raw_id}). Ask the administrator "
            f"to add the key in the Super Admin panel (or set '{key_env}' in backend/.env). "
            f"Provider={provider}, model={model_id}, base_url={base_url or 'https://api.openai.com/v1'}"
        )

    # Import new catalog for validation and metadata
    try:
        from ...llm_catalog import get_llm_model, validate_provider_model, get_llm_provider
        # If model_id empty, try to get default from catalog or env
        if not model_id:
            import os as _os
            env_model = _os.getenv("GROQ_MODEL") if provider == "groq" else _os.getenv("OPENAI_MODEL") if provider == "openai" else _os.getenv("LLM_MODEL")
            if env_model:
                model_id = env_model
                logger.info(f"🔍 LLM model from env: {env_model} for provider {provider}")
            else:
                # Get first enabled model for provider as default (DB snapshot
                # first so admin-added providers get a default too, code fallback).
                try:
                    from ...services import config_store as _cs
                    models = [m for m in _cs.list_llm_models()
                              if m.get("provider") == provider
                              and m.get("enabled", True) and m.get("status") == "active"]
                except Exception:
                    models = []
                if not models:
                    from ...llm_catalog import list_models_for_provider
                    models = list_models_for_provider(provider)
                if models:
                    model_id = models[0]["model_id"]
                    logger.info(f"🔍 LLM model default from catalog: {model_id} for provider {provider} (no model in config)")

        # Validate provider/model combination - NO SILENT REPLACEMENT, clear error.
        # Code catalog first; the dynamic (super-admin) catalog then covers
        # admin-added providers/models (Qwen/Claude/...) not present in code.
        is_valid, validation_msg = validate_provider_model(provider, model_id)
        if not is_valid:
            try:
                from ...services.config_store import get_llm_meta as _glm_dyn
                if _glm_dyn(provider, model_id):
                    is_valid, validation_msg = True, "ok (dynamic catalog)"
            except Exception:
                pass
        if not is_valid:
            # Check if model exists under different provider for helpful error
            from ...llm_catalog import get_llm_model_by_id
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
                from ...llm_catalog import list_models_for_provider
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
        
        # Get model metadata for logging and pricing (DB snapshot merged over code)
        model_meta = get_llm_model(provider, model_id)
        if model_meta is None:
            try:
                from ...services.config_store import get_llm_meta as _glm2
                model_meta = _glm2(provider, model_id)
            except Exception:
                pass
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
        from ...llm_catalog import get_llm_model
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
    from .. import http_timing as _http_timing
    _http_inst = {"n": 0}

    async def _on_http_send(_request):
        try:
            _http_inst["n"] += 1
            _rid = _uuid_mod.uuid4().hex[:8]
            # extensions is httpx-internal metadata, never sent on the wire
            _request.extensions["voice_rid"] = _rid
            _http_timing.note_send(model_id, _rid)
            # httpx's request hook is before transport acquisition. httpcore's
            # trace extension separates connection-pool wait, DNS/TCP/TLS,
            # upload and response-header wait without touching the stream.
            _trace_events = {}
            async def _trace(_name, _info):
                try:
                    _phase, _edge = _name.rsplit(".", 1)
                    _trace_events.setdefault(_phase, {})[_edge] = time.perf_counter()
                except Exception:
                    pass
            _request.extensions["trace"] = _trace
            _http_timing.set_trace(_rid, _trace_events)
            # Critical-path: log REQUEST_START immediately without blocking work.
            # The old code did JSON decode + hashing synchronously on the event
            # loop (107ms block warning) — that adds directly to
            # request_start->response_headers and delays audio/turn handling.
            logger.info(
                "\U0001f310 [HTTP_REQUEST_START] monotonic_ns=%d rid=%s model=%s client_attempt#%d sdk_retry_count=%s path=%s — one send of one chat() attempt (see B/C distinction in builder comment; SDK retries are disabled by max_retries=0)",
                time.monotonic_ns(), _rid, model_id, _http_inst["n"],
                _request.headers.get("x-stainless-retry-count", "absent"),
                _request.url.path,
            )
            # --- Provider-bound fingerprint off critical path ---
            # Offload JSON parsing + hashing to a background task / thread so it
            # never blocks the agent event loop. Cache is FIXED and working
            # (1792 hit), so diagnostic can be async. No PII, only hashes/lens.
            try:
                _body_snapshot = _request.content  # bytes, safe to capture
                if _body_snapshot:
                    import asyncio as _aio2

                    def _parse_fp():
                        try:
                            import json as _js
                            import hashlib as _hl2

                            _j = _js.loads(
                                _body_snapshot.decode("utf-8", "ignore")
                                if isinstance(_body_snapshot, (bytes, bytearray))
                                else str(_body_snapshot)
                            )
                            _pck = _j.get("prompt_cache_key", "?")
                            _msgs = _j.get("messages", []) or []
                            _role_seq = ",".join([str(m.get("role", "?")) for m in _msgs])
                            _len_seq = ",".join([str(len(str(m.get("content", "")))) for m in _msgs])
                            _first_c = str(_msgs[0].get("content", "")) if _msgs else ""
                            _first_hash = (
                                _hl2.sha256(_first_c.encode("utf-8", "ignore")).hexdigest()[:12]
                                if _first_c
                                else "?"
                            )
                            _pref_c = "".join([str(m.get("content", "")) for m in _msgs[:2]])
                            _pref_hash = (
                                _hl2.sha256(_pref_c.encode("utf-8", "ignore")).hexdigest()[:12]
                                if _pref_c
                                else "?"
                            )
                            return (_pck, len(_msgs), _role_seq, _len_seq, _first_hash, _pref_hash)
                        except Exception:
                            return None

                    async def _log_fp():
                        try:
                            _res = await _aio2.to_thread(_parse_fp)
                            if _res is None:
                                return
                            _pck, _cnt, _role_seq, _len_seq, _first_hash, _pref_hash = _res
                            logger.info(
                                "\U0001f50d [HTTP_BODY_FINGERPRINT] rid=%s model=%s prompt_cache_key=%s prov_messages=%d role_seq=%s len_seq=%s first_hash=%s prefix_hash=%s",
                                _rid, model_id, _pck, _cnt, _role_seq, _len_seq, _first_hash, _pref_hash,
                            )
                        except Exception as _e:
                            logger.debug(f"[HTTP_BODY_FINGERPRINT] failed: {_e!r}")

                    _aio2.create_task(_log_fp())
            except Exception as _e:
                logger.debug(f"[HTTP_BODY_FINGERPRINT] schedule failed: {_e!r}")
        except Exception:
            pass

    async def _on_http_headers(_response):
        try:
            _rid = _response.request.extensions.get("voice_rid", "?")
            _el = _http_timing.note_headers(_rid, _response.status_code)
            _transport = _http_timing.trace_summary(_rid)
            logger.info(
                "\U0001f310 [HTTP_RESPONSE_HEADERS] monotonic_ns=%d rid=%s model=%s status=%d request_start->response_headers=%s transport=%s — headers boundary only; first streamed body bytes come later (see [HTTP_CHUNK])",
                time.monotonic_ns(), _rid, model_id, _response.status_code,
                ("%.0fms" % _el) if _el >= 0 else "?",
                _transport or "no_trace_events",
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

    # Temperature is intentionally NOT sent anywhere (product decision): every
    # provider runs on its own default. Do not reintroduce a temperature kwarg
    # here — reasoning models (gpt-5 family, o-series) reject it anyway.
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
        from ...llm_catalog import get_prompt_cache_capability as _gcc
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
                        # temperature omitted — provider default (see builder note above)
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
        f"provider_type={provider_type} max_tokens={llm_kwargs['max_completion_tokens']} reasoning={llm_kwargs.get('reasoning_effort','none')} "
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




