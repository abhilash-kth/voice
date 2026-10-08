"""Customer subscription routes: view entitlements + purchasable plans, buy
(replace) the monthly plan. All prices are Super-Admin-set (BillingConfig +
PlanTier) so nothing is hardcoded here.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field

from .. import auth
from ..services import config_store, plan_tiers, subscription_service

logger = logging.getLogger("voice-agent-saas-api")
router = APIRouter(tags=["subscription"])


class PurchaseBody(BaseModel):
    capacity_tier_id: str = ""
    extra_lines: int = Field(0, ge=0, le=1000)
    telephony: bool = False
    kb_pack_ids: list[str] = Field(default_factory=list, max_length=20)


@router.get("/api/subscription")
async def get_subscription(user=Depends(auth.get_current_user)):
    await config_store.refresh_if_stale()
    b = config_store.get_billing()
    ent = await subscription_service.get_subscription(user.id)
    return {
        "entitlement": ent,
        "prices": {
            "line_price_per_month": float(b.get("concurrency_line_price_per_month") or 0),
            "telephony_rent_per_month": float(b.get("telephony_rent_per_month") or 0),
        },
        "plans": {
            "capacity": await plan_tiers.list_plans(kind="capacity"),
            "kb_packs": await plan_tiers.list_plans(kind="kb_pack"),
        },
        "base_limits": {
            "kb_chars": subscription_service.BASE_KB_CHARS,
            "faqs": subscription_service.BASE_FAQS,
            "concurrency_lines": subscription_service.FREE_LINES,
        },
    }


@router.post("/api/subscription/purchase")
async def purchase(body: PurchaseBody, user=Depends(auth.get_current_user)):
    await config_store.refresh_if_stale()
    try:
        ent = await subscription_service.purchase(
            user.id, capacity_tier_id=body.capacity_tier_id,
            extra_lines=body.extra_lines, telephony=body.telephony,
            kb_pack_ids=body.kb_pack_ids)
    except subscription_service.SubscriptionError as e:
        msg = str(e)
        raise HTTPException(402 if "balance" in msg.lower() else 400, msg) from None
    return {"ok": True, "entitlement": ent}
