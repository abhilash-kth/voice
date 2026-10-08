"""PlanTier (Super-Admin-managed purchasable plan rows) — DAO + admin CRUD.

kind="capacity": units = number of agents the plan allows (platform fee).
kind="kb_pack":  units = extra KB characters, faqs = extra FAQ entries.
Prices are ₹/month. Split from subscription_service (≤300-line rule); the
config snapshot is invalidated on every mutation so fresh prices propagate.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from ..db import get_prisma


def _plan_dict(r: Any) -> Dict[str, Any]:
    return {
        "id": r.id, "kind": r.kind, "label": r.label, "units": r.units or 0,
        "faqs": r.faqs or 0, "price_per_month": float(r.pricePerMonth or 0),
        "enabled": bool(r.enabled), "sort_order": r.sortOrder or 0,
    }


async def list_plans(kind: Optional[str] = None, only_enabled: bool = True) -> List[Dict[str, Any]]:
    db = get_prisma()
    where: Dict[str, Any] = {}
    if kind:
        where["kind"] = kind
    if only_enabled:
        where["enabled"] = True
    rows = await db.plantier.find_many(where=where, order={"sortOrder": "asc"})
    return [_plan_dict(r) for r in rows]


def _ts() -> str:
    return time.strftime("%Y-%m-%d %H:%M")


def _validate(kind: str, label: str, units: int, faqs: int, price: float) -> None:
    if kind not in ("capacity", "kb_pack"):
        raise ValueError("kind must be capacity or kb_pack")
    if not (label or "").strip():
        raise ValueError("label is required")
    if units < (1 if kind == "capacity" else 0):
        raise ValueError("capacity plans need units >= 1 agent")
    if kind == "kb_pack" and units <= 0 and faqs <= 0:
        raise ValueError("kb packs need extra chars or faqs > 0")
    if faqs < 0 or price < 0 or price > 10_000_000:
        raise ValueError("invalid faqs/price")


async def _save(kind: str, label: str, units: int, faqs: int, price: float,
                enabled: bool, sort_order: int, pid: Optional[str] = None) -> Dict[str, Any]:
    _validate(kind, label, units, faqs, price)
    data: Dict[str, Any] = {
        "kind": kind, "label": label.strip(), "units": int(units),
        "faqs": int(faqs), "pricePerMonth": float(price),
        "enabled": bool(enabled), "sortOrder": int(sort_order),
    }
    db = get_prisma()
    if pid:
        row = await db.plantier.update(where={"id": pid}, data=data)
    else:
        row = await db.plantier.create(data={**data, "createdAt": _ts()})
    from . import config_store
    config_store.invalidate()
    return _plan_dict(row)


async def create_plan(*, admin: Dict[str, Any], kind: str, label: str, units: int = 0,
                      faqs: int = 0, price_per_month: float = 0, enabled: bool = True,
                      sort_order: int = 0) -> Dict[str, Any]:
    out = await _save(kind, label, units, faqs, price_per_month, enabled, sort_order)
    from .admin_shared import audit
    await audit(admin, "plan_created", target_type="plan", target_id=out["id"],
                detail={"label": label, "kind": kind, "price_per_month": price_per_month})
    return out


async def update_plan(pid: str, *, admin: Dict[str, Any], **fields: Any) -> Optional[Dict[str, Any]]:
    db = get_prisma()
    cur = await db.plantier.find_unique(where={"id": pid})
    if not cur:
        return None
    merged = {
        "kind": fields.get("kind", cur.kind), "label": fields.get("label", cur.label),
        "units": fields.get("units", cur.units), "faqs": fields.get("faqs", cur.faqs),
        "price_per_month": fields.get("price_per_month", cur.pricePerMonth),
        "enabled": fields.get("enabled", cur.enabled),
        "sort_order": fields.get("sort_order", cur.sortOrder),
    }
    out = await _save(pid=pid, **merged)
    from .admin_shared import audit
    await audit(admin, "plan_updated", target_type="plan", target_id=pid,
                detail={"label": merged["label"], "price_per_month": merged["price_per_month"]})
    return out


async def delete_plan(pid: str, *, admin: Dict[str, Any]) -> bool:
    db = get_prisma()
    cur = await db.plantier.find_unique(where={"id": pid})
    if not cur:
        return False
    await db.plantier.delete(where={"id": pid})
    from . import config_store
    config_store.invalidate()
    from .admin_shared import audit
    await audit(admin, "plan_deleted", target_type="plan", target_id=pid,
                detail={"label": cur.label, "kind": cur.kind})
    return True
