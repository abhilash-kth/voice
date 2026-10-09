"""Catalog queries over the merged code catalog (facade helpers).

Extracted from catalog.py. ``CATALOG['llm']`` is wired here on import so
``providers_of``/``get_provider`` see exactly the same dict the old
single-module catalog exposed.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


from ..llm_catalog import (
    LLM_PROVIDERS,
    LLM_MODELS,
    get_llm_model as _get_llm_model_v2,
    catalog_summary_v2 as _llm_catalog_summary_v2,
)
from .data import CATALOG
from .llm_compat import _build_llm_catalog_v2_with_compat


# ---------------------------------------------------------------------------
# Helper functions - V2 architecture with backward compat
# ---------------------------------------------------------------------------
CATALOG["llm"] = _build_llm_catalog_v2_with_compat()


def providers_of(kind: str) -> List[Dict[str, Any]]:
    """Return provider list for kind, each with id embedded.
    
    For LLM, filter out legacy ids from main catalog list to avoid cluttering UI
    with 'GPT-4o Mini (legacy id, use openai provider)' etc. Legacy ids still
    exist in CATALOG['llm'] for backward compat (old agents), but are hidden from
    provider dropdown. Frontend V2 uses llm_providers (3 providers) + llm_by_provider
    for model selection. Legacy mapping still works for existing agents.
    """
    out = []
    for pid, spec in CATALOG.get(kind, {}).items():
        # For LLM, hide legacy ids from providers_of to clean UI
        if kind == "llm" and spec.get("legacy"):
            continue
        # Hide deprecated providers (e.g. the OpenRouter TTS entries) from the
        # picker; get_provider() still resolves them for saved agents.
        if spec.get("deprecated"):
            continue
        item = dict(spec)
        item["id"] = pid
        out.append(item)
    return out

def get_provider(kind: str, provider_id: str) -> Optional[Dict[str, Any]]:
    """Get provider by kind and id. Supports both new and legacy ids."""
    if kind == "llm":
        # Try new catalog first
        if provider_id in CATALOG["llm"]:
            return CATALOG["llm"][provider_id]
        # Try to parse provider:model format
        if ":" in provider_id:
            prov, model = provider_id.split(":", 1)
            model_meta = _get_llm_model_v2(prov, model)
            if model_meta:
                prov_meta = LLM_PROVIDERS.get(prov, {})
                return {
                    "kind": "llm",
                    "id": provider_id,
                    "display_name": model_meta["display_name"],
                    "provider": prov_meta.get("provider_type", prov),
                    "provider_id": prov,
                    "base_url": model_meta["base_url"],
                    "model": model_meta["model_id"],
                    "model_meta": model_meta,
                    "tier": prov_meta.get("tier", "paid"),
                    "requires_key": True,
                    "key_env": prov_meta.get("key_env", ""),
                    "cost": {
                        "per_1k_in": model_meta["input_price_per_1m"] / 1000,
                        "per_1k_out": model_meta["output_price_per_1m"] / 1000,
                    },
                }
        # Try model_id alone
        model_meta = next((m for m in LLM_MODELS if m["model_id"] == provider_id), None)
        if model_meta:
            prov_meta = LLM_PROVIDERS.get(model_meta["provider"], {})
            return {
                "kind": "llm",
                "id": provider_id,
                "display_name": model_meta["display_name"],
                "provider": prov_meta.get("provider_type", model_meta["provider"]),
                "provider_id": model_meta["provider"],
                "base_url": model_meta["base_url"],
                "model": model_meta["model_id"],
                "model_meta": model_meta,
                "tier": prov_meta.get("tier", "paid"),
                "requires_key": True,
                "key_env": prov_meta.get("key_env", ""),
                "cost": {
                    "per_1k_in": model_meta["input_price_per_1m"] / 1000,
                    "per_1k_out": model_meta["output_price_per_1m"] / 1000,
                },
            }
    return CATALOG.get(kind, {}).get(provider_id)

def catalog_summary() -> Dict[str, Any]:
    """Return catalogue organised for frontend config UI - backward compat + new."""
    out: Dict[str, Any] = {}
    for kind in ("llm", "stt", "tts", "telephony"):
        out[kind] = providers_of(kind)
    # Add new V2 structure for LLM
    out["llm_v2"] = _llm_catalog_summary_v2()
    from ..llm_catalog import list_providers as _active_llm_providers
    out["llm_providers"] = _active_llm_providers()
    out["llm_models"] = LLM_MODELS
    out["llm_by_provider"] = {pid: [m for m in LLM_MODELS if m["provider"] == pid] for pid in LLM_PROVIDERS}
    return out

# ---------------------------------------------------------------------------
# New V2 API for LLM - Provider → Multiple Models
# ---------------------------------------------------------------------------
