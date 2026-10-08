from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any
logger = logging.getLogger("voice-agent-saas-worker")


# cross-module imports (auto-generated)
from .billing_turn_report import _billing_report, _post_billing
from .gcp_env import threading
from .dep_imports import AgentConfig, calculate_call_cost, db_init, leadfile, memory, repo
from .loop_diagnostics import build_loop_diagnostics
from .turn_metrics_log import attach_turn_metrics, new_turn_timing
from .user_turn_items import new_call_bookkeeping
from .transcription_pipeline import build_user_input_transcription
from .call_closing import build_closing_pipeline
from .conversation_items import attach_conversation_items
from .agent_state_events import attach_agent_state_events
from .reply_stall_probe import build_reply_stall_probe
from .billing_finalize import register_finalize_billing
from .call_end_watchdog import build_call_end_watchdog
from .agent_fetch import fetch_agent_record, mark_call_in_progress, parse_job_metadata, read_agent_cache
from .call_gates import subscription_call_gate
from .greeting import select_greeting
from .ssl_cert_patch import ensure_ssl_before_db_init
from .runtime_env import DEFAULT_FALLBACK_RESPONSE, DETERMINISTIC_CLOSING_MESSAGE, DETERMINISTIC_CLOSING_MESSAGE_EN, FALLBACK_REPLY, LLM_FALLBACK_DELAY, WORKER_AGENT_NAME, _FAIL_THRESHOLD_SECONDS, _get_deterministic_closing, _item_is_tool_related, _mark_call_failed, _msg_text, clean_reply_text
from . import runtime_env as _wr
from . import ssl_cert_patch as _ws
from .session_announcer import build_announcement_session, start_egress
from .assistant_mode_setup import build_assistant_session
from .ssl_cert_patch import _prewarm_ssl_context

from .call_dispatch import(
    entrypoint  # noqa: F401   public API: imported via package __init__,
)




