"""
Provider catalog for the Voice Agent SaaS platform - V2 architecture.

Provider → Multiple Models architecture.

Each provider has multiple models with rich metadata:
- provider, model_id, display_name, base_url
- input_price_per_1m, cached_input_price_per_1m, output_price_per_1m
- context_window, max_output_tokens
- reasoning_supported, reasoning_default
- streaming_supported, tool_calling_supported, structured_output_supported
- expected_speed (very_fast, fast, medium, slow)
- status (active/deprecated), capabilities, notes

No silent model substitution. Invalid provider/model returns clear config error.
"""
from __future__ import annotations

# Facade: this package keeps the full import surface of the old
# app/catalog.py module - data, compat bridge, queries, llm passthroughs.
from .data import CATALOG

from .queries import catalog_summary, get_provider, providers_of
from .llm_v2 import (
    calculate_llm_cost,
    get_llm_model,
    get_llm_provider,
    get_model_pricing,
    list_llm_models_for_provider,
    list_llm_providers,
    validate_llm_provider_model,
)

# llm_catalog passthrough names (historically importable from app.catalog)
from ..llm_catalog import (  # noqa: F401
    LLM_MODELS,
    LLM_PROVIDERS,
    catalog_summary_v2 as _llm_catalog_summary_v2,
    calculate_llm_cost as _calculate_llm_cost_v2,
    get_llm_model as _get_llm_model_v2,
    get_llm_model_by_id as _get_llm_model_by_id_v2,
    get_llm_provider as _get_llm_provider_v2,
    list_models_for_provider as _list_llm_models_for_provider_v2,
    list_providers as _list_llm_providers_v2,
    validate_provider_model as _validate_llm_provider_model,
)
