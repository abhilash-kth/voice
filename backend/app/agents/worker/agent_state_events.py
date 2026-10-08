"""agent_state_changed hook: turn-timing bookkeeping and reply-stall /
empty-turn race handling driven by listening/thinking/speaking transitions.

Extracted verbatim from `w_entrypoint.py` (<=300-line rule). Identical
behaviour to the previous inline `_on_state`.
"""
from __future__ import annotations

import logging
import time

logger = logging.getLogger("voice-agent-saas-worker")


def attach_agent_state_events(session, state_tracker, turn_timing, call_closed,
                              closing_in_progress, closing_requested, no_response_state,
                              _cancel_no_response, _cancel_pending,
                              _schedule_no_response, late, _instrument_sync_callback):

    # Late-bound: stall-probe cancellation is defined further down in the
    # entrypoint (identical late binding to the previous inline closure).
    def _cancel_stall_probe(*a, **k):
        return late["cancel_stall_probe"](*a, **k)

    def _on_state(ev):
        turn_timing["agent_state"] = ev.new_state
        turn_timing["pipeline_stage"] = f"agent_state_{ev.new_state}"
        now = time.time()
        prev = state_tracker["state"]
        elapsed = now - state_tracker["since"]
        if prev == "thinking" and elapsed > 2.5:
            logger.warning(f"🐢 Slow turn: agent was in 'thinking' for {elapsed:.2f}s")
        logger.info(f"🔄 [AGENT_STATE] {prev} -> {ev.new_state} ({elapsed:.2f}s)")
        # Reply-stall probe: any forward progress into thinking/speaking means
        # the reply pipeline is alive — stand the diagnostic timer down.
        if ev.new_state in ("thinking", "speaking"):
            _cancel_stall_probe(reason=f"agent_state_{ev.new_state}")

        # --- Production timing instrumentation ---
        if prev == "listening" and ev.new_state == "thinking":
            # Turn detected: listening -> thinking = endpointing triggered
            # This is speech_end + VAD + endpointing + STT final -> LLM request path
            turn_timing["turn_detected"] = now
            turn_timing["turn_detected_mono"] = time.monotonic_ns()
            if turn_timing["stt_final"] > 0 and now >= turn_timing["stt_final"]:
                stt_to_turn = (now - turn_timing["stt_final"]) * 1000
                logger.info(f"⏱️ TIMING STT_final->turn_detected (endpointing): {stt_to_turn:.0f}ms")
                if stt_to_turn > 150:
                    logger.warning(f"🐢 Slow endpointing: STT_final->turn {stt_to_turn:.0f}ms exceeds 100ms target")
            else:
                logger.info("⏱️ TIMING STT_final->turn_detected (endpointing): N/A")
            if turn_timing["speech_end"] > 0:
                speech_to_turn = (now - turn_timing["speech_end"]) * 1000
                logger.info(f"⏱️ TIMING speech_end->turn_detected (VAD+STT+endpointing): {speech_to_turn:.0f}ms")
                if speech_to_turn > 700:
                    logger.warning(f"🐢 Slow turn detection: speech_end->turn {speech_to_turn:.0f}ms exceeds 500ms target (outlier!)")
            # Also log as LLM start (turn completed -> LLM request)
            turn_timing["llm_start"] = now
            if turn_timing["stt_final"] > 0 and now >= turn_timing["stt_final"]:
                stt_to_llm = (now - turn_timing["stt_final"]) * 1000
                logger.info(f"⏱️ TIMING STT_final->LLM_start: {stt_to_llm:.0f}ms (target ≤100ms)")
            else:
                logger.info("⏱️ TIMING STT_final->LLM_start: N/A")

        elif prev == "thinking" and ev.new_state == "speaking":
            # First token -> first audio: LLM first token arrived, TTS starting
            # FIX: Don't overwrite first_token if already set by LLM wrapper (authoritative TTFT)
            # Previous bug: wrapper set first_token at TTFT time (e.g. 772ms), then _on_state set it again at speaking time (1.07s),
            # causing first_token->llm_complete to be calculated from speaking time, not actual first_token, leading to 6-9s delay logs
            if turn_timing.get("first_token", 0) == 0:
                turn_timing["first_token"] = now
                turn_timing["first_token_mono"] = time.monotonic_ns()
                logger.info(f"ℹ️ first_token set from state thinking->speaking (no wrapper TTFT yet)")
            else:
                # first_token already set by wrapper at actual TTFT time, preserve it
                existing_age = (now - turn_timing["first_token"]) * 1000
                logger.info(f"ℹ️ first_token already set {existing_age:.0f}ms ago by wrapper (TTFT {turn_timing.get('ttft_ms',0):.0f}ms), preserving authoritative")
            
            if turn_timing["llm_start"] > 0:
                llm_to_token = (now - turn_timing["llm_start"]) * 1000
                logger.info(f"⏱️ TIMING LLM_start->first_token: {llm_to_token:.0f}ms (target ≤500ms) (wrapper TTFT {turn_timing.get('ttft_ms',0):.0f}ms is authoritative)")
            if turn_timing["speech_end"] > 0:
                speech_to_token = (now - turn_timing["speech_end"]) * 1000
                logger.info(f"⏱️ TIMING speech_end->first_token: {speech_to_token:.0f}ms (wrapper {turn_timing.get('ttft_ms',0):.0f}ms is authoritative)")

        elif prev == "thinking" and ev.new_state == "listening":
            # Empty turn: thinking->listening without speaking - FIXED RACE CONDITION + DETERMINISTIC CLOSING
            # FIX: is_closing=True must prevent Empty LLM turn detected from firing, closing 0/0 excluded from failed_requests
            if turn_timing.get("is_closing", False):
                logger.info(f"👋 Deterministic closing in progress (is_closing=True), thinking->listening {elapsed:.2f}s is intentional closing, not empty failure - suppressing warning")
                state_tracker["state"] = ev.new_state
                state_tracker["since"] = now
                return
            if turn_timing.get("gov_turn_state") == "suppress":
                # Incomplete fragment: llm_node deliberately produced nothing so
                # the caller can continue their sentence. Silence here is the
                # feature — do not run the empty-turn warning/fallback ladder.
                # The 15s silence fallback + 30s watchdog still recover the call
                # if the caller stops mid-thought.
                logger.info("⏸️ thinking->listening on an INCOMPLETE_TURN — staying silent, awaiting continuation")
                state_tracker["state"] = ev.new_state
                state_tracker["since"] = now
                return
            
            # Previous bug: detector fired before async LLM stream finished (0.04-0.08s)
            # Evidence: LLM REQUEST START, then thinking->listening 0.04s, then TTFT 800ms, then GENERATION COMPLETE
            # This means empty detection raced with active stream.
            # Fix: Only fire when LLM stream has actually terminated (llm_active False) AND no assistant output
            is_llm_active = turn_timing.get("llm_active", False)
            has_output = turn_timing.get("assistant_output_received", False) or turn_timing.get("first_token",0) > 0
            gen_complete = turn_timing.get("generation_complete",0)
            request_start = turn_timing.get("request_start",0)
            
            if is_llm_active:
                # LLM still streaming, don't treat as empty - this is the race fix
                # FIX: Don't update state_tracker to listening, keep thinking to prevent new REQUEST START while previous active
                # Previous bug: set state to listening even though LLM active, allowing new listening->thinking and second REQUEST START
                # This caused 0/0 failed requests (Request 1 and 5) even though preemptive disabled
                # New: keep state as thinking, don't allow new turn until LLM completes
                # request_start may be 0 (timing not yet stamped); guard so the
                # log doesn't print epoch seconds like "1789768698.62s ago".
                _rs_ago = now - request_start if request_start else 0.0
                logger.info(f"⏳ Ignoring thinking->listening (0.04s race): LLM still active request_start {_rs_ago:.2f}s ago, first_token={turn_timing.get('first_token',0)>0}, gen_complete={gen_complete>0}, has_output={has_output} - keeping thinking, waiting for stream to finish (prevents duplicate REQUEST START)")
                # Do NOT update state_tracker, keep as thinking, do NOT reset timing, keep active request alive
                # This ensures exactly one valid LLM request per completed user turn
                return
            
            # Only if LLM terminated and no output, then it's truly empty
            # FIX: Check is_closing again before warning
            if turn_timing.get("is_closing", False):
                logger.info(f"👋 Deterministic closing in progress (is_closing=True), empty turn confirmed but is intentional closing, not failure")
                state_tracker["state"] = ev.new_state
                state_tracker["since"] = now
                return
            
            if not has_output and gen_complete == 0 and request_start > 0:
                # LLM terminated with no output and no assistant item - check if it was 0-token generation
                if turn_timing.get("output_tokens",0) == 0 and turn_timing.get("input_tokens",0) == 0:
                    # Check if this is closing
                    if turn_timing.get("is_closing", False):
                        logger.info(f"👋 Empty LLM turn confirmed but is_closing=True, intentional closing 0/0, not failure")
                        state_tracker["state"] = ev.new_state
                        state_tracker["since"] = now
                        return
                    logger.warning(f"⚠️ Empty LLM turn confirmed (stream terminated with 0 tokens): thinking {elapsed:.2f}s → listening without speaking. request_start {now-request_start:.2f}s ago, gen_complete {gen_complete}. Possible preemptive invalidation or 0-token response.")
                else:
                    if turn_timing.get("is_closing", False):
                        logger.info(f"👋 Empty LLM turn detected but is_closing=True, intentional closing, not failure - suppressing warning")
                        state_tracker["state"] = ev.new_state
                        state_tracker["since"] = now
                        return
                    logger.warning(f"⚠️ Empty LLM turn detected (thinking {elapsed:.2f}s → listening without speaking). Possible causes: LLM 404/429, empty response, or tool filtering. speech_end age: {(now-turn_timing.get('speech_end',0)) if turn_timing.get('speech_end') else 'N/A'} active={is_llm_active} has_output={has_output}")
            elif not has_output:
                if turn_timing.get("is_closing", False):
                    logger.info(f"👋 Empty LLM turn detected (thinking {elapsed:.2f}s) but is_closing=True, intentional closing, not failure")
                    state_tracker["state"] = ev.new_state
                    state_tracker["since"] = now
                    return
                logger.warning(f"⚠️ Empty LLM turn detected (thinking {elapsed:.2f}s → listening without speaking). No assistant output, llm_active={is_llm_active}, gen_complete={gen_complete>0}, first_token={turn_timing.get('first_token',0)>0}")
            else:
                # Had output but still went listening->thinking without speaking? Might be tool filtering
                logger.info(f"ℹ️ thinking->listening after output (has_output={has_output}, first_token {turn_timing.get('first_token',0)>0}) - not empty, likely TTS finished")
                state_tracker["state"] = ev.new_state
                state_tracker["since"] = now
                return
            
            if turn_timing["speech_end"] != 0 and turn_timing["first_audio"] == 0 and not is_llm_active:
                # Only reset if LLM not active
                logger.info(f"🔄 Resetting turn_timing after confirmed empty turn (LLM terminated, no output) to avoid next-turn outlier")
                turn_timing["speech_end"] = 0.0
                turn_timing["stt_final"] = 0.0
                turn_timing["turn_detected"] = 0.0
                turn_timing["stt_final_mono"] = 0.0
                turn_timing["turn_commit_mono"] = 0.0
                turn_timing["pipeline_stage"] = "user_speech"
                turn_timing["llm_start"] = 0.0
                turn_timing["request_start"] = 0.0
                turn_timing["first_token"] = 0.0
                turn_timing["first_audio"] = 0.0
                turn_timing["llm_active"] = False
                if "tts_request" in turn_timing:
                    turn_timing["tts_request"] = 0.0
                if "first_tts_audio" in turn_timing:
                    turn_timing["first_tts_audio"] = 0.0
                if "audio_published" in turn_timing:
                    turn_timing["audio_published"] = 0.0
                if "llm_complete" in turn_timing:
                    turn_timing["llm_complete"] = 0.0
                if "generation_complete" in turn_timing:
                    turn_timing["generation_complete"] = 0.0
                if "request_start" in turn_timing:
                    turn_timing["request_start"] = 0.0
                if "ttft_ms" in turn_timing:
                    turn_timing["ttft_ms"] = 0.0
                if "generation_time_ms" in turn_timing:
                    turn_timing["generation_time_ms"] = 0.0
                if "assistant_output_received" in turn_timing:
                    turn_timing["assistant_output_received"] = False

        elif ev.new_state == "listening" and prev == "speaking":
            turn_timing["playout_end_ts"] = time.time()
            # Agent finished speaking, now listening: estimate speech_end for next turn
            # Reset timing for next turn, but keep last turn's metrics for final calc
            # Actually speech_end will be set when user starts speaking? We need VAD hook.
            # For now, reset stt_final and turn_detected for next turn
            # Keep speech_end as 0 until next VAD end (we approximate via last_user_transcript timing)
            pass

        # Track VAD speech end approximation: when listening starts, user hasn't spoken yet
        # When user stops speaking, STT final arrives, then turn detected.
        # For barge-in detection: listening->thinking is turn, but we also need speech_end.
        # We approximate speech_end as stt_final - 200ms (Deepgram endpointing) or use VAD if available.
        # Better: set speech_end when we get interim STT that then becomes final after silence.
        # For now, we set speech_end when state goes listening->thinking minus endpointing delay
        # to measure outlier.

        if ev.new_state == "speaking":
            _cancel_pending()
            # Don't cancel if we are in no-response closing flow — keep triggered flag
            if not no_response_state.get("triggered"):
                _cancel_no_response()
            no_response_state["last_activity"] = now
            # First audio timing will be logged in TTS handler
        elif ev.new_state == "listening":
            # If no-response already triggered or call closing, do NOT re-arm
            if no_response_state.get("triggered") or call_closed["done"] or closing_in_progress["done"] or closing_requested["done"]:
                logger.info(f"⏱️ Listening but no-response/closing already triggered — not re-arming")
            else:
                no_response_state["last_activity"] = now
                _schedule_no_response()
            # Reset for next turn's speech_end detection
            # We will set speech_end when VAD would have detected end, approx now + user speech
            # Actually we need to track when user starts speaking vs stops.
            # For outlier detection, we log listening duration: if >3s, flag
            if elapsed > 3.0 and prev in ("listening", None):
                logger.warning(f"🐢 Listening outlier: {prev}->{ev.new_state} took {elapsed:.2f}s (possible 3-7s outlier, check VAD/STT)")
        elif ev.new_state == "thinking":
            if not no_response_state.get("triggered"):
                _cancel_no_response()
            no_response_state["last_activity"] = now
        state_tracker["state"] = ev.new_state
        state_tracker["since"] = now

    session.on("agent_state_changed", _instrument_sync_callback("agent_state_changed", _on_state))
