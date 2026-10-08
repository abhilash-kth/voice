"""conversation_item_added hook: reply/fallback tracking, closing detection,
token/conversation accounting, watchdog resets on agent activity.

Extracted verbatim from `w_entrypoint.py` (<=300-line rule). Behaviour
identical to the previous inline `on_item_added`.
"""
from __future__ import annotations

import logging
import time

from .user_turn_items import process_user_turn_item
from .w_runtime import (
    DETERMINISTIC_CLOSING_MESSAGE, DETERMINISTIC_CLOSING_MESSAGE_EN,
    FALLBACK_REPLY, _item_is_tool_related, _msg_text, clean_reply_text,
)

logger = logging.getLogger("voice-agent-saas-worker")


def attach_conversation_items(session, cfg, agent_mode, turn_timing, usage,
                               call_closed, closing_in_progress, closing_requested,
                               no_response_state, reply_tracker, last_user_transcript,
                               _schedule_no_response, _schedule_silence_fallback,
                               _cancel_pending, _mark_reply,
                               _schedule_deterministic_closing,
                               _instrument_sync_callback):

    def on_item_added(ev):
        # Allow system closing/no-response messages even after call_closed is set
        # to ensure transcript logging works; otherwise early return hides TTS log
        try:
            _item_role = getattr(getattr(ev, "item", None), "role", None)
            # P4 chain marker: proves on_user_turn_completed's chat-context
            # insert ran (reply pipeline alive past scheduling).
            _it = getattr(ev, "item", None)
            _tx = _msg_text(_it) if _it is not None else ""
            logger.info("💬 [CONVERSATION_ITEM] role=%s len=%d text='%s'", _item_role, len(_tx or ""), (_tx or "")[:60])
        except Exception:
            _item_role = None
        if call_closed["done"] and _item_role != "assistant" and not no_response_state.get("triggered"):
            return
        if call_closed["done"] and _item_role == "assistant":
            # Still process if it's system closing (triggered flag) — otherwise skip LLM chatter after close
            if not (no_response_state.get("triggered") or closing_in_progress["done"]):
                return
        item = getattr(ev, "item", None)
        role = getattr(item, "role", None)
        text = _msg_text(item)
        if role == "user":
            process_user_turn_item(
                role, text, turn_timing, usage, last_user_transcript,
                closing_requested, reply_tracker, _schedule_silence_fallback,
                _schedule_deterministic_closing, _schedule_no_response, _cancel_pending)
        elif role == "assistant":
            # Post-barge-in clarity (00:53:35.857 log): when an interrupted
            # generation still yields an assistant item, LiveKit commits ONLY
            # the audio actually played before the interrupt (truncated text).
            # That is correct library semantics — flag it so the log reads
            # intentionally, not like a missed cancellation.
            try:
                if (time.time() - float(turn_timing.get("last_bargein_ts", 0.0))) < 1.5:
                    logger.info("ℹ️ assistant item committed after a barge-in — truncated to played audio per LiveKit semantics (generation=%s)", turn_timing.get("gen", 0))
            except Exception:
                pass
            # Mark assistant output received for empty-turn race fix
            turn_timing["assistant_output_received"] = True
            # Preserve last successful turn metrics for final billing
            try:
                if turn_timing.get("ttft_ms",0) > 0:
                    turn_timing["last_ttft"] = turn_timing.get("ttft_ms",0)
                if turn_timing.get("generation_time_ms",0) > 0:
                    turn_timing["last_gen_time"] = turn_timing.get("generation_time_ms",0)
                turn_timing["last_input"] = turn_timing.get("input_tokens",0)
                turn_timing["last_output"] = turn_timing.get("output_tokens",0)
                turn_timing["last_cached"] = turn_timing.get("cached_input_tokens",0)
                turn_timing["last_provider"] = turn_timing.get("llm_provider","")
                turn_timing["last_model"] = turn_timing.get("llm_model","")
            except Exception:
                pass
            
            # Log raw assistant item for debugging empty turns
            raw_text = _msg_text(item)
            is_tool = _item_is_tool_related(item)
            if is_tool:
                logger.info(f"🔧 Assistant item is tool-related, skipping TTS (role={role}, text_len={len(raw_text)}, attrs={[a for a in ('function_call','tool_call','tool_calls') if getattr(item,a,None)]})")
                return
            now = time.time()
            if not text.strip():
                # FIX: Don't treat deterministic closing as empty failure
                if turn_timing.get("is_closing", False):
                    logger.info(f"👋 Deterministic closing in progress, empty assistant item is intentional (is_closing=True), not failure")
                    return
                # Check if LLM still active - if so, don't treat as empty yet
                if turn_timing.get("llm_active", False):
                    logger.info(f"⏳ LLM still active (request_start {now-turn_timing.get('request_start',now):.2f}s ago), empty assistant item ignored, waiting for stream")
                    return
                # Detailed logging for empty LLM turn root cause - only when stream terminated
                logger.warning(f"🧮 LLM produced an empty assistant item after stream terminated (raw_len={len(raw_text)}, role={role}, text_content={getattr(item,'text_content',None)}, content={getattr(item,'content',None)}); waiting for speakable reply. Possible 404/429 or filtered. llm_active={turn_timing.get('llm_active')} gen_complete={turn_timing.get('generation_complete')} is_closing={turn_timing.get('is_closing',False)}")
                # Also log timing for empty turn diagnostics
                if turn_timing.get("llm_start",0) > 0:
                    logger.warning(f"⏱️ Empty turn timing: llm_start->now {(now-turn_timing['llm_start'])*1000:.0f}ms, speech_end->now {(now-turn_timing.get('speech_end',now))*1000:.0f}ms active={turn_timing.get('llm_active')}")
                return
            _mark_reply(now)
            # Reset no-response timer when agent speaks - timeout starts after agent finishes
            no_response_state["last_activity"] = now
            cleaned = clean_reply_text(text)
            if (
                cleaned == FALLBACK_REPLY
                and text.strip()
                and turn_timing.get("gov_turn_state") == "ack"
            ):
                # Deterministic ack replies ("जी।") are INTENTIONALLY 3-4 chars;
                # the "< 4 chars => fallback" rule in clean_reply_text must not
                # rewrite them into the apology (00:31:31 log did exactly that:
                # llm_node answered 'Ok.' with 'जी।' and the caller heard
                # "Sorry, mujhe yeh samajh nahi aaya" instead).
                cleaned = text.strip()
            # Never let the LLM close a call on its own. Models sometimes emit
            # a farewell after ambiguous STT fragments such as "company go".
            # Only transcript-level explicit intent may produce a closing TTS.
            # EXEMPT system-initiated messages: no-response and deterministic closing
            # must never be suppressed (they contain "thank you for calling").
            is_system_closing = False
            try:
                sys_closing_msgs = [
                    DETERMINISTIC_CLOSING_MESSAGE,
                    DETERMINISTIC_CLOSING_MESSAGE_EN,
                    (getattr(cfg, "no_response_message", "") or "").strip(),
                ]
                # also check configured message truncated log comparison
                if any(cleaned == m or text.strip() == m for m in sys_closing_msgs if m):
                    is_system_closing = True
                if no_response_state.get("triggered") or closing_in_progress["done"] or closing_requested["done"]:
                    # If we are already in closing/no-response flow, allow any farewell
                    is_system_closing = True
            except Exception:
                pass
            latest_user = last_user_transcript["text"].lower()
            explicit_end = any(term in latest_user for term in (
                "goodbye", "good bye", "bye", "hang up", "cut the call",
                "disconnect", "end the call", "thank you", "thankyou", "bye bye",
                "ok bye", "okay bye", "कॉल कट", "call काट", "कॉल काट",
                "call cut कर दीजिए", "call काट दीजिए", "कॉल बंद कर दीजिए",
                "फोन काट दीजिए",
                # Same hang-up / nothing-needed additions as closing_substrings
                "फोन रख", "फ़ोन रख", "phone रख", "call रख", "कॉल रख",
                "phone rakh", "कुछ भी नहीं चाहिए", "जानकारी नहीं चाहिए",
                "kuch bhi nahi chahiye", "koi jaankari nahi chahiye"
            ))
            if not is_system_closing and not explicit_end and any(term in cleaned.lower() for term in ("goodbye", "good bye", "thank you for calling")):
                logger.warning("🛡️ Suppressed model farewell without explicit caller goodbye")
                cleaned = "Ji, batayiye, aapko kis tarah ki madad chahiye?"
            if cleaned == FALLBACK_REPLY and text.strip() != FALLBACK_REPLY:
                # The model returned something but we flagged it as a fallback —
                # surface the raw text so we can see WHY.
                logger.warning(f"🧮 LLM reply flagged as fallback. RAW: {text!r}")
            usage["tts_chars"] += len(cleaned)
            # Only count LLM output in assistant mode; announcement plays a fixed
            # script with no LLM, so it must not be billed for LLM tokens.
            if agent_mode != "announcement":
                words = max(len(cleaned.split()), 1)
                usage["llm_output_tokens"] += int(words * 1.3)
            usage["transcripts"].append({"role": "agent", "text": cleaned})
            # --- Production timing: LLM complete - FIXED 6-9s delay ---
            # Previous bug: conversation_item_added (llm_complete) fired 6-9s after first_token,
            # even though REAL stream already completed in 1.0-1.2s and first_audio at 1.3-1.6s.
            # This caused duplicate completion path and misleading first_token->llm_complete 6735ms logs.
            # Fix: Authoritative completion is generation_complete from wrapper (REAL stream), not llm_complete from conversation_item_added.
            # conversation_item_added is delayed (after TTS speaking), so we should NOT treat it as authoritative for latency.
            # Only set llm_complete if REAL audio not yet happened, and don't log fallback if REAL already happened.
            now_llm_complete = time.time()
            # REAL audio only counts when the TTS wrapper (or the audio
            # listener) stamped it; the assistant conversation-item event is
            # transcript lag and must never masquerade as "audio" (the old
            # last_speech_end_to_first_audio in this expression made every turn
            # after the first inherit a bogus "REAL audio at 11431ms").
            has_real_audio = turn_timing.get("first_audio", 0) > 0 or turn_timing.get("first_tts_audio", 0) > 0
            
            # Only set llm_complete if not already set AND real audio not yet happened (avoid delayed overwrite)
            if turn_timing.get("llm_complete", 0) == 0 and not has_real_audio:
                turn_timing["llm_complete"] = now_llm_complete
                if turn_timing["first_token"] > 0:
                    logger.info(f"⏱️ TIMING first_token->llm_complete (LLM full response): {(now_llm_complete-turn_timing['first_token'])*1000:.0f}ms (authoritative if no REAL audio yet)")
                if turn_timing["llm_start"] > 0:
                    logger.info(f"⏱️ TIMING llm_start->llm_complete: {(now_llm_complete-turn_timing['llm_start'])*1000:.0f}ms")
                if turn_timing["speech_end"] > 0:
                    logger.info(f"⏱️ TIMING speech_end->llm_complete: {(now_llm_complete-turn_timing['speech_end'])*1000:.0f}ms (NOTE: REAL audio via TTS wrapper is authoritative)")
            elif has_real_audio:
                # REAL audio already happened at 1.3-1.6s, this llm_complete is delayed 6-9s, don't treat as authoritative
                if turn_timing["first_token"] > 0:
                    delay = (now_llm_complete - turn_timing["first_token"]) * 1000
                    if delay > 5000:
                        logger.info(f"ℹ️ Delayed conversation_item_added {delay:.0f}ms after first_token (REAL audio already measured) - not authoritative, REAL stream is authoritative")
                # Don't overwrite llm_complete if already set from REAL path
                if turn_timing.get("llm_complete", 0) == 0:
                    turn_timing["llm_complete"] = now_llm_complete
            
            # TTS is intentionally left unwrapped (so the greeting can play
            # immediately), so most turns never get an audio timestamp. The
            # numbers below then measure when the assistant's *transcript item*
            # was committed — NOT when audio started. (Real human-perceived
            # speech start is visible from [AGENT_STATE] -> speaking.) Never
            # label these as first_audio again: turn 23:35:57 logged a bogus
            # "first audio at 12015ms" that was pure item_added lag.
            if turn_timing.get("first_tts_audio", 0) == 0 and turn_timing.get("first_audio", 0) == 0 and not has_real_audio:
                if turn_timing["first_token"] > 0:
                    token_to_item = (now_llm_complete - turn_timing["first_token"]) * 1000
                    logger.info(f"⏱️ TIMING first_token->item_added (transcript lag, audio not measured): {token_to_item:.0f}ms")
                if turn_timing["speech_end"] > 0:
                    speech_to_item = (now_llm_complete - turn_timing["speech_end"]) * 1000
                    logger.info(f"⏱️ TIMING speech_end->item_added (transcript lag, audio not measured): {speech_to_item:.0f}ms")
                    if turn_timing["stt_final"] > 0 and turn_timing["turn_detected"] > 0 and turn_timing["llm_start"] > 0 and turn_timing["first_token"] > 0:
                        logger.info(
                            f"📊 TURN BREAKDOWN (to transcript item): speech_end->STT_final {(turn_timing['stt_final']-turn_timing['speech_end'])*1000:.0f}ms est | "
                            f"STT_final->turn {(turn_timing['turn_detected']-turn_timing['stt_final'])*1000:.0f}ms | "
                            f"turn->LLM {(turn_timing['llm_start']-turn_timing['turn_detected'])*1000:.0f}ms | "
                            f"LLM->first_token {(turn_timing['first_token']-turn_timing['llm_start'])*1000:.0f}ms | "
                            f"first_token->item_added {(now_llm_complete-turn_timing['first_token'])*1000:.0f}ms | "
                            f"TOTAL {speech_to_item:.0f}ms (audio start: see [AGENT_STATE] speaking)"
                        )
                    if turn_timing.get("tts_request", 0) == 0:
                        turn_timing["speech_end"] = 0.0
                        turn_timing["stt_final"] = 0.0
                        turn_timing["turn_detected"] = 0.0
                        turn_timing["stt_final_mono"] = 0.0
                        turn_timing["turn_commit_mono"] = 0.0
                        turn_timing["pipeline_stage"] = "user_speech"
                        turn_timing["llm_start"] = 0.0
                        turn_timing["request_start"] = 0.0
                        turn_timing["first_token"] = 0.0
                        turn_timing["tts_request"] = 0.0
                        turn_timing["first_tts_audio"] = 0.0
                        turn_timing["llm_complete"] = 0.0
                        turn_timing["generation_complete"] = 0.0
                        turn_timing["first_audio"] = 0.0
                        turn_timing["ttft_ms"] = 0.0
                        turn_timing["generation_time_ms"] = 0.0
            _real_audio_ms = turn_timing.get("last_speech_end_to_first_audio", 0)
            _real_note = f"REAL first audio at {_real_audio_ms:.0f}ms after speech_end (tts_node probe)" if _real_audio_ms else "no audio frame reached the tts_node this turn (silent turn or interrupted before speech)"
            logger.info(f"🗣️ TTS (LLM complete): {cleaned} (transcript-only event; {_real_note})")

    session.on("conversation_item_added", _instrument_sync_callback("conversation_item_added", on_item_added))
