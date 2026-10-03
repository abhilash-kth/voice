"""Shared telephony plumbing: SDK timeout wrapper, credentials check,
room naming and room metadata builders. Extracted from telephony.py.
"""
from __future__ import annotations


import asyncio
import uuid
import logging
from datetime import timedelta
from typing import Any, Optional

from ..config import (
    LIVEKIT_URL,
    LIVEKIT_API_KEY,
    LIVEKIT_API_SECRET,
    DEFAULT_SIP_TRUNK_ID,
)

logger = logging.getLogger("voice-agent-saas-telephony")

AGENT_NAME = "voice-agent-saas"



async def _lk(coro: Any, timeout: float, op: str) -> Any:
    """Run a LiveKit API call with a hard timeout.

    Without this, a slow/unreachable LiveKit server (e.g. the PC losing reach to
    the cloud SFU) hangs the *caller* of the call forever: start_call never
    returns, the worker's call-end cleanup never completes, and the worker
    process stays busy — so the NEXT call is dispatched to nobody and the room
    goes silent. TimeoutError is raised to the caller so it can surface a real
    error instead of an endless spinner.
    """
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError:
        raise TimeoutError(
            f"{op} timed out after {timeout:.0f}s (LiveKit server unreachable or overloaded)"
        )

def _req_creds() -> None:
    if not (LIVEKIT_API_KEY and LIVEKIT_API_SECRET):
        raise RuntimeError("LIVEKIT_API_KEY / LIVEKIT_API_SECRET not configured")

def make_room_name() -> str:
    return f"saas-{uuid.uuid4().hex[:10]}"

def _metadata(agent_id: str, mode: str, phone: str = "", call_id: str = "",
              user_id: str = "", lead_data: Optional[dict] = None) -> str:
    import json
    return json.dumps({
        "agent_id": agent_id,
        "mode": mode,
        "phone": phone,
        "call_id": call_id,
        "user_id": user_id,
        "lead_data": lead_data or None,   # for dynamic-script substitution in the worker
    })


# ---------------------------------------------------------------------------
# Browser mode: return a join token that also dispatches the agent into the room
# ---------------------------------------------------------------------------
