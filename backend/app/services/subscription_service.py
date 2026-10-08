"""Monthly subscription engine — the "purchase first, then build agents" model.

What a customer buys (all priced by the Super Admin; prices snapshotted into
the Subscription row at purchase time so mid-cycle price changes never alter
an active plan):

  * Agent-capacity plan — PlanTier(kind="capacity", units=agent count): the
    monthly platform fee. agentLimit = units; the customer can create at most
    that many agents (0 = no plan → creation blocked).
  * Extra concurrency lines — BillingConfig.concurrencyLinePricePerMonth ×
    (lines - 1); the FREE first line is lines=1.
  * Telephony rent — BillingConfig.telephonyRentPerMonth (flat flag).
  * Knowledge-base packs — PlanTier(kind="kb_pack"): extra KB chars + extra
    FAQs on top of the free base allowance.

Charging: first month is deducted from the wallet at purchase. A scheduler
(app/main.py) sweeps renewals daily; insufficient balance → status
"past_due" (calls / agent creation blocked), and after PAST_DUE_GRACE_DAYS
the plan becomes "inactive". A wallet recharge auto-retries a past_due plan.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from ..db import get_prisma
from .. import repo
from . import config_store
from .plan_tiers import _plan_dict

logger = logging.getLogger("voice-agent-saas-subscription")

BASE_KB_CHARS = 20_000          # free knowledge-base text-allowance (chars)
BASE_FAQS = 50                  # free FAQ entries
FREE_LINES = 1                  # free concurrent line
PAST_DUE_GRACE_DAYS = 7
SUBSCRIPTION_DAYS = 30


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(s: str) -> Optional[datetime]:
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except Exception:
        return None


_INACTIVE: Dict[str, Any] = {
    "status": "inactive", "agent_limit": 0, "concurrency_lines": FREE_LINES,
    "telephony_rented": False, "kb_char_limit": BASE_KB_CHARS, "kb_faq_limit": BASE_FAQS,
    "monthly_total": 0.0, "renews_at": "", "past_due_since": "", "plan_label": "",
}


def _entitlement(s: Any) -> Dict[str, Any]:
    """Subscription row (or None) → the enforcement view used everywhere."""
    if s is None:
        return dict(_INACTIVE)
    status = s.status or "inactive"
    entitled = status in ("active",)
    return {
        "status": status,
        "agent_limit": (s.agentLimit or 0) if entitled else 0,
        # Concurrency lines stay usable while past_due so a missed renewal
        # does not silently shrink running agents mid-grace.
        "concurrency_lines": max(s.concurrencyLines or FREE_LINES, FREE_LINES),
        "telephony_rented": bool(s.telephonyRented) if entitled else False,
        "kb_char_limit": BASE_KB_CHARS + (s.kbCharLimit or 0) if entitled else _INACTIVE["kb_char_limit"],
        "kb_faq_limit": BASE_FAQS + (s.kbFaqLimit or 0) if entitled else _INACTIVE["kb_faq_limit"],
        "monthly_total": float(s.monthlyTotal or 0),
        "renews_at": s.renewsAt or "",
        "past_due_since": s.pastDueSince or "",
        "plan_label": "",
    }


async def get_subscription(user_id: str) -> Dict[str, Any]:
    s = await get_prisma().subscription.find_unique(where={"userId": user_id})
    return _entitlement(s)


# ---------------------------------------------------------------------------
# Pricing (pure, unit-testable)
# ---------------------------------------------------------------------------
def price_selection(*, capacity_tier: Optional[Dict[str, Any]], extra_lines: int,
                    telephony: bool, kb_packs: List[Dict[str, Any]],
                    line_price: float, telephony_rent: float) -> float:
    """Monthly ₹ for one selection. extra_lines = lines beyond the free one."""
    total = 0.0
    if capacity_tier:
        total += float(capacity_tier.get("pricePerMonth") or 0)
    total += max(extra_lines, 0) * float(line_price or 0)
    if telephony:
        total += float(telephony_rent or 0)
    for p in kb_packs:
        total += float(p.get("pricePerMonth") or 0)
    return round(total, 2)


# ---------------------------------------------------------------------------
# Purchase / renew / recharge-retry
# ---------------------------------------------------------------------------
class SubscriptionError(Exception):
    """User-visible subscription problem (surfaced as HTTP 400/402)."""


async def _wallet_balance(user_id: str) -> float:
    w = await repo.get_wallet(user_id)
    return float(w.get("balance", 0) or 0)


async def purchase(user_id: str, *, capacity_tier_id: str = "",
                   extra_lines: int = 0, telephony: bool = False,
                   kb_pack_ids: Optional[List[str]] = None) -> Dict[str, Any]:
    """Buy/replace the user's monthly plan. Charges the wallet NOW (month 1)."""
    db = get_prisma()
    b = config_store.get_billing()
    line_price = float(b.get("concurrency_line_price_per_month") or 0)
    telephony_rent = float(b.get("telephony_rent_per_month") or 0)

    tier = None
    if capacity_tier_id:
        row = await db.plantier.find_unique(where={"id": capacity_tier_id})
        if not row or row.kind != "capacity" or not row.enabled:
            raise SubscriptionError("Unknown or disabled agent plan")
        tier = _plan_dict(row)
    packs: List[Dict[str, Any]] = []
    for pid in (kb_pack_ids or []):
        prow = await db.plantier.find_unique(where={"id": pid})
        if not prow or prow.kind != "kb_pack" or not prow.enabled:
            raise SubscriptionError("Unknown or disabled knowledge-base pack")
        packs.append(_plan_dict(prow))
    if tier is None and extra_lines <= 0 and not telephony and not packs:
        raise SubscriptionError("Select at least one plan item to purchase")

    monthly = price_selection(
        capacity_tier=tier, extra_lines=int(extra_lines), telephony=telephony,
        kb_packs=packs, line_price=line_price, telephony_rent=telephony_rent)
    if monthly > 0 and await _wallet_balance(user_id) < monthly:
        raise SubscriptionError(
            f"Insufficient wallet balance (needs ₹{monthly:.2f}). Recharge first.")

    now = _now()
    agent_limit = (tier or {}).get("units", 0)
    lines = FREE_LINES + max(int(extra_lines), 0)
    kb_chars = sum(p["units"] for p in packs)
    kb_faqs = sum(p["faqs"] for p in packs)
    labels = [x for x in ([tier["label"]] if tier else []) + [p["label"] for p in packs]
              + (["telephony"] if telephony else []) + ([f"+{extra_lines} lines"] if extra_lines > 0 else [])]
    if monthly > 0:
        await repo.deduct(user_id, monthly, note=f"Subscription {', '.join(labels)}")
    data = {
        "agentLimit": int(agent_limit), "concurrencyLines": lines,
        "telephonyRented": bool(telephony), "kbCharLimit": kb_chars,
        "kbFaqLimit": kb_faqs, "monthlyTotal": monthly, "status": "active",
        "startedAt": _iso(now), "renewsAt": _iso(now + timedelta(days=SUBSCRIPTION_DAYS)),
        "lastChargedAt": _iso(now), "pastDueSince": "", "updatedAt": _iso(now),
    }
    existing = await db.subscription.find_unique(where={"userId": user_id})
    if existing:
        await db.subscription.update(where={"userId": user_id}, data=data)
    else:
        await db.subscription.create(data={**data, "userId": user_id, "createdAt": _iso(now)})
    ent = await get_subscription(user_id)
    ent["plan_label"] = ", ".join(labels)
    logger.info(f"🛒 Subscription purchased by {user_id}: {ent['plan_label']} @ ₹{monthly}/mo")
    return ent


