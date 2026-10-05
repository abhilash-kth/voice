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
