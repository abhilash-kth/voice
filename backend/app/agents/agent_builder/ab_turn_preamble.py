"""Turn-completion preamble: computes the current user text, snapshot logs,
and previous-request bookkeeping (log-only; superseded requests are simply
cancelled and report 0/0 tokens, which billing ignores).

Extracted verbatim from agent_builder/ab_agent.py (<=300-line rule). The
explicit_goodbye guards became closing_state["explicit_goodbye"] writes.
"""
from __future__ import annotations

import logging
import time
import time as _time

from .ab_prompt import _chat_msg_text

logger = logging.getLogger("voice-agent-saas-worker")


def prepare_turn(self, new_message, closing_state):
    """Returns {user_text, _rag_t0} for the engine phases that follow."""

    """Hook that runs after the user finishes speaking — CRITICAL LATENCY PATH.

    LiveKit's ``AgentSession`` ``await``s this hook, so any blocking here
    directly adds to STT_final->LLM_start latency (target ≤100ms).

    Production fixes:
    - Explicit goodbye detection is fast (string ops, ~1ms)
    - Conversation trim is fast (list slice)
    - RAG is now async via to_thread to avoid blocking event loop (was sync, could be 100-300ms)
    - Turn governor (below): ack turns answer deterministically via the
      agent's llm_node override (zero LLM), incomplete fragments are held
      silently and merged into the next completed turn's RAG query
    - Added timing logs for STT_final->LLM_start to detect 3-7s outliers
    - FIX: Prevent duplicate/invalidated LLM requests - wait for previous LLM to complete before new REQUEST START
    - Exactly one REQUEST START per completed user turn, no 0/0 race
    """
    # NOTE: LiveKit `await`s this hook before generating the reply, so any
    # waiting here stalls the whole turn pipeline. The old code busy-waited
    # up to 2s for the previous LLM request to finish; when the user barged
    # in, LiveKit's interruption had to wait on this hook, the speech handle
    # never resolved, and the 5s INTERRUPTION_TIMEOUT fired:
    #   "speech not done in time after interruption, cancelling arbitrarily"
    # — which killed the rest of the call's audio (livekit/agents #5359).
    # Turn serialization is LiveKit's job, not ours: a superseded request is
    # simply cancelled and reported as 0/0 tokens, which billing ignores.
    # So: log only, never wait.
    try:
        _turn_marker_text = _chat_msg_text(new_message).strip()
        logger.info("🗣️ [USER_TURN_COMPLETED] callback entered for user turn: '%s'", _turn_marker_text[:80])
        if self._turn_timing_ref is not None:
            _commit_ts = time.time()
            self._turn_timing_ref["turn_callback_enter_ts"] = _commit_ts
            _commit_mono = time.monotonic_ns()
            self._turn_timing_ref["callback_enter_mono_ns"] = _commit_mono
            self._turn_timing_ref["pipeline_stage"] = "user_turn_completed"
            _final_mono = int(self._turn_timing_ref.get("stt_final_mono_ns", 0) or 0)
            _commit_ms = (
                f"{(_commit_mono - _final_mono) / 1_000_000:.0f}ms"
                if _final_mono > 0 and _commit_mono >= _final_mono
                else "N/A"
            )
            logger.info("⏱️ [TURN_TIMING] stt_final_to_callback_enter_ms=%s", _commit_ms)
    except Exception:
        pass
    try:
        if self._turn_timing_ref and self._turn_timing_ref.get("llm_active", False):
            prev_start = self._turn_timing_ref.get("request_start", 0)
            elapsed = time.time() - prev_start if prev_start else 0
            logger.info(
                f"↪️ New user turn while previous LLM request still active "
                f"(elapsed {elapsed:.2f}s) — LiveKit will cancel the superseded "
                f"request; not waiting (waiting here stalls barge-in)"
            )
    except Exception as e:
        logger.debug(f"Could not inspect previous LLM state: {e}")
    import time as _time
    _rag_t0 = _time.time()
    try:
        user_text = _chat_msg_text(new_message).strip()
        normalized = " ".join(
            user_text.lower()
            .replace(".", " ")
            .replace(",", " ")
            .split()
        )
        # Expanded deterministic closing detection — must match worker.py logic
        closing_exact = {
            "bye", "bye bye", "goodbye", "good bye", "ok bye",
            "okay bye", "ok good bye", "okay good bye", "ok goodbye",
            "okay goodbye", "good bye bye", "thank you", "thanks", "thankyou",
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
        disconnect_sub = (
            "cut the call", "hang up", "disconnect", "end the call", "call cut",
            "कॉल कट", "call काट", "कॉल काट", "call cut कर दीजिए", "call काट दीजिए",
            "कॉल बंद कर दीजिए", "फोन काट दीजिए", "फोन काट दो",
            # Hang-up granted in Hindi / mixed script (caller: "आप phone रख सकते")
            "फोन रख दो", "फ़ोन रख दो", "फोन रख दीजिए", "फ़ोन रख दीजिए", "फ़ोन रख",
            "फोन रख", "phone रख", "call रख", "कॉल रख",
            "phone rakh do", "phone rakh dijiye", "phone rakh sakte", "aap phone rakh sakte",
            # "I need nothing (else)"
            "कुछ भी नहीं चाहिए", "जानकारी नहीं चाहिए", "कोई भी जानकारी नहीं चाहिए",
            "kuch bhi nahi chahiye", "koi jaankari nahi chahiye", "kisi bhi tarah ki madad nahi chahiye",
            "और तो मुझे कुछ नहीं जानना", "अब मुझे कुछ नहीं जानना",
            "मुझे और कुछ नहीं जानना", "बस इतना ही", "बस इतना ही पूछना था",
            "no more questions", "no more help", "that's all", "that is all",
            "नहीं और कोई मदद नहीं चाहिए", "और कोई मदद नहीं चाहिए",
            "नहीं और कोई सवाल नहीं है", "और कोई सवाल नहीं है",
            "मुझे कुछ नहीं पूछना है", "कुछ नहीं पूछना है",
            "mujhe kuch nahi puchna", "kuch nahi puchna",
            "koi sawaal nahi", "koi sawal nahi",
        )
        has_goodbye = "goodbye" in normalized or "good bye" in normalized
        tokens = normalized.split()
        has_bye_token = "bye" in tokens or normalized.endswith(" bye") or normalized.startswith("bye ")
        has_thank = "thank" in normalized or "thanks" in normalized or "धन्यवाद" in user_text
        has_positive_close = any(w in normalized for w in ("accha laga", "achha laga", "khushi", "very much", "bahut"))
        # Fix: Don't treat contact info as goodbye - user giving number/email is NOT closing
        has_contact_info = any(c in normalized for c in ("nine", "five", "double", "triple", "zero", "at the rate", "gmail", "dot com", "number", "email")) or any(ch.isdigit() for ch in user_text if len(user_text.split()) <= 20)
        # If message looks like phone number or email, never treat as goodbye
        if has_contact_info and len(tokens) >= 4:
            closing_state["explicit_goodbye"] = False
        else:
            closing_state["explicit_goodbye"] = bool(
                normalized in closing_exact
                or has_goodbye
                or (has_bye_token and len(tokens) <= 8)
                or (has_thank and "?" not in user_text and (len(tokens) <= 18 or has_positive_close or "accha laga" in normalized))
                or any(p in normalized for p in disconnect_sub)
            )
    except Exception:
        closing_state["explicit_goodbye"] = False

    return {"user_text": user_text, "_rag_t0": _rag_t0}