def _renewal_note(period_due: datetime) -> str:
    """Period-scoped ledger note: makes renewals idempotent across both the
    scheduler sweep and the post-recharge retry."""
    return f"Subscription renewal {period_due.strftime('%Y-%m-%d')}"


async def _advance_and_activate(db: Any, sub_id: str, due: datetime, now: datetime) -> None:
    while due <= now:
        due += timedelta(days=SUBSCRIPTION_DAYS)
    await db.subscription.update(where={"id": sub_id}, data={
        "renewsAt": _iso(due), "lastChargedAt": _iso(now),
        "status": "active", "pastDueSince": "", "updatedAt": _iso(now)})


async def renew_due() -> Dict[str, int]:
    """Sweep subscriptions whose renewsAt has passed. Charges the wallet for
    each; insufficient balance → past_due (grace), then inactive."""
    db = get_prisma()
    now = _now()
    rows = await db.subscription.find_many(where={"status": {"in": ["active", "past_due"]}})
    renewed = past_due = deactivated = 0
    for s in rows:
        due = _parse(s.renewsAt or "")
        if due is None or due > now:
            continue
        monthly = float(s.monthlyTotal or 0)
        charged = monthly <= 0
        if not charged and await _wallet_balance(s.userId) >= monthly:
            try:
                await repo.deduct(s.userId, monthly, note=_renewal_note(due))
                charged = True
            except Exception as e:
                logger.warning(f"renewal charge failed for {s.userId}: {e!r}")
        if charged:
            await _advance_and_activate(db, s.id, due, now)
            renewed += 1
            continue
        # Not chargeable → grace period, then deactivate.
        since = _parse(s.pastDueSince or "") or now
        if (now - since).days >= PAST_DUE_GRACE_DAYS:
            await db.subscription.update(where={"id": s.id}, data={
                "status": "inactive", "updatedAt": _iso(now)})
            deactivated += 1
        else:
            await db.subscription.update(where={"id": s.id}, data={
                "status": "past_due",
                "pastDueSince": s.pastDueSince or _iso(now), "updatedAt": _iso(now)})
            past_due += 1
    if renewed or past_due or deactivated:
        logger.info(f"🔄 Subscription sweep: renewed={renewed} past_due={past_due} deactivated={deactivated}")
    return {"renewed": renewed, "past_due": past_due, "deactivated": deactivated}


