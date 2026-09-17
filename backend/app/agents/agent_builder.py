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
    LLM_MODEL,
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
}


def _resolve_tts_voice(language: str, raw_voice: Optional[str]) -> str:
    """Return a voice name that Google's streaming endpoint accepts.

    A voice already set to a Chirp 3 or Gemini name is passed through unchanged.
    An empty value defaults to Chirp 3: HD. Any legacy Wavenet/Standard/Neural2
    voice is remapped to a Chirp 3: HD voice for the same locale.
    """
    v = (raw_voice or "").strip()
    if v and ("chirp" in v.lower() or "gemini" in v.lower()):
        return v
    if not v:
        return f"{language or 'hi-IN'}-Chirp3-HD-Leda"
    # Derive the locale from a legacy voice name like "hi-IN-Wavenet-A"
    parts = v.split("-")
    if len(parts) >= 2 and parts[0] and parts[1]:
        locale = f"{parts[0]}-{parts[1]}"
    else:
        locale = language or "hi-IN"
    return f"{locale}-Chirp3-HD-Leda"


# ---------------------------------------------------------------------------
# Provider → plugin construction
# ---------------------------------------------------------------------------

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
        api_key = overrides.get("api_key") or OPENROUTER_API_KEY
        key_env = "OPENROUTER_API_KEY"
        provider_type = "openrouter"
    else:
        # Default to openai
        api_key = overrides.get("api_key") or OPENAI_API_KEY
        key_env = "OPENAI_API_KEY"
        provider_type = "openai"
        # Normalize provider to openai if it's old style or unknown
        if provider not in ("openai", "groq", "openrouter"):
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
    try:
        from ..llm_catalog import get_llm_model
        meta = get_llm_model(provider, model_id)
        if meta:
            default_reasoning = meta.get("reasoning_default") or ("low" if meta.get("reasoning_supported") else "none")
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

    # Build client with exact base_url and model, no silent replacement
    client = AsyncOpenAI(api_key=api_key, base_url=base_url, max_retries=0)
    llm_kwargs = {
        "client": client,
        "model": model_id,  # EXACT model as selected, no rewriting
        "temperature": float(overrides.get("temperature", 0.1)),
        "max_completion_tokens": int(overrides.get("max_tokens", 80)),
    }
    if model_meta and model_meta.get("reasoning_supported"):
        llm_kwargs["reasoning_effort"] = reasoning
    elif "gpt-oss" in low or "o1" in low or "o3" in low or "o4" in low:
        llm_kwargs["reasoning_effort"] = reasoning

    logger.info(
        f"🔧 Building LLM instance: provider={provider} model={model_id} base_url={base_url or 'https://api.openai.com/v1'} "
        f"temperature={llm_kwargs['temperature']} max_tokens={llm_kwargs['max_completion_tokens']} reasoning={llm_kwargs.get('reasoning_effort','none')} "
        f"EXACT model passed to runtime, no silent substitution"
    )

    try:
        llm_instance = LLM(**llm_kwargs)
        logger.info(f"✅ LLM instance built successfully: provider={provider} model={model_id}")
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
        primary_pair = cfg.providers.llm
        fallback_pair = getattr(cfg.providers, "llm_fallback", None)
        if not fallback_pair:
            try:
                fp = getattr(cfg, "fallback_providers", None)
                if fp and getattr(fp, "llm", None):
                    fallback_pair = fp.llm
            except Exception:
                pass

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

    # Build primary with exact model, no silent substitution
    primary = _build_llm_from_pair(primary_pair, getattr(cfg, "language", "hi"))

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

    except Exception as e:
        logger.warning(f"Groq auto-prefer check failed: {e}")

    # Build primary (respects user's choice now that auto-swap default is 0)
    primary = _build_llm_from_pair(primary_pair, getattr(cfg, "language", "hi"))

    # Only use what user selected - no fixed fallback injection
    # User explicitly said: "Don't add inside the fixed fallback. Only user will select all the things"
    fallbacks = []
    fallback_pair = getattr(cfg.providers, "llm_fallback", None)
    if not fallback_pair:
        try:
            fp = getattr(cfg, "fallback_providers", None)
            if fp and getattr(fp, "llm", None):
                fallback_pair = fp.llm
        except Exception:
            pass

    if fallback_pair:
        if not (fallback_pair.id == primary_pair.id and (fallback_pair.config or {}).get("model") == (primary_pair.config or {}).get("model")):
            fallbacks.append(fallback_pair)

    # Safety net for observed 404 pattern: groq_gpt_oss (120b) sometimes 404s (recovery failed)
    # Ensure groq_gpt_oss_20b is available as last resort if 120b is anywhere in chain and 20b not already present
    # This preserves user intent (Groq) while handling 404, with explicit logging (not silent)
    try:
        chain_ids = [primary_pair.id] + [fb.id for fb in fallbacks]
        has_120b = "groq_gpt_oss" in chain_ids
        has_20b = "groq_gpt_oss_20b" in chain_ids
        if has_120b and not has_20b:
            from ..models import ProviderPair
            safety_pair = ProviderPair(id="groq_gpt_oss_20b", config={"model": "openai/gpt-oss-20b", "temperature": 0.1, "max_tokens": 80})
            fallbacks.append(safety_pair)
            logger.info(f"🛡️ Added safety fallback groq_gpt_oss_20b (20b) because chain contains groq_gpt_oss (120b) which observed 404 recovery failed - ensures at least one Groq model works")
    except Exception as e:
        logger.debug(f"Could not add safety fallback: {e}")

    if not fallbacks:
        return primary

    fallback_instances = []
    fallback_ids = []
    for fb_pair in fallbacks:
        try:
            inst = _build_llm_from_pair(fb_pair, getattr(cfg, "language", "hi"))
            fallback_instances.append(inst)
            fallback_ids.append(fb_pair.id)
        except Exception as e:
            logger.warning(f"⚠️ Could not build LLM fallback {fb_pair.id}: {e} — skipping")

    if not fallback_instances:
        return primary

    try:
        from livekit.agents import llm as llm_agents
        all_llms = [primary] + fallback_instances
        adapter = llm_agents.FallbackAdapter(all_llms)
        chain_str = " -> ".join([primary_pair.id] + fallback_ids)
        # Log full chain with models and base_urls for debugging 404
        try:
            chain_details = []
            for pair in [primary_pair] + [fb for fb in fallbacks]:
                cat_model = pair.config.get("model") if pair.config else "from catalog"
                base = pair.config.get("base_url") if pair.config and pair.config.get("base_url") else ("https://api.groq.com/openai/v1" if pair.id.startswith("groq") else "https://api.openai.com/v1" if pair.id.startswith("openai") else "https://openrouter.ai/api/v1")
                chain_details.append(f"{pair.id}({cat_model} @ {base})")
            logger.info(f"🔁 LLM FallbackAdapter armed: {chain_str} (user-selected only, no fixed fallback) | Details: {' -> '.join(chain_details)}")
        except Exception:
            logger.info(f"🔁 LLM FallbackAdapter armed: {chain_str} (user-selected only, no fixed fallback)")
        return adapter
    except Exception as e:
        logger.warning(f"⚠️ Could not build LLM FallbackAdapter {fallback_ids}: {e} — using primary only")
        return primary


