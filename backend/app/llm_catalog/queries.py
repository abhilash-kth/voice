"""Query layer over the static LLM providers + models.

Import from ``app.llm_catalog`` (the package façade re-exports everything);
this module should not be imported directly.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .providers_data import LLM_PROVIDERS
from .models_data import LLM_MODELS

_MODEL_INDEX: Dict[str, Dict[str, Any]] = {}
for m in LLM_MODELS:
    key = f"{m['provider']}:{m['model_id']}"
    _MODEL_INDEX[key] = m
    # Also index by model_id alone for backward compat (last wins, but provider-specific preferred)
    _MODEL_INDEX[m['model_id']] = m

def get_llm_provider(provider_id: str) -> Optional[Dict[str, Any]]:
    return LLM_PROVIDERS.get(provider_id)

def get_llm_model(provider: str, model_id: str) -> Optional[Dict[str, Any]]:
    """Get model by provider and model_id. Returns None if not found."""
    key = f"{provider}:{model_id}"
    if key in _MODEL_INDEX:
        return _MODEL_INDEX[key]
    # Fallback: search list for exact provider+model_id
    for m in LLM_MODELS:
        if m["provider"] == provider and m["model_id"] == model_id:
            return m
    return None

def get_llm_model_by_id(model_id: str) -> Optional[Dict[str, Any]]:
    """Get model by model_id alone (any provider). Returns first match."""
    for m in LLM_MODELS:
        if m["model_id"] == model_id:
            return m
    return _MODEL_INDEX.get(model_id)

def list_providers(include_deprecated: bool = False) -> List[Dict[str, Any]]:
    """Providers offered in the UI. Deprecated ones (openrouter) are hidden from
    new selections but keep validating existing agents (see validate_provider_model)."""
    return [p for p in LLM_PROVIDERS.values()
            if include_deprecated or p.get("status") != "deprecated"]

# ---------------------------------------------------------------------------
# Prompt-cache capability layer (Task 2, 2026-09-24).
#
# The old code hard-labelled caching as "prompt_cache_key is OpenAI-only,
# everyone else unsupported". That was half-wrong twice over: OpenAI does
# have automatic prefix caching (the key pins routing), and Groq DOES do
# native prompt caching — AUTOMATICALLY, zero client fields, for the models
# it lists (console.groq.com/docs/prompt-caching, retrieved 2026-09-24: the
# gpt-oss family; usage exposes authoritative
# usage.prompt_tokens_details.cached_tokens). What Groq does NOT accept is
# the OpenAI-only prompt_cache_key FIELD (it 400'd every request on
# 2026-09-19) and it exposes no cached-token usage for qwen/*, so those
# models are honestly capability=none — not "a cache that silently misses".
#
# Modes:
#   native_explicit   provider accepts our prompt_cache_key and its usage
#                     reports cached tokens (OpenAI chat API).
#   native_automatic  provider prefix-caches automatically; NEVER send
#                     OpenAI-only fields; hit/miss counted only when usage
#                     actually carries the cached-tokens detail.
#   none              no provider-side cache for this model. Report
#                     cache_status=unsupported; never label a request "miss"
#                     (there is no cache to miss), never invent fields.
# This layer must NEVER trigger a model substitution — customers choose the
# provider/model; caching is informational and field-shaping only.
# ---------------------------------------------------------------------------
def get_prompt_cache_capability(provider: str, model_id: str) -> Dict[str, Any]:
    """{supported, mode, configuration} for one provider+model pair."""
    p = str(provider or "").strip().lower()
    m = str(model_id or "").strip().lower()
    entry = None
    try:
        entry = get_llm_model(p, m) or get_llm_model_by_id(m)
    except Exception:
        entry = None
    pc = entry.get("prompt_cache") if isinstance(entry, dict) else None
    if not isinstance(pc, dict):
        # provider defaults (hooks for other providers: absent = none —
        # add an explicit entry to a catalog model dict to enable support,
        # never by sending unknown fields on the wire).
        pc = {"mode": "native_explicit"} if p == "openai" else {"mode": "none"}
    mode = str(pc.get("mode") or "none")
    if mode == "native_explicit":
        return {"supported": True, "mode": mode,
                "configuration": {"prompt_cache_key": "voice-%s-v1" % (m or "model")}}
    if mode == "native_automatic":
        return {"supported": True, "mode": mode, "configuration": None}
    return {"supported": False, "mode": "none", "configuration": None}
def list_all_providers() -> List[Dict[str, Any]]:
    """Every provider including deprecated — for validation/legacy display only."""
    return list(LLM_PROVIDERS.values())

def list_models_for_provider(provider: str) -> List[Dict[str, Any]]:
    return [m for m in LLM_MODELS if m["provider"] == provider and m["status"] == "active"]

def list_all_models() -> List[Dict[str, Any]]:
    return LLM_MODELS

def validate_provider_model(provider: str, model_id: str) -> tuple[bool, str]:
    """
    Validate provider/model combination.
    Returns (is_valid, error_message). If invalid, error_message explains why.
    Does NOT silently replace.
    """
    prov = get_llm_provider(provider)
    if not prov:
        return False, f"Unknown LLM provider '{provider}'. Valid providers: {list(LLM_PROVIDERS.keys())}"
    
    model = get_llm_model(provider, model_id)
    if not model:
        # Check if model exists under different provider
        existing = get_llm_model_by_id(model_id)
        if existing:
            return False, f"Invalid model '{model_id}' for provider '{provider}'. Model '{model_id}' belongs to provider '{existing['provider']}' (base_url {existing['base_url']}). Use provider='{existing['provider']}' with model='{model_id}'. Do not treat Groq's 120B as OpenAI model. Provider and model must remain separate."
        else:
            # List valid models for this provider
            valid_models = [m["model_id"] for m in list_models_for_provider(provider)]
            return False, f"Unknown model '{model_id}' for provider '{provider}'. Valid models for {provider}: {valid_models}. If model is from another provider, use that provider."
    
    if model["status"] == "deprecated":
        # Still valid but warn
        return True, f"Warning: model '{model_id}' for provider '{provider}' is deprecated: {model.get('notes','')}"
    
    return True, ""

def calculate_llm_cost(model_meta: Dict[str, Any], input_tokens: int, cached_input_tokens: int, output_tokens: int) -> Dict[str, float]:
    """
    Calculate LLM cost per request using selected model's pricing metadata.
    """
    input_price = model_meta.get("input_price_per_1m", 0) / 1_000_000
    cached_price = model_meta.get("cached_input_price_per_1m", 0) / 1_000_000
    output_price = model_meta.get("output_price_per_1m", 0) / 1_000_000
    
    # If cached tokens not separately tracked, treat all input as regular
    # But if cached provided, subtract from input? Actually input_tokens includes cached? We assume separate.
    # For OpenAI, cached_input_tokens are part of input_tokens that were cached.
    # So we calculate: (input - cached) * input_price + cached * cached_price + output * output_price
    # If input_tokens already excludes cached, then use as is.
    # We will assume input_tokens is total input, and cached is subset that was cached.
    # To be safe, if cached > input, cap.
    if cached_input_tokens > input_tokens:
        cached_input_tokens = input_tokens
    
    non_cached_input = input_tokens - cached_input_tokens
    input_cost = non_cached_input * input_price + cached_input_tokens * cached_price
    output_cost = output_tokens * output_price
    total = input_cost + output_cost
    
    return {
        "input_cost": input_cost,
        "cached_input_cost": cached_input_tokens * cached_price,
        "output_cost": output_cost,
        "total_llm_cost": total,
        "input_price_per_1m": model_meta.get("input_price_per_1m", 0),
        "cached_input_price_per_1m": model_meta.get("cached_input_price_per_1m", 0),
        "output_price_per_1m": model_meta.get("output_price_per_1m", 0),
    }

def catalog_summary_v2() -> Dict[str, Any]:
    """Return new catalog organized for frontend: providers with models.

    Deprecated providers (openrouter) are excluded from the picker; their saved
    agents keep working via the legacy-id mapping + validate_provider_model().
    Deprecated *models* stay visible under their provider (marked) so users see
    when a saved model was retired and can pick the replacement.
    """
    active_providers = {p["id"]: p for p in list_providers()}
    return {
        "providers": active_providers,
        "models": LLM_MODELS,
        "by_provider": {pid: list_models_for_provider(pid) for pid in active_providers},
    }