async def _entrypoint_body(ctx, setup_complete):
    from livekit.agents import AgentSession
    from app.agents.agent_builder import (
        build_vad, build_stt, build_llm, build_tts, build_voice_agent,
        build_announce_agent,
    )

    call_start = time.time()

    # Connect to the LiveKit room immediately per LiveKit Agents architecture.
    # Satisfies the 10-second connection deadline and initializes WebRTC transport
    # concurrently while agent config and models are prepared.
    try:
        await ctx.connect()
        logger.info("⚡ LiveKit room connected immediately: %s", getattr(ctx.room, "name", ""))
    except Exception as exc:
        logger.warning("ctx.connect() warning: %r (session.start will attempt connect)", exc)

    # --- Latency fix: cache DB init per process, build providers in parallel
    # (job request -> first audio was ~13.5s; each part now documented in the
    # helper modules that own it: ssl_cert_patch / agent_fetch / this file's setup).
    await ensure_ssl_before_db_init()

    agent_id, mode, phone, call_id, user_id, lead_data, meta_agent_config = parse_job_metadata(ctx)

    logger.info("[CALL_START] room=%s agent_id=%s mode=%s call_id=%s", getattr(ctx.room, "name", ""), agent_id, mode, call_id)
    logger.info("[AGENT_SELECTED] room=%s agent_id=%s user_id=%s mode=%s", getattr(ctx.room, "name", ""), agent_id, user_id, mode)

    rec = read_agent_cache(agent_id)

    cfg, agent_id, aborted = await fetch_agent_record(ctx, agent_id, user_id, call_id, rec)
    if aborted:
        return

    # --- Panel-set API keys / models: force-load the DB snapshot so Super-Admin
    # panel keys are used by THIS call (panel first, .env as fallback).
    try:
        from app.services import config_store as _cs
        await asyncio.wait_for(_cs.refresh_if_stale(force=True), timeout=8)
        logger.info("⏱️ Config snapshot loaded — panel API keys/models active for this call")
    except Exception as _e:
        logger.warning("Config snapshot refresh failed (falling back to env keys): %r", _e)

    # --- Monthly-plan gate (no active subscription → no calls) ---
    if await subscription_call_gate(ctx, user_id, call_id):
        return

    logger.info(f"📞 agent={cfg.name} mode={mode} phone={phone} call={call_id}")

    call_record = {"id": call_id or f"call_{uuid.uuid4().hex[:8]}", "user_id": user_id}
    mark_call_in_progress(ctx, call_id, user_id)  # async — must not block audio

    usage, last_user_transcript, state_tracker = new_call_bookkeeping()

    # Cross-call memory key (only if the agent enabled memory): SIP → phone
    # number; browser → user+agent (else a random room name per call forgets them).
    if phone:
        customer_key = phone
    elif user_id:
        customer_key = f"user:{user_id}:{agent_id}"
    else:
        customer_key = ctx.room.name
    memory_enabled = bool(getattr(cfg, "memory_enabled", True))
    prior_memory = (await asyncio.to_thread(memory.load, customer_key)) if memory_enabled else ""

    greeting = select_greeting(cfg, lead_data)

    turn_timing = new_turn_timing(ctx)
    loop_diag = build_loop_diagnostics(ctx, turn_timing)
    _sync_callback_records = loop_diag["sync_callback_records"]
    _turn_task_wait_samples = loop_diag["turn_task_wait_samples"]
    _loop_stack_samples = loop_diag["loop_stack_samples"]
    _loop_sampler_stop = loop_diag["sampler_stop"]
    _instrument_sync_callback = loop_diag["instrument"]
    

    # ------------------------------------------------------------------
    # Mode: assistant (STT+LLM+TTS) vs announcement (fixed script only).
    # ------------------------------------------------------------------
    agent_mode = getattr(cfg, "agent_mode", "assistant") or "assistant"
    logger.info("[AGENT_WAITING] room=%s agent_id=%s name=%s agent_mode=%s", getattr(ctx.room, "name", ""), agent_id, cfg.name, agent_mode)
    if agent_mode == "announcement":
        session = build_announcement_session(cfg)
    else:
        session = await build_assistant_session(cfg, turn_timing_ref=turn_timing)

    attach_turn_metrics(session, turn_timing, _sync_callback_records,
                        _turn_task_wait_samples, _loop_stack_samples)

    # ------------------------------------------------------------------
    # RAG precomputation (latency) + barge-in/transcription handler — extracted
    # to transcription_pipeline.py. `late` is filled below once the no-response
    # and stall-probe functions are defined (same late binding as before).
    late: dict = {}
    rag_prefetch = build_user_input_transcription(
        ctx, session, turn_timing, state_tracker, usage, cfg, agent_mode,
        late, _instrument_sync_callback)

    # Closing/no-response/silence-fallback pipeline — extracted to call_closing.py.
    closing_ctx = build_closing_pipeline(
        ctx, session, cfg, agent_mode, turn_timing, state_tracker, usage,
        _loop_sampler_stop, late)
    call_finished = closing_ctx["call_finished"]
    call_closed = closing_ctx["call_closed"]
    closing_requested = closing_ctx["closing_requested"]
    closing_in_progress = closing_ctx["closing_in_progress"]
    agent_holder = closing_ctx["agent_holder"]
    reply_tracker = closing_ctx["reply_tracker"]
    no_response_state = closing_ctx["no_response_state"]
    _cancel_no_response = closing_ctx["cancel_no_response"]
    _cancel_pending = closing_ctx["cancel_pending"]
    _schedule_no_response = closing_ctx["schedule_no_response"]
    late["schedule_no_response"] = _schedule_no_response


    attach_conversation_items(
        session, cfg, agent_mode, turn_timing, usage, call_closed,
        closing_in_progress, closing_requested, no_response_state, reply_tracker,
        last_user_transcript, _schedule_no_response, closing_ctx["schedule_silence_fallback"],
        closing_ctx["cancel_pending"], closing_ctx["mark_reply"],
        closing_ctx["schedule_deterministic_closing"], _instrument_sync_callback)

    attach_agent_state_events(
        session, state_tracker, turn_timing, call_closed, closing_in_progress,
        closing_requested, no_response_state, _cancel_no_response, _cancel_pending,
        _schedule_no_response, late, _instrument_sync_callback)

    # ------------------------------------------------------------------
    # P4/P6 diagnostics: reply-stall probe + [SPEECH_CREATED] marker.
    # After a user transcript FINAL the healthy chain is:
    #   [USER_TRANSCRIPT_FINAL] -> [USER_TURN_COMPLETED] (agent hook)
    #   -> [SPEECH_CREATED] -> [AGENT_STATE] listening -> thinking
    #   -> LLM REQUEST START -> first_token -> TTS -> speaking
    # If nothing reaches thinking/speaking within ~6s of the final, the reply
    # pipeline is stalled inside LiveKit's scheduling/authorization layer
    # (observed 2026-09-23 21:45: greeting fine, turn committed, RAG
    # injected, then no thinking, no LLM request, billing 0/0 for 18+s).
    # The probe ONLY logs a red-alert; it never retries and never calls
    # generate_reply — a forced retry would mask the root cause.
    # ------------------------------------------------------------------
    stall_fns = build_reply_stall_probe(
        session, agent_mode, state_tracker, call_closed, closing_in_progress,
        closing_requested, _schedule_no_response, _instrument_sync_callback)
    late["arm_stall_probe"] = stall_fns["arm"]
    late["cancel_stall_probe"] = stall_fns["cancel"]


    # Start recording if the agent has it on — but DO NOT block the call from
    # connecting. A missing/unavailable Egress service used to add ~21s before
    # session.start(), delaying every call. Now it runs in the background and the
    # recording URL is filled in before billing finalizes (or skipped if Egress
    # isn't reachable).
    recording_url = None
    egress_task = None
    if getattr(cfg, "recording_enabled", True):
        async def _start_egress_later():
            nonlocal recording_url
            try:
                recording_url = await asyncio.wait_for(start_egress(ctx.room.name), timeout=10)
            except asyncio.TimeoutError:
                logger.warning("⏱️ Egress timed out after 10s — recording disabled for this call.")
            except Exception as e:
                logger.warning(f"⚠️ Egress unavailable; continuing without recording: {e}")
        egress_task = asyncio.create_task(_start_egress_later())

    if agent_mode == "announcement":
        script = getattr(cfg, "announce_text", "") or greeting
        script = leadfile.render_template(script, lead_data)
        if not (script or "").strip():
            script = greeting or f"Hello, this is {cfg.name}."
        agent = build_announce_agent(cfg, announce_text=script)
        logger.info("[ANNOUNCEMENT_STARTED] room=%s agent_id=%s script=%s", getattr(ctx.room, "name", ""), agent_id, script[:60])
    else:
        agent = build_voice_agent(cfg, greeting=greeting, prior_memory=prior_memory, lead_data=lead_data, turn_timing_ref=turn_timing, rag_prefetch=rag_prefetch)
        logger.info("[ASSISTANT_STARTED] room=%s agent_id=%s greeting=%s", getattr(ctx.room, "name", ""), agent_id, greeting[:60])
    agent_holder["agent"] = agent
    logger.info("[AGENT_STARTED] room=%s agent_id=%s agent_mode=%s", getattr(ctx.room, "name", ""), agent_id, agent_mode)

    # Server-side noise cancellation. Two tiers:
    #   * NOISE_CANCELLATION=krisp -> server-side Krisp (BVC) filter. Only works on
    #     LiveKit Cloud WITH the `livekit-krisp-noise-cancellation` package installed
    #     (it's a closed-source binary; it does NOT run on a plain self-hosted SFU).
    #   * default (browser calls) -> the browser already applies WebRTC
    #     noiseSuppression/echoCancellation/autoGainControl (see CallPanel.tsx),
    #     and Deepgram STT uses its built-in VAD (`vad_events=True`), which rejects
    #     non-speech/noise frames before they reach the LLM.
    room_options = None
    try:
        from livekit.agents.voice import room_io as _rio
        room_options = _rio.RoomOptions(
            close_on_disconnect=False,
            delete_room_on_close=False,
        )
        logger.info("🎤 RoomOptions(close_on_disconnect=False, delete_room_on_close=False) armed.")
    except Exception as e:
        logger.warning(f"Could not set RoomOptions: {e}")

    # Finalization (idempotent) — extracted to billing_finalize.py (same
    # shutdown-callback registration as before).
    register_finalize_billing(
        ctx, cfg, agent_mode, agent_id, user_id, mode, phone, customer_key,
        call_start, call_record, recording_url, turn_timing, usage,
        memory_enabled)


    # Call-end watchdog — extracted to call_end_watchdog.py (identical
    # end-of-call + billing-finalize trigger as before).
    watch_call_end, opening_backup = build_call_end_watchdog(
        ctx, session, cfg, agent_mode, agent_id, greeting, state_tracker, usage,
        call_closed, call_finished, closing_in_progress, reply_tracker,
        agent_holder, _cancel_no_response, _cancel_pending)
    watchdog = asyncio.create_task(watch_call_end())

    start_kwargs: dict = {"agent": agent, "room": ctx.room}
    if room_options is not None:
        start_kwargs["room_options"] = room_options
    setup_complete["done"] = True   # setup finished — release the setup watchdog
    try:
        await session.start(**start_kwargs)
        # Keep entrypoint alive until the call completes so background watchdogs run
        await call_finished.wait()
    except Exception as e:
        logger.exception("session.start failed — job will exit so the worker can take the next call: %r", e)
        raise
    finally:
        opening_backup.cancel()
        watchdog.cancel()
        _cancel_no_response()
        if egress_task is not None:
            egress_task.cancel()