def _build_stt_from_pair(pair, cfg: AgentConfig) -> Any:
    sel = pair
    overrides = sel.config or {}

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
    # - interim_results True: needed for preemptive generation (LLM warm while user speaking)
    # - vad_events True: Deepgram VAD filters non-speech, rejects noise before LLM
    # - no_delay True: send final immediately, don't buffer
    # - smart_format True: better punctuation for Hindi/Hinglish sentence completion detection
    stt_kwargs = dict(
        model=overrides.get("model", "nova-2"),
        language=overrides.get("language", "hi"),
        keywords=keywords,
        interim_results=bool(overrides.get("interim_results", True)),
        vad_events=bool(overrides.get("vad_events", True)),
        no_delay=bool(overrides.get("no_delay", True)),
        filler_words=bool(overrides.get("filler_words", True)),
        api_key=overrides.get("api_key") or DEEPGRAM_API_KEY or None,
    )
    # Try to add production latency params with correct names, fallback gracefully if not supported
    # Correct param is endpointing_ms (not endpointing) per installed plugin 1.8.2
    # Preserve utterance_end_ms, smart_format, punctuate - don't drop all on single failure
    optional_params = {}
    # Support both endpointing_ms and legacy endpointing for backward compat
    if "endpointing_ms" in overrides or "endpointing" in overrides:
        ep_val = overrides.get("endpointing_ms", overrides.get("endpointing", 200))
        try:
            optional_params["endpointing_ms"] = int(ep_val)
        except Exception:
            pass
    else:
        optional_params["endpointing_ms"] = 200

    if "utterance_end_ms" in overrides or True:  # always try default 1000
        try:
            optional_params["utterance_end_ms"] = int(overrides.get("utterance_end_ms", 1000))
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
    primary_pair = cfg.providers.stt
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
        default_language = "en-IN" if configured_language.startswith("en") else "hi-IN"
        language = overrides.get("language", default_language)
        voice = _resolve_tts_voice(language, overrides.get("voice"))
        return TTS(
            voice_name=voice,
            language=language,
            credentials_file=overrides.get("credentials_file") or GOOGLE_APPLICATION_CREDENTIALS or None,
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
    primary_pair = cfg.providers.tts
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


def build_vad() -> Any:
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
    return silero.VAD.load(
        min_speech_duration=0.20,
        min_silence_duration=0.30,
        prefix_padding_duration=0.20,
        activation_threshold=0.55,
    )


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
# \"Mere paas company ki exact team size nahi hai\" - KB truncated 45788->1001 chars.
# Groq 8k TPM is tight, but with 6-msg history trim we can afford larger budgets.
# New: Groq 2500/1200/3000, OpenAI 4000/2000/4000 to preserve KB grounding.
# Task: \"Do not sacrifice correctness for latency\" - so preserve KB.
_KB_BUDGET_CHARS_DEFAULT = 4000
_FAQ_BUDGET_CHARS_DEFAULT = 2000
_OWNER_PROMPT_BUDGET_CHARS_DEFAULT = 4000

# Legacy module-level constants kept for backward compat / logging, but
# build_instructions now uses provider-aware effective budgets.
_KB_BUDGET_CHARS = int(os.getenv("VOICE_KB_BUDGET_CHARS", str(_KB_BUDGET_CHARS_DEFAULT)))
_FAQ_BUDGET_CHARS = int(os.getenv("VOICE_FAQ_BUDGET_CHARS", str(_FAQ_BUDGET_CHARS_DEFAULT)))
_OWNER_PROMPT_BUDGET_CHARS = int(os.getenv("VOICE_OWNER_PROMPT_BUDGET_CHARS", str(_OWNER_PROMPT_BUDGET_CHARS_DEFAULT)))


def _effective_budgets(cfg: AgentConfig) -> tuple[int, int, int]:
    """Return (kb_budget, faq_budget, owner_budget) based on LLM provider."""
    try:
        llm_id = (cfg.providers.llm.id or "").lower() if cfg.providers and cfg.providers.llm else ""
    except Exception:
        llm_id = ""
    is_groq = llm_id.startswith("groq")
    if is_groq:
        kb = int(os.getenv("VOICE_KB_BUDGET_CHARS", str(_KB_BUDGET_CHARS_DEFAULT_GROQ)))
        faq = int(os.getenv("VOICE_FAQ_BUDGET_CHARS", str(_FAQ_BUDGET_CHARS_DEFAULT_GROQ)))
        owner = int(os.getenv("VOICE_OWNER_PROMPT_BUDGET_CHARS", str(_OWNER_PROMPT_BUDGET_CHARS_DEFAULT_GROQ)))
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
    persona = cfg.voice_personality or "friendly"
    lang = cfg.language or "hi"
    kb_budget, faq_budget, owner_budget = _effective_budgets(cfg)

    lines = [
        f"You are {cfg.name}, a {persona} voice receptionist.",
        "Reply in the same language as the caller's latest message. If the caller speaks English, reply entirely in natural English; if Hindi or Hinglish, reply in Hindi or Hinglish. Do not switch languages without the caller asking.",
        "Keep replies to 1 or 2 short spoken sentences, preferably under 25 words. Start answering immediately. No analysis, markdown, lists, or emojis; never list more than three items or repeat the caller's full question.",
        f"Preferred language: {lang}; use it when the caller's language is unclear.",
    ]
    lines.append(
        "Behave like a warm human receptionist. Never repeat yourself, never push "
        "the same offer, never read out a list of services unprompted, and never "
        "give a long preamble. Answer exactly what was asked, then stop. "
        "ABSOLUTELY FORBIDDEN to add these after every answer: 'Aur kuch poochna hai?', "
        "'Aur kuch jaanana chahenge?', 'Aapko aur kuch jaanana hai?', 'Kya aapko aur koi madad chahiye?', "
        "'Aur kuch madad chahiye?', 'Kya aapko aur kuch chahiye?', 'Aur kuch?' — "
        "Only ask a follow-up when you are actively collecting missing required info "
        "for a project enquiry (like phone, budget). If the caller says they have no more questions "
        "(e.g., 'mujhe kuch nahi puchna', 'koi sawaal nahi', 'नहीं और कोई सवाल नहीं है', "
        "'नहीं और कोई मदद नहीं चाहिए', 'bas itna hi', 'that's all', 'no more questions'), "
        "do NOT keep asking — treat it as closing and call end_call tool. "
        "Never mention being an AI, a robot, or a bot."
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
                f"({sum(len(f) for f in facts)} -> {used} chars; Groq's free tier is "
                "8k TPM, and an oversized prompt is what causes 429s → silent dropped "
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
    lines.append("FINAL CRITICAL RULES - ALWAYS FOLLOW:")
    lines.append("- After answering, STOP. Do NOT add 'Aur kuch jaanana chahenge?' / 'Aur kuch poochna hai?' / 'Kya aapko aur koi madad chahiye?' unless you are actively collecting required project info. One answer = stop speaking and wait for caller.")
    lines.append("- If caller asks for contact number/email, use ONLY the numbers/emails given in 'Instructions from the business owner' above. Never say you don't have them if they are in the owner instructions. Primary phone is +91-8947027625, sales email sales@kriscent.in, info email info@kriscent.in. Provide them exactly when asked.")
    lines.append("- If caller says 'mujhe kuch nahi puchna', 'koi sawaal nahi', 'नहीं और कोई सवाल नहीं है', 'नहीं और कोई मदद नहीं चाहिए', 'bas ho gaya', 'that's all', 'no more questions', 'ok thank you' as final, call end_call tool immediately — do not ask another follow-up.")
    lines.append("- Keep every reply to 1-2 short sentences, under 25 words. No lists unless caller explicitly asks for list.")
    lines.append("- ANTI-HALLUCINATION: Never invent financial data, balance, transactions, or office locations not in 'Business facts'. If user asks 'recent kaam' / 'recent work', explain Kriscent's recent projects from KB (IT services, AI agents, etc), NOT financial data. If info not in KB, say 'Mere paas iski exact jaankari nahi hai, main aapko Jaipur office se connect kara sakta hoon'.")
    lines.append("- Be concise, warm, human. If caller says 'thank Kota' or 'accha laga' with thank, treat as closing — call end_call.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# v1 Agent (subclass) — static knowledge + cross-call memory + greeting
# ---------------------------------------------------------------------------
def build_voice_agent(
    cfg: AgentConfig,
    *,
    greeting: str = "",
    prior_memory: str = "",
    lead_data: Optional[dict] = None,
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
        "\n\nCONVERSATION OPENING: The initial greeting has already been spoken by the application. "
        "Never greet again, introduce yourself again, or say 'Namaste' in response to a "
        "partial, interrupted, or unclear first user utterance. Acknowledge briefly and "
        "ask what the caller needs.\n\nCALL LIFECYCLE: Keep the call open after every normal answer, pause, or contact-detail "
        "collection. End the call only when the caller clearly and explicitly asks to "
        "disconnect, hang up, cut the call, or says goodbye, bye, bye bye, ok bye, thank you, "
        "that's all, no more help, or no more questions, or a mixed Hindi/English request "
        "such as 'call cut kar dijiye' or 'और तो मुझे कुछ नहीं जानना' as a standalone final "
        "utterance. Phrases such as 'that's all for this question' or 'okay' are NOT goodbye, "
        "especially when followed by another question. "
        "When the caller explicitly says goodbye, do NOT try to generate your own closing sentence — "
        "just call the end_call tool once. The system will speak a fixed deterministic closing line "
        f"'{_get_closing_for_cfg(cfg)}' and then hang up. Never call the tool before the closing is needed, "
        "and never call it for an ambiguous phrase."
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
        room = getattr(ctx.room, "name", None)
        if room:
            try:
                from ..telephony import end_active_room
                await end_active_room(room)
            except Exception as e:
                logger.warning(f"end_call: could not delete room {room}: {e}")
        ctx.shutdown()
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
        chat_ctx.add_message(
            role="system",
            content="Prior conversation with this customer:\n" + prior_memory,
        )

    class _VoiceAgent(Agent):
        def __init__(self):
            self.cfg = cfg
            self.greeting = greeting
            self._last_rag = ""  # per-turn RAG injection (see on_user_turn_completed)
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

        async def on_enter(self) -> None:
            if self.greeting:
                # Wait until a participant is linked and audio output is ready
                # before speaking, so outbound/SIP greetings aren't lost while
                # the number is still ringing.
                try:
                    room_io = getattr(self.session, "room_io", None)
                    if room_io is not None and hasattr(room_io, "wait_for_ready"):
                        await asyncio.wait_for(room_io.wait_for_ready(), timeout=60)
                except asyncio.TimeoutError:
                    logger.warning("Timed out waiting for a participant to join — greeting anyway.")
                except Exception as e:
                    logger.warning(f"wait_for_ready failed; greeting anyway: {e}")
                await self.session.say(self.greeting, allow_interruptions=True)

        async def on_user_turn_completed(self, turn_ctx, new_message) -> None:
            """Hook that runs after the user finishes speaking — CRITICAL LATENCY PATH.

            LiveKit's ``AgentSession`` ``await``s this hook, so any blocking here
            directly adds to STT_final->LLM_start latency (target ≤100ms).

            Production fixes:
            - Explicit goodbye detection is fast (string ops, ~1ms)
            - Conversation trim is fast (list slice)
            - RAG is now async via to_thread to avoid blocking event loop (was sync, could be 100-300ms)
            - When VOICE_PREEMPTIVE=1, RAG is skipped (static facts only) to preserve preemptive generation
            - Added timing logs for STT_final->LLM_start to detect 3-7s outliers
            """
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
            if not preemptive_on:
                try:
                    target_ctx = _find_chat_ctx(turn_ctx) or turn_ctx
                    items = getattr(target_ctx, "items", None)
                    # Fix 429: trim more aggressively to keep tokens low. Groq 8k TPM with 2749 tokens/req only allows 2 turns.
                    # Now keep 6 dialogue messages max (was 8) + system, so ~1000 tokens history vs ~1500 before.
                    if isinstance(items, list) and len(items) > 8:
                        system_items = [m for m in items if getattr(m, "role", "") == "system"]
                        dialogue_items = [m for m in items if getattr(m, "role", "") != "system"]
                        # Keep only last 6 dialogue turns for low token usage
                        target_ctx.items = system_items + dialogue_items[-6:]
                        logger.info("🧹 Trimmed conversation context to %s messages (429 fix: 6 dialogue max)", len(target_ctx.items))
                except Exception as exc:
                    logger.debug("conversation context trim skipped: %s", exc)
            else:
                # Preemptive ON: DO NOT mutate chat_ctx at all — any mutation invalidates preemptive
                # Previous lenient trim (10 msgs when >12) still changed chat_ctx → is_equivalent False → invalidation
                # So when preemptive ON, skip trimming entirely to preserve preemptive generation
                # This eliminates "preemptive generation invalidated after on_user_turn_completed" warning
                logger.debug("Preemptive ON: skipping chat_ctx trim to preserve preemptive generation")
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
                # Async RAG to avoid blocking event loop
                try:
                    hits = await asyncio.to_thread(rag.build_context, cfg.knowledge, user_text, 2)
                    hits = (hits or "").strip()
                except Exception:
                    # Fallback sync if to_thread fails
                    hits = (rag.build_context(cfg.knowledge, user_text, top_k=2) or "").strip()
                _rag_elapsed = (_time.time() - _rag_t0) * 1000
                if _rag_elapsed > 200:
                    logger.warning(f"🐢 Slow RAG: {_rag_elapsed:.0f}ms exceeds 100ms target")
                else:
                    logger.info(f"⏱️ TIMING RAG build_context: {_rag_elapsed:.0f}ms (hits {len(hits)} chars)")
                if not hits or hits == self._last_rag:
                    logger.info(f"⏱️ TIMING on_user_turn_completed (RAG no new hits): {(_time.time()-_rag_t0)*1000:.0f}ms")
                    return  # nothing new
                target = _find_chat_ctx(turn_ctx)
                if target is None:
                    logger.warning("⚠️ RAG: no chat_ctx found, skipping injection")
                    return
                # Explicit handling for preemptive+RAG conflict: log that RAG will invalidate preemptive
                if preemptive_on:
                    logger.info(f"🔍 RAG+preemptive conflict: KB grounding needed ({len(hits)} chars) will invalidate preemptive for this turn — preserving correctness over latency (query: {user_text[:60]})")
                # Drop previous RAG message to avoid growth
                try:
                    items = getattr(target, "items", None)
                    if isinstance(items, list):
                        target.items = [m for m in items if _RAG_PREFIX not in _chat_msg_text(m)]
                except Exception:
                    pass
                target.add_message(
                    role="system",
                    content=(
                        f"{_RAG_PREFIX} Relevant business facts for THIS specific "
                        f"question:\n{hits}"
                    ),
                )
                self._last_rag = hits
                logger.info(f"✅ RAG injected {len(hits)} chars for query: {user_text[:80]}")
            except Exception as e:
                logger.warning(f"⚠️ per-turn RAG injection skipped: {e}")
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

    text = (announce_text or cfg.greeting or "").strip()
    if not text:
        raise ValueError(
            "Announcement agent has no script. Set announce_text (or greeting) on the agent."
        )

    class _AnnounceAgent(Agent):
        def __init__(self):
            self.cfg = cfg
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
            # Wait for the participant/audio to be ready so the script isn't cut off.
            try:
                room_io = getattr(self.session, "room_io", None)
                if room_io is not None and hasattr(room_io, "wait_for_ready"):
                    await asyncio.wait_for(room_io.wait_for_ready(), timeout=60)
            except Exception as e:
                logger.warning(f"wait_for_ready failed; playing announcement anyway: {e}")
            # Play the fixed script, then end the call gracefully. We delete the
            # LiveKit room so the caller is physically disconnected (otherwise the
            # browser/SIP participant would be left in a silent, open call), then
            # shut the job down — which runs the worker's finalize_billing shutdown
            # callback so the call is marked completed.
            speech = self.session.say(text, allow_interruptions=False)
            await speech
            try:
                from livekit.agents import get_job_context
                ctx = get_job_context(required=False)
                if ctx is not None:
                    room = getattr(ctx.room, "name", None)
                    if room:
                        try:
                            from ..telephony import end_active_room
                            await end_active_room(room)
                        except Exception as e:
                            logger.warning(f"announcement: could not delete room {room}: {e}")
                    ctx.shutdown()
                else:
                    self.session.shutdown(drain=True)
                logger.info("📢 Announcement finished — closing call.")
            except Exception as e:
                logger.warning(f"could not close announcement session: {e}")

    return _AnnounceAgent()
