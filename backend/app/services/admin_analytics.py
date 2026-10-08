"""Super Admin platform analytics (stats + usage rows).\n\nExtracted from the old monolithic admin_service — behavior unchanged.\n"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from ..db import get_prisma
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


def _load(s: Any) -> dict:
    if not s:
        return {}
    try:
        return json.loads(s)
    except Exception:
        return {}