async def retry_after_recharge(user_id: str) -> None:
    """Wallet just got money: immediately settle a past_due subscription
    (same period-scoped ledger note as the sweep → never double-charged)."""
    db = get_prisma()
    s = await db.subscription.find_unique(where={"userId": user_id})
    if not s or s.status != "past_due":
        return
    monthly = float(s.monthlyTotal or 0)
    due = _parse(s.renewsAt or "")
    if monthly <= 0 or due is None or await _wallet_balance(user_id) < monthly:
        return
    now = _now()
    try:
        await repo.deduct(user_id, monthly, note=_renewal_note(due))
    except Exception as e:
        logger.warning(f"post-recharge renewal failed for {user_id}: {e!r}")
        return
    await _advance_and_activate(db, s.id, due, now)
    logger.info(f"✅ Subscription reactivated for {user_id} after recharge")


# ---------------------------------------------------------------------------
# Enforcement helpers (routes + worker call gate)
# ---------------------------------------------------------------------------
async def ensure_agent_creation_allowed(user_id: str, current_agent_count: int) -> None:
    ent = await get_subscription(user_id)
    if ent["status"] != "active":
        raise SubscriptionError(
            "No active plan. Purchase a monthly agent plan on the Billing page first.")
    if ent["agent_limit"] <= 0:
        raise SubscriptionError("Your plan has no agent slots — purchase an agent plan first.")
    if current_agent_count >= ent["agent_limit"]:
        raise SubscriptionError(
            f"Agent limit reached ({ent['agent_limit']}). Upgrade your plan to add more agents.")


async def ensure_concurrency_allowed(user_id: str, requested: int) -> None:
    ent = await get_subscription(user_id)
    if requested > ent["concurrency_lines"]:
        raise SubscriptionError(
            f"Max concurrent {requested} exceeds your plan's {ent['concurrency_lines']} line(s). "
            "Buy extra concurrency lines on the Billing page.")


async def kb_limits(user_id: str) -> Dict[str, int]:
    ent = await get_subscription(user_id)
    return {"kb_char_limit": ent["kb_char_limit"], "kb_faq_limit": ent["kb_faq_limit"]}


async def call_gate(user_id: str) -> Optional[str]:
    """Worker call gate. Returns None when the call may proceed, else a short
    user-facing block reason (call is marked failed, never billed)."""
    ent = await get_subscription(user_id)
    if ent["status"] == "active":
        return None
    if ent["status"] == "past_due":
        return "Your monthly plan payment is due. Recharge your wallet to resume calls."
    return "No active monthly plan. Purchase a plan on the Billing page to start calling."
