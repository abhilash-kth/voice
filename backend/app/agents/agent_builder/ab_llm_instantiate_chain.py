"""Final LLM instantiation chain: OpenAI Responses-API preference with
Chat-Completions fallback, cache-capability application, request/watchdog
instrumentation and LLM PROVIDER CONFIG logging.
Extracted 1:1 from `agent_builder/ab_llm_pair.py` (<=300-line rule).
"""
from __future__ import annotations

import logging
import time

logger = logging.getLogger("voice-agent-saas-agent-builder")


def instantiate_llm_from_kwargs(provider, provider_type, model_id, base_url, api_key, key_env, raw_id, llm_kwargs, _cache_cap, _cap, reasoning, use_responses_api):
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
    return llm_instance
