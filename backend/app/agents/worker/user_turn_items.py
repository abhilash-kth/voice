"""User-turn portion of the conversation_item_added hook: debounce,
utterance-start timing bookkeeping, contact-info/closing-request detection,
and watchdog (re)arms on caller activity.

Extracted verbatim from `on_item_added` (<=300-line rule). The returns in
this branch simply skipped the rest of the handler; after extraction the
helper call is followed only by the disjoint elif-branch, so behaviour is
identical.
"""
from __future__ import annotations

import logging
import time

logger = logging.getLogger("voice-agent-saas-worker")


def process_user_turn_item(role, text, turn_timing, usage, last_user_transcript,
                           closing_requested, reply_tracker, _schedule_silence_fallback,
                           _schedule_deterministic_closing, _schedule_no_response,
                           _cancel_pending):

    # Role/user branch extracted verbatim from on_item_added.
        if not text:
            return
        now = time.time()
        # Production debounce fix: 2.5s was too long for short "haan/ok/yes" causing missed turns
        # For short utterances (<3 words), debounce 0.8s, for longer 1.5s (was 2.5s)
        # Prevents duplicate STT events (interim->final same text) from delaying turn, but allows quick repeats
        words_in_text = len(text.split())
        debounce_threshold = 0.8 if words_in_text <= 2 else 1.5
        if text == last_user_transcript["text"] and (now - last_user_transcript["ts"]) < debounce_threshold:
            logger.info(f"⏭️ Dedupe STT duplicate (same text within {debounce_threshold}s): {text[:60]}")
            return
        last_user_transcript["text"] = text
        last_user_transcript["ts"] = now
        # --- Production timing: STT final received ---
        # FIX: Always start fresh timing for each user turn (unconditional reset)
        # Previous bug: conditional reset only if stale>5s caused first_token from previous turn
        # to leak into next turn's tts_request (2099ms artifact) and speech_end 16.8s old artifact
        # Now: unconditional fresh reset per turn, then set speech_end and stt_final fresh
        prev_speech_end = turn_timing.get("speech_end", 0)
        if prev_speech_end != 0:
            stale_age = now - prev_speech_end
            if stale_age > 2.0:
                logger.info(f"🔄 Resetting turn_timing: prev speech_end {stale_age:.1f}s old (empty turn or long pause) for fresh turn")
        # Fresh timing for this turn - reset ALL keys unconditionally (V2 with TTFT)
        turn_timing["turn_detected"] = 0.0
        turn_timing["llm_start"] = 0.0
        turn_timing["request_start"] = 0.0
        turn_timing["first_token"] = 0.0
        turn_timing["tts_request"] = 0.0
        turn_timing["first_tts_audio"] = 0.0
        turn_timing["llm_complete"] = 0.0
        turn_timing["generation_complete"] = 0.0
        turn_timing["first_audio"] = 0.0
        turn_timing["last_speech_end_to_first_audio"] = 0.0
        turn_timing["ttft_ms"] = 0.0
        turn_timing["generation_time_ms"] = 0.0
        turn_timing["input_tokens"] = 0
        turn_timing["cached_input_tokens"] = 0
        turn_timing["output_tokens"] = 0
        # Fresh timing values for this turn. Deepgram does not expose the
        # acoustic speech-end timestamp, so speech_end remains unavailable.
        _final_ts = float(turn_timing.get("stt_final_ts", 0.0) or 0.0)
        turn_timing["speech_end"] = 0.0
        turn_timing["stt_final"] = _final_ts
        turn_timing["pipeline_stage"] = "turn_detected"
        # User turn committed — start a fresh silence window NOW rather than
        # only cancelling: if the agent then replies, the state transitions
        # cancel/re-arm this timer anyway; if the reply wedges, the call
        # still ends after the timeout instead of sitting in dead air
        # forever (an old cancel-only path left exactly that hole).
        _schedule_no_response(reason="user_turn_committed")
        words = max(len(text.split()), 1)
        usage["llm_input_tokens"] += int(words * 1.3)
        usage["user_speech_seconds"] += (words / 150.0) * 60.0
        usage["transcripts"].append({"role": "user", "text": text})
        logger.info(f"👂 User: {text}")
        normalized_user = " ".join(text.lower().replace(".", " ").replace(",", " ").split())
        # Expanded closing detection for low-latency deterministic goodbye.
        # Covers: bye variants, ok good bye, thank you, mixed Hindi/English,
        # and natural no-help phrases like "नहीं और कोई मदद नहीं चाहिए"
        # and transliterated "mujhe kuch nahi puchna hai".
        closing_exact = {
            "bye", "bye bye", "goodbye", "good bye", "ok bye", "okay bye",
            "ok good bye", "okay good bye", "ok goodbye", "okay goodbye",
            "good bye bye", "thank you", "thanks", "thankyou",
            "और तो मुझे कुछ नहीं जानना", "अब मुझे कुछ नहीं जानना",
            "मुझे और कुछ नहीं जानना", "बस इतना ही", "बस इतना ही पूछना था",
            "no more questions", "no more help", "that's all", "that is all",
            "नहीं और कोई मदद नहीं चाहिए", "और कोई मदद नहीं चाहिए",
            "कोई मदद नहीं चाहिए", "और कुछ नहीं चाहिए", "बस हो गया",
            "नहीं और कोई सवाल नहीं है", "और कोई सवाल नहीं है",
            "कोई सवाल नहीं है", "मुझे कुछ नहीं पूछना है", "मुझे कुछ नहीं पूछना",
            "कुछ नहीं पूछना है", "कुछ नहीं पूछना",
            "mujhe kuch nahi puchna hai", "mujhe kuch nahi puchna",
            "kuch nahi puchna hai", "kuch nahi puchna",
            "koi sawaal nahi hai", "koi sawal nahi hai",
            "aur koi sawaal nahi hai", "aur koi sawal nahi hai",
            "nahi aur koi madad nahi chahiye", "aur koi madad nahi chahiye",
            "nahi aur koi sawaal nahi hai",
        }
        closing_substrings = (
            "cut the call", "hang up", "disconnect", "end the call", "call cut",
            "कॉल कट", "call काट", "कॉल काट", "call cut कर दीजिए", "call काट दीजिए",
            "कॉल बंद कर दीजिए", "फोन काट दीजिए", "फोन काट दो",
            # Hang-up permission granted in Hindi / mixed script (2026-09-19: caller
            # said "मुझे कुछ भी नहीं चाहिए. आप phone रख सकते" twice, call dragged 33s)
            "फोन रख दो", "फ़ोन रख दो", "फोन रख दीजिए", "फ़ोन रख दीजिए", "फ़ोन रख",
            "फोन रख", "phone रख", "call रख", "कॉल रख",
            "phone rakh do", "phone rakh dijiye", "phone rakh sakte", "aap phone rakh sakte",
            # "I need nothing (else)" — direct answer to 'anything else?' means close
            "कुछ भी नहीं चाहिए", "जानकारी नहीं चाहिए", "कोई भी जानकारी नहीं चाहिए",
            "kuch bhi nahi chahiye", "koi jaankari nahi chahiye", "kisi bhi tarah ki madad nahi chahiye",
            "और तो मुझे कुछ नहीं जानना", "अब मुझे कुछ नहीं जानना",
            "मुझे और कुछ नहीं जानना", "बस इतना ही", "बस इतना ही पूछना था",
            "no more questions", "no more help", "that's all", "that is all",
            "नहीं और कोई मदद नहीं चाहिए", "और कोई मदद नहीं चाहिए",
            "कोई मदद नहीं चाहिए", "और कुछ नहीं चाहिए",
            "नहीं और कोई सवाल नहीं है", "और कोई सवाल नहीं है",
            "मुझे कुछ नहीं पूछना है", "कुछ नहीं पूछना है",
            "mujhe kuch nahi puchna", "kuch nahi puchna",
            "koi sawaal nahi", "koi sawal nahi",
        )
        # Robust bye detection: any occurrence of goodbye/good bye, or standalone bye
        has_goodbye = "goodbye" in normalized_user or "good bye" in normalized_user
        # bye as separate token or at end, avoid false positive from "by" substring
        tokens = normalized_user.split()
        has_bye_token = "bye" in tokens or normalized_user.endswith(" bye") or normalized_user.startswith("bye ")
        # Enhanced thank detection: "thank you very much", "thank kota" (mis-heard), "accha laga thank" etc
        # Previous logic required <=12 tokens and exact thank you — too strict, caused
        # "Ok, चलिए ठीक है आपसे बात करके अच्छा लगा thank Kota." to NOT close.
        # Now: thank/thanks/dhanyavaad + positive sentiment or accha laga/khushi = closing
        has_thank = "thank" in normalized_user or "thanks" in normalized_user or "धन्यवाद" in text or "dhanyavaad" in normalized_user
        has_positive_close = any(w in normalized_user for w in ("accha laga", "achha laga", "khushi", "bahut accha", "very much", "bahut"))
        has_contact_info = any(c in normalized_user for c in ("nine", "five", "double", "triple", "zero", "at the rate", "gmail", "dot com", "number", "email")) or (any(ch.isdigit() for ch in text) and len(tokens) >= 4 and len(tokens) <= 20)
        if has_contact_info:
            closing_requested["done"] = False
        else:
            closing_requested["done"] = (
                normalized_user in closing_exact
                or has_goodbye
                or (has_bye_token and len(tokens) <= 8)
                or (has_thank and "?" not in text and (len(tokens) <= 18 or has_positive_close or "accha laga" in normalized_user or "achha laga" in normalized_user))
                or any(phrase in normalized_user for phrase in closing_substrings)
            )
        if closing_requested["done"]:
            # Never let the generic provider-timeout fallback speak after a
            # caller has already asked to leave. Speak deterministic closing
            # and hang up (bb393dd fix).
            # FIX: Mark as closing to separate intentional 0/0 closing from genuine empty turns
            turn_timing["is_closing"] = True
            logger.info(f"👋 Deterministic closing requested, marking is_closing=True to exclude 0/0 from failure count")
            _cancel_pending()
            old_fallback = reply_tracker.get("fallback_say")
            if old_fallback is not None and not old_fallback.done():
                old_fallback.cancel()
            reply_tracker["fallback_say"] = None
            _schedule_deterministic_closing()
            return
        # A fresh turn supersedes any fallback still speaking from the
        # previous failed turn; never let it bleed into this reply.
        old_fallback = reply_tracker.get("fallback_say")
        if old_fallback is not None and not old_fallback.done():
            old_fallback.cancel()
        reply_tracker["fallback_say"] = None
        # A fresh turn starts: arm the silence watchdog so a 429'd or empty
        # LLM turn never leaves the caller in dead air.
        reply_tracker["last_user_ts"] = now
        reply_tracker["empty_spoken"] = False
        _schedule_silence_fallback(now)


def new_call_bookkeeping():
    """Fresh per-call bookkeeping records: usage counters, user-transcript
    dedupe cell, agent-state tracker. Extracted verbatim from
    `_entrypoint_body`."""
    usage = {"tts_chars": 0, "llm_input_tokens": 0, "llm_output_tokens": 0,
             "user_speech_seconds": 0.0, "transcripts": []}
    # Dedupe identical user transcripts (STT can emit the same phrase twice) and
    # track how long the agent stays in each state so we can flag slow turns.
    last_user_transcript = {"text": "", "ts": 0.0}
    state_tracker = {"state": None, "since": time.time()}
    return usage, last_user_transcript, state_tracker

