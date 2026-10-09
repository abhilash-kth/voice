"""Wallet transactions (atomic + idempotent) and usage analytics."""
from __future__ import annotations

from typing import Optional

from ..db import get_prisma
from .. import billing as billing_mod
from .common import _load_dict, _ts


# ---------------------------------------------------------------------------
# Wallet / usage
# ---------------------------------------------------------------------------
async def get_wallet(user_id: str) -> dict:
    db = get_prisma()
    u = await db.user.find_unique(where={"id": user_id})
    txs = await db.transaction.find_many(where={"userId": user_id}, order={"ts": "desc"})
    return {
        "balance": round(u.walletBalance or 0, 2) if u else 0.0,
        "currency": "INR",
        "transactions": [
            {"ts": t.ts, "kind": t.kind, "amount": t.amount, "note": t.note} for t in txs
        ],
    }


async def recharge(user_id: str, amount: float) -> dict:
    db = get_prisma()
    # Atomic: balance update + ledger row succeed or fail together.
    async with db.tx(timeout=8000) as tx:
        u = await tx.user.find_unique(where={"id": user_id})
        if not u:
            raise ValueError("user not found")
        new_balance = round((u.walletBalance or 0) + amount, 2)
        await tx.user.update(where={"id": user_id}, data={"walletBalance": new_balance})
        await tx.transaction.create(
            data={"userId": user_id, "kind": "recharge", "amount": amount, "note": "Top-up", "ts": _ts()}
        )
    return await get_wallet(user_id)


async def deduct(user_id: str, amount: float, note: str = "") -> dict:
    """Idempotent wallet deduction WITHOUT interactive transactions.

    The generated client's ``db.tx()`` raises ``ClientNotConnectedError`` on
    the per-event-loop clients used by LiveKit job processes (plain queries
    work on the same connected client — interactive tx does not), which used
    to drop the entire direct-deduct fallback when the API server was
    unreachable. Instead: idempotency pre-check → optimistic compare-and-set
    on the balance → ledger row, with best-effort balance compensation if
    the ledger write fails. The CAS predicate makes concurrent deducts
    single-winner, matching the old tx semantics.
    """
    db = get_prisma()
    if amount <= 0:
        return await get_wallet(user_id)
    for _attempt in range(2):
        # Idempotency first thing EVERY attempt: if a ledger row for this exact
        # note already exists, another deduct (API settle / worker fallback)
        # already charged this call — return without charging again.
        if note:
            try:
                existing = await db.transaction.find_first(
                    where={"userId": user_id, "kind": "spend", "note": note}
                )
                if existing:
                    return await get_wallet(user_id)
            except Exception:
                pass
        u = await db.user.find_unique(where={"id": user_id})
        if not u:
            raise ValueError("user not found")
        old_balance = u.walletBalance or 0
        new_balance = round(max(old_balance - amount, 0.0), 2)
        # Compare-and-set: only the deduct that matches the exact balance it
        # read gets to move the balance; a concurrent change loses and retries
        # (the retry re-checks the ledger first, closing the double charge).
        res = await db.user.update_many(
            where={"id": user_id, "walletBalance": old_balance},
            data={"walletBalance": new_balance},
        )
        if getattr(res, "count", 0) == 0:
            continue
        try:
            await db.transaction.create(
                data={"userId": user_id, "kind": "spend", "amount": -amount, "note": note, "ts": _ts()}
            )
        except Exception:
            # Keep money and ledger in step: restore the balance, then fail
            # loudly so the caller can retry rather than double-charging.
            try:
                await db.user.update_many(
                    where={"id": user_id, "walletBalance": new_balance},
                    data={"walletBalance": old_balance},
                )
            except Exception:
                pass
            raise
        return await get_wallet(user_id)
    raise RuntimeError("wallet deduct failed: balance changed concurrently (retry)")


async def has_spend_for_call(user_id: str, call_id: str) -> bool:
    db = get_prisma()
    try:
        existing = await db.transaction.find_first(
            where={"userId": user_id, "kind": "spend", "note": {"contains": call_id}}
        )
        return existing is not None
    except Exception:
        return False


async def get_usage(user_id: str, agent_id: Optional[str] = None) -> dict:
    where: dict = {"userId": user_id, "status": "completed"}
    if agent_id:
        where["agentId"] = agent_id
    calls = await get_prisma().call.find_many(where=where)

    total_seconds = sum(c.durationSeconds or 0 for c in calls)
    spend = sum(float(_load_dict(c.cost).get("client_price_inr", 0) or 0) for c in calls)
    llm_in = sum(int(_load_dict(c.usage).get("llm_input_tokens", 0) or 0) for c in calls)
    llm_out = sum(int(_load_dict(c.usage).get("llm_output_tokens", 0) or 0) for c in calls)
    tts = sum(int(_load_dict(c.usage).get("tts_chars", 0) or 0) for c in calls)
    stt = sum(float(_load_dict(c.usage).get("stt_seconds", 0) or 0) for c in calls)

    u = await get_prisma().user.find_unique(where={"id": user_id})
    recent = []
    for c in calls:
        cost = _load_dict(c.cost)
        usage = _load_dict(c.usage)
        recent.append({
            "id": c.id,
            "agentId": c.agentId,
            "date": c.startedAt or "",
            "mode": c.mode,
            "durationSeconds": c.durationSeconds,
            "ttsChars": usage.get("tts_chars", 0),
            "llmTokens": usage.get("llm_output_tokens", 0),
            "tokensUsed": (usage.get("llm_input_tokens", 0) or 0) + (usage.get("llm_output_tokens", 0) or 0),
            "costToUser": f"₹{cost.get('client_price_inr', 0)}",
            "costToUserNumber": cost.get("client_price_inr", 0),
            "providerCost": cost.get("total_cost_inr", 0),
            "costPerMin": cost.get("your_cost_per_min", 0),
            "status": c.status,
        })
    return {
        "walletBalance": round(u.walletBalance or 0, 2) if u else 0.0,
        "totalCallsCount": len(calls),
        "totalMinutesUsed": round(total_seconds / 60.0, 1),
        "currentMonthSpend": round(spend, 2),
        "llmInputTokens": llm_in,
        "llmOutputTokens": llm_out,
        "ttsChars": tts,
        "sttSeconds": round(stt, 1),
        "recentCalls": recent,
    }


# Backward-compat helper for the cost preview calculations.
def cost_calc(*args, **kwargs) -> dict:
    return billing_mod.calculate_call_cost(*args, **kwargs)
