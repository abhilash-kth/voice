"""Super-Admin routes: monthly plan tiers (agent capacity + KB packs) and the
subscriber list. Split from admin routes.py (≤300-line rule); mounted under
/admin's prefix + auth dependencies by routes.py.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from ..db import get_prisma
from ..services import plan_tiers
from . import deps, schemas

router = APIRouter()
ADMIN = Depends(deps.get_super_admin)


@router.get("/plans")
async def list_plans(kind: Optional[str] = None, admin=ADMIN):
    return {"items": await plan_tiers.list_plans(kind=kind, only_enabled=False)}


@router.post("/plans", status_code=201)
async def create_plan(body: schemas.PlanBody, admin=ADMIN):
    try:
        return await plan_tiers.create_plan(admin=admin, **body.model_dump())
    except Exception as e:
        raise HTTPException(400, str(e))


@router.put("/plans/{pid}")
async def update_plan(pid: str, body: schemas.PlanUpdateBody, admin=ADMIN):
    try:
        out = await plan_tiers.update_plan(pid, admin=admin, **body.model_dump(exclude_none=True))
    except Exception as e:
        raise HTTPException(400, str(e))
    if not out:
        raise HTTPException(404, "Plan not found")
    return out


@router.delete("/plans/{pid}", status_code=204)
async def delete_plan(pid: str, admin=ADMIN):
    if not await plan_tiers.delete_plan(pid, admin=admin):
        raise HTTPException(404, "Plan not found")


@router.get("/subscriptions")
async def list_subscriptions(admin=ADMIN):
    """All customer subscriptions with the subscriber's name/email (read-only)."""
    db = get_prisma()
    rows = await db.subscription.find_many(order={"updatedAt": "desc"}, take=500)
    uids = list({r.userId for r in rows})
    users = await db.user.find_many(where={"id": {"in": uids}}) if uids else []
    uname = {u.id: (u.name or "") for u in users}
    uemail = {u.id: (u.email or "") for u in users}
    return {"items": [{
        "user_id": r.userId, "user_name": uname.get(r.userId, ""), "user_email": uemail.get(r.userId, ""),
        "status": r.status, "agent_limit": r.agentLimit or 0,
        "concurrency_lines": r.concurrencyLines or 1, "telephony_rented": bool(r.telephonyRented),
        "kb_char_limit": r.kbCharLimit or 0, "kb_faq_limit": r.kbFaqLimit or 0,
        "monthly_total": float(r.monthlyTotal or 0), "renews_at": r.renewsAt or "",
    } for r in rows]}
