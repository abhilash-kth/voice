"""Super Admin views/actions for the telephony marketplace.

Reads join the owning user in-process (same pattern as the subscriptions
admin list). Mutations reuse the customer-facing services and are audited
by the admin routes. Secrets never leave: SIP passwords are only ever the
masked value, and the reseller token is reported as configured/not.
"""
from __future__ import annotations

from typing import Optional

from .. import repo
from ..db import get_prisma
from ..telephony import trunks as lk_trunks
from . import telephony_account as accounts
from . import telephony_provisioning as provisioning
from . import telephony_purchase as purchases
from . import telephony_settings
from . import voicelink_client as vl
from .telephony_policy import TelephonyError


async def _users_map(user_ids: list[str]) -> dict:
    ids = sorted({u for u in user_ids if u})
    if not ids:
        return {}
    rows = await get_prisma().user.find_many(where={"id": {"in": ids}})
    return {u.id: {"email": u.email or "", "name": u.name or ""} for u in rows}


def _page(items: list, page: int, page_size: int) -> dict:
    page = max(page, 1)
    start = (page - 1) * page_size
    return {"items": items[start:start + page_size], "total": len(items),
            "page": page, "page_size": page_size}


async def overview() -> dict:
    settings = await telephony_settings.get_settings()
    account_rows = await repo.list_accounts()
    number_rows = await repo.list_phone_numbers()
    purchase_rows = await repo.list_purchases()
    profile = None
    provider_error = ""
    if settings.configured:
        try:
            profile = accounts.safe_profile(await vl.profile())
        except Exception as e:
            provider_error = str(e)[:300]
    by = lambda rows, key: {s: sum(1 for r in rows if r.get(key) == s)
                            for s in sorted({r.get(key) or "" for r in rows})}
    return {
        "configured": settings.configured,
        "config": {
            "source": settings.source,
            "api_base_url": settings.voicelink_api_base_url,
            "voicelink_sip": (
                f"{settings.voicelink_sip_host}:{settings.voicelink_sip_port}"),
            "livekit_sip": (
                f"{settings.livekit_sip_host}:{settings.livekit_sip_port}"),
            "tech_prefix": settings.voicelink_tech_prefix,
            "wallet_bypass": settings.voicelink_wallet_bypass,
            "kyc_finalize_verified": settings.kyc_finalize_verified,
            "kyc_terms_configured": bool(
                accounts.terms_url(settings.voicelink_kyc_terms_url)),
            "default_trunk_configured": bool(settings.default_sip_trunk_id),
            "frontend_url": settings.frontend_url,
            "public_api_url": settings.public_api_url,
            "updated_at": settings.updated_at,
        },
        "provider_profile": profile,
        "provider_error": provider_error,
        "counts": {
            "accounts": len(account_rows),
            "numbers": len(number_rows),
            "purchases": len(purchase_rows),
            "accounts_by_kyc": by(account_rows, "kyc_status"),
            "numbers_by_status": by(number_rows, "status"),
            "purchases_by_state": by(purchase_rows, "state"),
        },
    }


async def list_accounts_admin(*, q: str = "", kyc_status: str = "",
                              status: str = "", page: int = 1,
                              page_size: int = 25) -> dict:
    rows = await repo.list_accounts()
    numbers = await repo.list_phone_numbers()
    counts: dict[str, int] = {}
    for n in numbers:
        if n.get("voice_link_account_id"):
            counts[n["voice_link_account_id"]] = counts.get(
                n["voice_link_account_id"], 0) + 1
    users = await _users_map([r["user_id"] for r in rows])
    items = []
    for r in rows:
        u = users.get(r["user_id"], {})
        item = {**r, "user_email": u.get("email", ""),
                "user_name": u.get("name", ""),
                "numbers_count": counts.get(r["id"], 0)}
        if kyc_status and item["kyc_status"] != kyc_status:
            continue
        if status and item["status"] != status:
            continue
        if q and q.lower() not in (
                item["user_email"] + item["user_name"] + item["client_id"]
                + item["email"] + item["name"]).lower():
            continue
        items.append(item)
    return _page(items, page, page_size)


async def account_detail(account_id: str) -> Optional[dict]:
    account = await repo.get_account(account_id)
    if not account:
        return None
    users = await _users_map([account["user_id"]])
    numbers = [n for n in await repo.list_phone_numbers(account["user_id"])
               if n.get("voice_link_account_id") == account_id]
    return {
        "account": {**account, **{
            "user_email": users.get(account["user_id"], {}).get("email", ""),
            "user_name": users.get(account["user_id"], {}).get("name", "")}},
        "numbers": numbers,
        "purchases": await repo.list_purchases(account_id=account_id),
    }


