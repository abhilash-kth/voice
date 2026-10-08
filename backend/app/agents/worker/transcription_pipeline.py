"""User-input transcription pipeline: barge-in cancellation + RAG prefetch.

Extracted verbatim from `w_entrypoint.py` (<=300-line rule). Contains:
  * `_precompute_rag` — retrieval runs on each STT interim so the awaited
    on_user_turn_completed hook becomes a dict lookup (~0ms).
  * `_on_transcription` — immediate barge-in cancellation on the first
    transcript edge while the agent speaks, greeting-cancel handling,
    turn-timing bookkeeping, no-response watchdog reset, stall-probe arming.
"""
from __future__ import annotations

import asyncio
import logging
import time

logger = logging.getLogger("voice-agent-saas-worker")


def build_user_input_transcription(ctx, session, turn_timing, state_tracker,
                                   usage, cfg, agent_mode, late,
                                   _instrument_sync_callback):
    """Wire the user_input_transcribed handler; returns the rag_prefetch dict."""

    # RAG precomputation (latency): the session AWAITs on_user_turn_completed
    # before the LLM starts, and per-turn RAG (BM25 over the knowledge base)
    # used to run inside that hook — 27-105ms+ added to every single turn.
    # Instead, run retrieval on each STT interim (while the user is still
    # finishing the sentence, i.e. during the endpointing silence) and cache
    # the result by normalized text. The final text almost always matches the
    # last interim, so the awaited hook becomes a dict lookup (~0ms).
    # ------------------------------------------------------------------
    rag_prefetch: dict = {}
    rag_prefetch_inflight: set = set()
    # Late-bound wiring: the no-response scheduler + reply-stall probe are
    # defined further down in the entrypoint (they were late-bound in the
    # original closure too — they only run after session start). The caller
    # fills `late` once those functions exist.
    def _schedule_no_response(*a, **k):
        return late["schedule_no_response"](*a, **k)
    def _arm_stall_probe(*a, **k):
        return late["arm_stall_probe"](*a, **k)

    # [USER_SPEECH_STARTED] edge detector state (mutable cells; updated from
    # the transcription handler, which is sync and loop-local).
    _last_tx_ts = [0.0]
    _last_bargein_ts = [0.0]  # edge debounce for the immediate barge-in interrupt

    def _precompute_rag(text: str) -> None:
        try:
            from app import rag as _rag_mod
            from app.turn_rules import is_contextual_followup as _is_ctx, build_contextual_retrieval_query as _build_ctx_q
            key = _rag_mod.normalize_query(text)
        except Exception:
            return
        if len(key) < 4 or key in rag_prefetch or key in rag_prefetch_inflight:
            return
        if _rag_mod.is_acknowledgement(text):
            return  # "Ok," etc — answered deterministically by llm_node; no retrieval
        if _rag_mod.is_incomplete_turn(text):
            return  # fragment will be merged into the completed turn; don't spend CPU

        # --- Conversational context for prefetch (same logic as builder hook) ---
        # Uses only immediately preceding user turn, not entire conversation.
        # Actual LLM user message remains unchanged; only retrieval query enriched.
        recent_user = ""
        try:
            for entry in reversed(usage.get("transcripts", [])):
                if entry.get("role") == "user":
                    t = (entry.get("text") or "").strip()
                    if t and t != text and len(t) >= 4:
                        try:
                            if not _rag_mod.is_acknowledgement(t) and not _rag_mod.is_incomplete_turn(t):
                                recent_user = t
                                break
                        except Exception:
                            recent_user = t
                            break
        except Exception:
            recent_user = ""

        retrieval_query = text
        context_used = False
        try:
            if recent_user and _is_ctx(text):
                _built = _build_ctx_q(text, recent_user)
                if _built and _built != text:
                    retrieval_query = _built
                    context_used = True
        except Exception:
            retrieval_query = text
            context_used = False

        try:
            if context_used:
                logger.info(
                    "🔎 [RAG_CONTEXT_QUERY] user_query='%s' retrieval_query='%s' context_used=yes source=prefetch recent_len=%d",
                    text[:80],
                    retrieval_query[:120],
                    len(recent_user),
                )
        except Exception:
            pass

        rag_prefetch_inflight.add(key)

        async def _work():
            try:
                from app import rag as _rag_mod
                res = await asyncio.wait_for(
                    asyncio.to_thread(_rag_mod.build_context_detailed, cfg.knowledge, retrieval_query, 3),
                    timeout=4,
                )
                hits = (res.get("text") or "").strip()
                if hits:
                    if len(rag_prefetch) > 8:   # bound the cache to one utterance worth
                        rag_prefetch.pop(next(iter(rag_prefetch)))
                    # Store the FULL detailed structure (text + kb/faq flags),
                    # not just the text — the turn hook then reports prefetch
                    # HITs with the exact same result structure as a MISS.
                    # Key is original normalized query so final-turn lookup hits,
                    # but result was built with contextual retrieval_query.
                    rag_prefetch[key] = res
            except Exception as e:
                logger.debug(f"RAG precompute skipped: {e!r}")
            finally:
                rag_prefetch_inflight.discard(key)

        try:
            asyncio.ensure_future(_work())
        except Exception:
            rag_prefetch_inflight.discard(key)

    def _on_transcription(ev) -> None:
        try:
            # v1 UserInputTranscribedEvent carries `.transcript` (+ `.is_final`);
            # legacy "transcription" events used `.text`.
            text = getattr(ev, "transcript", None) or getattr(ev, "text", None) or ""
            is_final = bool(getattr(ev, "is_final", False))
            # --- Immediate barge-in cancellation (2026-09-24 00:53 log) ---
            # The library gates its own interruption behind min_words=2 +
            # turn-commit logic, so "Ok" (1 word) at 00:53:34.191 was detected
            # but the agent kept talking until 00:53:35.770 — 1.57s of
            # non-interruptible output, with the (truncated) assistant item
            # committing at 00:53:35.857. We keep the library gate as-is and
            # add our own trigger on the FIRST transcript edge while the agent
            # is speaking: session.interrupt() is the library's supported
            # cancellation (AgentActivity.interrupt -> cancels preemptive
            # generation + the live LLM/TTS tasks + flushes playback, commits
            # only the already-played audio as the assistant item, then flips
            # speaking->listening). force=False so protected speeches — the
            # deterministic closing say() with allow_interruptions=False —
            # keep playing. Stale-output protection: turn_timing["gen"] is
            # bumped here BEFORE interrupting, and every LLM stream stamps its
            # birth gen in the timing wrapper; a late callback from an
            # invalidated generation logs [STALE_GENERATION_DROPPED] instead
            # of touching this turn's timing.
            try:
                if text.strip() and not is_final and state_tracker.get("state") == "speaking":
                    _now_b = time.time()
                    if _now_b - _last_bargein_ts[0] <= 0.30:
                        pass  # debounce: one cancellation per user-utterance onset
                    elif turn_timing.get("is_closing", False):
                        logger.info("🔇 [AGENT_INTERRUPTED_BY_USER] caller resumed speech during the protected closing speech — not interrupting")
                    else:
                        _gen0 = int(turn_timing.get("gen", 0))
                        _llm_was = bool(turn_timing.get("llm_active", False))
                        _in_greet = bool(turn_timing.get("greeting_active", False))
                        _last_bargein_ts[0] = _now_b
                        turn_timing["last_bargein_ts"] = _now_b
                        if _in_greet:
                            logger.info("🗣️ [USER_SPEECH_DURING_GREETING] caller spoke over the greeting: '%s' — cancelling, not waiting for min_words/turn-commit", text.strip()[:40])
                        logger.info("🔇 [AGENT_INTERRUPTED_BY_USER] caller resumed speech — interrupting immediately (no wait for the min_words gate / turn commit)")
                        logger.info("⚡ [INTERRUPTION_START] generation=%d transcript='%s'", _gen0, text.strip()[:40])
                        if _llm_was:
                            # interrupt() below tears the pipeline down; annotate the
                            # intent up front so the completion log pairs read right.
                            logger.info("🧠 [LLM_CANCELLED] reason=user_barge_in generation=%d", _gen0)
                        logger.info("🔈 [TTS_CANCELLED] reason=user_barge_in generation=%d (playback flush + truncate via SpeechHandle)", _gen0)
                        turn_timing["gen"] = _gen0 + 1
                        logger.info("🚫 [GENERATION_INVALIDATED] generation=%d — current is now %d; late callbacks from %d cannot publish", _gen0, _gen0 + 1, _gen0)
                        try:
                            _fut = session.interrupt()
                            if _in_greet:
                                logger.info("⛔ [GREETING_INTERRUPTED] generation=%d — greeting speech + TTS + playback cancelled", _gen0)

                            def _barge_done(_f, _g=_gen0, _ig=_in_greet):
                                try:
                                    if not _f.cancelled() and _f.exception() is None:
                                        logger.info("✅ [INTERRUPTION_COMPLETE] generation=%d — agent returned to listening", _g)
                                        if _ig:
                                            # session.interrupt()'s future completes only AFTER the
                                            # library finished teardown: playback flushed, the
                                            # played-partial committed to chat_ctx, state ->
                                            # listening. That is the proof the greeting AUDIO
                                            # stopped (not just a log). tell the builder on_enter.
                                            turn_timing["greeting_interrupted"] = True
                                            turn_timing["greeting_bargein_ts"] = time.time()
                                            logger.info("🔇 [GREETING_CANCELLED] generation=%d — greeting audio actually stopped (playout flushed + partial committed)", _g)
                                            # "when I interrupt the greeting it should ALSO
                                            # listen": from this instant the floor belongs to
                                            # the caller. The 6s apology is suppressed while
                                            # this window is fresh (see _silence_fallback) and
                                            # the 30s no-response watchdog still guards real
                                            # silence — the agent waits like a human being
                                            # interrupted, it does not talk back over them.
                                            logger.info("👂 [GREETING_LISTENING] caller owns the floor — agent listens until their utterance endpoint-finishes; no apology, no resume")
                                except Exception:
                                    pass

                            _fut.add_done_callback(_barge_done)
                        except RuntimeError as _ie:
                            # session not running / current speech disallows
                            # interruptions: nothing we should force past.
                            logger.info("ℹ️ immediate interrupt skipped: %s", _ie)
            except Exception:
                pass
            if text.strip():
                _precompute_rag(text)
                # P4 marker — utterance-start edge: first transcript after a
                # >0.7s gap is treated as [USER_SPEECH_STARTED] (interims fire
                # every ~200ms, so logging each one would spam the call log).
                _now = time.time()
                if _now - _last_tx_ts[0] > 0.7:
                    _last_tx_ts[0] = _now
                    turn_timing["stt_final_ts"] = 0.0
                    turn_timing["turn_commit_ts"] = 0.0
                    turn_timing["llm_request_start_ts"] = 0.0
                    logger.info("🎙️ [USER_SPEECH_STARTED] first transcript: '%s'", text.strip()[:60])
            else:
                _last_tx_ts[0] = time.time()
            # P5 ROOT-CAUSE FIX (watchdog sync, 2026-09-23 call at 21:45):
            # the no-response watchdog was cancelled ONLY via
            # conversation_item_added / agent_state_changed. When the reply
            # pipeline stalled (no LLM ever started), neither event fired, so
            # the 30s timer armed at greeting-end FIRED while the user was
            # actively speaking and the call was auto-cut. STT finals are
            # authoritative proof of user activity that flows on its own event
            # (this handler is what drives RAG prefetch, so it demonstrably
            # works even when the reply pipeline wedges): reset the clock on
            # every final with text. Interims don't reset — they fire too
            # often; a user mid-utterance emits finals every few seconds
            # anyway (STT endpointing).
            if is_final and text.strip():
                logger.info("📝 [USER_TRANSCRIPT_FINAL] '%s'", text.strip()[:80])
                _final_ts = time.time()
                turn_timing["stt_final_ts"] = _final_ts
                turn_timing["stt_final_mono_ns"] = time.monotonic_ns()
                turn_timing["turn_id"] = int(turn_timing.get("turn_id", 0)) + 1
                turn_timing["pipeline_stage"] = "stt_final"
                logger.info("[TURN_TRACE] stage=stt_final monotonic_ns=%d call_id=%s room=%s turn_id=%s generation_id=%s", turn_timing["stt_final_mono_ns"], turn_timing.get("call_id"), getattr(ctx.room, "name", ""), turn_timing["turn_id"], turn_timing.get("gen", 0))
                # STT final does not expose the acoustic speech-end timestamp.
                # Keep this stage unavailable rather than reporting endpointing
                # configuration as though it were a measured duration.
                turn_timing["speech_end"] = 0.0
                logger.info("⏱️ [TURN_TIMING] speech_end_to_stt_final_ms=N/A source=timestamp_unavailable")
                # A newer final supersedes any uncommitted final. Avoid
                # carrying commit/request timestamps across that boundary.
                turn_timing["turn_commit_ts"] = 0.0
                turn_timing["llm_request_start_ts"] = 0.0
                # [PREEMPTIVE] would_cancel (Task 3, 2026-09-24): this FINAL
                # arrived while the agent was mid-speech/thinking. Under naive
                # speculative generation each one = a speculative request to
                # cancel+discard (billed tokens, no reuse) — and in THIS call
                # style these continuations are the NORM (fragment merges).
                if turn_timing.get("agent_state") in ("speaking", "thinking"):
                    turn_timing["spec_would_cancel"] = int(turn_timing.get("spec_would_cancel", 0)) + 1
                    logger.info("🔇 [PREEMPTIVE] would_cancel=1 (FINAL during '%s' state — avoided by design)", turn_timing.get("agent_state"))
                # One call does it all: cancels the armed window (single
                # [WATCHDOG_CANCELLED]+[WATCHDOG_ARMED] log) and starts a fresh
                # full window measured from this utterance.
                _schedule_no_response(reason="user_transcript_final")
                # P4 diagnostic: start the reply-stall probe for this turn.
                _arm_stall_probe(text.strip())
        except Exception:
            pass

    if agent_mode != "announcement":
        # livekit-agents v1 emits "user_input_transcribed" for every STT interim
        # and final; the legacy "transcription" event never fires on 1.x, so we
        # attach the single live event name.
        attached_events = []
        for _ev_name in ("user_input_transcribed",):
            try:
                session.on(_ev_name, _instrument_sync_callback("user_input_transcribed", _on_transcription))
                attached_events.append(_ev_name)
            except Exception:
                continue
        if attached_events:
            logger.info(f"🔧 RAG precompute armed on STT events: {attached_events}")
        else:
            logger.debug("transcription hook unavailable (RAG precompute off)")
    return rag_prefetch
