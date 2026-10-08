"""No-response watchdog: if the caller stays silent past the configured
timeout, speaks the no-response message deterministically and hangs up.

Extracted verbatim from `worker_entrypoint.py` via call_closing.py (<=300-line
rule). Cross-calls (pending-reply cancel) are late-wired as before.
"""
from __future__ import annotations

import asyncio
import logging
import time


logger = logging.getLogger("voice-agent-saas-worker")

def build_no_response_watchdog(ctx, session, cfg, agent_mode, state_tracker,
                               usage, no_response_state, call_closed, call_finished,
                               closing_in_progress, closing_requested, agent_holder,
                               reply_tracker, late):
    # Late-bound: pending-reply cancellation lives in the closing-speech module.
    def _cancel_pending(*a, **k):
        return late["cancel_pending"](*a, **k)

    def _cancel_no_response(reason: str = "cancel"):
        t = no_response_state.get("task")
        no_response_state["gen"] = no_response_state.get("gen", 0) + 1  # stale-task guard
        if t is not None and not t.done():
            t.cancel()
            logger.info(f"⏱️ [WATCHDOG_CANCELLED] gen={no_response_state['gen']} reason={reason}")
        no_response_state["task"] = None

    async def _no_response_timeout_handler(gen: int):
        idle_timeout = max(15, int(getattr(cfg, "no_response_timeout_seconds", 30) or 30))
        no_response_msg = (getattr(cfg, "no_response_message", "") or
                           "I did not hear a response, so I will end the call now. Thank you for calling.").strip()
        try:
            await asyncio.sleep(idle_timeout)
        except asyncio.CancelledError:
            return
        # Stale-window guard: if this handler was re-armed/cancelled while it
        # slept, its generation no longer matches — never act on old windows.
        if gen != no_response_state.get("gen"):
            return
        if call_closed["done"] or closing_in_progress["done"] or closing_requested["done"] or no_response_state.get("triggered"):
            return
        ag = agent_holder.get("agent")
        if ag is not None and getattr(ag, "_opening_started", False) and not getattr(ag, "_opening_done", False):
            logger.info("⏱️ No-response timer fired during the opening line — not interrupting it")
            _schedule_no_response()
            return
        elapsed = time.time() - no_response_state.get("last_activity", 0)
        # Defensive double-check against the per-final activity clock: if the
        # user spoke during the sleep window, skip AND re-arm a full window
        # (the old code returned without re-arming, silently disabling the
        # watchdog for the remainder of the call).
        if elapsed < idle_timeout - 0.5:
            logger.info(f"⏱️ No-response timer fired but user spoke {elapsed:.1f}s ago (timeout {idle_timeout}s) — skipping and re-arming")
            _schedule_no_response()
            return
        # Only trigger when waiting for user
        cur_state = state_tracker.get("state")
        if cur_state not in ("listening", None):
            logger.info(f"⏱️ No-response timer fired but state is {cur_state} (not listening) — rescheduling")
            _schedule_no_response()
            return
        no_response_state["triggered"] = True
        logger.info(f"⏱️ [WATCHDOG_FIRED] gen={gen} — no user response for {elapsed:.0f}s (timeout {idle_timeout}s)")
        # Mark call as closing to prevent re-arming watchdog on listening transition
        call_closed["done"] = True
        closing_in_progress["done"] = True
        logger.info(f"⏱️ No user response for {elapsed:.0f}s (timeout {idle_timeout}s) — speaking no-response message and ending call")
        try:
            _cancel_pending()
            fb = reply_tracker.get("fallback_say")
            if fb is not None and not fb.done():
                fb.cancel()
            reply_tracker["fallback_say"] = None
            try:
                session.interrupt()
                await asyncio.sleep(0.15)
            except Exception:
                pass
            usage["tts_chars"] += len(no_response_msg)
            usage["transcripts"].append({"role": "agent", "text": no_response_msg})
            logger.info(f"⏱️ No-response closing TTS: {no_response_msg} — will play fully then auto-cut")
            try:
                await asyncio.wait_for(session.say(no_response_msg, allow_interruptions=False), timeout=20)
                logger.info(f"✅ No-response TTS completed: {no_response_msg}")
            except asyncio.TimeoutError:
                logger.warning(f"⏱️ No-response TTS timed out after 20s: {no_response_msg}")
            except Exception as e:
                if "transport is closed" in str(e).lower() or "no stream" in str(e).lower():
                    logger.warning(f"⚠️ Transport closed during no-response TTS (frontend left early), but message was: {no_response_msg}: {e}")
                else:
                    logger.warning(f"No-response say failed: {e}")
            await asyncio.sleep(2.5)
        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.warning(f"No-response outer failed: {e}")
            await asyncio.sleep(1.0)
        logger.info("[CALL_END_REQUESTED] source=timeout reason=no_response")
        logger.info("✂️ Auto-cutting call after no-response TTS")
        try:
            session.shutdown(drain=False)
        except Exception:
            pass
        room_name = getattr(ctx.room, "name", None)
        if room_name:
            try:
                from app.telephony import end_active_room
                await end_active_room(room_name)
            except Exception:
                pass
        try:
            ctx.shutdown()
        except Exception:
            pass
        call_finished.set()

    def _schedule_no_response(reason: str = "re-arm"):
        # Announcement mode reads a script and hangs up. A silence timer would
        # interrupt that script or start a second goodbye.
        if agent_mode == "announcement":
            return
        if no_response_state.get("triggered") or call_closed["done"] or closing_in_progress["done"] or closing_requested["done"]:
            logger.info("⏱️ Not arming no-response — call already closing/triggered")
            return
        _cancel_no_response(reason=reason)
        idle_timeout = max(15, int(getattr(cfg, "no_response_timeout_seconds", 30) or 30))
        no_response_msg = (getattr(cfg, "no_response_message", "") or
                           "I did not hear a response, so I will end the call now. Thank you for calling.").strip()
        no_response_state["last_activity"] = time.time()
        no_response_state["gen"] = no_response_state.get("gen", 0) + 1
        gen = no_response_state["gen"]
        try:
            no_response_state["task"] = asyncio.ensure_future(_no_response_timeout_handler(gen))
            logger.info(f"⏱️ [WATCHDOG_ARMED] gen={gen} timeout={idle_timeout}s -> '{no_response_msg[:60]}'")
        except Exception as e:
            logger.warning(f"Could not arm no-response watchdog: {e}")

    return {
        "cancel": _cancel_no_response,
        "handler": _no_response_timeout_handler,
        "schedule": _schedule_no_response,
    }