async def list_numbers_admin(*, q: str = "", status: str = "",
                             user_id: str = "", page: int = 1,
                             page_size: int = 25) -> dict:
    rows = await repo.list_phone_numbers()
    users = await _users_map([r["user_id"] for r in rows])
    agent_rows = await get_prisma().agent.find_many(
        where={"phoneNumberId": {"in": [r["id"] for r in rows]}}) if rows else []
    agents_by_phone: dict[str, list] = {}
    for a in agent_rows:
        d = repo._agent_dict(a)
        agents_by_phone.setdefault(d["phone_number_id"], []).append(
            {"id": d["id"], "name": d["name"], "purpose": d["purpose"],
             "enabled": d["enabled"]})
    items = []
    for r in rows:
        if status and r["status"] != status:
            continue
        if user_id and r["user_id"] != user_id:
            continue
        u = users.get(r["user_id"], {})
        item = {**r, "user_email": u.get("email", ""),
                "user_name": u.get("name", ""),
                "agents": agents_by_phone.get(r["id"], [])}
        if q and q.lower() not in (
                item["number"] + item["user_email"] + item["user_name"]
                + item["livekit_outbound_trunk_id"]).lower():
            continue
        items.append(item)
    return _page(items, page, page_size)


async def list_purchases_admin(*, state: str = "", page: int = 1,
                               page_size: int = 25) -> dict:
    rows = await repo.list_purchases()
    users = await _users_map([r["user_id"] for r in rows])
    items = []
    for r in rows:
        if state and r["state"] != state:
            continue
        u = users.get(r["user_id"], {})
        items.append({**r, "user_email": u.get("email", ""),
                      "user_name": u.get("name", "")})
    return _page(items, page, page_size)


async def sync_account_admin(account_id: str) -> dict:
    account = await repo.get_account(account_id)
    if not account:
        raise TelephonyError("Telephony account not found.", 404)
    account = await accounts.sync_account(account)
    await purchases.sync_purchased_numbers(account)
    return await account_detail(account_id) or {"account": account}


async def allocate_admin(account_id: str, amount: float,
                         description: str = "") -> dict:
    account = await repo.get_account(account_id)
    if not account:
        raise TelephonyError("Telephony account not found.", 404)
    await vl.allocate_wallet(account["client_id"], round(float(amount), 2),
                             description or "Operator allocation")
    try:
        account = await accounts.sync_account(account)
    except Exception:
        pass
    return account


async def set_account_status(account_id: str, status: str) -> dict:
    account = await repo.get_account(account_id)
    if not account:
        raise TelephonyError("Telephony account not found.", 404)
    active = status == "active"
    row = next((c for c in await vl.clients()
                if vl.id_of(c, "id") == str(account["client_id"])), None)
    if row is None:
        raise TelephonyError("VoiceLink client not found provider-side.", 409)
    parts = str(account.get("name") or "Customer").split()
    await vl.update_client(account["client_id"], {
        "first_name": str(row.get("first_name") or parts[0]),
        "last_name": str(row.get("last_name")
                         or (" ".join(parts[1:]) or "Customer")),
        "is_active": 1 if active else 0,
        "channel_count": accounts._client_channels(row)
        or int(account.get("channels_allocated") or 1),
    })
    account = await repo.update_account(
        account_id, {"status": "active" if active else "suspended"}) or account
    numbers = [n for n in await repo.list_phone_numbers(account["user_id"])
               if n.get("voice_link_account_id") == account_id]
    for n in numbers:
        if not active and n.get("livekit_dispatch_rule_id"):
            await lk_trunks.delete_dispatch_rule(n["livekit_dispatch_rule_id"])
            await repo.update_phone_number(n["id"], {
                "livekit_dispatch_rule_id": "", "inbound_agent_id": None})
        elif active:
            await provisioning._sync_inbound_best_effort(n["id"])
    return await repo.get_account(account_id) or account


async def create_manual_number_admin(body) -> dict:
    user = await repo.get_user(body.user_id)
    if not user:
        raise TelephonyError("User not found.", 404)
    return await provisioning.create_manual_number(
        body.user_id, body.model_dump())
