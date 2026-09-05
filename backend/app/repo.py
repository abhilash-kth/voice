"""
Repository / data-access layer built on the Prisma client.

All reads/writes are async and go through the shared Prisma client
(app/db.get_prisma()). JSON blobs are stored as strings and (de)serialized here
so the same code runs on SQLite and Postgres/Neon.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional

from .db import get_prisma
from . import billing as billing_mod


def _ts() -> str:
    return datetime.utcnow().isoformat(timespec="seconds")


def _dump(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False) if v is not None else "{}"


def _load_dict(s: Optional[str]) -> dict:
    if not s:
        return {}
    try:
        return json.loads(s)
    except Exception:
        return {}


def _load_list(s: Optional[str]) -> list:
    if not s:
        return []
    try:
        return json.loads(s)
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------
async def create_user(email: str, name: str, password_hash: str) -> dict:
    db = get_prisma()
    u = await db.user.create(data={"email": email.lower(), "name": name, "passwordHash": password_hash})
    return _user_dict(u)


async def get_user_by_email(email: str) -> Optional[Any]:
    return await get_prisma().user.find_unique(where={"email": email.lower()})


async def get_user(user_id: str) -> Optional[Any]:
    return await get_prisma().user.find_unique(where={"id": user_id})


def _user_dict(u: Any) -> dict:
    return {
        "id": u.id,
        "email": u.email,
        "name": u.name or "",
        "wallet_balance": round(u.walletBalance or 0, 2),
        "created_at": u.createdAt or "",
    }


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------
def _agent_dict(a: Any) -> dict:
    return {
        "id": a.id,
        "user_id": a.userId,
        "name": a.name,
        "description": a.description or "",
        "greeting": a.greeting or "",
        "language": a.language,
        "voice_personality": a.voicePersonality,
        "client_rate_per_min": a.clientRatePerMin,
        "memory_enabled": bool(a.memoryEnabled),
        "recording_enabled": bool(a.recordingEnabled),
        "max_concurrency": a.maxConcurrency,
        "enabled": bool(a.enabled),
        "agent_mode": a.agentMode or "assistant",
        "announce_text": a.announceText or "",
        "providers": _load_dict(a.providers),
        "knowledge": _load_dict(a.knowledge),
        "created_at": a.createdAt,
    }


async def list_agents(user_id: str) -> list[dict]:
    rows = await get_prisma().agent.find_many(
        where={"userId": user_id}, order={"createdAt": "desc"}
    )
    return [_agent_dict(a) for a in rows]


async def get_agent(agent_id: str, user_id: str) -> Optional[dict]:
    a = await get_prisma().agent.find_first(where={"id": agent_id, "userId": user_id})
    return _agent_dict(a) if a else None


async def create_agent(user_id: str, data: dict) -> dict:
    db = get_prisma()
    a = await db.agent.create(
        data={
            "userId": user_id,
            "name": data.get("name", "Agent"),
            "description": data.get("description", ""),
            "greeting": data.get("greeting", ""),
            "language": data.get("language", "hi"),
            "voicePersonality": data.get("voice_personality", "friendly"),
            "clientRatePerMin": float(data.get("client_rate_per_min", 2.5)),
            "memoryEnabled": bool(data.get("memory_enabled", True)),
            "recordingEnabled": bool(data.get("recording_enabled", True)),
            "maxConcurrency": int(data.get("max_concurrency", 1)),
            "enabled": bool(data.get("enabled", True)),
            "agentMode": data.get("agent_mode", "assistant"),
            "announceText": data.get("announce_text", ""),
            "providers": _dump(data.get("providers", {})),
            "knowledge": _dump(data.get("knowledge", {})),
        }
    )
    return _agent_dict(a)


async def update_agent(agent_id: str, user_id: str, patch: dict) -> Optional[dict]:
    data: dict = {}
    mapping = {
        "name": "name", "description": "description", "greeting": "greeting",
        "language": "language", "voice_personality": "voicePersonality",
        "client_rate_per_min": "clientRatePerMin", "memory_enabled": "memoryEnabled",
        "recording_enabled": "recordingEnabled", "max_concurrency": "maxConcurrency",
        "enabled": "enabled", "agent_mode": "agentMode", "announce_text": "announceText",
    }
    for k, v in patch.items():
        if k in mapping:
            data[mapping[k]] = v
    if "providers" in patch:
        data["providers"] = _dump(patch["providers"])
    if "knowledge" in patch:
        data["knowledge"] = _dump(patch["knowledge"])

    existing = await get_agent(agent_id, user_id)
    if not existing:
        return None
    a = await get_prisma().agent.update(where={"id": agent_id}, data=data)
    return _agent_dict(a)


async def delete_agent(agent_id: str, user_id: str) -> bool:
    existing = await get_agent(agent_id, user_id)
    if not existing:
        return False
    await get_prisma().agent.delete(where={"id": agent_id})
    return True


async def set_agent_knowledge(agent_id: str, user_id: str, kb: dict) -> Optional[dict]:
    existing = await get_agent(agent_id, user_id)
    if not existing:
        return None
    current = dict(existing["knowledge"])
    if "text" in kb:
        current["text"] = kb.get("text") or ""
    if "system_prompt" in kb:
        current["system_prompt"] = kb.get("system_prompt") or ""
    if "faq" in kb:
        current["faq"] = kb.get("faq") or []
    a = await get_prisma().agent.update(where={"id": agent_id}, data={"knowledge": _dump(current)})
    return _agent_dict(a)


async def append_agent_document(agent_id: str, user_id: str, doc: dict) -> Optional[dict]:
    existing = await get_agent(agent_id, user_id)
    if not existing:
        return None
    current = dict(existing["knowledge"])
    docs = list(current.get("documents", []))
    docs.append(doc)
    current["documents"] = docs
    a = await get_prisma().agent.update(where={"id": agent_id}, data={"knowledge": _dump(current)})
    return _agent_dict(a)


# ---------------------------------------------------------------------------
# Calls
# ---------------------------------------------------------------------------
def _call_dict(c: Any) -> dict:
    return {
        "id": c.id,
        "user_id": c.userId,
        "agent_id": c.agentId,
        "mode": c.mode,
        "room": c.room or "",
        "phone": c.phone or None,
        "status": c.status,
        "started_at": c.startedAt or "",
        "ended_at": c.endedAt or "",
        "duration_seconds": c.durationSeconds or 0,
        "transcripts": _load_list(c.transcripts),
        "recording_url": c.recordingUrl or None,
        "usage": _load_dict(c.usage),
        "cost": _load_dict(c.cost),
    }


async def list_calls(user_id: str, agent_id: Optional[str] = None) -> list[dict]:
    where: dict = {"userId": user_id}
    if agent_id:
        where["agentId"] = agent_id
    rows = await get_prisma().call.find_many(where=where, order={"startedAt": "desc"})
    return [_call_dict(c) for c in rows]


async def get_call(call_id: str, user_id: str) -> Optional[dict]:
    c = await get_prisma().call.find_unique(where={"id": call_id})
    if not c or c.userId != user_id:
        return None
    return _call_dict(c)


async def create_call(data: dict) -> dict:
    db = get_prisma()
    c = await db.call.create(
        data={
            "userId": data["user_id"],
            "agentId": data["agent_id"],
            "mode": data.get("mode", "browser"),
            "room": data.get("room", ""),
            "phone": data.get("phone"),
            "status": data.get("status", "planned"),
            "startedAt": data.get("started_at", ""),
            "transcripts": _dump(data.get("transcripts", [])),
        }
    )
    return _call_dict(c)


async def update_call(call_id: str, patch: dict) -> Optional[dict]:
    data: dict = {}
    mapping = {
        "status": "status", "room": "room", "ended_at": "endedAt",
        "duration_seconds": "durationSeconds", "phone": "phone",
        "recording_url": "recordingUrl", "started_at": "startedAt",
    }
    for k, v in patch.items():
        if k in mapping:
            data[mapping[k]] = v
    if "transcripts" in patch:
        data["transcripts"] = _dump(patch["transcripts"])
    if "usage" in patch:
        data["usage"] = _dump(patch["usage"])
    if "cost" in patch:
        data["cost"] = _dump(patch["cost"])

    try:
        c = await get_prisma().call.update(where={"id": call_id}, data=data)
    except Exception:
        return None
    return _call_dict(c)


async def count_active_calls(agent_id: str) -> int:
    return await get_prisma().call.count(where={"agentId": agent_id, "status": "in-progress"})


async def list_inprogress_rooms(agent_id: str) -> set:
    """Return the room names of this agent's in-progress calls."""
    try:
        rows = await get_prisma().call.find_many(
            where={"agentId": agent_id, "status": "in-progress"}
        )
    except Exception:
        return set()
    return {c.room for c in rows if c.room}


