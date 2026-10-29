"""Agent-join watchdog for /api/calls (split from calls_routes.py; ≤300-line rule).

A room + dispatch being ACCEPTED by LiveKit is not the same as a worker actually
joining. This background task heals the classic dead/racing-worker case with one
explicit re-dispatch, then fails the call loudly (visible in the UI via the ~2s
waiting poll) instead of leaving the caller in a silent room.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time

from .. import repo
from .. import telephony

logger = logging.getLogger("voice-agent-saas-api")

_AGENT_JOIN_VERIFY_SECONDS = float(os.getenv("DISPATCH_VERIFY_SECONDS", "18"))
_SIP_CALLER_GONE_GRACE_SECONDS = max(
    1.0, min(12.0, float(os.getenv("SIP_CALLER_GONE_GRACE_SECONDS", "3"))))
_sip_caller_missing_since: dict[str, float] = {}


async def reconcile_sip_call(rec: dict) -> dict:
    """Terminalize a SIP call after its phone participant has left.

    The worker normally finalizes a caller disconnect itself, but the customer
    UI should not depend solely on that DB write: if the SIP participant is
    gone while the agent/room remains, the API closes the room (which lets the
    worker finish billing) and applies the same terminal mapping as the manual
    end endpoint. A short two-poll grace protects the brief dispatch/ringing
    window from a transient participant-list result.
    """
    if not rec:
        return rec
    call_id = rec.get("id") or ""
    if rec.get("mode") != "sip" or rec.get("status") not in (
            "planned", "in-progress"):
        if call_id:
            _sip_caller_missing_since.pop(call_id, None)
        return rec

    room = rec.get("room") or ""
    if not room:
        return rec

    state = await telephony.room_caller_state(room)
    if state is None:
        return rec  # LiveKit unknown — never guess that a live call ended.
    if state.get("has_caller"):
        _sip_caller_missing_since.pop(call_id, None)
        return rec

    now = time.monotonic()
    missing_since = _sip_caller_missing_since.setdefault(call_id, now)
    if now - missing_since < _SIP_CALLER_GONE_GRACE_SECONDS:
        return rec

    _sip_caller_missing_since.pop(call_id, None)
    # The worker may have finalized (or advanced) the row while LiveKit was
    # being inspected; never overwrite a newer terminal/billing state.
    try:
        latest = await repo.get_call(call_id, rec.get("user_id") or "")
    except Exception:
        latest = None
    if latest:
        if latest.get("status") not in ("planned", "in-progress"):
            return latest
        rec = latest

    room_deleted = False
    if state.get("exists", True):
        try:
            room_deleted = bool(await telephony.end_active_room(room))
        except Exception as e:
            logger.warning(
                "SIP caller-gone room close failed call=%s room=%s: %r",
                call_id, room, e)

    previous_status = rec.get("status")
    next_status = "failed" if previous_status == "planned" else "completed"
    patch = {
        "status": next_status,
        "ended_at": time.strftime("%Y-%m-%d %H:%M"),
    }
    if previous_status == "planned":
        usage = dict(rec.get("usage") or {})
        usage["error"] = (
            "the phone call ended before the agent joined — no charge")
        patch["usage"] = usage

    logger.info(
        "[CALL_ENDED] source=sip_caller_left call_id=%s room=%s "
        "previous_status=%s status=%s room_deleted=%s participants=%s",
        call_id, room, previous_status, next_status, room_deleted,
        state.get("participant_count", 0))
    updated = await repo.update_call(call_id, patch)
    return updated or {**rec, **patch}


async def reconcile_active_sip_calls(user_id: str,
                                     agent_id: str | None = None) -> list[dict]:
    """Reconcile and return one user's still-active SIP calls."""
    rows = await repo.list_calls(user_id, agent_id=agent_id)
    active: list[dict] = []
    for row in rows:
        if row.get("mode") != "sip" or row.get("status") not in (
                "planned", "in-progress"):
            continue
        updated = await reconcile_sip_call(row)
        if updated.get("status") in ("planned", "in-progress"):
            active.append(updated)
    return active


async def agent_join_watchdog(call_id: str, room: str, user_id: str,
                              agent_id: str, mode: str, phone: str) -> None:
    """Heal, then fail loudly, when the LiveKit dispatch never produces an agent.

    Room creation + agent dispatch succeeding only means the server ACCEPTED the
    dispatch — a worker still has to be OFFERED the job and join. Self-hosted
    LiveKit drops a dispatch when no worker is registered for the agent name at
    that moment (worker still booting, re-registering after a network blip, or
    stuck draining a previous call), and older servers do not retry it. So:

      1. ~8s with no agent in the room  → create the dispatch explicitly ONCE
         ([DISPATCH_RETRY]) — by then a freshly (re)started worker is registered,
         so this alone heals the classic "first click after worker restart".
      2. Still no agent after DISPATCH_VERIFY_SECONDS → mark the call `failed`
         with the real reason in `usage.error`. The UI polls the call row every
         ~2s while waiting, so the caller sees it far earlier than the old
         silent 30s timeout.

    One-shot by design: repeated re-dispatch against a genuinely dead worker
    changes nothing, so this is remediation, not a retry loop.
    """
    try:
        await asyncio.sleep(3.0)  # dispatch head start; the agent normally joins in 2-8s
        deadline = time.monotonic() + max(8.0, _AGENT_JOIN_VERIFY_SECONDS)
        retry_at = time.monotonic() + 5.0  # ~8s after the call was placed
        retried = False
        while time.monotonic() < deadline:
            try:
                row = await repo.get_call(call_id, user_id)
            except Exception:
                return
            if not row or row.get("status") not in ("planned", "in-progress"):
                return  # already completed/failed — user ended it or the worker did
            joined = await telephony.room_agent_joined(room)
            if joined is True:
                logger.info("[AGENT_JOIN_VERIFIED] room=%s call=%s", room, call_id)
                return
            if not retried and time.monotonic() >= retry_at:
                retried = True
                meta = telephony._metadata(agent_id, mode, phone or "", call_id, user_id)
                dispatch_id = await telephony.create_agent_dispatch(room, meta)
                logger.warning(
                    "[DISPATCH_RETRY] room=%s call=%s: no agent after ~8s, one-shot "
                    "explicit dispatch %s (worker now registered?)",
                    room, call_id, dispatch_id or "FAILED",
                )
                if dispatch_id:
                    deadline += 8.0  # graceful slack for the re-dispatch to land
            await asyncio.sleep(2.0)

        # Final re-check before failing (the agent may have joined during the
        # last sleep and flipped the row already).
        try:
            row = await repo.get_call(call_id, user_id)
        except Exception:
            return
        if not row or row.get("status") not in ("planned", "in-progress"):
            return
        reason = (
            f"the agent did not join the room within {int(max(8.0, _AGENT_JOIN_VERIFY_SECONDS))} seconds — "
            "the agent worker is not picking up the dispatch. Make sure exactly ONE agent worker is running "
            "(python -m app.agents.worker), that no old worker window is still open, and that the worker is "
            "connected to the LiveKit server; then try again."
        )
        logger.error("[AGENT_JOIN_TIMEOUT] room=%s call=%s: %s", room, call_id, reason)
        try:
            await repo.update_call(call_id, {
                "status": "failed",
                "ended_at": time.strftime("%Y-%m-%d %H:%M"),
                "usage": {"error": reason},
            })
        except Exception as e:
            logger.warning("could not mark call %s failed after agent-join timeout: %r", call_id, e)
    except Exception as e:
        logger.debug("agent-join watchdog stopped early for call %s: %r", call_id, e)
