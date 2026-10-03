from __future__ import annotations

import time
import asyncio
import logging
import os
import re
from typing import Any, Optional

from ...models import AgentConfig, KnowledgeBase
from ...config import (
    GROQ_API_KEY,
    OPENAI_API_KEY,
    DEEPGRAM_API_KEY,
    GOOGLE_APPLICATION_CREDENTIALS,
    OPENROUTER_API_KEY,
    GEMINI_API_KEY,
    SARVAM_API_KEY,
    CARTESIA_API_KEY,
    ANTHROPIC_API_KEY,
    QWEN_API_KEY,
    FISH_AUDIO_API_KEY,
    MINIMAX_API_KEY,
)

logger = logging.getLogger("voice-agent-saas-agent-builder")


# cross-module imports (auto-generated)
from .ab_instructions import build_instructions
from .ab_opening import speak_opening_line, wait_until_caller_can_hear
from .ab_prompt import _FRAGMENT_TTL_S, _RAG_PREFIX, _SUPERSEDED_MERGE_MAX_AGE_S, _chat_msg_text, _find_chat_ctx, _frag_append_fresh, _frag_consume, _get_closing_for_cfg, _rag_per_turn_enabled, _strip_trailing_ack_turns

def build_voice_agent(
    cfg: AgentConfig,
    *,
    greeting: str = "",
    prior_memory: str = "",
    lead_data: Optional[dict] = None,
    turn_timing_ref: Optional[dict] = None,
    rag_prefetch: Optional[dict] = None,
) -> "Any":
    """Return a LiveKit v1 ``Agent`` instance wired for this config.

    The returned agent:
      * speaks ``greeting`` when the session enters (LiveKit's ``on_enter``),
      * has a CAPPED summary of the knowledge base in its static system prompt
        (full-KB prompts 429 Groq's free tier; relevant chunks are injected
        per-turn via RAG in on_user_turn_completed), and
      * seeds the conversation with ``prior_memory`` (cross-call memory).

    The KB is split: a capped summary stays static (fast, stable), and the
    question-specific chunks are added in ``on_user_turn_completed`` (per-turn
    RAG). Per-turn mutation would invalidate preemptive generation, so RAG is
    skipped when ``VOICE_PREEMPTIVE=1`` (only the capped static facts are used
    then). See the context-size budgets comment above for why the static part
    is capped.
    """
    from livekit.agents import Agent, llm
    from livekit.agents import get_job_context

    # A CAPPED summary of the knowledge base is baked into the static system
    # prompt (see context-size budgets above). Baking in the FULL KB made every
    # LLM request 6-7k tokens, which 429s Groq's free tier (8k TPM) and silently
    # dropped turns. The specific chunks a question needs are injected per turn
    # by on_user_turn_completed (lightweight RAG) — safe because preemptive
    # generation is off by default; when VOICE_PREEMPTIVE=1 the hook stands down
    # and only the capped static facts are used.
    instructions = build_instructions(cfg)

    # The model may request the tool, but only a deterministic transcript check
    # may authorize room deletion. This prevents phrases such as "no more help,
    # thank you" from being mistaken for a final goodbye. The closing speech
    # itself is deterministic (bb393dd fix) — always the same fixed line.
    explicit_goodbye = False
    agent_ref: dict[str, Any] = {"instance": None}

    # Auto hang-up: when the conversation is finished the LLM calls `end_call`,
    # which shuts the job down so the call is cut AND the billing is finalized.
    # We make the trigger explicit so the model reliably hangs up on its own and
    # doesn't leave the caller in a silent, open call. Closing speech is now
    # deterministic: the tool itself speaks the fixed closing line.
    instructions += (
        "\n\nCALL LIFECYCLE: keep the call open after every normal answer, pause or detail-collection turn. End the call ONLY on a clear, standalone goodbye or hang-up grant in any language ('bye', 'ok bye', 'thank you' as a closer, 'that\'s all', 'no more questions/help', 'फ़ोन रख दीजिए', 'कॉल काट दीजिए', 'मुझे कुछ और नहीं चाहिए/जानना'). 'ok', or 'that\'s all for this question' followed by another question, is NOT a goodbye. On a real goodbye do not compose a closing sentence yourself: call the end_call tool once — the system speaks the fixed closing line and hangs up. Never call end_call at any other time."
    )

    async def _end_call() -> str:
        """End this call and hang up. Call it ONLY when user says goodbye, bye, thank you, etc.
        Do NOT call for 'sahi baat hai', 'ok', 'achhi lagti', 'product hai', number, email, etc.
        Deterministic closing: worker speaks fixed closing line, tool only deletes room.
        """
        if not explicit_goodbye:
            logger.warning("end_call rejected: caller did not give an explicit final goodbye - keeping call open")
            # Return instruction for LLM to continue naturally, not silence
            return "DO NOT END CALL. User did NOT say goodbye. Phrases like 'sahi baat hai', 'ok', 'achhi lagti', 'product hai', phone numbers, emails are NOT goodbye. Continue conversation warmly, ask how you can help."
        ctx = get_job_context(required=False)
        if ctx is None:
            return "No job context; call not ended."
        logger.info("[CALL_END_REQUESTED] source=agent reason=completed")
        # Avoid duplicate TTS: worker.py already spoke deterministic closing.
        # Only speak here as fallback if worker hasn't (check last closing timestamp).
        import time as _time
        now = _time.time()
        last_ts = agent_ref.get("last_closing_ts", 0)
        agent_inst = agent_ref.get("instance")
        if agent_inst is not None:
            # Check timestamp set by worker.py _do_deterministic_closing
            ts1 = getattr(agent_inst, '_last_deterministic_closing_ts', 0)
            ts2 = getattr(getattr(agent_inst, 'cfg', None), '_last_closing_ts', 0) if hasattr(agent_inst, 'cfg') else 0
            last_ts = max(last_ts, ts1, ts2)
        # If worker spoke within last 4s, skip TTS here.
        if now - last_ts > 4:
            # Fallback deterministic closing if worker missed it
            closing_line = _get_closing_for_cfg(cfg)
            agent_inst = agent_ref.get("instance")
            if agent_inst is not None:
                try:
                    sess = getattr(agent_inst, "session", None)
                    if sess is not None:
                        logger.info(f"👋 Fallback deterministic closing via end_call tool: {closing_line}")
                        await sess.say(closing_line, allow_interruptions=False)
                        await asyncio.sleep(0.6)
                except Exception as e:
                    logger.warning(f"Fallback closing via tool failed: {e}")
        else:
            await asyncio.sleep(0.4)
        # Physically cut the call: delete the LiveKit room so the caller/SIP
        # participant is disconnected (not left in a silent, open call).
        agent_inst = agent_ref.get("instance")
        if agent_inst is not None:
            sess = getattr(agent_inst, "session", None)
            if sess is not None:
                try:
                    sess.shutdown(drain=False)
                except Exception:
                    pass
        room = getattr(ctx.room, "name", None)
        if room:
            try:
                from ...telephony import end_active_room
                await end_active_room(room)
            except Exception as e:
                logger.warning(f"end_call: could not delete room {room}: {e}")
        ctx.shutdown()
        logger.info("[CALL_ENDED] reason=completed")
        return "Call ended."

    # `name="end_call"` keeps the LLM-visible tool name in sync with the prompt
    # (otherwise it would default to "_end_call" and the model might not call it).
    end_call_tool = llm.function_tool(
        _end_call,
        name="end_call",
        description="End the call and hang up. Call this once the conversation is finished.",
    )

    # Cross-call memory becomes part of the initial conversation history, so it
    # influences every turn without being re-inserted.
    chat_ctx = llm.ChatContext()
    _in_call_memory_lines: list[str] = []
    if lead_data:
        # For bulk-call campaigns, give the agent the lead's details (from the
        # uploaded file) so it can address them by name / reference their data.
        lead_blurb = ", ".join(f"{k}: {v}" for k, v in (lead_data or {}).items() if v)
        chat_ctx.add_message(
            role="system",
            content=(
                "You are now speaking with a specific caller from a contact list.\n"
                f"This caller's details: {lead_blurb or '(none)'}.\n"
                "Use the caller's name naturally when it is known, and reference their "
                "details when relevant."
            ),
        )
    if prior_memory:
        # Voice latency: truncate prior_memory to 800 chars when RAG enabled (was unlimited 40 turns ~4000 tokens)
        # Preserves recent cross-call memory (name, preferences) without bloating input tokens 3500-3700
        try:
            import os as _os_pm
            _rag_pm = (_os_pm.getenv("VOICE_RAG_PER_TURN") or "").strip().lower() not in ("0", "false", "off")
            _pm_budget = int(_os_pm.getenv("VOICE_PRIOR_MEMORY_BUDGET_CHARS", "800")) if _rag_pm else 2000
        except Exception:
            _pm_budget = 800
        _pm_truncated = prior_memory
        if len(prior_memory) > _pm_budget:
            # Keep last _pm_budget chars (most recent)
            _pm_truncated = prior_memory[-_pm_budget:]
            # Try to cut at line boundary
            _nl = _pm_truncated.find("\n")
            if _nl != -1 and _nl < _pm_budget * 0.3:
                _pm_truncated = _pm_truncated[_nl+1:]
        chat_ctx.add_message(
            role="system",
            content="Prior conversation with this customer:\n" + _pm_truncated,
        )
        if len(prior_memory) != len(_pm_truncated):
            logger.info(f"🔧 Prior memory truncated {len(prior_memory)} -> {len(_pm_truncated)} chars (budget {_pm_budget}) to reduce 3500-3700 tokens")

    class _VoiceAgent(Agent):
        def __init__(self):
            self.cfg = cfg
            self.greeting = greeting
            self._opening_started = False
            self._opening_done = False
            self._turn_timing_ref = turn_timing_ref  # For preventing duplicate REQUEST START while previous active
            # Store instance so _end_call tool can speak deterministic closing via session.
            agent_ref["instance"] = self
            super().__init__(
                instructions=instructions,
                chat_ctx=chat_ctx,
                # The tool is gated by the explicit goodbye instructions above.
                # It is used only after the closing sentence has been generated.
                tools=[end_call_tool],
                # NOTE: turn-handling (endpointing / interruption / preemptive
                # generation) is set on the AgentSession (build_assistant_session),
                # where LiveKit actually reads the interruption min_duration/window.
                # Keeping it there is the single source of truth; do NOT also set it
                # here or the two can disagree.
            )

        def llm_node(self, chat_ctx, tools, model_settings):
            """Deterministic ack + incomplete-turn silence (see app/turn_rules.py).

            Library contract (voice/generation.py `_llm_inference_task`): a
            coroutine resolving to ``str`` IS the complete reply (fed straight to
            TTS); one resolving to ``None`` yields no output at all. That is how
            an acknowledgement gets answered with ZERO LLM calls (no REQUEST
            START, no tokens, no billing entry to exclude) and how an incomplete
            fragment stays silent until the caller finishes the thought. Every
            other turn falls through to the default LLM path untouched.
            """
            tt = self._turn_timing_ref
            if tt is not None:
                ack = tt.get("ack_reply")
                if ack is not None:
                    tt.pop("ack_reply", None)
                    logger.info(
                        "✅ [ACK_FAST_PATH] text='%s' response='%s' (no LLM request)",
                        str(ack.get("text", ""))[:60], str(ack.get("reply", ""))[:40],
                    )

                    async def _ack_reply():
                        return str(ack.get("reply") or "जी।")

                    return _ack_reply()
                if tt.get("gov_turn_state") == "suppress":
                    logger.info("⏸️ [LLM_REQUEST_SKIPPED] reason=incomplete_turn — awaiting caller continuation")

                    async def _skip():
                        return None

                    return _skip()
            return Agent.default.llm_node(self, chat_ctx, tools, model_settings)

        async def tts_node(self, text, model_settings):
            """Measure the FIRST assistant audio frame per speech (Task 3).

            Deliberately NOT a TTS-object wrapper — an earlier experiment that
            wrapped the TTS instance broke the greeting (see worker's
            "TTS left unwrapped" note). Instead we override the agent's
            tts_node hook, call the library default (which owns
            synthesize/segmenting/aligned transcripts and works with ANY
            provider behind it, including the FallbackAdapter), and wrap only
            the frame generator. Zero added latency: it is a pass-through
            async for. Stamps exactly the keys the existing turn-summary code
            already understands (tts_request / first_tts_audio /
            first_audio / last_speech_end_to_first_audio) so the 🗣️ TTS line
            upgrades from "audio not measured" to REAL audio automatically.
            """
            tt = self._turn_timing_ref
            _tts_entered = time.time()
            _logger = logging.getLogger("voice-agent-saas-agent-builder")

            async def _trace_text():
                _first_text = True
                async for _delta in text:
                    if _first_text:
                        _first_text = False
                        _now = time.time()
                        _ft = float(tt.get("first_token", 0) or 0) if tt is not None else 0
                        _logger.info(
                            "🔡 [TTS_TEXT_FIRST_DELTA] first_token_to_tts_node=%s tts_node_to_text=%dms chars=%d",
                            (f"{(_now - _ft) * 1000:.0f}ms" if _ft and _now >= _ft else "na"),
                            (_now - _tts_entered) * 1000,
                            len(str(_delta)),
                        )
                    yield _delta

            res = Agent.default.tts_node(self, _trace_text(), model_settings)
            if asyncio.iscoroutine(res):
                res = await res
            if res is None or tt is None:
                return res
            tt["tts_request"] = _tts_entered

            async def _probe():
                _logger.info("🔌 [TTS_STREAM_START] first_token_to_stream_start=%s",
                    (f"{(time.time() - float(tt.get('first_token', 0))) * 1000:.0f}ms"
                     if float(tt.get("first_token", 0) or 0) else "na"))
                _first = True
                async for frame in res:
                    if _first:
                        _first = False
                        if float(tt.get("first_tts_audio", 0) or 0) == 0.0:
                            _now = time.time()
                            tt["first_tts_audio"] = _now
                            tt["first_audio"] = _now
                            _se = float(tt.get("speech_end", 0) or 0)
                            _sf = float(tt.get("stt_final_ts", 0) or 0)
                            _tc = float(tt.get("turn_commit_ts", 0) or 0)
                            _ft = float(tt.get("first_token", 0) or 0)
                            _ttft = float(tt.get("ttft_ms", 0) or 0)
                            def _ms(a, b):
                                return f"{(b - a) * 1000:.0f}ms" if a and b and b >= a else "na"
                            _synth_ms = int((_now - _ft) * 1000) if _ft else -1
                            _s2fa = (tt["first_tts_audio"] - _se) * 1000 if _se else 0.0
                            if _s2fa > 0:
                                tt["last_speech_end_to_first_audio"] = _s2fa
                            _logger.info(
                                "🔊 [FIRST_ASSISTANT_AUDIO] t=%.3f (generation=%s)",
                                _now, tt.get("gen", 0),
                            )
                            _logger.info(
                                "⏱️ [LATENCY] stt_final_ms=%s turn_commit_ms=%s llm_ttft_ms=%s tts_first_audio_ms=%s speech_to_first_audio_ms=%s",
                                _ms(_se, _sf) if _sf else "na",
                                _ms(_sf if _sf else _se, _tc),
                                f"{_ttft:.0f}ms" if _ttft else "na",
                                f"{_synth_ms}ms" if _synth_ms >= 0 else "na",
                                f"{_s2fa:.0f}ms" if _s2fa > 0 else "na",
                            )
                            try:
                                _samples = tt.setdefault("latency_samples", [])
                                if len(_samples) < 40:
                                    _samples.append({
                                        "speech_end_to_first_audio_ms": round(_s2fa) if _s2fa > 0 else None,
                                        "ttft_ms": round(_ttft) if _ttft else None,
                                        "tts_synth_ms": _synth_ms if _synth_ms >= 0 else None,
                                        "turn_commit_ms": round((_tc - _sf) * 1000) if _tc and _sf else None,
                                    })
                            except Exception:
                                pass
                    yield frame

            return _probe()

        async def on_enter(self) -> None:
            # Assistant mode: greet as soon as the caller can hear, then listen.
            self._opening_started = True
            try:
                if not (self.greeting or "").strip():
                    logger.info("[ASSISTANT_STARTED] Assistant has no greeting — listening immediately")
                    return
                logger.info("[ASSISTANT_STARTED] Assistant connected — waiting for caller audio path")
                await wait_until_caller_can_hear(self.session)
                logger.info("[ASSISTANT_STARTED] Speaking greeting: %s", self.greeting[:60])
                _gtt = self._turn_timing_ref
                if _gtt is not None:
                    _gtt["greeting_active"] = True
                logger.info("👋 [GREETING_STARTED] '%s' — interruptible: caller speech cancels playback", self.greeting[:60])
                try:
                    await speak_opening_line(self.session, self.greeting, timeout=45, allow_interruptions=True)
                finally:
                    if _gtt is not None:
                        _gtt["greeting_active"] = False
                if _gtt is not None and _gtt.pop("greeting_interrupted", None):
                    logger.info("🔇 Greeting ended via caller barge-in — only the played portion counts; caller's turn proceeds")
                else:
                    logger.info("[ASSISTANT_STARTED] Greeting finished — now listening for caller speech")
            except Exception as e:
                logger.warning(f"Greeting failed: {type(e).__name__}: {e!r}")
            finally:
                self._opening_done = True
                if self._turn_timing_ref is not None:
                    self._turn_timing_ref["greeting_active"] = False

        async def on_user_turn_completed(self, turn_ctx, new_message) -> None:
            _tt = self._turn_timing_ref
            _entered_ns = time.monotonic_ns()
            if _tt is not None:
                _tt["callback_enter_mono_ns"] = _entered_ns
                logger.info(
                    "[TURN_TRACE] stage=callback_enter monotonic_ns=%d call_id=%s turn_id=%s generation_id=%s",
                    _entered_ns, _tt.get("call_id", "N/A"), _tt.get("turn_id", "N/A"), _tt.get("gen", "N/A"),
                )
            try:
                await self._on_user_turn_completed_impl(turn_ctx, new_message)
            finally:
                _completed_ns = time.monotonic_ns()
                if _tt is not None:
                    _tt["callback_complete_mono_ns"] = _completed_ns
                    logger.info(
                        "[TURN_TRACE] stage=callback_complete monotonic_ns=%d call_id=%s turn_id=%s generation_id=%s callback_duration_ms=%.3f",
                        _completed_ns, _tt.get("call_id", "N/A"), _tt.get("turn_id", "N/A"), _tt.get("gen", "N/A"),
                        max(0, _completed_ns - _entered_ns) / 1_000_000,
                    )

        async def _on_user_turn_completed_impl(self, turn_ctx, new_message) -> None:
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
                    _final_ts = float(self._turn_timing_ref.get("stt_final_ts", 0.0) or 0.0)
                    _final_age = _commit_ts - _final_ts
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
            nonlocal explicit_goodbye
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
                    explicit_goodbye = False
                else:
                    explicit_goodbye = bool(
                        normalized in closing_exact
                        or has_goodbye
                        or (has_bye_token and len(tokens) <= 8)
                        or (has_thank and "?" not in user_text and (len(tokens) <= 18 or has_positive_close or "accha laga" in normalized))
                        or any(p in normalized for p in disconnect_sub)
                    )
            except Exception:
                explicit_goodbye = False
            # --- Turn governor (2026-09-24 spec) — runs BEFORE any LLM
            # scheduling and decides three outcomes:
            #   ack        -> llm_node answers with a canned line; NO LLM request,
            #                 NO tokens, NO billing (00:31 log: 'Ok.' still cost a
            #                 2865-token request whose 3-char answer was then
            #                 mis-flagged into an apology).
            #   incomplete -> llm_node produces NOTHING; the fragment is kept in
            #                 pending_fragments and merged into the next complete
            #                 turn (00:31 log: one thought split into 4 finals
            #                 produced 3 invalidated 0/0 requests + 1 answered).
            #   complete   -> normal trim+RAG+LLM path; if fragments are pending,
            #                 RAG runs on the MERGED query.
            # Closing intent always wins (explicit_goodbye computed above), so
            # "thanks"/"बस इतना ही..." keep the existing deterministic closing.
            try:
                _gtext = user_text
            except NameError:
                _gtext = ""
            _tt = self._turn_timing_ref
            if _tt is not None:
                # per-turn flags: drop anything left from a cancelled turn so a
                # stale 'ack'/'suppress' can never hijack the next real question
                _tt.pop("gov_turn_state", None)
                _tt.pop("ack_reply", None)
                _tt.pop("combined_query", None)
                if _gtext and not explicit_goodbye:
                    try:
                        from ... import rag as _rag_rules
                        _is_ack = _rag_rules.is_acknowledgement(_gtext)
                        _is_inc = (not _is_ack) and _rag_rules.is_incomplete_turn(_gtext)
                    except Exception:
                        _is_ack = _is_inc = False
                    _now_f = _time.time()
                    _fb_before = len(list(_tt.get("pending_fragments") or []))
                    if _is_ack:
                        _tt["gov_turn_state"] = "ack"
                        _tt["ack_reply"] = {"text": _gtext, "reply": _rag_rules.ack_reply(_gtext)}
                        # an ACK means the caller moved past whatever they were
                        # composing — held fragments can never "continue" into
                        # this turn; clear so the NEXT turn starts clean.
                        _freshA, _dropA = _frag_consume(_tt, _now_f)
                        if _freshA or _dropA:
                            logger.info("🧹 fragments cleared on ACK turn (kept=%d dropped_stale=%d) — deterministic answer owns the floor", len(_freshA), _dropA)
                        logger.info("⏭️ [RAG_SKIPPED] acknowledgement turn: '%s' → deterministic reply, no LLM", _gtext[:40])
                        logger.info("📥 [TURN_INPUT] raw_stt='%s' cleaned_turn='' fragment_buffer_before=%d fragment_buffer_after=0 merged=no path=ack", _gtext[:70], _fb_before)
                        return
                    if _is_inc:
                        _pend = _frag_append_fresh(_tt, [_gtext], _now_f)
                        _tt["gov_turn_state"] = "suppress"
                        logger.info("⏸️ [INCOMPLETE_TURN] text='%s' waiting_for_continuation=true fragments=%d (TTL=%.0fs)", _gtext[:60], len(_pend), _FRAGMENT_TTL_S)
                        logger.info("📥 [TURN_INPUT] raw_stt='%s' cleaned_turn='' fragment_buffer_before=%d fragment_buffer_after=%d merged=no path=hold", _gtext[:70], _fb_before, len(_pend))
                        return
                    # complete turn — strong-evidence continuation merge: a
                    # previous question whose request was killed BEFORE any
                    # output (worker-set overwritten_turn, generation-tagged)
                    # joins the buffer as a fresh-in-time fragment.
                    _ov = _tt.pop("overwritten_turn", None)
                    _ov_used = False
                    if isinstance(_ov, dict):
                        _ovt = str(_ov.get("text") or "").strip()
                        _ov_age = _now_f - float(_ov.get("ts") or 0.0)
                        _ov_gen_ok = int(_ov.get("gen") or -1) == int(_tt.get("gen", 0) or 0)
                        if _ovt and _ov_gen_ok and _ov_age <= _SUPERSEDED_MERGE_MAX_AGE_S and _ovt[:120] != _gtext[:120]:
                            _old_p = list(_tt.get("pending_fragments") or [])
                            _tt["pending_fragments"] = ([(_ovt, float(_ov.get("ts") or _now_f))] + _old_p)[-5:]
                            _ov_used = True
                            logger.info("🔗 [CONTINUATION_MERGE] caller's previous question was superseded %.1fs ago with zero output — treating '%s…' + '%s…' as ONE utterance", _ov_age, _ovt[:40], _gtext[:40])
                    _kept, _dropped = _frag_consume(_tt, _now_f)
                    if _dropped:
                        logger.info("🧹 dropped %d stale fragment(s) (>%.0fs) — independent turn gets a clean query", _dropped, _FRAGMENT_TTL_S)
                    if _kept:
                        _combined = " ".join(_kept + [_gtext])
                        _tt["gov_turn_state"] = "complete"
                        _tt["combined_query"] = _combined
                        logger.info("🧩 [COMPLETE_TURN] merged %d fragment(s)%s: '%s'", len(_kept) + 1, " (incl. superseded continuation)" if _ov_used else "", _combined[:90])
                        logger.info("📥 [TURN_INPUT] raw_stt='%s' cleaned_turn='%s' fragment_buffer_before=%d fragment_buffer_after=0 merged=%s", _gtext[:70], _combined[:70], _fb_before, "yes+continuation" if _ov_used else "yes")
                    else:
                        logger.info("📥 [TURN_INPUT] raw_stt='%s' cleaned_turn='%s' fragment_buffer_before=%d fragment_buffer_after=0 merged=no", _gtext[:70], _gtext[:70], _fb_before)
            # Keep the rolling conversation bounded. Groq accounts the entire
            # prompt against TPM; an unbounded voice call eventually turns every
            # request into a 429 even with the 20b model. Preserve system facts
            # and only the latest few conversational messages.
            # CRITICAL FIX: Do NOT trim when preemptive generation is enabled.
            # Trimming mutates chat_ctx (len changes) → is_equivalent False → 
            # preemptive generation invalidated after on_user_turn_completed
            # → full LLM restart adds 1-2s latency (observed 1826-2364ms)
            # When preemptive ON, skip trimming to preserve preemptive.
            # When preemptive OFF, trim to avoid 429.
            preemptive_on = os.getenv("VOICE_PREEMPTIVE", "0") == "1"
            # FIX 4: Conversation memory - name unavailable but mobile remembered
            # Root cause: trimming to 6 dialogue messages max drops early name if many turns
            # Evidence: user asked name after previously giving it, agent said unavailable, but mobile 9538450441 remembered (later in conversation)
            # Fix: increase trim limit from 6 to 20 dialogue messages to preserve name, and preserve memory when memory_enabled
            # Also check if KB present - when KB present we already disable preemptive in worker.py, so trimming will happen
            # We should preserve more history for memory retention, not aggressively trim
            if not preemptive_on:
                try:
                    target_ctx = _find_chat_ctx(turn_ctx) or turn_ctx
                    items = getattr(target_ctx, "items", None)
                    # Voice latency optimization v2: keep 8 dialogue max for OpenAI when RAG enabled (was 12) to reduce 3500-3700 tokens further
                    # Billing shows avg 4 turns per call, 8 covers full call. prior_memory 800 chars handles cross-call memory.
                    # Saves additional ~4*150=600 tokens vs 12. Groq still 16 for TPM safety (reduced from 20), OpenAI 8 for latency.
                    # Determine history limit based on provider
                    try:
                        _llm_id_hist = (cfg.providers.llm.id or "").lower() if cfg.providers and cfg.providers.llm else ""
                        _is_groq_hist = _llm_id_hist.startswith("groq")
                        _history_limit = 16 if _is_groq_hist else 8
                        _trim_threshold = 20 if _is_groq_hist else 12
                    except Exception:
                        _history_limit = 8
                        _trim_threshold = 12
                    if isinstance(items, list):
                        # Cache fix (applies ALWAYS, not just when trimming): keep ONLY the stable
                        # behavioral instructions at the very beginning (id=lk.agent_task.instructions)
                        # as the cacheable prefix. All other system messages (prior_memory, lead_data,
                        # prior RAG if ever left) are dynamic per customer/lead/turn and must be AFTER
                        # history so the stable prefix remains byte-identical across turns and across
                        # customers (cross-customer cache sharing). This guarantees the provider-bound
                        # prompt starts with the identical stable head.
                        _stable_sys = []
                        _other_sys = []
                        for m in items:
                            if getattr(m, "role", "") == "system":
                                if getattr(m, "id", "") == "lk.agent_task.instructions":
                                    _stable_sys.append(m)
                                else:
                                    _other_sys.append(m)
                        # If no explicit instructions id found (older contexts), treat first system as stable
                        if not _stable_sys:
                            _all_sys = [m for m in items if getattr(m, "role", "") == "system"]
                            if _all_sys:
                                _stable_sys = [_all_sys[0]]
                                _other_sys = _all_sys[1:]
                        dialogue_items = [m for m in items if getattr(m, "role", "") != "system"]
                        if len(items) > _trim_threshold:
                            kept_dialogue = dialogue_items[-_history_limit:]
                        else:
                            kept_dialogue = dialogue_items
                        trimmed_count = len(dialogue_items) - len(kept_dialogue)
                        if trimmed_count > 0:
                            # Keep a bounded, verbatim window of this call's older
                            # dialogue in the existing system-memory path. This
                            # prevents context trimming from erasing caller facts
                            # without RAG or entity-specific extraction.
                            for _old_item in dialogue_items[:-_history_limit]:
                                _old_role = getattr(_old_item, "role", "")
                                _old_text = _chat_msg_text(_old_item).strip()
                                if _old_role in ("user", "assistant") and _old_text:
                                    _speaker = "Customer" if _old_role == "user" else "Agent"
                                    _in_call_memory_lines.append(f"{_speaker}: {_old_text}")
                            try:
                                _memory_budget = int(os.getenv("VOICE_PRIOR_MEMORY_BUDGET_CHARS", "800"))
                            except (TypeError, ValueError):
                                _memory_budget = 800
                            _memory_budget = max(1, _memory_budget)
                            _memory_text = "\n".join(_in_call_memory_lines)[-_memory_budget:]
                            _line_boundary = _memory_text.find("\n")
                            if _line_boundary != -1 and _line_boundary < _memory_budget * 0.3:
                                _memory_text = _memory_text[_line_boundary + 1:]
                            _in_call_memory_lines[:] = [_memory_text] if _memory_text else []
                            _memory_id = "voice.in_call_memory"
                            _memory_message = next(
                                (m for m in _other_sys if getattr(m, "id", "") == _memory_id),
                                None,
                            )
                            _memory_content = (
                                "Earlier turns from this call (verbatim context):\n" + _memory_text
                            )
                            if _memory_message is None:
                                _memory_message = target_ctx.add_message(
                                    role="system", content=_memory_content, id=_memory_id,
                                )
                                _other_sys.append(_memory_message)
                            else:
                                _memory_message.content = [_memory_content]
                            logger.info(
                                "🧠 [IN_CALL_MEMORY] archived_dialogue_items=%d retained_chars=%d",
                                trimmed_count, len(_memory_text),
                            )
                        # Order: stable behavioral → history (dynamic) → other dynamic system (prior_memory, lead_data)
                        # RAG for THIS turn is injected later with created_at just before final user, so it lands after history as well.
                        # For cache: stable at beginning, identical across turns/customers; dynamic after.
                        if len(items) > _trim_threshold or _other_sys:
                            target_ctx.items = _stable_sys + kept_dialogue + _other_sys
                        # else: no reordering needed (only stable present)
                        logger.info("🧹 Trimmed conversation context to %s messages (dialogue max=%s, older turns retained in bounded in-call memory)", len(target_ctx.items), _history_limit)
                        if trimmed_count > 0:
                            logger.info(f"📝 Trimmed {trimmed_count} old dialogue items, kept last {_history_limit} for memory retention (reduces input tokens)")
                except Exception as exc:
                    logger.debug("conversation context trim skipped: %s", exc)
            else:
                # Preemptive ON: DO NOT mutate chat_ctx at all — any mutation invalidates preemptive
                # Previous lenient trim (10 msgs when >12) still changed chat_ctx → is_equivalent False → invalidation
                # So when preemptive ON, skip trimming entirely to preserve preemptive generation
                # This eliminates "preemptive generation invalidated after on_user_turn_completed" warning
                # FIX: Also for memory, when preemptive ON and KB present, we already disabled preemptive in worker.py
                # So this path is for non-KB calls where preemptive ON is safe and we want speed
                logger.debug("Preemptive ON: skipping chat_ctx trim to preserve preemptive generation and memory")
            # Log timing for STT_final->LLM_start path
            try:
                _elapsed_goodbye = (_time.time() - _rag_t0) * 1000
                if _elapsed_goodbye > 50:
                    logger.warning(f"🐢 Slow goodbye detection: {_elapsed_goodbye:.0f}ms (should be <10ms)")
                else:
                    logger.info(f"⏱️ TIMING on_user_turn_completed (goodbye check): {_elapsed_goodbye:.0f}ms")
            except Exception:
                pass

            # RAG handling - ALWAYS enabled for KB grounding (correctness > latency)
            # When preemptive ON, RAG will invalidate preemptive for this turn, but we explicitly log it
            # This is the fix for "Mere paas exact jaankari nahi hai" - KB grounding preserved
            if not _rag_per_turn_enabled():
                logger.info(f"⏱️ TIMING on_user_turn_completed (RAG disabled by env): {(_time.time()-_rag_t0)*1000:.0f}ms")
                return
            try:
                user_text = _chat_msg_text(new_message).strip()
                if not user_text:
                    logger.info(f"⏱️ TIMING on_user_turn_completed (empty text): {(_time.time()-_rag_t0)*1000:.0f}ms")
                    return
                from ... import rag  # local import: keep this module light
                from ...turn_rules import is_contextual_followup, build_contextual_retrieval_query
                # If this turn completed a split thought, retrieve for the MERGED
                # question (fragments + this final) instead of the bare tail —
                # [COMPLETE_TURN] logged above shows the merge.
                _cq = (self._turn_timing_ref or {}).get("combined_query")
                if _cq:
                    user_text = str(_cq)

                # --- Conversational context for RAG (fix for pronoun follow-ups) ---
                # Preserve actual user message for LLM (new_message unchanged).
                # Only the INTERNAL retrieval query gets enriched with recent context.
                original_user_query = user_text
                retrieval_query = original_user_query
                recent_user_ctx = ""
                recent_assistant_ctx = ""
                context_used = False
                try:
                    _ctx_for_recent = _find_chat_ctx(turn_ctx)
                    if _ctx_for_recent is not None:
                        _items = getattr(_ctx_for_recent, "items", []) or []
                        # Find last user before current (not ack/incomplete, not same text)
                        for m in reversed(_items):
                            if getattr(m, "role", "") == "user":
                                _txt = _chat_msg_text(m).strip()
                                if not _txt or _txt == original_user_query or len(_txt) < 4:
                                    continue
                                try:
                                    from ...turn_rules import is_acknowledgement as _is_ack_r, is_incomplete_turn as _is_inc_r
                                    if _is_ack_r(_txt) or _is_inc_r(_txt):
                                        continue
                                except Exception:
                                    pass
                                recent_user_ctx = _txt
                                break
                        if not recent_user_ctx:
                            for m in reversed(_items):
                                if getattr(m, "role", "") == "assistant":
                                    _txt = _chat_msg_text(m).strip()
                                    if _txt and len(_txt) > 10:
                                        recent_assistant_ctx = _txt[:200]
                                        break
                except Exception:
                    recent_user_ctx = ""
                    recent_assistant_ctx = ""

                try:
                    if is_contextual_followup(original_user_query):
                        _ctx_candidate = recent_user_ctx or recent_assistant_ctx
                        if _ctx_candidate:
                            _built = build_contextual_retrieval_query(
                                original_user_query, recent_user_ctx, recent_assistant_ctx
                            )
                            if _built and _built != original_user_query:
                                retrieval_query = _built
                                context_used = True
                except Exception:
                    retrieval_query = original_user_query
                    context_used = False

                try:
                    logger.info(
                        "🔎 [RAG_CONTEXT_QUERY] user_query='%s' retrieval_query='%s' context_used=%s recent_len=%d",
                        original_user_query[:80],
                        retrieval_query[:120],
                        "yes" if context_used else "no",
                        len(recent_user_ctx or recent_assistant_ctx),
                    )
                except Exception:
                    pass

                logger.info(
                    "🔎 [RAG_STARTED] query='%s' retrieval_query='%s' context_used=%s",
                    original_user_query[:60],
                    retrieval_query[:60],
                    "yes" if context_used else "no",
                )
                # --- Fast path: the worker precomputes RAG from STT interim
                # text (in parallel with endpointing), so by the time the turn
                # completes the retrieval result for this exact text is usually
                # already cached. This hook is AWAITED by the session before the
                # LLM starts, so a cache hit removes ~30-100ms from EVERY turn.
                hits = ""
                _rag_src = "normal"
                # P3 ROOT-CAUSE FIX: initialize EVERY retrieval-result field
                # before either branch. Previously kb_used/faq_used & friends
                # were assigned ONLY on the cache-MISS path; the shared log
                # line after injection then raised UnboundLocalError on each
                # prefetch-HIT turn (surfacing as the misleading
                # "per-turn RAG injection skipped" warning — the context was in
                # fact injected). Both branches now produce the same structure.
                kb_used = False
                kb_chars = 0
                kb_hits = 0
                faq_used = False
                faq_chars = 0
                faq_hits = 0
                total_chars = 0
                _prefetch_entry = None
                if rag_prefetch is not None:
                    try:
                        # Prefetch cache is keyed by original normalized query (worker stores contextual result under original key)
                        _prefetch_entry = rag_prefetch.get(rag.normalize_query(original_user_query))
                        # Fallback: try retrieval_query key as well (in case worker stored under contextual key)
                        if _prefetch_entry is None and retrieval_query != original_user_query:
                            _prefetch_entry = rag_prefetch.get(rag.normalize_query(retrieval_query))
                    except Exception:
                        _prefetch_entry = None
                # The worker caches the full detailed result; tolerate the old
                # bare-string shape too so a worker/builder version skew cannot
                # turn a hit into a crash.
                if isinstance(_prefetch_entry, dict):
                    hits = (_prefetch_entry.get("text") or "").strip()
                elif isinstance(_prefetch_entry, str):
                    hits = _prefetch_entry.strip()
                else:
                    hits = ""
                if hits:
                    _rag_src = "prefetch"
                    if isinstance(_prefetch_entry, dict):
                        kb_used = bool(_prefetch_entry.get("kb_used", False))
                        kb_chars = int(_prefetch_entry.get("kb_chars", 0) or 0)
                        kb_hits = int(_prefetch_entry.get("kb_hits", 0) or 0)
                        faq_used = bool(_prefetch_entry.get("faq_used", False))
                        faq_chars = int(_prefetch_entry.get("faq_chars", 0) or 0)
                        faq_hits = int(_prefetch_entry.get("faq_hits", 0) or 0)
                        total_chars = int(_prefetch_entry.get("total_chars", len(hits)) or len(hits))
                    else:  # bare text (older worker): source flags unknown
                        kb_used = True
                        kb_chars = total_chars = len(hits)
                    _rag_elapsed = (_time.time() - _rag_t0) * 1000
                    logger.info(
                        "📚 [KNOWLEDGE_RETRIEVAL] query='%s' | latency=%.0fms | kb_used=%s (%d chars, %d hits) | faq_used=%s (%d chars, %d hits) | total=%d chars | prefetch=true",
                        retrieval_query[:60], _rag_elapsed, kb_used, kb_chars, kb_hits,
                        faq_used, faq_chars, faq_hits, total_chars,
                    )
                    logger.info(
                        "⚡ RAG PREFETCH HIT '%s' (%d chars) — computed during the STT interim, "
                        "critical-path cost %.0fms",
                        retrieval_query[:60], len(hits), _rag_elapsed,
                    )
                else:
                    # Cache miss (final text diverged from every interim, or the
                    # interim compute lost the race): compute now using contextual retrieval_query.
                    # Actual LLM user message (new_message) remains unchanged.
                    try:
                        rag_res = await asyncio.to_thread(rag.build_context_detailed, cfg.knowledge, retrieval_query, 3)
                    except Exception:
                        # Fallback sync if to_thread fails
                        rag_res = rag.build_context_detailed(cfg.knowledge, retrieval_query, top_k=3)
                    _rag_elapsed = (_time.time() - _rag_t0) * 1000
                    hits = (rag_res.get("text") or "").strip()
                    kb_used = rag_res.get("kb_used", False)
                    kb_chars = rag_res.get("kb_chars", 0)
                    kb_hits = rag_res.get("kb_hits", 0)
                    faq_used = rag_res.get("faq_used", False)
                    faq_chars = rag_res.get("faq_chars", 0)
                    faq_hits = rag_res.get("faq_hits", 0)
                    total_chars = rag_res.get("total_chars", 0)

                    # Authoritative user-facing retrieval log detailing KB and FAQ usage
                    logger.info(
                        "📚 [KNOWLEDGE_RETRIEVAL] query='%s' | latency=%.0fms | kb_used=%s (%d chars, %d hits) | faq_used=%s (%d chars, %d hits) | total=%d chars",
                        retrieval_query[:60],
                        _rag_elapsed,
                        kb_used,
                        kb_chars,
                        kb_hits,
                        faq_used,
                        faq_chars,
                        faq_hits,
                        total_chars,
                    )

                    if _rag_elapsed > 200:
                        logger.warning(f"🐢 Slow RAG: {_rag_elapsed:.0f}ms exceeds 100ms target")

                logger.info(
                    "🔎 [RAG_QUERY] query='%s' source=%s result_count=%d relevant_context_found=%s",
                    retrieval_query[:70], _rag_src, int(kb_hits) + int(faq_hits), "yes" if hits else "no",
                )
                # NOTE: deliberately NO "same as last turn" dedupe here. This hook
                # edits the per-turn copy of the chat context (temp_mutable_chat_ctx);
                # the library discards it after generation, so the previous turn's
                # injected facts are NOT in this turn's prompt. Skipping injection on
                # "no new hits" (the old behavior) silently left repeat-question turns
                # ungrounded (23:19 log: identical kb result -> "RAG no new hits" ->
                # model answered from generic priors). Same text = same injection cost
                # (~600 tokens); correctness wins.
                _rag_kind = "retrieved"
                target = _find_chat_ctx(turn_ctx)
                _nstripped = _strip_trailing_ack_turns(target)
                if _nstripped:
                    logger.info("🧹 [ACK_STRIPPED] removed %d trailing acknowledgement assistant message(s) from this turn's generation context (per-turn copy only — session history untouched)", _nstripped)
                if not hits:
                    # ---- 0-hit turn: ONE cheap containment fallback over the
                    # cached corpus (rag.fallback_context — BM25/ranking
                    # untouched, runs in a thread so the loop stays free).
                    # STT-mangled keywords ("Kriscent" heard as "sent") share
                    # no exact token with any chunk, so main retrieval is
                    # legitimately empty; containment still finds the chunk
                    # containing the fragment, capped at ~560 chars. If the
                    # fallback also finds nothing, the request proceeds
                    # ungrounded — the prompt tells the model to say so
                    # honestly instead of guessing.
                    _fb_text = ""
                    _fb_hits = 0
                    try:
                        _fb_text, _fb_hits = await asyncio.to_thread(
                            rag.fallback_context, cfg.knowledge, retrieval_query
                        )
                    except Exception as _fb_exc:
                        logger.debug("RAG fallback failed: %r", _fb_exc)
                    if _fb_text:
                        hits = _fb_text
                        _rag_kind = "near-match"
                        logger.info(
                            "🕳️ [RAG_MISS] query='%s' fallback_attempted=yes fallback_hits=%d fallback_context_chars=%d",
                            retrieval_query[:70], _fb_hits, len(_fb_text),
                        )
                    else:
                        logger.info(
                            "🕳️ [RAG_MISS] query='%s' fallback_attempted=yes fallback_hits=0 fallback_context_chars=0",
                            retrieval_query[:70],
                        )
                        logger.info("🧠 [LLM_CONTEXT] user_query='%s' rag_context_present=no", retrieval_query[:70])
                        logger.info(f"⏱️ TIMING on_user_turn_completed (no RAG hits): {(_time.time()-_rag_t0)*1000:.0f}ms")
                        return  # nothing to inject, main retrieval AND fallback came up empty
                if target is None:
                    logger.warning("⚠️ RAG: no chat_ctx found, skipping injection")
                    return
                
                # FIX ROOT CAUSE: When KB/FAQ RAG enabled, preemptive must be disabled BEFORE turn begins
                rag_enabled = True
                try:
                    import os as _os_rag_check
                    v = (_os_rag_check.getenv("VOICE_RAG_PER_TURN") or "").strip().lower()
                    if v in ("0", "false", "off"):
                        rag_enabled = False
                except Exception:
                    rag_enabled = True
                
                if preemptive_on and rag_enabled:
                    logger.info(f"🔧 RAG+preemptive: KB grounding needed ({len(hits)} chars) but preemptive already disabled at session level (rag_enabled={rag_enabled}, env preemptive={preemptive_on}) - no invalidation, exactly one REQUEST START per turn (query: {retrieval_query[:60]})")
                elif preemptive_on:
                    logger.info(f"🔍 RAG+preemptive conflict: KB grounding needed ({len(hits)} chars) will invalidate preemptive for this turn — preserving correctness over latency (query: {retrieval_query[:60]})")
                
                if _rag_kind == "near-match":
                    _header = (
                        f"{_RAG_PREFIX} NEAR-MATCH business context (the exact question "
                        "keywords were not found in the knowledge base; use ONLY statements "
                        "this excerpt makes verbatim, do not stretch it to fit the question):"
                    )
                else:
                    _header = (
                        f"{_RAG_PREFIX} Relevant business facts for THIS specific question:"
                    )
                # 11:41 log defect #1 (ORDER, not presence — final_user=0c
                # explained): agent_activity creates user_message BEFORE this
                # hook, then inserts it into the generation ctx by
                # created_at (_pipeline_reply_task_impl: chat_ctx.insert()).
                # A plain add_message() stamps created_at=NOW — newer than the
                # question — so [RAG] landed AFTER it: [..., USER question,
                # [RAG] system]. The question was never the last message and
                # the trailing system line read like new instructions. Anchor
                # the block 1ms before the question instead: the library then
                # slots the question right behind it — [..., [RAG] facts,
                # USER question] — facts precede the question it grounds, and
                # the question is last (stable prefix → dynamic RAG → user
                # content, per the cache-prefix contract).
                _inj_at = float(getattr(new_message, "created_at", 0.0) or 0.0) - 0.001
                if _inj_at <= 0:
                    _inj_at = _time.time() - 0.001
                target.add_message(
                    role="system",
                    content=f"{_header}\n{hits}",
                    created_at=_inj_at,
                )
                logger.info(f"✅ [RAG_DONE] RAG injected {len(hits)} chars for query: {retrieval_query[:80]} (kb_used={kb_used}, faq_used={faq_used}) original='{original_user_query[:60]}'")
                logger.info("🧠 [LLM_CONTEXT] user_query='%s' rag_context_present=yes (chars=%d, kind=%s)", retrieval_query[:70], len(hits), _rag_kind)
            except Exception as e:
                # RAG only *enriches* the turn context: a retrieval failure must
                # never gate or delay the LLM reply (brief P4). Log loudly with
                # the real exception, then fall through so LiveKit generates.
                logger.warning(f"⚠️ per-turn RAG handling raised {type(e).__name__}: {e!r} — LLM reply still proceeds ungrounded for this turn")
                logger.info(f"⏱️ TIMING on_user_turn_completed (RAG error, fallback): {(_time.time()-_rag_t0)*1000:.0f}ms")

    return _VoiceAgent()


# ---------------------------------------------------------------------------
# Announcement / fixed-script "reminder" agent — no STT, no LLM
# ---------------------------------------------------------------------------
