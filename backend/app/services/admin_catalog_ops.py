"""Super Admin provider + catalog-model CRUD.\n\nExtracted from the old monolithic admin_service — behavior unchanged.\n"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from ..db import get_prisma
from .admin_shared import _now, _invalidate, audit

logger = logging.getLogger("voice-agent-saas-admin")


# ---------------------------------------------------------------------------
# Providers (DB platform level)
# ---------------------------------------------------------------------------
def _provider_public(p) -> Dict[str, Any]:
    return {
        "id": p.id, "kind": p.kind, "slug": p.slug,
        "display_name": p.displayName, "adapter": p.providerType or "",
        "base_url": p.baseUrl or "", "key_env": p.keyEnv or "",
        "tier": p.tier, "requires_key": bool(p.requiresKey),
        "enabled": bool(p.enabled), "status": p.status or "active",
        "notes": p.notes or "", "sort_order": p.sortOrder or 0,
        "created_at": p.createdAt or "", "updated_at": p.updatedAt or "",
    }


async def list_providers(kind: Optional[str] = None) -> List[Dict[str, Any]]:
    db = get_prisma()
    where = {"kind": kind} if kind else {}
    rows = await db.provider.find_many(where=where, order={"sortOrder": "asc"})
    return [_provider_public(p) for p in rows]


async def create_provider(data: Dict[str, Any], *, admin: Dict[str, Any]) -> Dict[str, Any]:
    db = get_prisma()
    kind = (data.get("kind") or "").strip()
    slug = (data.get("slug") or "").strip().lower()
    if kind not in ("llm", "stt", "tts", "telephony"):
        raise ValueError("kind must be one of llm|stt|tts|telephony")
    if not slug or not slug.replace("-", "").replace("_", "").isalnum():
        raise ValueError("slug must be alphanumeric (dashes/underscores allowed)")
    existing = await db.provider.find_unique(
        where={"kind_slug": {"kind": kind, "slug": slug}}
    )
    if existing:
        raise ValueError(f"provider '{slug}' already exists for kind {kind}")
    now = _now()
    p = await db.provider.create(data={
        "kind": kind, "slug": slug,
        "displayName": (data.get("display_name") or "").strip() or slug,
        "providerType": data.get("adapter") or "",
        "baseUrl": data.get("base_url") or "",
        "keyEnv": data.get("key_env") or "",
        "tier": data.get("tier") or "paid",
        "requiresKey": bool(data.get("requires_key", True)),
        "enabled": bool(data.get("enabled", False)),  # new providers start hidden
        "notes": data.get("notes") or "",
        "sortOrder": int(data.get("sort_order", 0) or 0),
        "createdAt": now, "updatedAt": now,
    })
    await audit(admin, "provider_created", target_type="provider", target_id=p.id,
                detail={"kind": kind, "slug": slug})
    _invalidate()
    return _provider_public(p)


async def update_provider(pid: str, patch: Dict[str, Any], *, admin: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    db = get_prisma()
    p = await db.provider.find_unique(where={"id": pid})
    if not p:
        return None
    data: Dict[str, Any] = {}
    allowed = {
        "display_name": "displayName", "adapter": "providerType",
        "base_url": "baseUrl", "key_env": "keyEnv", "tier": "tier",
        "requires_key": "requiresKey", "enabled": "enabled",
        "status": "status", "notes": "notes", "sort_order": "sortOrder",
    }
    for k, v in patch.items():
        if k in allowed and v is not None:
            data[allowed[k]] = v
    if "enabled" in data:
        data["enabled"] = bool(data["enabled"])
    if "requires_key" in data:
        data["requires_key"] = bool(data["requires_key"])
    if data.get("status") and data["status"] not in ("active", "deprecated"):
        raise ValueError("status must be active|deprecated")
    if not data:
        return _provider_public(p)
    data["updatedAt"] = _now()
    p = await db.provider.update(where={"id": pid}, data=data)
    await audit(admin, "provider_updated", target_type="provider", target_id=pid,
                detail={"kind": p.kind, "slug": p.slug, "fields": sorted(patch.keys()),
                        "enabled": p.enabled})
    _invalidate()
    return _provider_public(p)


async def delete_provider(pid: str, *, admin: Dict[str, Any]) -> bool:
    db = get_prisma()
    p = await db.provider.find_unique(where={"id": pid}, include={"catalogModels": True})
    if not p:
        return False
    if p.catalogModels:
        # Delete+models is destructive to saved agents that reference those ids.
        # Allow only via explicit models cascade after the caller confirmed.
        await db.catalogmodel.delete_many(where={"providerId": pid})
        logger.warning(
            f"provider {p.kind}:{p.slug} deleted WITH {len(p.catalogModels)} model row(s) "
            f"(admin={admin.get('email')}) — saved agents referencing them now fall back to code defaults"
        )
    await db.providercredential.delete_many(where={"providerId": pid})
    await db.provider.delete(where={"id": pid})
    await audit(admin, "provider_deleted", target_type="provider", target_id=pid,
                detail={"kind": p.kind, "slug": p.slug})
    _invalidate()
    return True


# ---------------------------------------------------------------------------
# Catalog models
# ---------------------------------------------------------------------------
def _model_public(m) -> Dict[str, Any]:
    try:
        meta = json.loads(m.meta or "{}")
    except Exception:
        meta = {}
    return {
        "id": m.id, "kind": m.kind, "provider_id": m.providerId,
        "provider_slug": m.providerSlug, "catalog_id": m.catalogId,
        "model_id": m.modelId or "", "display_name": m.displayName,
        "enabled": bool(m.enabled), "status": m.status or "active",
        "tier": m.tier or "paid",
        "customer_price_per_min": float(m.customerPricePerMin or 0),
        "price_currency": m.priceCurrency or "INR",
        "input_price_per_1m": float(m.inputPricePer1M or 0),
        "cached_input_price_per_1m": float(m.cachedInputPricePer1M or 0),
        "output_price_per_1m": float(m.outputPricePer1M or 0),
        "cost_per_min": float(m.costPerMin or 0),
        "cost_per_1k_chars": float(m.costPer1kChars or 0),
        "meta": meta, "sort_order": m.sortOrder or 0,
        "created_at": m.createdAt or "", "updated_at": m.updatedAt or "",
    }


async def list_models(kind: Optional[str] = None, provider_id: Optional[str] = None,
                      *, page: int = 1, page_size: int = 200) -> Dict[str, Any]:
    db = get_prisma()
    where: Dict[str, Any] = {}
    if kind:
        where["kind"] = kind
    if provider_id:
        where["providerId"] = provider_id
    rows = await db.catalogmodel.find_many(where=where, order={"sortOrder": "asc"})
    items = [_model_public(m) for m in rows]
    total = len(items)
    start = (max(page, 1) - 1) * page_size
    return {"items": items[start:start + page_size], "total": total, "page": page, "page_size": page_size}


async def get_model(mid: str) -> Optional[Dict[str, Any]]:
    m = await get_prisma().catalogmodel.find_unique(where={"id": mid})
    return _model_public(m) if m else None


async def create_model(data: Dict[str, Any], *, admin: Dict[str, Any]) -> Dict[str, Any]:
    db = get_prisma()
    kind = (data.get("kind") or "").strip()
    provider_id = (data.get("provider_id") or "").strip()
    catalog_id = (data.get("catalog_id") or "").strip()
    model_id = (data.get("model_id") or "").strip()
    if kind not in ("llm", "stt", "tts", "telephony"):
        raise ValueError("kind must be one of llm|stt|tts|telephony")
    if not catalog_id:
        raise ValueError("catalog_id required (selection id, e.g. 'openai' or 'deepgram_nova2')")
    p = await db.provider.find_unique(where={"id": provider_id})
    if not p:
        raise LookupError("provider not found")
    if kind == "llm" and not model_id:
        raise ValueError("model_id required for LLM models (e.g. 'gpt-4.1-mini')")
    existing = await db.catalogmodel.find_unique(where={
        "kind_catalogId_providerSlug_modelId": {
            "kind": kind, "catalogId": catalog_id,
            "providerSlug": p.slug, "modelId": model_id,
        }
    })
    if existing:
        raise ValueError("a model row with this (kind, catalog_id, provider, model_id) already exists")
    now = _now()
    m = await db.catalogmodel.create(data={
        "kind": kind, "providerId": p.id, "providerSlug": p.slug,
        "catalogId": catalog_id, "modelId": model_id,
        "displayName": (data.get("display_name") or "").strip() or (model_id or catalog_id),
        "enabled": bool(data.get("enabled", False)),  # new rows start hidden
        "status": "active",
        "tier": data.get("tier") or p.tier,
        "customerPricePerMin": float(data.get("customer_price_per_min") or 0),
        "priceCurrency": data.get("price_currency") or "INR",
        "inputPricePer1M": float(data.get("input_price_per_1m") or 0),
        "cachedInputPricePer1M": float(data.get("cached_input_price_per_1m") or 0),
        "outputPricePer1M": float(data.get("output_price_per_1m") or 0),
        "costPerMin": float(data.get("cost_per_min") or 0),
        "costPer1kChars": float(data.get("cost_per_1k_chars") or 0),
        "meta": json.dumps(data.get("meta") or {}, ensure_ascii=False),
        "sortOrder": int(data.get("sort_order", 0) or 0),
        "createdAt": now, "updatedAt": now,
    })
    await audit(admin, "model_created", target_type="model", target_id=m.id,
                detail={"kind": kind, "provider": p.slug, "catalog_id": catalog_id, "model_id": model_id})
    _invalidate()
    return _model_public(m)


async def update_model(mid: str, patch: Dict[str, Any], *, admin: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    db = get_prisma()
    m = await db.catalogmodel.find_unique(where={"id": mid})
    if not m:
        return None
    data: Dict[str, Any] = {}
    allowed = {
        "display_name": "displayName", "enabled": "enabled", "status": "status",
        "tier": "tier", "customer_price_per_min": "customerPricePerMin",
        "price_currency": "priceCurrency",
        "input_price_per_1m": "inputPricePer1M",
        "cached_input_price_per_1m": "cachedInputPricePer1M",
        "output_price_per_1m": "outputPricePer1M",
        "cost_per_min": "costPerMin", "cost_per_1k_chars": "costPer1kChars",
        "sort_order": "sortOrder",
    }
    for k, v in patch.items():
        if k in allowed and v is not None:
            data[allowed[k]] = v
    if "enabled" in data:
        data["enabled"] = bool(data["enabled"])
    if data.get("status") and data["status"] not in ("active", "deprecated"):
        raise ValueError("status must be active|deprecated")
    if "meta" in patch and isinstance(patch["meta"], dict):
        # merge meta so partial admin edits don't wipe the rest
        try:
            cur = json.loads(m.meta or "{}")
        except Exception:
            cur = {}
        cur.update(patch["meta"])
        data["meta"] = json.dumps(cur, ensure_ascii=False)
    if not data:
        return _model_public(m)
    data["updatedAt"] = _now()
    before = {"price": m.customerPricePerMin, "enabled": m.enabled}
    m = await db.catalogmodel.update(where={"id": mid}, data=data)
    await audit(admin, "model_updated", target_type="model", target_id=mid,
                detail={"kind": m.kind, "provider": m.providerSlug,
                        "catalog_id": m.catalogId, "model_id": m.modelId,
                        "fields": sorted(patch.keys()),
                        "price_from": before["price"], "price_to": m.customerPricePerMin})
    _invalidate()
    return _model_public(m)


async def delete_model(mid: str, *, admin: Dict[str, Any]) -> bool:
    db = get_prisma()
    m = await db.catalogmodel.find_unique(where={"id": mid})
    if not m:
        return False
    await db.catalogmodel.delete(where={"id": mid})
    await audit(admin, "model_deleted", target_type="model", target_id=mid,
                detail={"kind": m.kind, "provider": m.providerSlug,
                        "catalog_id": m.catalogId, "model_id": m.modelId})
    _invalidate()
    return True


# ---------------------------------------------------------------------------
# Billing config
# ---------------------------------------------------------------------------