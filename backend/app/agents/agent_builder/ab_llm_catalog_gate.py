"""LLM catalog validation: model resolution from catalog/env, provider-model
compatibility gating, model_meta enrichment. Raises on invalid pairs (V2:
no silent model substitution).
Extracted 1:1 from `agent_builder/ab_llm_pair.py` (<=300-line rule).
"""
from __future__ import annotations

import logging
import time

logger = logging.getLogger("voice-agent-saas-agent-builder")


def gate_and_enrich_model(overrides, raw_id, provider, model_id, base_url, provider_type):
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
    return model_id, model_meta
