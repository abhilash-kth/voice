"""LLM Provider → Multiple Models catalog (split into data + queries).

This package is a pure re-export façade; the import surface is IDENTICAL to
the old single-file ``app/llm_catalog.py``::

    from app.llm_catalog import LLM_PROVIDERS, LLM_MODELS  # still works
    from .llm_catalog import validate_provider_model        # still works

Layout:
- ``providers_data.py`` — static LLM provider definitions (seed data; the live
  source-of-truth is the DB Provider table maintained via the Super Admin).
- ``models_data.py`` — static LLM model definitions (same merge story).
- ``queries.py`` — lookups, validation, cost math, summarising helpers.

LLM temperature is intentionally NOT part of any model metadata — the runtime
always uses the provider's default sampling.
"""
from .providers_data import LLM_PROVIDERS
from .models_data import LLM_MODELS
from .queries import (
    get_llm_provider,
    get_llm_model,
    get_llm_model_by_id,
    list_providers,
    get_prompt_cache_capability,
    list_all_providers,
    list_models_for_provider,
    list_all_models,
    validate_provider_model,
    calculate_llm_cost,
    catalog_summary_v2,
)

__all__ = [
    "LLM_PROVIDERS",
    "LLM_MODELS",
    "get_llm_provider",
    "get_llm_model",
    "get_llm_model_by_id",
    "list_providers",
    "get_prompt_cache_capability",
    "list_all_providers",
    "list_models_for_provider",
    "list_all_models",
    "validate_provider_model",
    "calculate_llm_cost",
    "catalog_summary_v2",
]
