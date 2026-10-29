"""Paid channel upgrades for an already-owned phone number.

A channel is one simultaneous PSTN call. Increasing channels on the same
DID is a subscription change, not a new DID purchase:

* channels already granted by the plan, VoiceLink account, or another DID
  are not charged again;
* only the increase above the workspace's current effective channels is
  billable, at the Super Admin's per-extra-channel monthly price;
* the current cycle is prorated to the subscription renewal date, and the
  full monthly increment is added to the subscription for later renewals;
* VoiceLink's client allocation is raised and verified before charging;
* the DID row and subscription row are then updated to the same target.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from .. import repo
from ..db import get_prisma
from . import config_store, subscription_service
from . import telephony_account as accounts
from . import voicelink_client as vl
from .telephony_policy import TelephonyError

logger = logging.getLogger("voice-agent-saas-channels")


def _channel_price() -> float:
    billing = config_store.get_billing()
    return float(billing.get("concurrency_line_price_per_month") or 0)


async def _load_quote_context(user_id: str, phone_id: str,
                              target_channels: int) -> tuple[dict, dict, dict]:
    phone = await repo.get_phone_number(phone_id, user_id)
    if not phone:
        raise TelephonyError("Phone number not found.", 404)
    if phone.get("status") != "active":
        raise TelephonyError(
            "Channels can be increased only on an active phone number.", 409)
    current = max(1, int(phone.get("channels") or 1))
    if int(target_channels) <= current:
        raise TelephonyError(
            f"Choose more than this number's current {current} channel(s).",
            400)
    entitlement = await subscription_service.get_subscription(user_id)
    if entitlement.get("status") != "active":
        raise TelephonyError(
            "An active monthly subscription is required to increase "
            "channels. Purchase or renew your plan on Billing first.", 402)
    # Manual numbers also need a linked provider account here: without one
    # the platform cannot verify/raise the carrier-side allocation and must
    # not merely relabel the local DID row after taking payment.
    account = await accounts.require_account(user_id)
    return phone, entitlement, account


async def quote_channel_upgrade(user_id: str, phone_id: str,
                                target_channels: int) -> dict:
    phone, entitlement, account = await _load_quote_context(
        user_id, phone_id, target_channels)
    target = int(target_channels)
    current_phone = max(1, int(phone.get("channels") or 1))
    current_effective = max(1, int(entitlement.get("channels") or 1))
    price = _channel_price()
    billable = subscription_service.billable_channel_increase(
        current_effective, target)
    monthly_increment = round(billable * price, 2)
    due_now, remaining_days = subscription_service.prorated_charge(
        monthly_increment, entitlement.get("renews_at") or "")
    wallet = await repo.get_wallet(user_id)
    return {
        "phone_number_id": phone["id"],
        "number": phone["number"],
        "current_phone_channels": current_phone,
        "target_channels": target,
        "added_phone_channels": target - current_phone,
        "current_effective_channels": current_effective,
        "plan_channels": int(entitlement.get("plan_channels") or 1),
        "provider_channels_allocated": int(
            account.get("channels_allocated") or 0),
        "billable_added_channels": billable,
        "channel_price_per_month": price,
        "monthly_increment": monthly_increment,
        "due_now": due_now,
        "remaining_days": remaining_days,
        "current_monthly_total": float(entitlement.get("monthly_total") or 0),
        "new_monthly_total": round(
            float(entitlement.get("monthly_total") or 0) + monthly_increment, 2),
        "renews_at": entitlement.get("renews_at") or "",
        "wallet_balance": float(wallet.get("balance") or 0),
        "sufficient_balance": float(wallet.get("balance") or 0) >= due_now,
    }


async def _provider_client(account: dict) -> tuple[dict, int]:
    row = next(
        (client for client in await vl.clients()
         if vl.id_of(client, "id", "client_id") == str(account["client_id"])),
        None)
    if row is None:
        raise TelephonyError(
            "Your VoiceLink client could not be found. Contact support.", 409)
    return row, accounts._client_channels(row)


async def _write_provider_channels(account: dict, target: int) -> None:
    row, _ = await _provider_client(account)
    account_name = str(account.get("name") or "Customer")
    first = str(row.get("first_name") or account_name.split()[0] or "Customer")
    last = str(row.get("last_name") or "Customer")
    try:
        await vl.update_client(account["client_id"], {
            "first_name": first, "last_name": last, "is_active": 1,
            "channel_count": int(target)})
    except Exception as e:
        # A timeout/5xx may still have applied. Reconcile by reading the
        # provider state once; never blindly replay the mutation.
        _, verified = await _provider_client(account)
        if verified != int(target):
            raise TelephonyError(
                f"VoiceLink could not allocate {target} channels: {e}. "
                "The operator may need more channels in the reseller pool.",
                502) from None
    _, verified = await _provider_client(account)
    if verified != int(target):
        raise TelephonyError(
            "VoiceLink did not confirm the new channel allocation.", 502)
    await repo.update_account(
        account["id"], {"channels_allocated": verified})


async def _ensure_provider_channels(account: dict, target: int) -> int:
    """Raise/verify the provider allocation; returns its previous count."""
    _, previous = await _provider_client(account)
    if previous < int(target):
        await _write_provider_channels(account, int(target))
    else:
        await repo.update_account(
            account["id"], {"channels_allocated": previous})
    return previous


async def _rollback_provider_channels(account: dict, previous: int,
                                      target: int) -> None:
    if previous >= target:
        return
    try:
        _, current = await _provider_client(account)
        if current != previous:
            await _write_provider_channels(account, previous)
    except Exception as e:
        logger.warning(
            "[CHANNEL_UPGRADE_ROLLBACK_WARN] account=%s previous=%s: %r",
            account.get("id"), previous, e)


async def upgrade_phone_channels(user_id: str, phone_id: str, *,
                                 target_channels: int,
                                 accept_charge: bool,
                                 expected_due_now: float,
                                 expected_monthly_increment: float) -> dict:
    if not accept_charge:
        raise TelephonyError(
            "Confirm the channel-upgrade charge before continuing.", 400)
    quote = await quote_channel_upgrade(user_id, phone_id, target_channels)
    if round(float(expected_due_now), 2) != quote["due_now"] or round(
            float(expected_monthly_increment), 2) != quote["monthly_increment"]:
        raise TelephonyError(
            "The channel price or capacity changed. Review a fresh quote "
            "before confirming.", 409)
    if not quote["sufficient_balance"]:
        raise TelephonyError(
            f"Insufficient wallet balance (needs ₹{quote['due_now']:.2f}). "
            "Recharge first.", 402)

    phone, _, account = await _load_quote_context(
        user_id, phone_id, target_channels)
    target = int(target_channels)
    old_phone_channels = max(1, int(phone.get("channels") or 1))
    old_plan_channels = quote["plan_channels"]
    old_monthly_total = quote["current_monthly_total"]
    due_now = float(quote["due_now"])
    note = (f"Channel upgrade {phone_id} {old_phone_channels}->{target} "
            f"{uuid.uuid4().hex[:12]}")

    previous_provider: int | None = None
    charged = 0.0
    phone_updated = False
    subscription_attempted = False
    try:
        previous_provider = await _ensure_provider_channels(account, target)
        if due_now > 0:
            await repo.deduct_exact(user_id, due_now, note=note)
            charged = due_now
        updated = await repo.update_phone_number(
            phone_id, {"channels": target})
        if not updated:
            raise RuntimeError("could not update the phone number channels")
        phone_updated = True
        subscription_attempted = True
        entitlement = await subscription_service.record_paid_channel_upgrade(
            user_id, target, float(quote["monthly_increment"]))
    except Exception as e:
        if phone_updated or subscription_attempted:
            try:
                await repo.update_phone_number(
                    phone_id, {"channels": old_phone_channels})
            except Exception:
                pass
        if subscription_attempted:
            try:
                await get_prisma().subscription.update(
                    where={"userId": user_id}, data={
                        "concurrencyLines": old_plan_channels,
                        "monthlyTotal": old_monthly_total})
            except Exception:
                pass
        if charged > 0:
            try:
                await repo.credit(
                    user_id, charged, note=f"Refund: {note}")
            except Exception as refund_error:
                logger.error(
                    "[CHANNEL_UPGRADE_REFUND_FAILED] user=%s amount=%s: %r",
                    user_id, charged, refund_error)
        if previous_provider is not None:
            await _rollback_provider_channels(
                account, previous_provider, target)
        if isinstance(e, TelephonyError):
            raise
        if isinstance(e, ValueError):
            raise TelephonyError(str(e), 402) from None
        raise TelephonyError(
            f"Channel upgrade could not be completed: {e}", 502) from None

    updated = await repo.get_phone_number(phone_id, user_id) or updated
    return {
        "phone_number": updated,
        "entitlement": entitlement,
        "quote": quote,
        "charged_now": charged,
        "wallet": await repo.get_wallet(user_id),
    }
