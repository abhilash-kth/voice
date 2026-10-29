"""DID browse -> quote (provider lock) -> paid confirm -> assign -> activate.

Money discipline:
* A durable PhonePurchase row exists BEFORE any provider lock/confirm.
* The SaaS wallet is charged exactly the fresh provider quote total with
  ``deduct_exact`` (never floors at ₹0) and an idempotent note.
* A definite provider rejection refunds; an uncertain outcome (timeout/5xx)
  parks the purchase in ``needs_review`` — it is never blindly replayed.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Optional

from .. import repo
from . import telephony_account as accounts
from . import telephony_provisioning as provisioning
from . import telephony_settings
from . import voicelink_client as vl
from .telephony_policy import TelephonyError

logger = logging.getLogger("voice-agent-saas-purchase")

_QUOTE_MINUTES = 8
_OPEN_STATES = ("draft", "quoted", "confirming", "purchased", "assigned",
                "provisioning", "needs_review")


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def _expired(purchase: dict) -> bool:
    raw = purchase.get("expires_at") or ""
    try:
        return bool(raw) and datetime.fromisoformat(raw) <= datetime.utcnow()
    except Exception:
        return False


async def purchase_view(purchase: Optional[dict]) -> Optional[dict]:
    if not purchase:
        return None
    out = dict(purchase)
    out["confirmation_available"] = (
        purchase["state"] == "quoted" and not _expired(purchase))
    out["phone_number"] = None
    if purchase.get("phone_number_id"):
        out["phone_number"] = await repo.get_phone_number(
            purchase["phone_number_id"], purchase["user_id"])
    return out


async def search_numbers(user_id: str, *, did_type: str = "3", months: int = 1,
                         number: str = "", page: int = 1) -> dict:
    await accounts.require_account(user_id)
    if not re.fullmatch(r"\d{1,3}", str(did_type or "")):
        raise TelephonyError("Choose a valid number type.", 400)
    if number and not re.fullmatch(r"[+0-9]{1,16}", number):
        raise TelephonyError("Search digits only.", 400)
    raw = await vl.search_dids(did_type=str(did_type), months=int(months),
                               number=number, page=int(page), per_page=25)
    items = []
    for row in vl.as_list(raw):
        if not isinstance(row, dict):
            continue
        e164 = vl.normalize_in_number(row.get("did_number") or row.get("number"))
        did_id = vl.id_of(row, "id", "did_id")
        if not did_id or not e164.startswith("+91"):
            continue
        items.append({
            "id": did_id, "number": e164,
            "type_label": str(row.get("type_label") or row.get("type") or "")[:80],
            "monthly_rate": vl.money(row.get("monthly_rate", row.get("rate"))),
            "country_code": "+91",
        })
    total = raw.get("total") if isinstance(raw, dict) else None
    return {"items": items,
            "total": int(total) if isinstance(total, int) else len(items),
            "page": int(page)}


async def _ensure_client_channels(account: dict, wanted: int) -> None:
    """Best effort: raise the VoiceLink client's allocated channels after a
    purchase (using reseller-pool channels the order just bought/held)."""
    try:
        row = next((c for c in await vl.clients()
                    if vl.id_of(c, "id") == str(account["client_id"])), None)
        if not row:
            return
        current = accounts._client_channels(row)
        if current >= wanted:
            return
        name = str(row.get("first_name") or account.get("name") or "Customer")
        last = str(row.get("last_name") or "Customer")
        await vl.update_client(account["client_id"], {
            "first_name": name, "last_name": last, "is_active": 1,
            "channel_count": int(wanted)})
    except Exception as e:
        logger.warning("[PURCHASE_CHANNELS_WARN] account=%s: %s",
                       account.get("id"), e)


async def create_quote(user_id: str, body) -> dict:
    account = await accounts.require_account(user_id)
    state = await accounts.sync_kyc(account)
    if state["status"] != "verified":
        raise TelephonyError(
            "Complete KYC verification before buying a phone number.", 409)
    number = vl.normalize_in_number(body.number)
    if not number.startswith("+91"):
        raise TelephonyError("Choose an Indian (+91) number.", 400)
    existing = await repo.get_purchase_by_idempotency(user_id, body.idempotency_key)
    if existing:
        if existing["provider_did_id"] != str(body.did_id):
            raise TelephonyError("This quote key was used for another number.", 409)
        return await purchase_view(existing) or existing
    latest = await repo.latest_purchase(user_id)
    if latest and latest["state"] in _OPEN_STATES and not _expired(latest):
        if latest["provider_did_id"] == str(body.did_id) \
                and latest["state"] in ("draft", "quoted"):
            return await purchase_view(latest) or latest
        raise TelephonyError(
            "Finish or let support resolve your existing number purchase "
            "before reserving another number.", 409)

    purchase = await repo.create_purchase({
        "user_id": user_id, "voice_link_account_id": account["id"],
        "provider_did_id": str(body.did_id), "number": number,
        "months": int(body.months), "channels": int(body.channels),
        "idempotency_key": body.idempotency_key, "state": "draft"})
    try:
        locked = await vl.lock_did(str(body.did_id), int(body.months))
        order_id = vl.id_of(locked, "order_id", "id")
        locked_rows = locked.get("locked_dids") if isinstance(locked, dict) else None
        monthly = 0.0
        if isinstance(locked_rows, list) and locked_rows:
            row = locked_rows[0] if isinstance(locked_rows[0], dict) else {}
            if vl.id_of(row, "did_id", "id") not in ("", str(body.did_id)) \
                    or vl.normalize_in_number(row.get("did_number")) != number:
                raise TelephonyError(
                    "VoiceLink locked a different number than selected. "
                    "Support must review this quote.", 502)
            monthly = vl.money(row.get("monthly_rate"))
        if not order_id:
            raise TelephonyError("VoiceLink did not return an order id.", 502)
        purchase = await repo.update_purchase(purchase["id"], {
            "provider_order_id": order_id, "monthly_rate": monthly}) or purchase

        wanted = int(body.channels)
        allocated = int(account.get("channels_allocated") or 0)
        if wanted > allocated:
            profile = accounts.safe_profile(await vl.profile())
            short = wanted - allocated - int(profile["channels_available"] or 0)
            if short > 0:  # buy the missing channels inside this order
                await vl.add_channel(order_id, short, int(body.months))
        summary = await vl.purchase_summary(order_id)
        if summary.get("months") not in (None, int(body.months)) \
                or summary.get("did_count") not in (None, 1):
            raise TelephonyError("VoiceLink quote does not match the "
                                 "selected number.", 502)
        total = vl.money(summary.get("total"))
        if total <= 0:
            raise TelephonyError("VoiceLink returned an invalid quote total.", 502)
        if not monthly:
            monthly = vl.money(summary.get("did_cost")) or total
        purchase = await repo.update_purchase(purchase["id"], {
            "state": "quoted", "quote_total": total,
            "customer_charge": total, "monthly_rate": monthly,
            "expires_at": _iso(datetime.utcnow() + timedelta(minutes=_QUOTE_MINUTES)),
            "error": ""}) or purchase
    except Exception as e:
        uncertain = bool(getattr(e, "uncertain", False)) \
            or bool(purchase.get("provider_order_id"))
        await repo.update_purchase(purchase["id"], {
            "state": "needs_review" if uncertain else "failed",
            "error": str(e)[:500]})
        status = getattr(e, "status_code", 502)
        raise TelephonyError(str(e), status if isinstance(status, int) else 502)
    return await purchase_view(purchase) or purchase


async def confirm_purchase(user_id: str, purchase_id: str,
                           accept_auto_renew: bool) -> dict:
    if not accept_auto_renew:
        raise TelephonyError(
            "Confirm the recurring renewal terms before purchasing.", 400)
    purchase = await repo.get_purchase(purchase_id, user_id)
    if not purchase:
        raise TelephonyError("Purchase not found.", 404)
    if purchase["state"] in ("active", "assigned", "provisioning", "purchased"):
        return await purchase_view(purchase) or purchase
    if purchase["state"] != "quoted" or not purchase.get("provider_order_id"):
        raise TelephonyError(
            "This purchase cannot be confirmed again. Support must review "
            "its current state.", 409)
    if _expired(purchase):
        await repo.update_purchase(purchase_id, {"state": "expired"})
        raise TelephonyError(
            "This quote expired. Ask support to close the reserved draft "
            "before reserving another number.", 409)
    account = await accounts.require_account(user_id)
    if account["id"] != purchase["voice_link_account_id"]:
        raise TelephonyError("The telephony account changed since quoting.", 409)
    state = await accounts.sync_kyc(account)
    if state["status"] != "verified":
        raise TelephonyError("KYC must stay verified to buy a number.", 409)

    summary = await vl.purchase_summary(purchase["provider_order_id"])
    total = vl.money(summary.get("total"))
    if total <= 0 or round(total, 2) != round(float(purchase["quote_total"]), 2):
        await repo.update_purchase(purchase_id, {
            "state": "needs_review",
            "error": "Provider pricing changed after quoting."})
        raise TelephonyError(
            "Provider pricing changed. Support must review this quote "
            "before any charge.", 409)

    await repo.update_purchase(purchase_id, {"state": "confirming"})
    try:
        await repo.deduct_exact(
            user_id, total, note=f"Phone number purchase {purchase_id}")
    except ValueError as e:
        await repo.update_purchase(purchase_id, {"state": "quoted"})
        raise TelephonyError(str(e), 402) from None
    try:
        confirmed = await vl.confirm_purchase(purchase["provider_order_id"])
        provider_purchase_id = vl.id_of(
            confirmed, "purchase_order_id", "purchase_id", "id")
        if confirmed.get("total") is not None \
                and round(vl.money(confirmed["total"]), 2) != round(total, 2):
            raise TelephonyError(
                "VoiceLink confirmed a different total than quoted.", 502)
    except Exception as e:
        if getattr(e, "uncertain", False) or getattr(e, "status_code", 0) >= 500:
            await repo.update_purchase(purchase_id, {
                "state": "needs_review",
                "error": f"Wallet charged; provider outcome uncertain: {e}"[:500]})
            raise TelephonyError(
                "The purchase outcome could not be confirmed. Your wallet "
                "was charged and support must reconcile this order — do not "
                "buy again.", 502) from None
        await repo.credit(user_id, total,
                          note=f"Refund: phone purchase {purchase_id} rejected")
        await repo.update_purchase(purchase_id, {
            "state": "failed", "error": str(e)[:500]})
        status = getattr(e, "status_code", 502)
        raise TelephonyError(str(e), status if isinstance(status, int) else 502)

    purchase = await repo.update_purchase(purchase_id, {
        "state": "purchased", "provider_purchase_id": provider_purchase_id,
        "customer_charge": total, "error": ""}) or purchase
    try:
        await vl.map_did(account["client_id"], purchase["provider_did_id"])
    except Exception as e:
        await repo.update_purchase(purchase_id, {
            "state": "needs_review",
            "error": f"Purchased but assignment failed: {e}"[:500]})
        raise TelephonyError(
            "The number was purchased but could not be assigned yet. "
            "Support must finish assignment; do not buy again.", 502) from None
    await _ensure_client_channels(account, int(purchase["channels"]))

    phone = await repo.get_phone_by_number(purchase["number"])
    if phone and phone["user_id"] != user_id:
        await repo.update_purchase(purchase_id, {
            "state": "needs_review",
            "error": "Purchased number already registered to another user."})
        raise TelephonyError(
            "This number is already registered. Support must review it.", 409)
    if not phone:
        settings = await telephony_settings.get_settings()
        phone = await repo.create_phone_number({
            "user_id": user_id, "voice_link_account_id": account["id"],
            "number": purchase["number"], "source": "voicelink",
            "status": "provisioning", "provisioning_step": "purchased",
            "channels": int(purchase["channels"]),
            "monthly_rate": float(purchase["monthly_rate"] or 0),
            "expires_at": _iso(datetime.utcnow()
                               + timedelta(days=30 * int(purchase["months"]))),
            "provider_did_id": purchase["provider_did_id"],
            "provider_purchase_id": provider_purchase_id,
            "dial_prefix": settings.voicelink_tech_prefix,
            "meta": {"purchase_id": purchase_id}})
    purchase = await repo.update_purchase(purchase_id, {
        "state": "provisioning", "phone_number_id": phone["id"]}) or purchase
    warning = ""
    try:
        phone = await provisioning.provision_number(phone["id"], user_id)
        purchase = await repo.update_purchase(
            purchase_id, {"state": "active", "error": ""}) or purchase
    except Exception as e:
        warning = (f"Number purchased and assigned. Automatic activation "
                   f"needs a retry: {e}")
        await repo.update_purchase(purchase_id, {"error": warning[:500]})
    view = await purchase_view(purchase) or purchase
    if warning:
        view["warning"] = warning
    return view


async def sync_purchased_numbers(account: dict) -> dict:
    """Import/reconcile provider-owned DIDs for this client (read-only with
    VoiceLink; creates local rows in `provisioning` for activation)."""
    imported = 0
    seen = 0
    settings = await telephony_settings.get_settings()
    for page in range(1, 11):
        raw = await vl.purchased_dids(account["client_id"], page=page)
        rows = vl.as_list(raw)
        if not rows:
            break
        for row in rows:
            if not isinstance(row, dict):
                continue
            if str(row.get("client_id") or account["client_id"]) != str(account["client_id"]):
                continue
            if row.get("status") == 6:
                continue
            number = vl.normalize_in_number(row.get("did_number") or row.get("number"))
            if not number:
                continue
            seen += 1
            did_id = vl.id_of(row, "did_id", "id")
            expires = str(row.get("user_expiry_date") or row.get("expiry_date") or "")
            existing = await repo.get_phone_by_number(number)
            if existing:
                if existing["user_id"] != account["user_id"]:
                    continue
                patch = {}
                if not existing.get("voice_link_account_id"):
                    patch["voice_link_account_id"] = account["id"]
                if did_id and not existing.get("provider_did_id"):
                    patch["provider_did_id"] = did_id
                if expires and not existing.get("expires_at"):
                    patch["expires_at"] = expires
                if patch:
                    await repo.update_phone_number(existing["id"], patch)
                continue
            await repo.create_phone_number({
                "user_id": account["user_id"],
                "voice_link_account_id": account["id"], "number": number,
                "source": "voicelink", "status": "provisioning",
                "provisioning_step": "imported",
                "monthly_rate": vl.money(row.get("monthly_rate")),
                "expires_at": expires, "provider_did_id": did_id,
                "dial_prefix": settings.voicelink_tech_prefix})
            imported += 1
        if isinstance(raw, dict) and isinstance(raw.get("total"), int) \
                and seen >= raw["total"]:
            break
    return {"imported": imported, "provider_total": seen,
            "numbers": await repo.list_phone_numbers(account["user_id"])}
