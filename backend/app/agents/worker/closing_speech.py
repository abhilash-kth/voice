"""Deterministic closing speech + LLM-silence fallback.

Extracted verbatim from `w_entrypoint.py` via call_closing.py (<=300-line
rule). Speaks the fixed goodbye, squelches pending fallback says, and arms
the LLM-silence watchdog. Cross-calls to the no-response watchdog are
late-wired exactly as they were in the original shared closure.
"""
from __future__ import annotations

import asyncio
import logging
import time


logger = logging.getLogger("voice-agent-saas-worker")
from .w_runtime import DEFAULT_FALLBACK_RESPONSE, LLM_FALLBACK_DELAY, _get_deterministic_closing


def build_closing_speech(ctx, session, cfg, agent_mode, turn_timing, usage,
                         closing_in_progress, closing_requested, closing_task_ref,
                         agent_holder, reply_tracker, call_closed, call_finished, late):
    # Late-bound: the no-response cancel is defined by the sibling watchdog
    # module (same shared-closure late binding as before).
    def _cancel_no_response(*a, **k):
        return late["cancel_no_response"](*a, **k)

    async def _do_deterministic_closing():
        # Prevent duplicate closings, but allow if already closing to ensure completion
        if closing_in_progress["done"]:
            logger.info("Deterministic closing already in progress — skipping duplicate")
            return
        closing_in_progress["done"] = True
        call_closed["done"] = True
        closing_requested["done"] = True
        _cancel_pending()
        _cancel_no_response()
        fb = reply_tracker.get("fallback_say")
        if fb is not None and not fb.done():
            fb.cancel()
        reply_tracker["fallback_say"] = None
        closing_msg = _get_deterministic_closing(cfg)
        try:
            usage["tts_chars"] += len(closing_msg)
            usage["transcripts"].append({"role": "agent", "text": closing_msg})
            logger.info(f"👋 Deterministic closing: {closing_msg} — will play fully then auto-cut")
            # Mark timestamp so end_call tool knows closing was already spoken
            try:
                ag = agent_holder.get("agent")
                if ag is not None:
                    setattr(ag, '_last_deterministic_closing_ts', time.time())
                    if hasattr(ag, 'cfg'):
                        setattr(ag.cfg, '_last_closing_ts', time.time())
                    # Also store on global ref for agent_builder
                    setattr(ag, '_closing_msg', closing_msg)
            except Exception:
                pass
            # Interrupt any ongoing LLM/TTS generation to prioritize goodbye
            try:
                session.interrupt()
                await asyncio.sleep(0.15)
            except Exception:
                pass
            # Speak deterministic closing — MUST complete before shutdown
            try:
                await asyncio.wait_for(session.say(closing_msg, allow_interruptions=False), timeout=20)
                logger.info(f"✅ Deterministic closing TTS completed: {closing_msg}")
            except asyncio.TimeoutError:
                logger.warning(f"⏱️ Deterministic closing TTS timed out after 20s: {closing_msg}")
            except Exception as e:
                # Transport closed is expected if frontend already left, but try to still log
                if "transport is closed" in str(e).lower() or "no stream" in str(e).lower():
                    logger.warning(f"⚠️ Transport closed during closing TTS (frontend may have left early), but message was: {closing_msg} — will still shutdown after delay: {e}")
                else:
                    logger.warning(f"Deterministic closing say failed: {e}")
            # Critical: wait for audio to flush to frontend before cutting
            # 2.5s ensures TTS audio packet fully delivered even on slow network
            await asyncio.sleep(2.5)
        except asyncio.CancelledError:
            logger.info("Deterministic closing cancelled")
            return
        except Exception as e:
            logger.warning(f"Deterministic closing outer failed: {e}")
            await asyncio.sleep(1.0)
        logger.info("[CALL_END_REQUESTED] source=agent reason=completed")
        logger.info("✂️ Auto-cutting call after deterministic closing TTS")
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

    def _schedule_deterministic_closing():
        if agent_mode == "announcement":
            return
        if closing_in_progress["done"]:
            return
        if closing_task_ref["task"] is not None and not closing_task_ref["task"].done():
            return
        try:
            closing_task_ref["task"] = asyncio.ensure_future(_do_deterministic_closing())
        except Exception as e:
            logger.warning(f"Could not schedule deterministic closing: {e}")

    def _cancel_pending():
        t = reply_tracker["pending"]
        if t is not None:
            t.cancel()
            reply_tracker["pending"] = None

    def _mark_reply(ts: float):
        reply_tracker["last_assistant_ts"] = ts
        _cancel_pending()
        fallback_task = reply_tracker.get("fallback_say")
        if fallback_task is not None and not fallback_task.done():
            fallback_task.cancel()
        reply_tracker["fallback_say"] = None

    def _spawn_say(text_to_say: str):
        async def _say():
            try:
                await asyncio.wait_for(session.say(text_to_say, allow_interruptions=True), timeout=15)
            except asyncio.CancelledError:
                return
            except Exception as e:
                # str(e) is EMPTY for asyncio.TimeoutError — log the type so a
                # 15s session.say hang is diagnosable ("fallback say failed: " blank).
                logger.warning(f"🛟 fallback say failed: {type(e).__name__}: {e!r}")
        try:
            old = reply_tracker.get("fallback_say")
            if old is not None and not old.done():
                old.cancel()
            reply_tracker["fallback_say"] = asyncio.ensure_future(_say())
        except Exception as e:
            logger.warning(f"🛟 could not schedule fallback reply: {e}")

    async def _silence_fallback(turn_ts: float):
        try:
            await asyncio.sleep(LLM_FALLBACK_DELAY)
        except asyncio.CancelledError:
            return
        finally:
            if reply_tracker["pending"] is asyncio.current_task():
                reply_tracker["pending"] = None
        if reply_tracker["last_assistant_ts"] >= turn_ts or closing_requested["done"]:
            return  # closing turns must never receive a delayed fallback
        # REAL-stream markers (immediate) vs conversation_item_added (lags 5-15s
        # on reasoning-tool models like gpt-5-nano): _mark_reply only fires from
        # item_added, so a reply that already generated and STARTED PLAYING was
        # still getting an apology over it (2026-09-19 04:19: real answer played
        # at +3.3s, 'Sorry, technical problem' followed at +15s). If this turn's
        # LLM request exists and any immediate marker is set, the reply is alive.
        try:
            _rs = turn_timing.get("request_start", 0)
            if _rs and _rs >= turn_ts - 2:
                _m = max(
                    turn_timing.get("first_token", 0), turn_timing.get("tts_request", 0),
                    turn_timing.get("first_tts_audio", 0), turn_timing.get("first_audio", 0),
                )
                if _m >= _rs:
                    logger.info("🛟 silence watchdog suppressed: reply already streaming/speaking per REAL stream markers (item_added lag)")
                    return
        except Exception:
            pass
        # Barge-in-aware suppression (2026-09-24, "it should also listen"):
        # this exact apology was spoken OVER the caller right after a
        # greeting-cancel + interrupted-generation cascade (01:55:41.875 —
        # caller heard 'Sorry, temporary technical problem' while still
        # talking, and then asked the agent what the problem was). If a
        # barge-in/greeting-interrupt just happened, or the caller's speech
        # onset is <1.2s old (they may still be mid-sentence), SILENCE is the
        # correct behavior — their next FINAL re-arms everything normally.
        # Only this apology is suppressed; the 30s no-response watchdog and
        # every other path are untouched.
        try:
            _nowfb = time.time()
            _gb_age = _nowfb - float(turn_timing.get("greeting_bargein_ts", 0) or 0)
            _bb_age = _nowfb - float(turn_timing.get("last_bargein_ts", 0) or 0)
            if _gb_age < LLM_FALLBACK_DELAY + 1.0 or _bb_age < 1.2:
                logger.info(
                    "🛟 fallback suppressed: recent interrupt (greeting-barge %.1fs ago, any-barge %.1fs ago) — listening, not speaking over the caller",
                    _gb_age if _gb_age < 1e9 else -1, _bb_age if _bb_age < 1e9 else -1,
                )
                return
        except Exception:
            pass
        logger.warning(
            f"🛟 No LLM reply within {LLM_FALLBACK_DELAY:.0f}s of the user's turn "
            "(rate-limited 429 or failed generation) — speaking a fallback line "
            "so the call is not silent."
        )
        _spawn_say(getattr(cfg, "fallback_response", "").strip() or DEFAULT_FALLBACK_RESPONSE)

    def _schedule_silence_fallback(turn_ts: float):
        _cancel_pending()
        try:
            reply_tracker["pending"] = asyncio.ensure_future(_silence_fallback(turn_ts))
        except Exception as e:
            reply_tracker["pending"] = None
            logger.warning(f"🛟 could not arm silence watchdog: {e}")

    # ---------- No-response handling — robust scheduled timer ----------

    return {
        "do_closing": _do_deterministic_closing,
        "schedule_closing": _schedule_deterministic_closing,
        "cancel_pending": _cancel_pending,
        "mark_reply": _mark_reply,
        "spawn_say": _spawn_say,
        "silence_fallback": _silence_fallback,
        "schedule_silence_fallback": _schedule_silence_fallback,
    }
