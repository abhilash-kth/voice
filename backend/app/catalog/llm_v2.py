"""V2 LLM provider/model API + pricing helpers (thin wrappers).

Extracted from catalog.py - the real implementation lives in the
``llm_catalog`` package; these keep the historical import surface of
``app.catalog``.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


from ..llm_catalog import (
    get_llm_provider as _get_llm_provider_v2,
    get_llm_model as _get_llm_model_v2,
    list_providers as _list_llm_providers_v2,
    list_models_for_provider as _list_llm_models_for_provider_v2,
    validate_provider_model as _validate_llm_provider_model,
    calculate_llm_cost as _calculate_llm_cost_v2,
)


def get_llm_provider(provider_id: str) -> Optional[Dict[str, Any]]:
    return _get_llm_provider_v2(provider_id)

def get_llm_model(provider: str, model_id: str) -> Optional[Dict[str, Any]]:
    return _get_llm_model_v2(provider, model_id)

def list_llm_providers() -> List[Dict[str, Any]]:
    return _list_llm_providers_v2()

def list_llm_models_for_provider(provider: str) -> List[Dict[str, Any]]:
    return _list_llm_models_for_provider_v2(provider)

def validate_llm_provider_model(provider: str, model_id: str) -> tuple[bool, str]:
    return _validate_llm_provider_model(provider, model_id)

def calculate_llm_cost(provider: str, model_id: str, input_tokens: int, cached_input_tokens: int, output_tokens: int) -> Dict[str, float]:
    model = get_llm_model(provider, model_id)
    if not model:
        return {"input_cost": 0, "output_cost": 0, "total_llm_cost": 0}
    return _calculate_llm_cost_v2(model, input_tokens, cached_input_tokens, output_tokens)

def get_model_pricing(provider: str, model_id: str) -> Optional[Dict[str, Any]]:
    model = get_llm_model(provider, model_id)
    if not model:
        return None
    return {
        "provider": model["provider"],
        "model_id": model["model_id"],
        "display_name": model["display_name"],
        "input_price_per_1m": model["input_price_per_1m"],
        "cached_input_price_per_1m": model["cached_input_price_per_1m"],
        "output_price_per_1m": model["output_price_per_1m"],
        "context_window": model["context_window"],
        "max_output_tokens": model["max_output_tokens"],
        "reasoning_supported": model["reasoning_supported"],
        "reasoning_default": model["reasoning_default"],
        "streaming_supported": model["streaming_supported"],
        "tool_calling_supported": model["tool_calling_supported"],
        "structured_output_supported": model["structured_output_supported"],
        "expected_speed": model["expected_speed"],
        "status": model["status"],
        "capabilities": model["capabilities"],
        "notes": model["notes"],
        "base_url": model["base_url"],
    }
