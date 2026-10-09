"""Credentials + provider-identity resolution for `_build_llm_from_pair`: V2
resolve(), base_url defaults per provider, API-key lookup (Super Admin panel
credential ONLY — never .env), and the hard raise when no key exists.
Extracted 1:1 from agent_builder/ab_llm_pair.py (<=300-line rule).
"""
from __future__ import annotations

import logging

from .ab_config_access import _provider_api_key, _provider_base_url, _key_miss_reason

logger = logging.getLogger("voice-agent-saas-agent-builder")


def resolve_pair_credentials(sel, overrides, raw_id):

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

    # API key = Super Admin panel credential ONLY (never .env). A missing key
    # raises below with the exact panel location instead of a plugin ValueError.
    if provider.startswith("groq"):
        api_key = overrides.get("api_key") or _provider_api_key("llm", "groq")
        key_slug = "groq"
        provider_type = "groq"
    elif provider.startswith("openrouter"):
        # Deprecated provider: still resolvable so agents saved against it keep
        # running, but no longer offered in the picker (see llm_catalog).
        api_key = overrides.get("api_key") or _provider_api_key("llm", "openrouter")
        key_slug = "openrouter"
        provider_type = "openrouter"
    elif provider.lower() in ("google", "gemini"):
        provider = "google"
        api_key = overrides.get("api_key") or _provider_api_key("llm", "google")
        key_slug = "google"
        provider_type = "google"  # native livekit.plugins.google.LLM
        base_url = None           # plugin owns the endpoint
    elif provider.lower() in ("sarvam", "sarvamai", "sarvam-ai"):
        provider = "sarvam"
        api_key = overrides.get("api_key") or _provider_api_key("llm", "sarvam")
        key_slug = "sarvam"
        provider_type = "openai"  # OpenAI-compatible chat completions
        base_url = base_url or _provider_base_url("llm", "sarvam") or "https://api.sarvam.ai/v1"
    elif provider.lower() in ("qwen", "dashscope", "alibaba", "aliyun"):
        # Dynamic-catalog provider (Super Admin controlled): Alibaba Qwen via
        # the OpenAI-compatible DashScope endpoint.
        provider = "qwen"
        api_key = overrides.get("api_key") or _provider_api_key("llm", "qwen")
        key_slug = "qwen"
        provider_type = "openai"  # OpenAI-compatible chat completions
        base_url = base_url or _provider_base_url("llm", "qwen") or "https://dashscope.aliyuncs.com/compatible-mode/v1"
    elif provider.lower() in ("anthropic", "claude"):
        # Dynamic-catalog provider (Super Admin controlled): Anthropic Claude
        # via the native LiveKit Anthropic plugin.
        provider = "anthropic"
        api_key = overrides.get("api_key") or _provider_api_key("llm", "anthropic")
        key_slug = "anthropic"
        provider_type = "anthropic"  # native livekit.plugins.anthropic.LLM
        base_url = None             # plugin owns the endpoint
    else:
        # Default to openai
        api_key = overrides.get("api_key") or _provider_api_key("llm", "openai")
        key_slug = "openai"
        provider_type = "openai"
        # Normalize provider to openai if it's old style or unknown
        if provider not in ("openai", "groq", "openrouter", "google", "sarvam", "qwen", "anthropic"):
            # Check if raw_id maps to known provider via old mapping
            if raw_id.startswith("groq"):
                provider = "groq"
                base_url = base_url or "https://api.groq.com/openai/v1"
                api_key = overrides.get("api_key") or _provider_api_key("llm", "groq")
                key_slug = "groq"
            elif raw_id.startswith("openrouter"):
                provider = "openrouter"
                base_url = base_url or "https://openrouter.ai/api/v1"
                api_key = overrides.get("api_key") or _provider_api_key("llm", "openrouter")
                key_slug = "openrouter"
            else:
                provider = "openai"
                base_url = base_url or "https://api.openai.com/v1"

    if not api_key:
        raise RuntimeError(
            f"No API key for LLM provider '{provider}' (id={raw_id}). Set it in the Super Admin "
            f"panel (Providers → '{key_slug}' → Credentials) — provider keys are NOT read from .env. "
            f"Provider={provider}, model={model_id}, base_url={base_url or 'https://api.openai.com/v1'}" + _key_miss_reason()
        )
    return provider, model_id, base_url, api_key, key_slug, provider_type
