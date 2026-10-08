"""LLM backward-compat bridge.

Builds the legacy ``CATALOG['llm']`` mapping (provider_id -> spec with
a single ``model`` field) from the V2 provider/model metadata in
``llm_catalog``. Extracted from catalog.py - behavior unchanged.
"""
from __future__ import annotations

from typing import Any, Dict


from ..llm_catalog import (
    LLM_PROVIDERS,
    LLM_MODELS,
    get_llm_model as _get_llm_model_v2,
)


def _build_llm_catalog_v2_with_compat():
    """Populate CATALOG['llm'] from new LLM_PROVIDERS and LLM_MODELS with backward compat."""
    llm_catalog = {}
    
    # New provider → models structure: each provider id has multiple models
    # For backward compat, also create old-style ids like openai_gpt_4_1_mini
    # that map to provider=openai, model=gpt-4.1-mini
    
    # First, add new-style entries: provider id itself (e.g., "openai") with models list
    # But old code expects CATALOG["llm"] to be dict of provider_id -> spec with model field
    # We will create both:
    # - New style: "openai" provider with models catalog
    # - Old style: "openai_gpt_4_1_mini" etc for backward compat, marked deprecated
    
    # Map old ids to new provider/model for backward compat
    old_id_mapping = {
        "openai_gpt_4o_mini": ("openai", "gpt-4o-mini"),
        "openai_gpt_4o": ("openai", "gpt-4o"),
        "openai_gpt_4_1_mini": ("openai", "gpt-4.1-mini"),
        "openai_gpt_4_1": ("openai", "gpt-4.1"),
        "openai_gpt_oss_120b": ("openai", "gpt-4o"),  # Old invalid mapping, now points to valid gpt-4o
        "groq_gpt_oss": ("groq", "openai/gpt-oss-120b"),
        "groq_gpt_oss_20b": ("groq", "openai/gpt-oss-20b"),
        "groq_llama_3_3_70b": ("groq", "meta-llama/llama-4-maverick-17b-128e-instruct"),  # llama-3.3 retired 08/16/26 -> Llama 4 Maverick
        "groq_qwen_3_8_27b": ("groq", "qwen/qwen3.8-27b"),  # Qwen3 (deprecated) -> Qwen3.6 (superseded 2026-09-24) -> Qwen3.8 27B, Groq's current
        # openrouter is deprecated: map its legacy ids onto live equivalents so an
        # agent saved against them keeps working (and stops rate-limiting).
        "openrouter_gemma": ("google", "gemini-2.5-flash-lite"),
        "openrouter_gemma_26b": ("google", "gemini-2.5-flash-lite"),
    }
    
    # Build new provider entries
    for prov_id, prov_meta in LLM_PROVIDERS.items():
        # Get models for this provider
        models = [m for m in LLM_MODELS if m["provider"] == prov_id and m["status"] == "active"]
        # For new architecture, provider entry contains models list
        llm_catalog[prov_id] = {
            "kind": "llm",
            "id": prov_id,
            "display_name": prov_meta["display_name"],
            "provider": prov_meta["provider_type"],
            "provider_id": prov_id,
            "base_url": prov_meta["base_url"],
            "tier": prov_meta["tier"],
            "requires_key": prov_meta["requires_key"],
            "key_env": prov_meta["key_env"],
            "notes": prov_meta.get("notes", ""),
            "models": models,  # Rich model catalog
            "model_count": len(models),
            # For backward compat, keep single model field as first model
            "model": models[0]["model_id"] if models else "",
            "cost": {
                "per_1k_in": models[0]["input_price_per_1m"] / 1000 if models else 0,
                "per_1k_out": models[0]["output_price_per_1m"] / 1000 if models else 0,
            } if models else {},
            "options": {
                "model": [m["model_id"] for m in models],
            },
        }
    
    # Add backward compat old ids
    for old_id, (new_prov, new_model) in old_id_mapping.items():
        model_meta = _get_llm_model_v2(new_prov, new_model)
        if not model_meta:
            # Try by model_id alone
            model_meta = _get_llm_model_v2(new_prov, new_model) or next((m for m in LLM_MODELS if m["model_id"] == new_model), None)
        prov_meta = LLM_PROVIDERS.get(new_prov, {})
        if model_meta:
            llm_catalog[old_id] = {
                "kind": "llm",
                "id": old_id,
                "display_name": f"{model_meta['display_name']} (legacy id, use {new_prov} provider)",
                "provider": prov_meta.get("provider_type", new_prov),
                "provider_id": new_prov,
                "base_url": model_meta["base_url"],
                "model": model_meta["model_id"],
                "model_meta": model_meta,  # Rich metadata
                "tier": prov_meta.get("tier", "paid"),
                "requires_key": prov_meta.get("requires_key", True),
                "key_env": prov_meta.get("key_env", ""),
                "cost": {
                    "per_1k_in": model_meta["input_price_per_1m"] / 1000,
                    "per_1k_out": model_meta["output_price_per_1m"] / 1000,
                },
                "options": {
                    "model": [model_meta["model_id"]],
                },
                "notes": f"Legacy id for backward compat. New: provider={new_prov}, model={new_model}. {model_meta.get('notes','')}",
                "legacy": True,
                "new_provider": new_prov,
                "new_model": new_model,
            }
        else:
            # If model not found, keep minimal entry to avoid breaking existing agents
            llm_catalog[old_id] = {
                "kind": "llm",
                "id": old_id,
                "display_name": old_id,
                "provider": new_prov,
                "provider_id": new_prov,
                "base_url": prov_meta.get("base_url"),
                "model": new_model,
                "tier": "paid",
                "requires_key": True,
                "key_env": prov_meta.get("key_env", ""),
                "cost": {"per_1k_in": 0.15, "per_1k_out": 0.60},
                "options": {"model": [new_model]},
                "notes": f"Legacy id, maps to {new_prov}:{new_model}",
                "legacy": True,
            }
    
    return llm_catalog

