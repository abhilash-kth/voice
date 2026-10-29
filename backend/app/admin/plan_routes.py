"""Super-Admin routes: monthly plan tiers (agent capacity + KB packs) and the
subscriber list. Split from admin routes.py (≤300-line rule); mounted under
/admin's prefix + auth dependencies by routes.py.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from ..db import get_prisma
from ..services import admin_service, plan_tiers, subscription_service
from . import deps, schemas

router = APIRouter()
ADMIN = Depends(deps.get_super_admin)
logger = logging.getLogger("voice-agent-saas-admin")


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


def _subscription_item(row, *, user_name: str = "", user_email: str = "",
                       allocated_channels: int = 0,
                       number_channels: int = 0) -> dict:
    plan_channels = max(1, int(row.concurrencyLines or 1))
    channels = subscription_service.effective_channel_count(
        plan_channels, allocated_channels, number_channels)
    return {
        "subscription_id": row.id,
        "user_id": row.userId, "user_name": user_name,
        "user_email": user_email,
        "status": row.status, "agent_limit": row.agentLimit or 0,
        "channels": channels,
        "plan_channels": plan_channels,
        "allocated_channels": int(allocated_channels or 0),
        "number_channels": int(number_channels or 0),
        # Legacy alias for older admin clients; UI now says Channels.
        "concurrency_lines": channels,
        "telephony_rented": bool(row.telephonyRented),
        # Stored KB values are extras above the free base allowance.
        "kb_extra_chars": row.kbCharLimit or 0,
        "kb_extra_faqs": row.kbFaqLimit or 0,
        "kb_char_limit": row.kbCharLimit or 0,
        "kb_faq_limit": row.kbFaqLimit or 0,
        "monthly_total": float(row.monthlyTotal or 0),
        "started_at": row.startedAt or "",
        "renews_at": row.renewsAt or "",
        "last_charged_at": row.lastChargedAt or "",
        "past_due_since": row.pastDueSince or "",
        "created_at": row.createdAt or "",
        "updated_at": row.updatedAt or "",
    }


async def _subscription_item_for_user(user_id: str):
    """Freshly read one subscription row for the admin edit form/response.

    Telephony joins only enrich the effective-channel breakdown. They must
    not make an otherwise successful subscription read/save fail, so those
    lookups are best-effort here.
    """
    db = get_prisma()
    row = await db.subscription.find_unique(where={"userId": user_id})
    if not row:
        return None
    user = None
    account = None
    numbers = []
    try:
        user = await db.user.find_unique(where={"id": user_id})
    except Exception as e:
        logger.debug("subscription user lookup skipped: %r", e)
    try:
        account = await db.voicelinkaccount.find_unique(
            where={"userId": user_id})
    except Exception as e:
        logger.debug("subscription VoiceLink lookup skipped: %r", e)
    try:
        numbers = await db.phonenumber.find_many(
            where={"userId": user_id, "status": "active"})
    except Exception as e:
        logger.debug("subscription phone-number lookup skipped: %r", e)
    return _subscription_item(
        row,
        user_name=(user.name or "") if user else "",
        user_email=(user.email or "") if user else "",
        allocated_channels=(account.channelsAllocated or 0) if account else 0,
        number_channels=max(
            [int(n.channels or 1) for n in numbers] or [0]))


@router.get("/subscriptions")
async def list_subscriptions(admin=ADMIN):
    """All customer subscriptions with effective channel capacity."""
    db = get_prisma()
    rows = await db.subscription.find_many(order={"updatedAt": "desc"}, take=500)
    uids = list({r.userId for r in rows})
    users = await db.user.find_many(where={"id": {"in": uids}}) if uids else []
    uname = {u.id: (u.name or "") for u in users}
    uemail = {u.id: (u.email or "") for u in users}
    accounts = (await db.voicelinkaccount.find_many(
        where={"userId": {"in": uids}}) if uids else [])
    allocated = {a.userId: int(a.channelsAllocated or 0) for a in accounts}
    numbers = (await db.phonenumber.find_many(
        where={"userId": {"in": uids}, "status": "active"}) if uids else [])
    number_channels: dict[str, int] = {}
    for number in numbers:
        number_channels[number.userId] = max(
            number_channels.get(number.userId, 0),
            int(number.channels or 1))

    return {"items": [
        _subscription_item(
            r, user_name=uname.get(r.userId, ""),
            user_email=uemail.get(r.userId, ""),
            allocated_channels=allocated.get(r.userId, 0),
            number_channels=number_channels.get(r.userId, 0))
        for r in rows]}


@router.get("/subscriptions/{user_id}")
async def get_subscription(user_id: str, admin=ADMIN):
    """One customer's exact stored subscription values for Edit.

    The panel calls this when Edit is clicked instead of trusting a
    previously loaded table row, so amount/agent/KB/channel fields always
    start from the current DB row.
    """
    item = await _subscription_item_for_user(user_id)
    if not item:
        raise HTTPException(404, "Subscription not found")
    return item


@router.post("/subscriptions", status_code=201)
async def create_subscription(body: schemas.SubscriptionCreateBody, admin=ADMIN):
    db = get_prisma()
    user = await db.user.find_unique(where={"id": body.user_id})
    if not user:
        raise HTTPException(404, "Customer not found")
    try:
        await subscription_service.admin_create_subscription(
            body.user_id, **body.model_dump(exclude={"user_id"}))
    except subscription_service.SubscriptionError as e:
        raise HTTPException(409 if "already has" in str(e) else 400, str(e))
    item = await _subscription_item_for_user(body.user_id)
    await admin_service.audit(
        admin, "subscription_created", target_type="subscription",
        target_id=body.user_id,
        detail={"status": body.status, "agent_limit": body.agent_limit,
                "channels": body.channels,
                "monthly_total": body.monthly_total})
    return item


@router.put("/subscriptions/{user_id}")
async def update_subscription(user_id: str,
                              body: schemas.SubscriptionUpdateBody,
                              admin=ADMIN):
    try:
        updated = await subscription_service.admin_update_subscription(
            user_id, **body.model_dump(exclude_none=True))
        item = await _subscription_item_for_user(user_id)
    except subscription_service.SubscriptionError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.exception("admin subscription update failed for %s", user_id)
        raise HTTPException(
            500, f"Could not save this subscription: {e}") from None
    if updated is None or item is None:
        raise HTTPException(404, "Subscription not found")
    await admin_service.audit(
        admin, "subscription_updated", target_type="subscription",
        target_id=user_id, detail=body.model_dump(exclude_none=True))
    return item


@router.delete("/subscriptions/{user_id}", status_code=204)
async def delete_subscription(user_id: str, admin=ADMIN):
    if not await subscription_service.admin_delete_subscription(user_id):
        raise HTTPException(404, "Subscription not found")
    await admin_service.audit(
        admin, "subscription_deleted", target_type="subscription",
        target_id=user_id)
