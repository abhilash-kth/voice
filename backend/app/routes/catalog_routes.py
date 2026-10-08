"""Public provider-catalog routes (/api/catalog + /api/llm/*).

The payloads are rendered from the DB-backed snapshot (Super-Admin edits go
live without a deploy); code catalogs are the automatic fallback. Extracted
from the old monolithic main.py — behavior unchanged.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from ..catalog import catalog_summary, get_provider, validate_llm_provider_model
from ..llm_catalog import validate_provider_model as validate_llm_v2
from ..services import config_store

logger = logging.getLogger("voice-agent-saas-api")

router = APIRouter(tags=["catalog"])


# ---------------------------------------------------------------------------
# Provider catalog (for the config UI) - V2 Provider → Multiple Models
# ---------------------------------------------------------------------------
@router.get("/api/catalog")
async def get_catalog():
    # User-facing catalog: rendered from the dynamic config snapshot so the
    # Super Admin's enabled/price/language edits go live without a deploy, and
    # disabled providers/models are hidden from pickers. Falls back to the code
    # catalog unchanged when no DB snapshot exists (identical legacy payload).
    try:
        from ..services import catalog_service
        await config_store.refresh_if_stale()
        return catalog_service.build_user_catalog()
    except Exception as e:
        logger.warning(f"user catalog snapshot render failed, using code defaults: {e!r}")
    cat = catalog_summary()
    from ..llm_catalog import catalog_summary_v2, LLM_PROVIDERS, LLM_MODELS
    llm_v2 = catalog_summary_v2()
    provs = llm_v2["providers"]
    if not isinstance(provs, list):
        provs = list(provs.values())
    models = llm_v2["models"]
    if not isinstance(models, list):
        models = list(models.values())
    from ..config import WALLET_TOPUP_AMOUNT, SERVER_COST_PER_MIN
    return {
        "catalog": cat,
        "llm_catalog": llm_v2,
        "llm_providers": provs,
        "llm_models": models,
        # Every model incl. deprecated — a saved retired model still renders.
        "llm_models_all": list(LLM_MODELS),
        # Deprecated providers (openrouter) for legacy-agent display only.
        "llm_legacy_providers": [p for p in LLM_PROVIDERS.values() if p.get("status") == "deprecated"],
        "llm_by_provider": llm_v2["by_provider"],
        "walletTopupAmounts": WALLET_TOPUP_AMOUNT,
        "server_cost_per_min": SERVER_COST_PER_MIN,
        "voice_speed": {"min": 0.6, "max": 1.6, "default": 1.0},
    }

@router.get("/api/llm/providers")
async def list_llm_providers():
    # DB-aware (Super-Admin-enabled only), code catalog as automatic fallback.
    try:
        from ..services import catalog_service
        await config_store.refresh_if_stale()
        return catalog_service.llm_providers_public()
    except Exception as e:
        logger.warning(f"llm providers snapshot failed, code defaults: {e!r}")
    from ..llm_catalog import list_models_for_provider, list_providers, LLM_PROVIDERS
    provs = list_providers()
    return {
        "providers": provs,
        "legacy_providers": [p for p in LLM_PROVIDERS.values() if p.get("status") == "deprecated"],
        "by_provider": {p["id"]: list_models_for_provider(p["id"]) for p in provs},
    }

@router.get("/api/llm/providers/{provider_id}/models")
async def list_models_for_provider(provider_id: str):
    try:
        from ..services import catalog_service
        await config_store.refresh_if_stale()
        out = catalog_service.llm_models_for_provider_public(provider_id)
        if out is not None:
            return out
    except Exception as e:
        logger.warning(f"llm models snapshot failed, code defaults: {e!r}")
    from ..llm_catalog import list_models_for_provider as _list_models, get_llm_provider
    prov = get_llm_provider(provider_id)
    if not prov:
        raise HTTPException(404, f"Unknown LLM provider '{provider_id}'")
    models = _list_models(provider_id)
    return {"provider": prov, "models": models}

@router.get("/api/llm/models/{provider}/{model_id}")
async def get_model_details(provider: str, model_id: str):
    try:
        from ..services import catalog_service
        await config_store.refresh_if_stale()
        ok, msg, meta = catalog_service.llm_model_details_public(provider, model_id)
        if not ok:
            raise HTTPException(404 if meta is None and "not found" in msg else 400, msg)
        return {"model": meta}
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"llm model details snapshot failed, code defaults: {e!r}")
    from ..llm_catalog import get_llm_model, validate_provider_model
    is_valid, msg = validate_provider_model(provider, model_id)
    if not is_valid:
        raise HTTPException(400, msg)
    model = get_llm_model(provider, model_id)
    if not model:
        raise HTTPException(404, f"Model {model_id} not found for provider {provider}")
    return {"model": model}

@router.post("/api/llm/validate")
async def validate_llm_selection(body: dict):
    """Validate provider/model combination, return clear error if invalid, no silent substitution."""
    provider = body.get("provider", "")
    model_id = body.get("model_id", body.get("model", ""))
    if not provider or not model_id:
        raise HTTPException(400, "Both provider and model_id required")
    from ..services import catalog_service
    try:
        await config_store.refresh_if_stale()
        is_valid, msg = catalog_service.validate_llm(provider, model_id)
        if not is_valid:
            raise HTTPException(400, msg)
        from ..services.config_store import get_llm_meta
        model = get_llm_meta(provider, model_id)
    except HTTPException:
        raise
    return {"valid": True, "provider": provider, "model": model, "message": msg}


# ---------------------------------------------------------------------------