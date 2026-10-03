"""Call records + the stale-call sweeper."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from ..db import get_prisma
from .common import _dump, _load_dict, _load_list


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


async def list_calls(user_id: str, agent_id: Optional[str] = None, limit: Optional[int] = None) -> list[dict]:
    where: dict = {"userId": user_id}
    if agent_id:
        where["agentId"] = agent_id
    find_args: dict = {"where": where, "order": {"startedAt": "desc"}}
    if limit is not None:
        find_args["take"] = limit
    rows = await get_prisma().call.find_many(**find_args)
    return [_call_dict(c) for c in rows]


async def get_call(call_id: str, user_id: str) -> Optional[dict]:
    c = await get_prisma().call.find_unique(where={"id": call_id})
    if not c or c.userId != user_id:
        return None
    return _call_dict(c)


async def delete_call(call_id: str, user_id: str) -> bool:
    existing = await get_call(call_id, user_id)
    if not existing:
        return False
    await get_prisma().call.delete(where={"id": call_id})
    return True


async def create_call(data: dict):
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
