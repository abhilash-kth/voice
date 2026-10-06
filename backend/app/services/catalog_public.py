"""User-facing catalog renderers + the DB snapshot builder.

Extracted from the old monolithic catalog_service — behavior unchanged.
Import via ``app.services.catalog_service`` (the façade re-exports everything).
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from .. import llm_catalog as code_llm
from ..db import get_prisma
from .config_store import ConfigSnapshot

logger = logging.getLogger("voice-agent-saas-catalog-service")


def _load(s: Optional[str]) -> dict:
    if not s:
        return {}
    try:
        return json.loads(s)
    except Exception:
        return {}

def _now() -> str:
    from datetime import datetime

    return datetime.utcnow().isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Snapshot building
# ---------------------------------------------------------------------------
async def build_snapshot_from_db() -> Optional[ConfigSnapshot]:
    import time

    db = get_prisma()
    providers = await db.provider.find_many(order={"sortOrder": "asc"})
    models = await db.catalogmodel.find_many(order={"sortOrder": "asc"})
    creds = await db.providercredential.find_many()
    billing_row = await db.billingconfig.find_unique(where={"id": "global"})

    prov_map: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for p in providers:
        d = _provider_dict(p)
        prov_map.setdefault(p.kind, {})[p.slug] = d

    model_list: Dict[str, List[Dict[str, Any]]] = {}
    for m in models:
        d = _model_dict(m)
        model_list.setdefault(m.kind, []).append(d)

    cred_map: Dict[str, List[Dict[str, Any]]] = {}
    for c in creds:
        key = f"{c.kind or ''}:{c.providerSlug}"
        cred_map.setdefault(key, []).append({
            "id": c.id, "providerSlug": c.providerSlug, "kind": c.kind or "",
            "label": c.label or "", "encValue": c.encValue,
            "maskedValue": c.maskedValue or "", "status": c.status,
        })

    billing: Dict[str, Any] = {}
    if billing_row:
        billing = {
            "serverCostPerMin": billing_row.serverCostPerMin,
            "minClientPrice": billing_row.minClientPrice,
            "profitMarginPercent": billing_row.profitMarginPercent,
            "voiceSpeedMin": billing_row.voiceSpeedMin,
            "voiceSpeedMax": billing_row.voiceSpeedMax,
            "voiceSpeedDefault": billing_row.voiceSpeedDefault,
            "wallet_topup_amounts": json.loads(billing_row.walletTopupAmounts or "[]"),
            # Per-mode pricing + surcharges (billing_rates.customer_price)
            "announcementPricePerMin": getattr(billing_row, "announcementPricePerMin", 0) or 0,
            "assistantPricePerMin": getattr(billing_row, "assistantPricePerMin", 0) or 0,
            "miscFeePerMin": getattr(billing_row, "miscFeePerMin", 0) or 0,
            "concurrencyAddons": getattr(billing_row, "concurrencyAddons", "[]") or "[]",
        }

    return ConfigSnapshot(
        ts=time.time(), source="db",
        providers=prov_map, models=model_list, billing=billing, credentials=cred_map,
    )


def _provider_dict(p) -> Dict[str, Any]:
    return {
        "id": p.id, "kind": p.kind, "slug": p.slug,
        "displayName": p.displayName, "providerType": p.providerType or "",
        "baseUrl": p.baseUrl or "", "keyEnv": p.keyEnv or "",
        "tier": p.tier, "requiresKey": bool(p.requiresKey),
        "enabled": bool(p.enabled), "status": p.status or "active",
        "notes": p.notes or "", "sortOrder": p.sortOrder or 0,
        "createdAt": p.createdAt or "", "updatedAt": p.updatedAt or "",
    }


def _model_dict(m) -> Dict[str, Any]:
    return {
        "id": m.id, "kind": m.kind, "providerId": m.providerId,
        "providerSlug": m.providerSlug, "catalogId": m.catalogId,
        "modelId": m.modelId or "", "displayName": m.displayName,
        "enabled": bool(m.enabled), "status": m.status or "active",
        "tier": m.tier or "paid",
        "customerPricePerMin": float(m.customerPricePerMin or 0),
        "priceCurrency": m.priceCurrency or "INR",
        "inputPricePer1M": float(m.inputPricePer1M or 0),
        "cachedInputPricePer1M": float(m.cachedInputPricePer1M or 0),
        "outputPricePer1M": float(m.outputPricePer1M or 0),
        "costPerMin": float(m.costPerMin or 0),
        "costPer1kChars": float(m.costPer1kChars or 0),
        "_meta": _load(m.meta),
        "sortOrder": m.sortOrder or 0,
        "createdAt": m.createdAt or "", "updatedAt": m.updatedAt or "",
    }


# ---------------------------------------------------------------------------
# User-facing catalog (enabled-filtered, super-admin controlled)
# ---------------------------------------------------------------------------
def build_user_catalog() -> Dict[str, Any]:
    """Render /api/catalog payload from the snapshot, honouring enabled flags.

    Disabled providers/models are hidden from pickers. The llm_models_all key
    intentionally keeps EVERY model (incl. disabled) so an agent saved against
    one still renders in the edit form — matching the previous contract.
    """
    from . import config_store

    snap = config_store.get_snapshot()
    billing = config_store.get_billing()

    # Legacy catalog kinds (stt/tts/telephony): enabled-filtered provider lists
    cat: Dict[str, Any] = {}
    for kind in ("llm", "stt", "tts", "telephony"):
        provs = config_store.get_providers_of(kind)
        if kind in ("stt", "tts", "telephony"):
            provs = [p for p in provs
                     if p.get("enabled", True) and not p.get("deprecated")
                     and p.get("status", "active") != "deprecated"]
        elif kind == "llm":
            # llm key inside legacy catalog entry: keep code-merging behaviour
            provs = [p for p in provs if p.get("enabled", True) and not p.get("legacy")]
        cat[kind] = provs

    # ---- V2 LLM structures ----
    llm_providers_raw = _llm_provider_dicts()
    active_providers = [p for p in llm_providers_raw
                        if p.get("enabled", True) and p.get("status", "active") != "deprecated"]
    legacy_providers = [p for p in llm_providers_raw if p.get("status") == "deprecated"]

    all_models = config_store.list_llm_models()
    models_all = [m for m in all_models]
    enabled_models = [m for m in all_models
                      if m.get("enabled", m.get("status") == "active")
                      and m.get("status") == "active"
                      and config_store.get_llm_meta(m["provider"], m["model_id"]) is not None
                      and _provider_enabled(m["provider"])]

    by_provider: Dict[str, List[Dict[str, Any]]] = {}
    for p in active_providers:
        by_provider[p["id"]] = [m for m in enabled_models if m["provider"] == p["id"]]

    cat["llm_v2"] = {
        "providers": active_providers,
        "models": enabled_models,
        "by_provider": by_provider,
    }

    return {
        "catalog": cat,
        "llm_catalog": cat["llm_v2"],
        "llm_providers": active_providers,
        "llm_models": enabled_models,
        "llm_models_all": models_all,
        "llm_legacy_providers": legacy_providers,
        "llm_by_provider": by_provider,
        "walletTopupAmounts": billing["wallet_topup_amounts"],
        "server_cost_per_min": billing["server_cost_per_min"],
        "voice_speed": {
            "min": billing["voice_speed_min"],
            "max": billing["voice_speed_max"],
            "default": billing["voice_speed_default"],
        },
    }


def _provider_enabled(slug: str) -> bool:
    from . import config_store

    row = (config_store.get_snapshot().providers.get("llm") or {}).get(slug)
    if row is None:
        return True
    return bool(row.get("enabled", True)) and (row.get("status") or "active") != "deprecated"


def _llm_provider_dicts() -> List[Dict[str, Any]]:
    """LLM providers in llm_catalog code shape, merged with DB flags."""
    from . import config_store

    snap = config_store.get_snapshot()
    out: Dict[str, Dict[str, Any]] = {
        pid: dict(meta) for pid, meta in code_llm.LLM_PROVIDERS.items()
    }
    for slug, row in (snap.providers.get("llm") or {}).items():
        base = out.setdefault(slug, {
            "id": slug, "display_name": row.get("displayName") or slug,
            "provider_type": row.get("providerType") or "openai",
            "base_url": row.get("baseUrl") or "", "key_env": row.get("keyEnv") or "",
            "tier": row.get("tier") or "paid", "requires_key": True, "notes": "",
        })
        base["display_name"] = row.get("displayName") or base["display_name"]
        base["enabled"] = bool(row.get("enabled", True))
        base["status"] = row.get("status") or base.get("status", "active")
        base["key_env"] = row.get("keyEnv") or base.get("key_env", "")
        base["tier"] = row.get("tier") or base.get("tier", "paid")
        base["notes"] = row.get("notes") or base.get("notes", "")
        if row.get("baseUrl"):
            base["base_url"] = row["baseUrl"]
        if row.get("providerType"):
            base["provider_type"] = row["providerType"]
    return list(out.values())


# ---------------------------------------------------------------------------
# Public helpers for the /api/llm/* endpoints (enabled-filtered)
# ---------------------------------------------------------------------------
def llm_providers_public() -> Dict[str, Any]:
    """{providers, legacy_providers, by_provider} shape for the picker."""
    from . import config_store

    provs = _llm_provider_dicts()
    active = [p for p in provs if p.get("enabled", True) and p.get("status") != "deprecated"]
    legacy = [p for p in provs if p.get("status") == "deprecated"]
    enabled_models = [m for m in config_store.list_llm_models()
                      if m.get("status") == "active" and m.get("enabled", True)
                      and _provider_enabled(m["provider"])]
    return {
        "providers": active,
        "legacy_providers": legacy,
        "by_provider": {p["id"]: [m for m in enabled_models if m["provider"] == p["id"]]
                        for p in active},
    }


def llm_models_for_provider_public(provider_id: str) -> Optional[Dict[str, Any]]:
    from . import config_store

    provs = _llm_provider_dicts()
    prov = next((p for p in provs if p["id"] == provider_id), None)
    if not prov:
        return None
    models = [m for m in config_store.list_llm_models()
              if m["provider"] == provider_id and m.get("status") == "active"
              and m.get("enabled", True)]
    return {"provider": prov, "models": models}


def llm_model_details_public(provider: str, model_id: str) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    from . import config_store

    ok, msg = validate_llm(provider, model_id)
    if not ok:
        return False, msg, None
    meta = config_store.get_llm_meta(provider, model_id)
    if not meta:
        return False, f"Model {model_id} not found for provider {provider}", None
    return True, "ok", meta


# ---------------------------------------------------------------------------
# Validation helpers used by API paths (DB-aware, code fallback)
# ---------------------------------------------------------------------------
def validate_llm(provider: str, model_id: str) -> Tuple[bool, str]:
    """DB-aware provider/model validation with the same messages as code."""
    from . import config_store

    meta = config_store.get_llm_meta(provider, model_id)
    if meta is None:
        return code_llm.validate_provider_model(provider, model_id)
    row_prov = (config_store.get_snapshot().providers.get("llm") or {}).get(provider)
    if row_prov is not None and not bool(row_prov.get("enabled", True)):
        return False, (
            f"LLM provider '{provider}' is disabled by the administrator. "
            "Pick an enabled provider or ask the platform operator to enable it."
        )
    if meta.get("enabled") is False:
        return False, (
            f"Model '{model_id}' of provider '{provider}' is disabled by the "
            "administrator. Pick an enabled model."
        )
    return True, "ok"
