"""Reply-stall probe: watchdog that reports why an LLM reply never got
scheduled (authorized / never-scheduled / started / speech gates) and the
speech_created hook that remembers pending reply handles.

Extracted verbatim from `worker_entrypoint.py` (<=300-line rule).
"""
from __future__ import annotations

import asyncio
import logging
import time

logger = logging.getLogger("voice-agent-saas-worker")


def build_reply_stall_probe(session, agent_mode, state_tracker, call_closed,
                            closing_in_progress, closing_requested,
                            _schedule_no_response, _instrument_sync_callback):

    stall_probe = {"task": None, "gen": 0, "armed_for": "", "armed_ts": 0.0, "handle": None}

    def _reply_stall_snapshot() -> str:
        """Deep state dump of LiveKit's scheduling internals at wedge time.

        Distinguishes the three possible stuck points inside
        ``_pipeline_reply_task`` (all produce IDENTICAL silence in logs):
          A. handle never scheduled  -> scheduler didn't pop it (queue/starvation)
          B. scheduled+authorized but user-silence gate open/closed mismatch
          C. handle already interrupted (silent drop path)
        Read-only getattr everywhere; never raises — diagnostics must not
        change call behavior.
        """
        try:
            act = getattr(session, "_activity", None)
            if act is None:
                return "snapshot: activity=None"
            def _ev(e):
                try:
                    return e.is_set()
                except Exception:
                    return "?"
            def _fd(f):
                try:
                    return f.done()
                except Exception:
                    return "?"
            q = list(getattr(act, "_speech_q", None) or [])
            cs = getattr(act, "_current_speech", None)
            parts = [
                f"scheduling_paused={getattr(act, '_scheduling_paused', '?')}",
                f"new_turns_blocked={getattr(act, '_new_turns_blocked', '?')}",
                f"scheduler_task_done={_fd(getattr(act, '_scheduling_atask', None))}",
                f"queue_len={len(q)}",
                f"user_silence_event_set={_ev(getattr(act, '_user_silence_event', None))}",
                f"authorization_allowed={_ev(getattr(act, '_authorization_allowed', None))}",
                f"user_state={getattr(getattr(act, '_session', None), 'user_state', None)}",
            ]
            h = stall_probe.get("handle")
            for label, s in (("pending_reply", h), ("current_speech", cs)):
                if s is None:
                    parts.append(f"{label}=None")
                    continue
                parts.append(
                    f"{label}[id={getattr(s, 'id', '?')} scheduled={getattr(s, 'scheduled', '?')}"
                    f" interrupted={getattr(s, 'interrupted', '?')} done={s.done() if callable(getattr(s, 'done', None)) else '?'}"
                    f" scheduled_fut_done={_fd(getattr(s, '_scheduled_fut', None))}"
                    f" authorized={_ev(getattr(s, '_authorize_event', None))}"
                    f" generations_open={sum(0 if _fd(g) else 1 for g in (getattr(s, '_generations', None) or []))}]"
                )
            if q:
                parts.append("queued=" + ",".join(
                    f"(h={getattr(x[2], 'id', '?')},sched={getattr(x[2], 'scheduled', '?')},int={getattr(x[2], 'interrupted', '?')})"
                    for x in q[:5]
                ))
            age = time.time() - stall_probe.get("armed_ts", time.time())
            parts.append(f"seconds_since_final={age:.1f}")
            return "snapshot: " + " ".join(parts)
        except Exception as e:
            return f"snapshot: unavailable ({e!r})"

    def _cancel_stall_probe(reason: str = "progress"):
        t = stall_probe.get("task")
        stall_probe["gen"] = stall_probe.get("gen", 0) + 1
        if t is not None and not t.done():
            t.cancel()
            logger.debug(f"[REPLY_PROBE_CANCELLED] gen={stall_probe['gen']} reason={reason}")
        stall_probe["task"] = None

    async def _stall_probe_handler(gen: int):
        try:
            await asyncio.sleep(6.0)
        except asyncio.CancelledError:
            return
        if gen != stall_probe.get("gen"):
            return
        if call_closed["done"] or closing_in_progress["done"] or closing_requested["done"]:
            return
        cur = state_tracker.get("state")
        if cur in ("thinking", "speaking"):
            return
        since = time.time() - stall_probe.get("armed_ts", time.time())
        logger.error(
            f"🚨 [REPLY_STALLED] no agent thinking/speaking {since:.1f}s after user final "
            f"'{stall_probe.get('armed_for', '')[:60]}' (agent state={cur}). {_reply_stall_snapshot()}"
        )

    def _arm_stall_probe(text: str) -> None:
        if agent_mode == "announcement":
            return
        _cancel_stall_probe(reason="re-arm")
        stall_probe["gen"] = stall_probe.get("gen", 0) + 1
        gen = stall_probe["gen"]
        stall_probe["armed_for"] = text
        stall_probe["armed_ts"] = time.time()
        try:
            stall_probe["task"] = asyncio.ensure_future(_stall_probe_handler(gen))
        except Exception:
            stall_probe["task"] = None

    def _on_speech_created(ev) -> None:
        try:
            handle = getattr(ev, "speech_handle", None)
            if getattr(ev, "source", "") == "generate_reply":
                # remember the latest pending reply handle so the stall probe
                # can dump its exact wait-state (scheduled/authorized/gate)
                stall_probe["handle"] = handle
            logger.info(
                "🔊 [SPEECH_CREATED] id=%s source=%s user_initiated=%s",
                getattr(handle, "id", "?") if handle is not None else "?",
                getattr(ev, "source", "?"),
                getattr(ev, "user_initiated", "?"),
            )
        except Exception:
            pass

    session.on("speech_created", _instrument_sync_callback("speech_created", _on_speech_created))

    return {"arm": _arm_stall_probe, "cancel": _cancel_stall_probe}
