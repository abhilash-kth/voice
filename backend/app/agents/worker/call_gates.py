"""Pre-call gates: monthly subscription check that blocks the call with a
user-facing failure reason before any audio runs.

Extracted verbatim from `worker_entrypoint.py` (<=300-line rule); the inline
`return` on a blocked call is communicated as `True` ("aborted") instead.
"""
from __future__ import annotations

import logging

from .runtime_env import _mark_call_failed

logger = logging.getLogger("voice-agent-saas-worker")


async def subscription_call_gate(ctx, user_id, call_id) -> bool:
    """Returns True when the call is blocked (caller should return early)."""
    # No active subscription (or past_due) → no calls. The call row is marked
    # failed with a user-facing reason; the call is never billed.
    try:
        from app.services import subscription_service as _subs
        _gate_reason = await _subs.call_gate(user_id) if user_id else None
    except Exception as _ge:
        _gate_reason = None
        logger.debug(f"subscription gate check failed (allowing call): {_ge!r}")
    if _gate_reason:
        logger.warning("[CALL_BLOCKED] room=%s user=%s reason=%s", getattr(ctx.room, "name", ""), user_id, _gate_reason)
        try:
            await _mark_call_failed(call_id, _gate_reason)
        except Exception:
            pass
        try:
            ctx.shutdown()
        except Exception:
            pass
        return True
    return False
