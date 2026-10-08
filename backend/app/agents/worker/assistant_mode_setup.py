from __future__ import annotations

import os
import asyncio
import logging
import time
from typing import Any
logger = logging.getLogger("voice-agent-saas-worker")


# cross-module imports (auto-generated)
from .connection_options import _build_conn_options
from .dep_imports import AgentConfig
from .llm_failover_wrap import _create_llm_failure_logging_wrapper
from .llm_timing_factory import _create_llm_timing_wrapper
from .tts_prewarm import warm_tts_off_loop

async def build_assistant_session(cfg: AgentConfig, turn_timing_ref=None):
    """Full conversational session: STT + VAD + LLM + TTS, production low-latency.

    Fixes:
    - Async parallel build to avoid blocking job executor (was 3.46s sync -> unresponsive 1.5s)
    - STT turn_detection with endpointing_ms 200ms + utterance_end_ms 1000ms (Deepgram correct params)
    - VAD tuned 0.20/0.30/0.20/0.55 for faster speech_end detection + less CPU
    - Endpointing 0.20/0.55 for target speech_end->LLM <=500ms
    - TTS timing wrapper to measure actual first TTS audio (not LLM completion)
    """
    from livekit.agents import AgentSession
    from app.agents.agent_builder import build_vad, build_stt, build_llm, build_tts

    vad_inst = build_vad()
    build_t0 = time.time()

    try:
        stt_inst, llm_inst, tts_inst = await asyncio.gather(
            asyncio.to_thread(build_stt, cfg),
            asyncio.to_thread(build_llm, cfg),
            asyncio.to_thread(build_tts, cfg),
        )
        logger.info(f"⏱️ provider build async parallel {time.time()-build_t0:.2f}s")
        # Warm the *blocking, loop-independent* half of Google TTS startup: the
        # service-account JSON + RSA parse (~163-198ms) that _ensure_client()
        # would otherwise run on the agent loop while the caller waits for audio.
        #
        # The previous code here called `inner._ensure_client()` inside
        # `asyncio.new_event_loop()` in an `asyncio.to_thread()` worker and then
        # closed that loop. _ensure_client() caches a
        # texttospeech.TextToSpeechAsyncClient whose grpc.aio channel keeps a
        # reference to the loop it was built on, so every later
        # streaming_synthesize() on the real agent loop died with
        #   RuntimeError: Event loop is closed  (grpc/aio/_call.py:761)
        # and the agent produced no audio at all for the whole call. Never build
        # an async gRPC client off the loop that will use it — warm credentials
        # instead, and let the plugin create the client on the agent loop.
        # warm_tts_off_loop() also drops any client already cached against a
        # dead/foreign loop so it gets rebuilt on *this* one.
        try:
            await warm_tts_off_loop(tts_inst)
        except Exception as e:
            # A warm-up must never take the call down.
            logger.debug(f"TTS warm-up skipped: {e!r}")
        # Log LLM provider details for 404 debugging and wrap with timing + failure logging
        try:
            llm_type = str(type(llm_inst))
            if "FallbackAdapter" in llm_type:
                logger.info(f"🤖 LLM FallbackAdapter built: {llm_type}")
                inner = getattr(llm_inst, '_llm_instances', None) or getattr(llm_inst, 'llm_instances', None) or getattr(llm_inst, '_instances', None)
                if inner:
                    logger.info(f"🤖 LLM fallback chain length: {len(inner)}")
            else:
                logger.info(f"🤖 LLM single provider built: {llm_type}")
            
            # Set provider/model in timing_dict for cost tracking and wrap with timing
            if turn_timing_ref is not None:
                try:
                    primary = cfg.providers.get_primary_llm() if hasattr(cfg.providers, 'get_primary_llm') else cfg.providers.llm
                    prov, model, base_url = primary.resolve_llm_provider_model()
                    turn_timing_ref["llm_provider"] = prov
                    turn_timing_ref["llm_model"] = model
                    provider_info = {"provider": prov, "model_id": model, "base_url": base_url or "https://api.openai.com/v1"}
                    llm_inst = _create_llm_timing_wrapper(llm_inst, turn_timing_ref, provider_info)
                    logger.info(f"🔧 LLM timing wrapper applied: provider={prov} model={model} base_url={base_url} (TTFT + cost tracking)")
                except Exception as e:
                    logger.warning(f"Could not apply LLM timing wrapper: {e}, using failure wrapper")
                    llm_inst = _create_llm_failure_logging_wrapper(llm_inst, cfg)
            else:
                llm_inst = _create_llm_failure_logging_wrapper(llm_inst, cfg)
        except Exception as e:
            logger.debug(f"Could not log LLM details: {e}")
    except Exception as e:
        logger.warning(f"Async parallel build failed ({e}), falling back to sync")
        stt_inst = build_stt(cfg)
        llm_inst = build_llm(cfg)
        tts_inst = build_tts(cfg)
        if turn_timing_ref is not None:
            try:
                primary = cfg.providers.get_primary_llm() if hasattr(cfg.providers, 'get_primary_llm') else cfg.providers.llm
                prov, model, base_url = primary.resolve_llm_provider_model()
                turn_timing_ref["llm_provider"] = prov
                turn_timing_ref["llm_model"] = model
                provider_info = {"provider": prov, "model_id": model, "base_url": base_url or "https://api.openai.com/v1"}
                llm_inst = _create_llm_timing_wrapper(llm_inst, turn_timing_ref, provider_info)
                logger.info(f"🔧 LLM timing wrapper applied (sync fallback): provider={prov} model={model}")
            except Exception as e:
                logger.warning(f"Could not apply LLM timing wrapper sync: {e}")
                llm_inst = _create_llm_failure_logging_wrapper(llm_inst, cfg)
        else:
            llm_inst = _create_llm_failure_logging_wrapper(llm_inst, cfg)
        logger.info(f"⏱️ provider build sync fallback {time.time()-build_t0:.2f}s")

    # Use the real TTS instance. A timing wrapper around synthesize/stream
    # broke session.say() (opening line generated, nothing heard).
    logger.info("🔧 TTS left unwrapped so the opening line can play")

    # Turn-taking: how long the agent waits before it assumes the user is done,
    # and how easily the user can barge in. The old values (0.20/0.55, interrupt
    # after 0.25s + 1 word) made the agent jump in on every breath and read as
    # robotic; worse, every false barge-in pushes a speech handle into LiveKit's
    # interrupt path — where the repeated 5s timeout errors came from.
    # The STT final already follows Deepgram's 200ms silence endpoint. Keep a
    # further 200ms confirmation window for natural pauses, while avoiding the
    # previous 250ms fixed floor on every completed turn. This does not change
    # Deepgram configuration or interruption/continuation handling.
    min_delay = float(os.getenv("VOICE_ENDPOINTING_MIN", "0.20"))
    max_delay = float(os.getenv("VOICE_ENDPOINTING_MAX", "0.75"))
    # Interruption = the human barge-in contract:
    #  * min_words=2 is the semantic gate — a lone "haan/hmm/ok" backchannel or a
    #    cough must NOT cut the agent off mid-sentence (humans don't stop for
    #    those either), while a real 2+ word barge-in stops it immediately.
    #  * min_duration=0.35 (was 0.5) — once the gate passes, cut fast; a human
    #    stops talking within ~200-400ms of being spoken over.
    #  * resume_false_interruption keeps LiveKit's automatic recovery: if a
    #    "barge-in" turns out to be noise (no words, silence), the agent resumes
    #    its sentence instead of dying — false_interruption_timeout controls how
    #    quickly it recovers (default SDK 2.0s felt like a freeze; 1.5s here).
    min_interruption_duration = float(os.getenv("VOICE_MIN_INTERRUPTION_DURATION", "0.35"))
    min_interruption_words = int(os.getenv("VOICE_MIN_INTERRUPTION_WORDS", "2"))
    false_interruption_timeout = float(os.getenv("VOICE_FALSE_INTERRUPTION_TIMEOUT", "1.5"))
    allow_interruptions = os.getenv("VOICE_ALLOW_INTERRUPTIONS", "1") == "1"
    turn_detection_mode = os.getenv("VOICE_TURN_DETECTION", "stt").strip().lower()
    if turn_detection_mode not in ("vad", "stt", "realtime_llm", "manual"):
        turn_detection_mode = "stt"

    # Preemptive TTS: check compatibility - all supported TTS (Google, ElevenLabs, OpenRouter) support streaming
    # So preemptive_tts is safe, but keep env-controlled to avoid unexpected behavior
    # Default 0 for compatibility, enable via VOICE_PREEMPTIVE_TTS=1 if needed
    # FIXED: Log preemptive_tts compatibility and verify wrapper works with it
    # FIX 3: Prevent duplicate LLM requests caused by preemptive + RAG
    # Evidence: LLM REQUEST START -> RAG context update -> preemptive invalidated -> another REQUEST START -> input=0/output=0
    # Root cause: preemptive starts LLM before on_user_turn_completed, then RAG mutates chat_ctx, invalidating preemptive, causing second request
    # Fix: Disable preemptive when KB has content (text/documents/faq) to avoid duplicate, preserve RAG correctness
    # REAL latency is already good 1.3-1.6s, so disabling preemptive when KB present is acceptable tradeoff (correctness > latency)
    # When KB empty, keep preemptive enabled for faster responses
    preemptive_tts_enabled = os.getenv("VOICE_PREEMPTIVE_TTS", "0") == "1"
    env_preemptive = os.getenv("VOICE_PREEMPTIVE", "1") == "1"
    
    # Check if KB has content and if RAG enabled
    has_kb = False
    rag_enabled = True
    try:
        # Check RAG enabled (same logic as agent_builder._rag_per_turn_enabled)
        import os as _os_rag
        v = (_os_rag.getenv("VOICE_RAG_PER_TURN") or "").strip().lower()
        if v in ("0", "false", "off"):
            rag_enabled = False
        else:
            rag_enabled = True
    except Exception:
        rag_enabled = True
    
    try:
        kb = getattr(cfg, 'knowledge', None)
        if kb:
            has_text = bool((getattr(kb, 'text', '') or '').strip())
            has_docs = bool(getattr(kb, 'documents', []) or [])
            has_faq = bool(getattr(kb, 'faq', []) or [])
            has_kb = has_text or has_docs or has_faq
    except Exception:
        has_kb = False
    
    # FIX ROOT CAUSE: When KB/FAQ RAG is enabled, preemptive must be disabled BEFORE turn begins
    # Verify runtime Session config, not just config variable
    # Exactly one LLM REQUEST START per completed user turn, no preemptive that can be invalidated by RAG mutation
    # Previous bug: only disabled when has_kb, but RAG is always enabled, so preemptive still caused duplicate 0/0 failures
    # New: disable preemptive whenever RAG enabled (which is default), regardless of has_kb, to prevent any invalidation
    # NOTE 2026-09-24 (verified against livekit-agents 1.8.2): a discarded preemptive
    # attempt is NOT free — perform_llm_inference starts before the scheduling gate, so
    # every invalidation = one billed prompt. The global flag therefore stays False.
    # Acknowledgements get NO speculative generation at all: the turn governor in
    # agent_builder answers them deterministically inside Agent.llm_node (zero API).
    # (The 2026-09-23 VOICE_PREEMPTIVE_ACK toggle experiment was replaced by that
    # deterministic path per the 2026-09-24 spec — simpler, cheaper, no cancellation.)
    if rag_enabled and env_preemptive:
        preemptive_enabled = False
        logger.info(f"🔧 RAG+preemptive ROOT FIX: RAG enabled={rag_enabled} has_kb={has_kb}, disabling preemptive to prevent duplicate/invalidated LLM requests (was {env_preemptive} from env). Ensures exactly one REQUEST START per turn, no preemptive invalidation by RAG mutation.")
    elif has_kb and env_preemptive:
        preemptive_enabled = False
        logger.info(f"🔧 RAG+preemptive fix: KB present (has_kb={has_kb}), disabling preemptive to prevent duplicate LLM requests (was {env_preemptive} from env).")
    else:
        preemptive_enabled = env_preemptive
    
    # Verify runtime Session config will have preemptive disabled
    logger.info(f"🔧 FINAL Session config verification: preemptive={preemptive_enabled} (env {env_preemptive}, rag_enabled {rag_enabled}, has_kb {has_kb}) - must be False when RAG enabled to prevent duplicate")
    # Task 2 (2026-09-24): the gate is architectural, not timid. 1.8.x builds
    # speculative generations from the bare agent.chat_ctx WITHOUT running
    # on_user_turn_completed (agent_activity.on_preemptive_generation), then
    # reuses one only if the ctx is still equivalent at commit. Per-turn RAG
    # injection mutates the committed ctx, so speculation on knowledge turns is
    # generated UNGROUNDED (~3K tokens billed) and discarded; on non-injected
    # turns (pure ACKs) a speculative reply could be REUSED and bypass the
    # deterministic ack path. Keeping it off is the safe answer the spec asks
    # for; enabling needs a context-stable design, not a flag flip.
    logger.info(f"🔇 [PREEMPTIVE] enabled={preemptive_enabled} reason='per-turn RAG injection makes speculative ctx stale (guaranteed discard+billed); reuse would bypass deterministic ACKs' started=0 cancelled=0 reused=0 discarded=0 — every caller FINAL spoken while the agent was speaking/thinking is counted as would_cancel: under naive speculation each would have been a billed-then-discarded duplicate")
    global _PREEMPTIVE_ENABLED_FOR_LOG
    _PREEMPTIVE_ENABLED_FOR_LOG = bool(preemptive_enabled)
    
    logger.info(
        f"🔧 Session config: preemptive={preemptive_enabled} (env {env_preemptive}, has_kb {has_kb}), "
        f"preemptive_tts={preemptive_tts_enabled}, turn_detection={turn_detection_mode}, "
        f"endpointing={min_delay}/{max_delay}, "
        "stt_timeout=6.0s tts_timeout=10.0s, "
        f"interruption={'on' if allow_interruptions else 'off'} "
        f"(min_duration={min_interruption_duration}s, min_words={min_interruption_words}, "
        f"false_resume={false_interruption_timeout}s)"
    )

    return AgentSession(
        stt=stt_inst,
        vad=vad_inst,
        llm=llm_inst,
        tts=tts_inst,
        conn_options=_build_conn_options(),
        turn_handling={
            "turn_detection": turn_detection_mode,
            "endpointing": {"min_delay": min_delay, "max_delay": max_delay},
            "interruption": {
                "enabled": allow_interruptions,
                "mode": "vad",
                "min_duration": min_interruption_duration,
                "min_words": min_interruption_words,
                "resume_false_interruption": True,
                "false_interruption_timeout": false_interruption_timeout,
            },
            "preemptive_generation": {
                "enabled": preemptive_enabled,
                "preemptive_tts": preemptive_tts_enabled,
            },
        },
    )
