from __future__ import annotations

import time
import asyncio
import logging
from typing import Any, Optional

from ...models import AgentConfig

logger = logging.getLogger("voice-agent-saas-agent-builder")


# cross-module imports (auto-generated)
from .ab_instructions import build_instructions
from .ab_opening import speak_opening_line, wait_until_caller_can_hear
from .ab_end_call_tool import build_end_call_tool
from .ab_turn_governor import govern_and_trim
from .ab_turn_rag import apply_per_turn_rag
from .ab_turn_preamble import prepare_turn

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
    # Shared closing-guard cell (read by the end_call tool; flipped by the
    # turn hooks). Was a nonlocal boolean; a dict cell keeps the exact
    # same shared-cell semantics across the extracted modules.
    closing_state = {"explicit_goodbye": False}
    agent_ref: dict[str, Any] = {"instance": None}

    # Auto hang-up: when the conversation is finished the LLM calls `end_call`,
    # which shuts the job down so the call is cut AND the billing is finalized.
    # We make the trigger explicit so the model reliably hangs up on its own and
    # doesn't leave the caller in a silent, open call. Closing speech is now
    # deterministic: the tool itself speaks the fixed closing line.
    instructions += (
        "\n\nCALL LIFECYCLE: keep the call open after every normal answer, pause or detail-collection turn. End the call ONLY on a clear, standalone goodbye or hang-up grant in any language ('bye', 'ok bye', 'thank you' as a closer, 'that\'s all', 'no more questions/help', 'फ़ोन रख दीजिए', 'कॉल काट दीजिए', 'मुझे कुछ और नहीं चाहिए/जानना'). 'ok', or 'that\'s all for this question' followed by another question, is NOT a goodbye. On a real goodbye do not compose a closing sentence yourself: call the end_call tool once — the system speaks the fixed closing line and hangs up. Never call end_call at any other time."
    )

    # In-call memory digest lines — shared cell used by the turn engine
    # (writes) and the end_call tool (final memory save). Same semantics as the
    # original builder-scope list.
    _in_call_memory_lines = []
    end_call_tool, chat_ctx = build_end_call_tool(
        cfg, lead_data, llm, agent_ref, closing_state, prior_memory, _in_call_memory_lines)

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
            pre = prepare_turn(self, new_message, closing_state)
            user_text, _rag_t0 = pre["user_text"], pre["_rag_t0"]

            gov = await govern_and_trim(self, turn_ctx, new_message, user_text, _rag_t0,
                                        closing_state["explicit_goodbye"], cfg, _in_call_memory_lines)
            if gov["stop"]:
                return
            await apply_per_turn_rag(self, turn_ctx, new_message, cfg, rag_prefetch,
                                     user_text, gov["preemptive_on"], _rag_t0)

    return _VoiceAgent()

