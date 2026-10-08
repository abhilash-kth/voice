from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("voice-agent-saas-agent-builder")


# cross-module imports (auto-generated)
from .ab_config_access import _provider_api_key
from .ab_llm_catalog_gate import gate_and_enrich_model
from .ab_llm_reasoning import resolve_reasoning_budget
from .ab_llm_instantiate_chain import instantiate_llm_from_kwargs
from .ab_llm_instantiate import _instantiate_llm

def _build_llm_from_pair(pair, cfg_language: str = "hi") -> Any:
    """Build an LLM instance from a ProviderPair (primary or fallback) - V2 Provider → Multiple Models.
    
    No silent model substitution. Invalid provider/model returns clear config error.
    Logs LLM PROVIDER CONFIG with provider, model, base_url exactly as selected.
    Fixes OpenAI 404 by validating exact model and capturing actual API error.
    """
    from openai import AsyncOpenAI
    sel = pair
    overrides = sel.config or {}
    raw_id = sel.id

    # Resolve provider, model, base_url using V2 logic (no silent replacement)
    # Use ProviderPair's resolve method for backward compat
    from .ab_llm_credentials import resolve_pair_credentials
    provider, model_id, base_url, api_key, key_env, provider_type = resolve_pair_credentials(sel, overrides, raw_id)

    # Import new catalog for validation and metadata
    model_id, model_meta = gate_and_enrich_model(overrides, raw_id, provider, model_id, base_url, provider_type, key_env)

    low, meta, reasoning, _cap_override, _reasoning_mdl, _cap = resolve_reasoning_budget(provider, model_id, overrides)

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
    from .ab_llm_client_probe import build_instrumented_http_client
    client = build_instrumented_http_client(api_key, base_url, provider, model_id, _native_google)
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
    llm_instance = instantiate_llm_from_kwargs(
        provider, provider_type, model_id, base_url, api_key, key_env, raw_id,
        llm_kwargs, _cache_cap, _cap, reasoning, use_responses_api)

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




