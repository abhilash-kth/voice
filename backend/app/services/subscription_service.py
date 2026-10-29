"""Monthly subscription engine — the "purchase first, then build agents" model.

What a customer buys (all priced by the Super Admin; prices snapshotted into
the Subscription row at purchase time so mid-cycle price changes never alter
an active plan):

  * Agent-capacity plan — PlanTier(kind="capacity", units=agent count): the
    monthly platform fee. agentLimit = units; the customer can create at most
    that many agents (0 = no plan → creation blocked).
  * VoiceLink channels — BillingConfig.concurrencyLinePricePerMonth ×
    (selected channels - 1); the first channel is included. The legacy
    Subscription.concurrencyLines column stores this plan-selected total.
  * Telephony rent — BillingConfig.telephonyRentPerMonth (flat flag).
  * Knowledge-base packs — PlanTier(kind="kb_pack"): extra KB chars + extra
    FAQs on top of the free base allowance.

Charging: first month is deducted from the wallet at purchase. A scheduler
(app/main.py) sweeps renewals daily; insufficient balance → status
"past_due" (calls / agent creation blocked), and after PAST_DUE_GRACE_DAYS
the plan becomes "inactive". A wallet recharge auto-retries a past_due plan.
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from ..db import get_prisma
from .. import repo
from . import config_store
from .plan_tiers import _plan_dict

logger = logging.getLogger("voice-agent-saas-subscription")

BASE_KB_CHARS = 20_000          # free knowledge-base text-allowance (chars)
BASE_FAQS = 50                  # free FAQ entries
INCLUDED_CHANNELS = 1           # first VoiceLink channel included in a plan
FREE_LINES = INCLUDED_CHANNELS  # legacy alias (older imports/routes)
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
    "status": "inactive", "agent_limit": 0,
    "channels": INCLUDED_CHANNELS, "plan_channels": INCLUDED_CHANNELS,
    "allocated_channels": 0, "number_channels": 0,
    # Legacy response alias; new UI uses `channels` above.
    "concurrency_lines": INCLUDED_CHANNELS,
    "telephony_rented": False, "kb_char_limit": BASE_KB_CHARS, "kb_faq_limit": BASE_FAQS,
    "monthly_total": 0.0, "renews_at": "", "past_due_since": "", "plan_label": "",
}


def effective_channel_count(plan_channels: int,
                            allocated_channels: int = 0,
                            number_channels: int = 0,
                            phone_channels: Optional[int] = None) -> int:
    """One workspace channel entitlement from every purchase/allocation path.

    A customer may receive channels by selecting them with the monthly plan,
    by buying them inside a VoiceLink DID order, or by a Super Admin manual
    DID allocation. Those are the same product capacity, so the highest
    granted count wins instead of the old separate "plan lines" cap.
    """
    values = [
        max(1, int(plan_channels or INCLUDED_CHANNELS)),
        max(0, int(allocated_channels or 0)),
        max(0, int(number_channels or 0)),
    ]
    if phone_channels is not None:
        values.append(max(0, int(phone_channels or 0)))
    return max(values)


def _entitlement(s: Any) -> Dict[str, Any]:
    """Subscription row (or None) → the enforcement view used everywhere."""
    if s is None:
        return dict(_INACTIVE)
    status = s.status or "inactive"
    entitled = status in ("active",)
    plan_channels = max(
        int(s.concurrencyLines or INCLUDED_CHANNELS), INCLUDED_CHANNELS)
    return {
        "status": status,
        "agent_limit": (s.agentLimit or 0) if entitled else 0,
        # `channels` is refined with live telephony allocations in
        # get_subscription(); plan_channels is the quantity selected and
        # paid for with the subscription itself.
        "channels": plan_channels,
        "plan_channels": plan_channels,
        "allocated_channels": 0,
        "number_channels": 0,
        "concurrency_lines": plan_channels,  # legacy alias
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
    ent = _entitlement(s)
    try:
        account = await repo.get_account_by_user(user_id)
        if account:
            ent["allocated_channels"] = max(
                0, int(account.get("channels_allocated") or 0))
    except Exception as e:  # telephony tables are additive; plan still works
        logger.debug("VoiceLink channel allocation lookup skipped: %r", e)
    try:
        numbers = await repo.list_phone_numbers(user_id)
        ent["number_channels"] = max(
            [max(1, int(n.get("channels") or 1))
             for n in numbers if n.get("status") == "active"] or [0])
    except Exception as e:
        logger.debug("phone-number channel lookup skipped: %r", e)
    ent["channels"] = effective_channel_count(
        ent["plan_channels"], ent["allocated_channels"],
        ent["number_channels"])
    ent["concurrency_lines"] = ent["channels"]
    return ent


# ---------------------------------------------------------------------------
# Pricing (pure, unit-testable)
# ---------------------------------------------------------------------------
def price_selection(*, capacity_tier: Optional[Dict[str, Any]],
                    extra_channels: Optional[int] = None,
                    extra_lines: int = 0,
                    telephony: bool, kb_packs: List[Dict[str, Any]],
                    channel_price: Optional[float] = None,
                    line_price: float = 0,
                    telephony_rent: float) -> float:
    """Monthly ₹ for one selection.

    `extra_channels` is the quantity beyond the one included channel. The
    old `extra_lines`/`line_price` names remain accepted for compatibility.
    """
    extras = (int(extra_channels) if extra_channels is not None
              else int(extra_lines or 0))
    per_channel = float(
        channel_price if channel_price is not None else line_price or 0)

    def plan_price(plan: Optional[Dict[str, Any]]) -> float:
        if not plan:
            return 0.0
        # plan_tiers._plan_dict() returns snake_case API fields. Accept the
        # legacy camelCase key too: using only `pricePerMonth` silently
        # priced every purchased capacity/KB plan at ₹0.
        value = plan.get("price_per_month")
        if value is None:
            value = plan.get("pricePerMonth")
        return float(value or 0)

    total = 0.0
    if capacity_tier:
        total += plan_price(capacity_tier)
    total += max(extras, 0) * per_channel
    if telephony:
        total += float(telephony_rent or 0)
    for p in kb_packs:
        total += plan_price(p)
    return round(total, 2)


def billable_channel_increase(current_effective: int, target: int) -> int:
    """Extra channels not already granted by the plan/account/any DID."""
    return max(0, int(target or 1) - max(1, int(current_effective or 1)))


def prorated_charge(monthly_amount: float, renews_at: str,
                    *, now: Optional[datetime] = None) -> tuple[float, int]:
    """Charge only the part of a monthly add-on left in this 30-day cycle."""
    amount = max(0.0, float(monthly_amount or 0))
    if amount <= 0:
        return 0.0, 0
    current = now or _now()
    due = _parse(renews_at or "")
    if due is None:
        return round(amount, 2), SUBSCRIPTION_DAYS
    seconds = max(0.0, (due - current).total_seconds())
    fraction = min(1.0, seconds / (SUBSCRIPTION_DAYS * 24 * 60 * 60))
    return round(amount * fraction, 2), int(math.ceil(seconds / 86400))


# ---------------------------------------------------------------------------
# Purchase / renew / recharge-retry
# ---------------------------------------------------------------------------
class SubscriptionError(Exception):
    """User-visible subscription problem (surfaced as HTTP 400/402)."""


async def _wallet_balance(user_id: str) -> float:
    w = await repo.get_wallet(user_id)
    return float(w.get("balance", 0) or 0)


async def purchase(user_id: str, *, capacity_tier_id: str = "",
                   channels: Optional[int] = None,
                   extra_channels: Optional[int] = None,
                   extra_lines: int = 0, telephony: bool = False,
                   kb_pack_ids: Optional[List[str]] = None) -> Dict[str, Any]:
    """Buy/replace the user's monthly plan. Charges the wallet NOW (month 1).

    `channels` is the total VoiceLink channel quantity selected with the
    plan (minimum 1). It becomes the default/target channel count for the
    later KYC -> DID purchase flow; a DID order can still buy additional
    provider channels, and those are reflected in the DID's channel count.
    """
    if channels is not None:
        total_channels = max(INCLUDED_CHANNELS, int(channels))
    elif extra_channels is not None:
        total_channels = INCLUDED_CHANNELS + max(0, int(extra_channels))
    else:
        total_channels = INCLUDED_CHANNELS + max(0, int(extra_lines or 0))
    extra_channel_count = total_channels - INCLUDED_CHANNELS

    db = get_prisma()
    b = config_store.get_billing()
    channel_price = float(b.get("concurrency_line_price_per_month") or 0)
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
    if tier is None and extra_channel_count <= 0 and not telephony and not packs:
        raise SubscriptionError("Select at least one plan item to purchase")

    monthly = price_selection(
        capacity_tier=tier, extra_channels=extra_channel_count,
        telephony=telephony, kb_packs=packs,
        channel_price=channel_price, telephony_rent=telephony_rent)
    if monthly > 0:
        balance = await _wallet_balance(user_id)
        if balance < monthly:
            logger.warning(
                "Subscription purchase blocked for user=%s: wallet balance "
                "₹%.2f is below monthly total ₹%.2f",
                user_id, balance, monthly)
            raise SubscriptionError(
                f"Insufficient wallet balance (has ₹{balance:.2f}, "
                f"needs ₹{monthly:.2f}). Recharge first.")

    now = _now()
    agent_limit = (tier or {}).get("units", 0)
    kb_chars = sum(p["units"] for p in packs)
    kb_faqs = sum(p["faqs"] for p in packs)
    labels = [x for x in ([tier["label"]] if tier else []) + [p["label"] for p in packs]
              + (["telephony"] if telephony else [])
              + ([f"{total_channels} channels"] if total_channels > 1 else [])]
    if monthly > 0:
        await repo.deduct(user_id, monthly, note=f"Subscription {', '.join(labels)}")
    data = {
        # Legacy column name; now stores plan-selected total channels.
        "agentLimit": int(agent_limit), "concurrencyLines": total_channels,
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


def _admin_renews_at(value: Optional[str], fallback: str = "") -> str:
    # An omitted/blank date in an update must preserve the DB value rather
    # than silently moving the customer's renewal date.
    raw = (value or fallback or "").strip()
    if not raw:
        return _iso(_now() + timedelta(days=SUBSCRIPTION_DAYS))
    if len(raw) == 10:  # date input from the admin panel
        raw = f"{raw}T00:00:00Z"
    if _parse(raw) is None:
        raise SubscriptionError("renews_at must be a date or ISO timestamp")
    return raw


def _admin_subscription_data(fields: Dict[str, Any],
                             existing: Any = None) -> Dict[str, Any]:
    """Validate/map Super Admin subscription fields to the stored row.

    `channels` in admin APIs means the plan-selected VoiceLink channel
    total. It is stored in the legacy `concurrencyLines` column; the
    customer-visible effective channel count additionally considers the
    provider account and active DID grants in get_subscription().
    """
    def pick(name: str, attr: str, default: Any) -> Any:
        if fields.get(name) is not None:
            return fields[name]
        return getattr(existing, attr) if existing is not None else default

    status = str(pick("status", "status", "inactive") or "inactive")
    if status not in ("active", "past_due", "inactive"):
        raise SubscriptionError("status must be active, past_due, or inactive")
    channels = int(pick("channels", "concurrencyLines", INCLUDED_CHANNELS))
    if channels < 1 or channels > 1000:
        raise SubscriptionError("channels must be between 1 and 1000")
    now = _now()
    renews_at = _admin_renews_at(
        fields.get("renews_at"),
        getattr(existing, "renewsAt", "") if existing is not None else "")
    past_due_since = (
        (getattr(existing, "pastDueSince", "") or _iso(now))
        if status == "past_due" else "")
    return {
        "agentLimit": int(pick("agent_limit", "agentLimit", 0)),
        "concurrencyLines": channels,
        "telephonyRented": bool(
            pick("telephony_rented", "telephonyRented", False)),
        "kbCharLimit": int(pick("kb_extra_chars", "kbCharLimit", 0)),
        "kbFaqLimit": int(pick("kb_extra_faqs", "kbFaqLimit", 0)),
        "monthlyTotal": float(pick("monthly_total", "monthlyTotal", 0) or 0),
        "status": status,
        "renewsAt": renews_at,
        "pastDueSince": past_due_since,
        "updatedAt": _iso(now),
    }


async def admin_create_subscription(user_id: str,
                                    **fields: Any) -> Dict[str, Any]:
    """Create a subscription manually (no wallet charge; audited by route)."""
    db = get_prisma()
    if await db.subscription.find_unique(where={"userId": user_id}):
        raise SubscriptionError("This customer already has a subscription")
    now = _now()
    data = _admin_subscription_data(fields)
    await db.subscription.create(data={
        **data, "userId": user_id, "startedAt": _iso(now),
        "lastChargedAt": "", "createdAt": _iso(now)})
    return await get_subscription(user_id)


async def admin_update_subscription(user_id: str,
                                    **fields: Any) -> Optional[Dict[str, Any]]:
    """Edit a subscription manually (no immediate wallet charge/refund).

    `monthly_total` is the amount the existing renewal sweep will charge on
    `renews_at`; changing it here deliberately does not take money now.
    """
    db = get_prisma()
    existing = await db.subscription.find_unique(where={"userId": user_id})
    if not existing:
        return None
    await db.subscription.update(
        where={"id": existing.id},
        data=_admin_subscription_data(fields, existing))
    return await get_subscription(user_id)


async def admin_delete_subscription(user_id: str) -> bool:
    db = get_prisma()
    existing = await db.subscription.find_unique(where={"userId": user_id})
    if not existing:
        return False
    await db.subscription.delete(where={"id": existing.id})
    return True


async def record_paid_channel_upgrade(user_id: str, target_channels: int,
                                      monthly_increment: float) -> Dict[str, Any]:
    """Persist a same-number channel upgrade in the monthly subscription."""
    db = get_prisma()
    existing = await db.subscription.find_unique(where={"userId": user_id})
    if not existing or existing.status != "active":
        raise SubscriptionError("An active subscription is required")
    await db.subscription.update(where={"id": existing.id}, data={
        "concurrencyLines": max(int(existing.concurrencyLines or 1),
                                int(target_channels)),
        "monthlyTotal": round(float(existing.monthlyTotal or 0)
                              + float(monthly_increment or 0), 2),
        "updatedAt": _iso(_now())})
    return await get_subscription(user_id)


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


async def ensure_concurrency_allowed(user_id: str, requested: int,
                                     phone_number_id: Optional[str] = None) -> None:
    """Allow an agent's max concurrency up to its purchased channel capacity.

    The assigned DID is decisive for SIP: if that number was bought/manual-
    allocated with (for example) two channels, an older subscription row
    whose plan-selected quantity is one must not block setting the agent to
    two. Without an assigned DID, the workspace's plan-selected/allocated
    channel entitlement is the cap.
    """
    ent = await get_subscription(user_id)
    allowed = int(ent["channels"])
    if phone_number_id:
        try:
            phone = await repo.get_phone_number(phone_number_id, user_id)
        except Exception:
            phone = None
        if phone and phone.get("status") == "active":
            allowed = effective_channel_count(
                ent["plan_channels"], ent["allocated_channels"],
                ent["number_channels"],
                phone_channels=max(1, int(phone.get("channels") or 1)))
    if int(requested or 1) > allowed:
        raise SubscriptionError(
            f"Max concurrent {requested} exceeds your purchased/allocated "
            f"{allowed} channel(s). Select more channels with your plan, "
            "buy more channels with the phone number, or ask support to "
            "increase the assigned number's channels.")


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
