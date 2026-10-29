"""Super Admin platform analytics (stats + usage rows).\n\nExtracted from the old monolithic admin_service — behavior unchanged.\n"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from ..db import get_prisma
from ..telephony import end_active_room
from .admin_shared import _now, audit

logger = logging.getLogger("voice-agent-saas-admin")


# ---------------------------------------------------------------------------
# Stats / usage
# ---------------------------------------------------------------------------
async def stats_overview() -> Dict[str, Any]:
    db = get_prisma()
    users = await db.user.count()
    calls = await db.call.count()
    providers = await db.provider.count()
    models = await db.catalogmodel.count()
    enabled_models = await db.catalogmodel.count(where={"enabled": True})
    enabled_providers = await db.provider.count(where={"enabled": True})
    wallet_total = 0.0
    try:
        agg = await db.user.aggregate(sum={"walletBalance": True})
        wallet_total = float((agg.get("_sum") or {}).get("walletBalance") or 0.0)
    except Exception:
        pass
    recharge_total = 0.0
    try:
        agg = await db.transaction.aggregate(where={"kind": "recharge"}, sum={"amount": True})
        recharge_total = float((agg.get("_sum") or {}).get("amount") or 0.0)
    except Exception:
        pass
    return {
        "users": users, "calls": calls,
        "providers": providers, "models": models,
        "enabled_providers": enabled_providers, "enabled_models": enabled_models,
        "wallet_balance_total": round(wallet_total, 2),
        "wallet_recharge_total": round(recharge_total, 2),
    }


async def usage_rows() -> List[Dict[str, Any]]:
    """Per-call usage+cost rows for the analytics page (most recent 500).

    Rows carry the customer's name/email so the panel reads as people, not
    raw ids."""
    db = get_prisma()
    calls = await db.call.find_many(order={"startedAt": "desc"}, take=500)
    uids = list({c.userId for c in calls if c.userId})
    users = await db.user.find_many(where={"id": {"in": uids}}) if uids else []
    uname = {u.id: (u.name or "") for u in users}
    uemail = {u.id: (u.email or "") for u in users}
    out: List[Dict[str, Any]] = []
    for c in calls:
        usage = _load(c.usage)
        cost = _load(c.cost)
        out.append({
            "id": c.id, "user_id": c.userId,
            "user_name": uname.get(c.userId, ""), "user_email": uemail.get(c.userId, ""),
            "agent_id": c.agentId,
            "mode": c.mode, "status": c.status, "started_at": c.startedAt or "",
            "ended_at": c.endedAt or "", "phone": c.phone or "",
            "room": c.room or "",
            "duration_seconds": c.durationSeconds or 0,
            "stt_seconds": usage.get("stt_seconds", 0),
            "llm_input_tokens": usage.get("llm_input_tokens", 0),
            "llm_output_tokens": usage.get("llm_output_tokens", 0),
            "tts_chars": usage.get("tts_chars", 0),
            "client_price_inr": cost.get("client_price_inr", 0),
            "total_cost_inr": cost.get("total_cost_inr", 0),
            "profit_inr": cost.get("your_profit_inr", 0),
        })
    return out


async def end_call_admin(call_id: str, *, admin: Dict[str, Any]) -> Dict[str, Any]:
    """Force-end one active/stale call from the Super Admin usage ledger.

    This mirrors the customer end-call semantics without the customer ownership
    restriction: `planned` becomes `failed` (the agent never joined), while
    `in-progress` becomes `completed` and the worker's final billing write can
    still land afterwards. Terminal calls are idempotent no-ops.
    """
    db = get_prisma()
    call = await db.call.find_unique(where={"id": call_id})
    if not call:
        raise LookupError("Call not found")

    previous_status = call.status or ""
    if previous_status in ("completed", "failed"):
        return {
            "ok": True,
            "call_id": call.id,
            "status": previous_status,
            "already_ended": True,
            "room_deleted": False,
        }

    room_deleted = False
    if call.room:
        room_deleted = bool(await end_active_room(call.room))

    next_status = "failed" if previous_status == "planned" else "completed"
    data: Dict[str, Any] = {"status": next_status, "endedAt": _now()}
    if previous_status == "planned":
        usage = _load(call.usage)
        usage["error"] = "Ended by Super Admin before the agent joined — no charge."
        data["usage"] = json.dumps(usage)

    await db.call.update(where={"id": call.id}, data=data)
    await audit(
        admin,
        "call_ended",
        target_type="call",
        target_id=call.id,
        detail={
            "from_status": previous_status,
            "to_status": next_status,
            "room_deleted": room_deleted,
            "mode": call.mode or "",
        },
    )
    return {
        "ok": True,
        "call_id": call.id,
        "status": next_status,
        "already_ended": False,
        "room_deleted": room_deleted,
    }


def _load(s: Any) -> dict:
    if not s:
        return {}
    try:
        return json.loads(s)
    except Exception:
        return {}
