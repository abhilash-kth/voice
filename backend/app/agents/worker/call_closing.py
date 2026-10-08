"""Closing / no-response / silence-fallback pipeline for a call.

Extracted verbatim from `worker_entrypoint.py` (<=300-line rule). Contains the
deterministic closing speak + booking, the LLM-silence fallback watchdog,
the no-response (caller stayed quiet) watchdog, and room/session close
handlers. Behaviour is identical to the previous inline implementation.
"""
from __future__ import annotations

import asyncio
import logging
import time

logger = logging.getLogger("voice-agent-saas-worker")

from .closing_speech import build_closing_speech
from .no_response_watchdog import build_no_response_watchdog
from .runtime_env import DEFAULT_FALLBACK_RESPONSE, LLM_FALLBACK_DELAY


def build_closing_pipeline(ctx, session, cfg, agent_mode, turn_timing,
                           state_tracker, usage, _loop_sampler_stop, late):
    """Wire closing + watchdog handlers; returns the shared state map."""

    # ------------------------------------------------------------------
    # Silence watchdog + No-response watchdog.
    #
    # 1) LLM silence: When the LLM 429s (Groq free-tier TPM limit) the fail-fast
    #    retry budget gives up in <1s and LiveKit logs the error but speaks
    #    NOTHING — caller left in dead air. So arm timer on every user turn,
    #    if no assistant reply within LLM_FALLBACK_DELAY, speak fallback.
    # 2) User silence: If user says nothing for no_response_timeout_seconds
    #    (configurable per agent, e.g. 30 sec), speak the agent's
    #    no_response_message and hang up. Requested by user.
    # ------------------------------------------------------------------
    # Late-bound: the reply-stall probe is defined further down (same
    # late binding as the original inline closure).
    def _cancel_stall_probe(*a, **k):
        return late["cancel_stall_probe"](*a, **k)

    call_finished = asyncio.Event()
    call_closed = {"done": False}
    closing_requested = {"done": False}
    closing_in_progress = {"done": False}
    closing_task_ref = {"task": None}
    agent_holder = {"agent": None}
    reply_tracker = {
        "last_user_ts": 0.0,
        "last_assistant_ts": 0.0,
        "empty_spoken": False,
        "pending": None,
        "fallback_say": None,
    }
    # No-response tracking: last time user spoke or agent spoke.
    # `gen` is a monotonically increasing arming generation: every (re)arm or
    # cancel bumps it and each scheduled handler captures its generation, so a
    # stale handler left over from an earlier window can NEVER fire after a
    # cancel/reset (P5: no false no-response while the caller is talking).
    no_response_state = {
        "last_activity": time.time(),
        "task": None,
        "triggered": False,
        "gen": 0,
    }

    @ctx.room.on("disconnected")
    def _on_room_disconnected(*_):
        logger.info("Room disconnected event received")
        _loop_sampler_stop.set()
        _ll = turn_timing.pop("_loop_lag_task", None)
        if _ll is not None:
            try:
                _ll.cancel()
            except Exception:
                pass
        try:
            _cancel_no_response(reason="call_end_room_disconnected")
            _cancel_stall_probe(reason="call_end_room_disconnected")
        except Exception:
            pass
        call_finished.set()

    @session.on("close")
    def _on_session_close(*_):
        logger.info("Session close event received")
        try:
            _cancel_no_response(reason="call_end_session_close")
            _cancel_stall_probe(reason="call_end_session_close")
        except Exception:
            pass
        call_finished.set()

    async def _on_job_shutdown(*_):
        call_finished.set()
        # P2: this job thread's event loop is about to close — release its
        # Prisma client (per-loop registry) so engine processes do not pile
        # up in the worker. Best-effort, never blocks shutdown.
        try:
            from app.db import release_current_loop
            await asyncio.wait_for(release_current_loop(), timeout=6)
        except Exception:
            pass

    ctx.add_shutdown_callback(_on_job_shutdown)

    speech = build_closing_speech(
        ctx, session, cfg, agent_mode, turn_timing, usage, closing_in_progress,
        closing_requested, closing_task_ref, agent_holder, reply_tracker,
        call_closed, call_finished, late)
    _do_deterministic_closing = speech["do_closing"]
    _schedule_deterministic_closing = speech["schedule_closing"]
    _cancel_pending = speech["cancel_pending"]
    _mark_reply = speech["mark_reply"]
    _schedule_silence_fallback = speech["schedule_silence_fallback"]

    noresp = build_no_response_watchdog(
        ctx, session, cfg, agent_mode, state_tracker, usage, no_response_state,
        call_closed, call_finished, closing_in_progress, closing_requested,
        agent_holder, reply_tracker, late)
    _cancel_no_response = noresp["cancel"]
    _schedule_no_response = noresp["schedule"]
    late["cancel_pending"] = _cancel_pending
    late["cancel_no_response"] = _cancel_no_response

    return {
        "call_finished": call_finished,
        "call_closed": call_closed,
        "closing_requested": closing_requested,
        "closing_in_progress": closing_in_progress,
        "closing_task_ref": closing_task_ref,
        "agent_holder": agent_holder,
        "reply_tracker": reply_tracker,
        "no_response_state": no_response_state,
        "cancel_no_response": _cancel_no_response,
        "cancel_pending": _cancel_pending,
        "mark_reply": _mark_reply,
        "schedule_silence_fallback": _schedule_silence_fallback,
        "schedule_deterministic_closing": _schedule_deterministic_closing,
        "schedule_no_response": _schedule_no_response,
    }