async def count_live_calls(agent_id: str, active_rooms: Optional[set]) -> int:
    """Count *actually live* concurrent calls for an agent.

    When LiveKit is unreachable (`active_rooms is None`) we fall back to the DB
    in-progress count so the gate never lets everything through. When LiveKit IS
    reachable (even if there are legitimately zero live rooms -> empty set), we use
    the real live count and only count in-progress calls whose room still has
    participants.
    """
    if active_rooms is None:
        # LiveKit unreachable — fall back to the conservative DB in-progress count.
        return await count_active_calls(agent_id)
    # LiveKit reachable: count only in-progress calls whose room is genuinely live
    # with participants. An empty set means "no live rooms", so the count is 0.
    rooms = await list_inprogress_rooms(agent_id)
    return len(rooms & active_rooms)


def _call_age_minutes(c) -> float:
    try:
        started = datetime.strptime(c.startedAt, "%Y-%m-%d %H:%M")
    except Exception:
        return 0.0
    return (datetime.now() - started).total_seconds() / 60.0


async def fail_stale_calls(stale_minutes: int = 15, active_rooms: Optional[set] = None,
                           grace_minutes: int = 3) -> int:
    """Mark stuck 'in-progress' calls as 'failed'.

    Two safe rules, chosen so we never kill a genuinely live call:
      * If `active_rooms` is provided (LiveKit reachable): fail an in-progress call
        only when its room no longer has participants AND the call is older than
        `grace_minutes` (a freshly-dispatched call whose agent is still joining is
        protected). A long, active call keeps its live room, so it is never failed.
      * If `active_rooms` is None (LiveKit unreachable): fall back to age-based
        (`stale_minutes`) so stuck rows still get cleared.

    Returns how many calls were updated.
    """
    now = datetime.now()
    try:
        rows = await get_prisma().call.find_many(where={"status": "in-progress"})
    except Exception:
        return 0
    updated = 0
    for c in rows:
        age = _call_age_minutes(c)
        if active_rooms is not None:
            # Real (LiveKit-aware) check: room no longer live AND not too fresh.
            if c.room and c.room in active_rooms:
                continue  # still a live call — never touch it
            if age < grace_minutes:
                continue  # freshly dispatched; give the agent time to join
        else:
            # Conservative fallback: only clear genuinely old rows.
            if age < stale_minutes:
                continue
        try:
            await get_prisma().call.update(
                where={"id": c.id},
                data={"status": "failed", "endedAt": now.strftime("%Y-%m-%d %H:%M")},
            )
            updated += 1
        except Exception:
            pass
    return updated


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
    u = await db.user.find_unique(where={"id": user_id})
    if not u:
        raise ValueError("user not found")
    new_balance = round((u.walletBalance or 0) + amount, 2)
    await db.user.update(where={"id": user_id}, data={"walletBalance": new_balance})
    await db.transaction.create(
        data={"userId": user_id, "kind": "recharge", "amount": amount, "note": "Top-up", "ts": _ts()}
    )
    return await get_wallet(user_id)


async def deduct(user_id: str, amount: float, note: str = "") -> dict:
    db = get_prisma()
    u = await db.user.find_unique(where={"id": user_id})
    if not u:
        raise ValueError("user not found")
    new_balance = round(max((u.walletBalance or 0) - amount, 0.0), 2)
    await db.user.update(where={"id": user_id}, data={"walletBalance": new_balance})
    await db.transaction.create(
        data={"userId": user_id, "kind": "spend", "amount": -amount, "note": note, "ts": _ts()}
    )
    return await get_wallet(user_id)


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
