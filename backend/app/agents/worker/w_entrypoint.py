from __future__ import annotations

import os
import re
import sys
import asyncio
import logging
import time
import uuid
import json
import traceback
import hashlib as _hl
from typing import Any, Iterator, Optional

logger = logging.getLogger("voice-agent-saas-worker")


# cross-module imports (auto-generated)
from .w_billing_reporter import _billing_report, _post_billing
from .w_gcp import threading
from .w_imports import AgentConfig, calculate_call_cost, db_init, leadfile, memory, repo
from .w_runtime import DEFAULT_FALLBACK_RESPONSE, DETERMINISTIC_CLOSING_MESSAGE, DETERMINISTIC_CLOSING_MESSAGE_EN, FALLBACK_REPLY, LLM_FALLBACK_DELAY, WORKER_AGENT_NAME, _FAIL_THRESHOLD_SECONDS, _get_deterministic_closing, _item_is_tool_related, _mark_call_failed, _msg_text, clean_reply_text
from . import w_runtime as _wr
from . import w_ssl as _ws
from .w_session_announce import build_announcement_session, start_egress
from .w_session_assistant import build_assistant_session
from .w_ssl import _prewarm_ssl_context

async def entrypoint(ctx):
    """LiveKit job entrypoint — the worker's failure contract.

    Any exception during setup (agent load, provider build, session start) used
    to kill the job silently: the room stayed open with no agent, the UI waited
    on "Waiting for agent to connect..." forever, and the call row stayed
    "planned". Now every setup failure:

      1. logs CRITICAL with the full traceback,
      2. marks the call "failed" in the DB with the reason (the UI polls this
         and shows the caller the real error instead of an endless spinner),
      3. deletes the room (the caller's browser disconnects instead of hanging
         in a silent room),
      4. shuts the job down (frees the worker process for the next dispatch).

    A 90-second setup watchdog additionally force-fails jobs whose setup hangs
    (stuck provider build / DB init / dead loop) so one sick job can't clog
    dispatch — the classic "second call goes silent" symptom.
    """
    # FIRST observable link of the dispatch chain on the worker side. If the
    # API logs CALL_START -> ROOM_CREATED -> AGENT_DISPATCH_SENT but this line
    # never appears, LiveKit never offered the job to this worker (dispatch
    # dropped / worker not registered at dispatch time) — never a code issue.
    try:
        _md = getattr(getattr(ctx, "job", None), "metadata", "") or ""
        logger.info(
            "[JOB_RECEIVED] room=%s job_id=%s worker_agent=%s metadata=%s",
            getattr(getattr(ctx, "room", None), "name", ""),
            getattr(getattr(ctx, "job", None), "id", ""),
            WORKER_AGENT_NAME,
            _md[:200],
        )
        # P9 lifecycle marker: the job is now owned by THIS process (pid ties
        # every later log line to a concrete runner process — two "initializing
        # job runner" lines are two idle processes, not two worker instances).
        logger.info(
            "[JOB_ACCEPTED] job_id=%s room=%s pid=%s agent_name=%s",
            getattr(getattr(ctx, "job", None), "id", ""),
            getattr(getattr(ctx, "room", None), "name", ""),
            os.getpid(),
            WORKER_AGENT_NAME,
        )
    except Exception:
        pass
    setup_complete = {"done": False}

    async def _setup_watchdog():
        try:
            await asyncio.sleep(90.0)
        except asyncio.CancelledError:
            return
        if not setup_complete["done"]:
            logger.critical(
                "⛔ Setup exceeded 90s — force-shutting job to free the worker "
                "process (stuck provider build / DB init / event loop)"
            )
            try:
                ctx.shutdown()
            except Exception:
                pass

    watchdog_task = asyncio.create_task(_setup_watchdog())
    try:
        await _entrypoint_body(ctx, setup_complete)
    except Exception as e:
        # Avoid synchronous traceback.format_exc() on event loop (tokenize.open block)
        try:
            _tb_setup = await asyncio.to_thread(traceback.format_exc)
        except Exception:
            _tb_setup = f"{type(e).__name__}: {e}"
        logger.critical(
            "WORKER_JOB_SETUP_FAILED room=%s: %s: %s\n%s",
            getattr(ctx.room, "name", ""), type(e).__name__, e, _tb_setup,
        )
        try:
            meta = json.loads(ctx.job.metadata or "{}")
        except Exception:
            meta = {}
        await _mark_call_failed(
            meta.get("call_id", ""), meta.get("user_id", ""), f"{type(e).__name__}: {e}"
        )
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
        raise
    finally:
        if not watchdog_task.done():
            watchdog_task.cancel()


async def _entrypoint_body(ctx, setup_complete):
    from livekit.agents import AgentSession
    from app.agents.agent_builder import (
        build_vad,
        build_stt,
        build_llm,
        build_tts,
        build_voice_agent,
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

    # --- Latency fix: DB init was 2.33s per job + 1.13s lookup + 8.62s None->listening
    # Previous log: job request 10.184 -> DB init 2.33s (12.845) -> lookup 1.13s (13.978) -> provider build 4.37s (18.350) -> listening 8.62s (23.648)
    # Total 13.5s before user hears greeting. Fix: cache DB init per process, parallel provider build.
    global _AGENT_CACHE
    # Ensure SSL cache ready before DB init. If the import-time prewarm thread
    # hasn't finished, build it in a thread — NOT here: doing it on the loop is
    # the very >1s ssl.create_default_context stall we're avoiding, and it would
    # land right before the greeting plays.
    # NOTE: cross-module flags (_DB_INIT_DONE in w_runtime, _ssl_context_cache
    # in w_ssl) are read/written via module attribute — a plain `import` of the
    # NAME would bind a stale copy and `global` here would create a divergent
    # module-local variable (the bug that crashed every job with NameError).
    try:
        if _ws._ssl_context_cache is None:
            await asyncio.wait_for(asyncio.to_thread(_prewarm_ssl_context), timeout=4)
            if _ws._ssl_context_cache is None:
                logger.warning("⚠️ SSL context still not cached before DB init — first connect may block the loop")
            else:
                logger.info("🔧 SSL context ready before DB init (built off-loop)")
    except Exception as _e:
        logger.debug(f"SSL ensure failed: {_e!r}")

    try:
        meta = json.loads(ctx.job.metadata or "{}")
    except Exception:
        meta = {}
    agent_id = meta.get("agent_id")
    mode = meta.get("mode", "browser")
    phone = meta.get("phone")
    call_id = meta.get("call_id", "")
    user_id = meta.get("user_id", "")
    lead_data = meta.get("lead_data") or {}
    meta_agent_config = meta.get("agent_config")

    logger.info("[CALL_START] room=%s agent_id=%s mode=%s call_id=%s", getattr(ctx.room, "name", ""), agent_id, mode, call_id)
    logger.info("[AGENT_SELECTED] room=%s agent_id=%s user_id=%s mode=%s", getattr(ctx.room, "name", ""), agent_id, user_id, mode)

    logger.info("[CALL_START] room=%s agent_id=%s mode=%s call_id=%s", getattr(ctx.room, "name", ""), agent_id, mode, call_id)
    logger.info("[AGENT_SELECTED] room=%s agent_id=%s user_id=%s mode=%s", getattr(ctx.room, "name", ""), agent_id, user_id, mode)

    rec = None
    if agent_id:
        try:
            from app.config import DATA_DIR
            cache_file = DATA_DIR / f"agent_{agent_id}.json"
            if cache_file.exists():
                rec = json.loads(cache_file.read_text(encoding="utf-8"))
                logger.info("⚡ Fast-path: Agent '%s' loaded from local cache in 0ms (no DB delay)", rec.get("name", agent_id))
        except Exception as exc:
            logger.warning("Could not read agent cache file: %r", exc)

    if rec is not None:
        # Warm DB connection in background so billing/cleanup at end of call is instant
        if not _wr._DB_INIT_DONE:
            async def _bg_db_init():
                try:
                    await asyncio.wait_for(db_init(), timeout=10)
                    _wr._DB_INIT_DONE = True
                    logger.info("⏱️ Background DB init completed ready for billing")
                except Exception as exc:
                    logger.warning("Background DB init failed: %r", exc)
            asyncio.create_task(_bg_db_init())
    else:
        db_t0 = time.time()
        db_just_initialized = False
        if not _wr._DB_INIT_DONE:
            try:
                try:
                    def _ensure_prisma_engine_binary() -> bool:
                        import importlib
                        for mod_base in ("prisma_client", "prisma"):
                            try:
                                paths = importlib.import_module(f"{mod_base}.binaries.paths")
                                utils = importlib.import_module(f"{mod_base}.engine.utils")
                                utils.ensure(paths.BINARY_PATHS.query_engine)
                                return True
                            except Exception:
                                continue
                        return False
                    if await asyncio.to_thread(_ensure_prisma_engine_binary):
                        logger.info("🔥 Prewarm: Prisma engine binary verified off-loop")
                except Exception:
                    pass
                await asyncio.wait_for(db_init(), timeout=8)
                _wr._DB_INIT_DONE = True
                db_just_initialized = True
                logger.info(f"⏱️ DB init {time.time()-db_t0:.2f}s on agent loop (first time, cached for next calls)")
            except Exception as exc:
                logger.error("database initialization unavailable (%.2fs); continuing voice call: %r", time.time()-db_t0, exc)
        else:
            try:
                await asyncio.wait_for(db_init(), timeout=5)
                logger.info("⏱️ DB init rechecked on this event loop")
            except Exception as exc:
                _wr._DB_INIT_DONE = False
                logger.warning("database re-init failed (%.2fs): %r", time.time() - db_t0, exc)

        if agent_id and user_id:
            lookup_t0 = time.time()
            timeouts = [6.0, 3.0] if db_just_initialized else [3.0, 3.0]
            for attempt in range(2):
                try:
                    rec = await asyncio.wait_for(repo.get_agent(agent_id, user_id), timeout=timeouts[attempt])
                    logger.info(f"⏱️ agent lookup ok attempt {attempt+1} in {time.time()-lookup_t0:.2f}s")
                    break
                except Exception as exc:
                    logger.warning(
                        "agent lookup attempt %s/2 failed (%.2fs, timeout=%.1fs): %r",
                        attempt + 1, time.time() - lookup_t0, timeouts[attempt], exc,
                    )
                    if attempt < 1:
                        await asyncio.sleep(0.15)

    if rec is None:
        if agent_id and agent_id != "demo":
            logger.error(
                "[CALL_ERROR] room=%s Agent '%s' not found for user %s. Refusing silent fallback.",
                getattr(ctx.room, "name", ""), agent_id, user_id,
            )
            if call_id and user_id:
                try:
                    await repo.update_call(call_id, {
                        "status": "failed",
                        "ended_at": time.strftime("%Y-%m-%d %H:%M"),
                    })
                except Exception:
                    pass
            try:
                ctx.shutdown()
            except Exception:
                pass
            return
        logger.info("[AGENT_SELECTED] room=%s Using default demo agent config", getattr(ctx.room, "name", ""))
        from app.sample import default_config
        cfg = default_config()
        agent_id = "demo"
    else:
        cfg = AgentConfig(**rec)

    # --- Panel-set API keys / models -----------------------------------------
    # The sync pipeline reads provider keys from config_store's in-process
    # snapshot, which in a fresh job process is the code-default fallback
    # (NO panel credentials → silent .env key fallback). Force-load the DB
    # snapshot now so a key the Super Admin set in the panel is used by THIS
    # call — panel first, .env only as fallback (ab_config_access).
    try:
        from app.services import config_store as _cs
        await asyncio.wait_for(_cs.refresh_if_stale(force=True), timeout=8)
        logger.info("⏱️ Config snapshot loaded — panel API keys/models active for this call")
    except Exception as _e:
        logger.warning("Config snapshot refresh failed (falling back to env keys): %r", _e)

    logger.info(f"📞 agent={cfg.name} mode={mode} phone={phone} call={call_id}")

    # Ensure the call record status is tracked in-progress asynchronously without blocking audio
    call_record = {"id": call_id or f"call_{uuid.uuid4().hex[:8]}", "user_id": user_id}
    async def _mark_call_in_progress():
        try:
            if not _wr._DB_INIT_DONE:
                await asyncio.wait_for(db_init(), timeout=10)
            if call_id and user_id:
                await repo.update_call(call_id, {"status": "in-progress", "room": getattr(ctx.room, "name", "")})
        except Exception as e:
            logger.warning("Could not mark call in-progress: %s", e)
    asyncio.create_task(_mark_call_in_progress())

    usage = {"tts_chars": 0, "llm_input_tokens": 0, "llm_output_tokens": 0,
             "user_speech_seconds": 0.0, "transcripts": []}

    # Dedupe identical user transcripts (STT can emit the same phrase twice) and
    # track how long the agent stays in each state so we can flag slow turns.
    last_user_transcript = {"text": "", "ts": 0.0}
    state_tracker = {"state": None, "since": time.time()}

    # Cross-call memory (ONLY if the agent enabled it).
    # Cross-call memory key. SIP calls are keyed by the phone number (the person's
    # real identity). Browser calls have no phone, so key them by the logged-in
    # user + agent — otherwise a brand-new randomised room name per call means the
    # agent NEVER remembers a browser caller between calls.
    if phone:
        customer_key = phone
    elif user_id:
        customer_key = f"user:{user_id}:{agent_id}"
    else:
        customer_key = ctx.room.name
    memory_enabled = bool(getattr(cfg, "memory_enabled", True))
    prior_memory = (await asyncio.to_thread(memory.load, customer_key)) if memory_enabled else ""

    if (cfg.greeting or "").strip():
        greeting = cfg.greeting
    elif (getattr(cfg, "language", "hi") or "hi").lower().startswith("en"):
        greeting = f"Hello, this is {cfg.name}. How can I help you?"
    else:
        greeting = f"Namaste! Main {cfg.name} hoon. Aap kaise madad kar sakta hoon?"
    # Dynamic script: substitute {column} placeholders with this lead's values
    # (used by bulk-call campaigns so every call is personalized).
    greeting = leadfile.render_template(greeting, lead_data)

    # --- Production timing instrumentation for latency tracing - V2 with TTFT and generation time ---
    # Track complete path: user stops speaking -> STT final -> turn detection -> LLM request
    # These timestamps are per-turn, reset on each user turn
    # V2: Added request_start, first_token, generation_complete for TTFT and generation_time
    # Also logs provider, model, input_tokens, cached_input_tokens, output_tokens, costs
    turn_timing = {
        "speech_end": 0.0,
        "stt_final": 0.0,
        "turn_detected": 0.0,
        "llm_start": 0.0,
        "request_start": 0.0,
        "first_token": 0.0,
        "tts_request": 0.0,
        "first_tts_audio": 0.0,
        "llm_complete": 0.0,
        "generation_complete": 0.0,
        "first_audio": 0.0,
        "last_speech_end_to_first_audio": 0.0,
        "llm_provider": "",
        "llm_model": "",
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "output_tokens": 0,
        "ttft_ms": 0.0,
        "generation_time_ms": 0.0,
        "llm_active": False,
        "assistant_output_received": False,
        # FIX: Aggregated billing for actual successful provider usage
        "aggregated_input": 0,
        "aggregated_output": 0,
        "aggregated_cached": 0,
        "successful_requests": 0,
        "failed_requests": 0,
        "all_requests": [],  # list of {input, cached, output, success, ttft, gen_time, provider, model, is_closing}
        "is_closing": False,  # True when deterministic closing in progress
        "call_id": str(getattr(ctx.room, "name", "unknown")),
        "turn_id": 0,
        "stt_final_mono_ns": 0,
        "callback_enter_mono_ns": 0,
        "callback_complete_mono_ns": 0,
    }

    _sync_callback_records = []
    _turn_task_wait_samples = []
    _loop_stack_samples = []
    _loop_heartbeat = {"ns": time.monotonic_ns(), "active": False}
    _loop_sampler_stop = threading.Event()
    # Separate call-time loop stalls from worker startup/idle/shutdown stalls.
    async def _loop_lag_watch(_tt=turn_timing):
        import asyncio as _aio
        _last = time.perf_counter()
        _active, _background = [], []
        _counts = {"active": [0, 0, 0], "background": [0, 0, 0]}
        _maxima = {"active": 0.0, "background": 0.0}
        try:
            while True:
                await _aio.sleep(0.05)
                _now = time.perf_counter()
                _drift = max(0.0, (_now - _last - 0.05) * 1000.0)
                _last = _now
                _sample_ns = time.monotonic_ns()
                _room_obj = getattr(ctx, "room", None)
                _active_call = bool(getattr(_room_obj, "remote_participants", {}))
                _loop_heartbeat["ns"] = time.monotonic_ns()
                _loop_heartbeat["active"] = _active_call
                # Read-only stack samples for all live tasks during calls. At the
                # end-of-turn metric, samples can be restricted to the precise
                # decision->callback window and grouped by task/frame.
                if _active_call:
                    for _task in _aio.all_tasks():
                        if _task is asyncio.current_task() or _task.done():
                            continue
                        _frames = _task.get_stack(limit=8)
                        _stack = " <- ".join(
                            f"{os.path.basename(_frame.f_code.co_filename)}:{_frame.f_lineno}:{_frame.f_code.co_name}"
                            for _frame in _frames[-4:]
                        ) or "stack_unavailable"
                        _turn_task_wait_samples.append((_sample_ns, _task.get_name(), _stack))
                    if len(_turn_task_wait_samples) > 8192:
                        del _turn_task_wait_samples[:4096]
                _kind = "active" if _active_call else "background"
                _samples = _active if _active_call else _background
                _samples.append(_drift)
                if len(_samples) > 1200:
                    del _samples[:600]
                _maxima[_kind] = max(_maxima[_kind], _drift)
                _counts[_kind][0] += int(_drift > 100.0)
                _counts[_kind][1] += int(_drift > 200.0)
                _counts[_kind][2] += int(_drift > 500.0)
                if _drift > 100.0:
                    _sorted = sorted(_samples)
                    _p95 = _sorted[min(len(_sorted) - 1, int((len(_sorted) - 1) * 0.95))]
                    _room = getattr(_room_obj, "name", "")
                    _tag = "ACTIVE_CALL_LOOP_LAG" if _active_call else "BACKGROUND_LOOP_LAG"
                    logging.getLogger("voice-agent-saas-worker").warning(
                        "[%s] monotonic_ns=%d duration_ms=%.0f room=%s turn=%s generation=%s agent_state=%s pipeline_stage=%s max_ms=%.0f p95_ms=%.0f counts_gt100=%d counts_gt200=%d counts_gt500=%d",
                        _tag, time.monotonic_ns(), _drift, _room,
                        _tt.get("turn_id", "N/A"), _tt.get("gen", "N/A"),
                        _tt.get("agent_state", "N/A"), _tt.get("pipeline_stage", "N/A"),
                        _maxima[_kind], _p95, *_counts[_kind],
                    )
        except asyncio.CancelledError:
            return
        finally:
            for _kind, _samples in (("active", _active), ("background", _background)):
                if _samples:
                    _sorted = sorted(_samples)
                    _p95 = _sorted[min(len(_sorted) - 1, int((len(_sorted) - 1) * 0.95))]
                    _tag = "ACTIVE_CALL_LOOP_STATS" if _kind == "active" else "BACKGROUND_LOOP_STATS"
                    logging.getLogger("voice-agent-saas-worker").info(
                        "[%s] room=%s max_ms=%.0f p95_ms=%.0f counts_gt100=%d counts_gt200=%d counts_gt500=%d",
                        _tag, getattr(getattr(ctx, "room", None), "name", ""), _maxima[_kind], _p95,
                        *_counts[_kind],
                    )
    turn_timing["_loop_lag_task"] = asyncio.create_task(_loop_lag_watch())

    def _sample_blocked_loop_stack(_loop_thread_id):
        _stall_start_ns = 0
        _last_stack_ns = 0
        _latest_stack = ""
        _stall_start_logged = False
        while not _loop_sampler_stop.wait(0.025):
            if not _loop_heartbeat["active"]:
                continue
            _now_ns = time.monotonic_ns()
            _heartbeat_ns = int(_loop_heartbeat["ns"])
            if _now_ns - _heartbeat_ns <= 100_000_000:
                if _stall_start_ns:
                    _end_ns = _heartbeat_ns
                    _duration_ms = max(0.0, (_end_ns - _stall_start_ns) / 1_000_000)
                    logger.warning("[CALLBACK_BLOCK_END] task=N/A active_frame=%s monotonic_ns=%d duration_ms=%.3f room=%s turn=%s generation=%s state=%s stack=%s", _latest_stack.split(" <- ", 1)[0], _end_ns, _duration_ms, getattr(ctx.room, "name", ""), turn_timing.get("turn_id", "N/A"), turn_timing.get("gen", "N/A"), turn_timing.get("agent_state", "N/A"), _latest_stack)
                    _loop_stack_samples.append((_stall_start_ns, _end_ns, _latest_stack))
                    if len(_loop_stack_samples) > 1024:
                        del _loop_stack_samples[:512]
                    _stall_start_ns = 0
                    _latest_stack = ""
                    _stall_start_logged = False
                continue
            if not _stall_start_ns:
                _stall_start_ns = _heartbeat_ns
                _last_stack_ns = 0
                _stall_start_logged = False
            if _now_ns - _last_stack_ns < 50_000_000:
                continue
            _last_stack_ns = _now_ns
            _frame = sys._current_frames().get(_loop_thread_id)
            _frames = []
            while _frame is not None:
                _frames.append(f"{os.path.basename(_frame.f_code.co_filename)}:{_frame.f_lineno}:{_frame.f_code.co_name}")
                _frame = _frame.f_back
            _latest_stack = " <- ".join(_frames[:12]) or "stack_unavailable"
            if len(_loop_stack_samples) > 1024:
                del _loop_stack_samples[:512]
            if not _stall_start_logged:
                logger.warning("[CALLBACK_BLOCK_START] task=N/A active_frame=%s monotonic_ns=%d room=%s turn=%s generation=%s state=%s stack=%s", _latest_stack.split(" <- ", 1)[0], _stall_start_ns, getattr(ctx.room, "name", ""), turn_timing.get("turn_id", "N/A"), turn_timing.get("gen", "N/A"), turn_timing.get("agent_state", "N/A"), _latest_stack)
                _stall_start_logged = True

    _loop_thread_id = threading.get_ident()
    _loop_stack_sampler = threading.Thread(target=_sample_blocked_loop_stack, args=(_loop_thread_id,), name="voice-loop-stack-sampler", daemon=True)
    _loop_stack_sampler.start()

    def _instrument_sync_callback(_name, _callback):
        _code = getattr(_callback, "__code__", None)
        _file = getattr(_code, "co_filename", "unknown")
        _line = getattr(_code, "co_firstlineno", 0)
        def _wrapped(*args, **kwargs):
            _start_ns = time.monotonic_ns()
            _task = asyncio.current_task()
            _task_name = _task.get_name() if _task else "sync-event-callback"
            try:
                return _callback(*args, **kwargs)
            finally:
                _end_ns = time.monotonic_ns()
                _record = {
                    "name": _name, "task": _task_name, "start_ns": _start_ns, "end_ns": _end_ns,
                    "duration_ms": (_end_ns - _start_ns) / 1_000_000,
                    "file": _file, "line": _line, "turn": turn_timing.get("turn_id", "N/A"),
                    "generation": turn_timing.get("gen", "N/A"), "room": getattr(ctx.room, "name", ""),
                    "state": turn_timing.get("agent_state", "N/A"), "reported": False,
                }
                _sync_callback_records.append(_record)
                if len(_sync_callback_records) > 1024:
                    del _sync_callback_records[:512]
                if _record["duration_ms"] >= 100.0:
                    logger.warning("[CALLBACK_BLOCK_START] callback=%s task=%s monotonic_ns=%d room=%s turn=%s generation=%s state=%s file=%s line=%s", _name, _task_name, _start_ns, _record["room"], _record["turn"], _record["generation"], _record["state"], _file, _line)
                    logger.warning("[CALLBACK_BLOCK_END] callback=%s task=%s monotonic_ns=%d duration_ms=%.3f room=%s turn=%s generation=%s state=%s file=%s line=%s", _name, _task_name, _end_ns, _record["duration_ms"], _record["room"], _record["turn"], _record["generation"], _record["state"], _file, _line)
                    _record["reported"] = True

        return _wrapped
    if os.getenv("VOICE_ASYNCIO_SLOW_CALLBACK_DIAGNOSTICS", "0").strip().lower() in ("1", "true", "yes"):
        _diag_loop = asyncio.get_running_loop()
        _diag_loop.set_debug(True)
        _diag_loop.slow_callback_duration = 0.1
        logger.warning("[ASYNCIO_SLOW_CALLBACK_DIAGNOSTICS] enabled threshold_ms=100 room=%s", getattr(ctx.room, "name", ""))
    

    # ------------------------------------------------------------------
    # Mode: assistant (STT+LLM+TTS) vs announcement (fixed script only).
    # ------------------------------------------------------------------
    agent_mode = getattr(cfg, "agent_mode", "assistant") or "assistant"
    logger.info("[AGENT_WAITING] room=%s agent_id=%s name=%s agent_mode=%s", getattr(ctx.room, "name", ""), agent_id, cfg.name, agent_mode)
    if agent_mode == "announcement":
        session = build_announcement_session(cfg)
    else:
        session = await build_assistant_session(cfg, turn_timing_ref=turn_timing)

    # LiveKit 1.8.x emits EOUMetrics after the user-turn task. Its end_of_utterance_delay
    # and transcription_delay let us recover final-to-turn-decision time without
    # patching LiveKit internals: EOU delay minus transcription delay.
    def _on_turn_metrics(ev):
        _metrics = getattr(ev, "metrics", None)
        if type(_metrics).__name__ != "EOUMetrics":
            return
        _eou = getattr(_metrics, "end_of_utterance_delay", None)
        _trans = getattr(_metrics, "transcription_delay", None)
        _hook = getattr(_metrics, "on_user_turn_completed_delay", None)
        _final_ns = int(turn_timing.get("stt_final_mono_ns", 0) or 0)
        _entered_ns = int(turn_timing.get("callback_enter_mono_ns", 0) or 0)
        _eou_to_enter_ms = None
        _final_to_eou_ms = None
        if isinstance(_eou, (int, float)) and isinstance(_trans, (int, float)):
            _final_to_eou_ms = max(0.0, (_eou - _trans) * 1000.0)
            if _final_ns and _entered_ns:
                _entered_delta = (_entered_ns - _final_ns) / 1_000_000
                _eou_to_enter_ms = _entered_delta - _final_to_eou_ms
        _decision_ns = (
            _final_ns + int(_final_to_eou_ms * 1_000_000)
            if _final_ns and _final_to_eou_ms is not None
            else 0
        )
        if _decision_ns and _entered_ns:
            _window_tasks = {}
            for _sample_time, _task_name, _stack in _turn_task_wait_samples:
                if _decision_ns <= _sample_time <= _entered_ns:
                    _key = (_task_name, _stack)
                    _span = _window_tasks.setdefault(_key, [_sample_time, _sample_time, 0])
                    _span[1] = _sample_time
                    _span[2] += 1
            for (_task_name, _stack), (_first_ns, _last_ns, _samples) in _window_tasks.items():
                logger.info("[ASYNC_TASK_WINDOW_SAMPLE] task=%s first_monotonic_ns=%d last_monotonic_ns=%d samples=%d room=%s turn=%s generation=%s stack=%s", _task_name, _first_ns, _last_ns, _samples, turn_timing.get("call_id"), turn_timing.get("turn_id"), turn_timing.get("gen", "N/A"), _stack)
            for _block_start_ns, _block_end_ns, _block_stack in _loop_stack_samples:
                if _block_start_ns < _entered_ns and _block_end_ns > _decision_ns:
                    logger.warning("[TURN_WINDOW_BLOCK_STACK] start_monotonic_ns=%d end_monotonic_ns=%d duration_ms=%.3f room=%s turn=%s generation=%s stack=%s", _block_start_ns, _block_end_ns, (_block_end_ns - _block_start_ns) / 1_000_000, turn_timing.get("call_id"), turn_timing.get("turn_id"), turn_timing.get("gen", "N/A"), _block_stack)
            for _record in _sync_callback_records:
                if _record["start_ns"] < _entered_ns and _record["end_ns"] > _decision_ns and not _record["reported"]:
                    logger.warning("[CALLBACK_BLOCK_START] callback=%s task=%s monotonic_ns=%d room=%s turn=%s generation=%s state=%s file=%s line=%d", _record["name"], _record["task"], _record["start_ns"], _record["room"], _record["turn"], _record["generation"], _record["state"], _record["file"], _record["line"])
                    logger.warning("[CALLBACK_BLOCK_END] callback=%s task=%s monotonic_ns=%d duration_ms=%.3f room=%s turn=%s generation=%s state=%s file=%s line=%d", _record["name"], _record["task"], _record["end_ns"], _record["duration_ms"], _record["room"], _record["turn"], _record["generation"], _record["state"], _record["file"], _record["line"])
                    _record["reported"] = True
        logger.info(
            "[TURN_TRACE] stage=turn_detection_decision monotonic_ns=%s source=%s call_id=%s turn_id=%s generation_id=%s speech_id=%s",
            _decision_ns if _decision_ns else "N/A",
            "derived_from_livekit_eou_metrics" if _decision_ns else "unavailable",
            turn_timing.get("call_id"), turn_timing.get("turn_id"), turn_timing.get("gen", "N/A"),
            getattr(_metrics, "speech_id", "N/A"),
        )
        logger.info(
            "[ASYNC_TASK_DELAY] task=AgentActivity._user_turn_completed_task call_id=%s turn_id=%s schedule_to_start_ms=N/A turn_decision_to_callback_enter_ms=%s source=LiveKit_task_creation_is_internal",
            turn_timing.get("call_id"), turn_timing.get("turn_id"),
            f"{_eou_to_enter_ms:.1f}" if _eou_to_enter_ms is not None else "N/A",
        )
        logger.info(
            "[LIVEKIT_EOU_METRICS] call_id=%s turn_id=%s generation_id=%s speech_id=%s final_to_turn_decision_ms=%s turn_decision_to_callback_enter_ms=%s callback_hook_ms=%s callback_schedule_to_start_ms=N/A source=LiveKit_internal_schedule_not_public",
            turn_timing.get("call_id"), turn_timing.get("turn_id"), turn_timing.get("gen", "N/A"),
            getattr(_metrics, "speech_id", "N/A"),
            f"{_final_to_eou_ms:.1f}" if _final_to_eou_ms is not None else "N/A",
            f"{_eou_to_enter_ms:.1f}" if _eou_to_enter_ms is not None else "N/A",
            f"{float(_hook) * 1000:.1f}" if isinstance(_hook, (int, float)) else "N/A",
        )
    try:
        session.on("metrics_collected", _on_turn_metrics)
    except Exception as _metric_hook_error:
        logger.warning("Could not attach LiveKit EOU metric listener: %s", _metric_hook_error)

    # ------------------------------------------------------------------
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
    # [USER_SPEECH_STARTED] edge detector state (mutable cell; updated from
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

    # ------------------------------------------------------------------
    # Silence watchdog + No-response watchdog.
    #
    # 1) LLM silence: When the LLM 429s (Groq free-tier TPM limit) the fail-fast
    #    retry budget gives up in <1s and LiveKit logs the error but speaks
    #    NOTHING — caller left in dead air. So arm timer on every user turn,
    #    if no assistant reply within LLM_FALLBACK_DELAY, speak fallback.
    # 2) User silence: If user says nothing for no_response_timeout_seconds
    #    (configurable per agent, e.g. 30 sec), speak the agent's
    #    no_response_message and hang up. Requested by user.
    # ------------------------------------------------------------------
    call_finished = asyncio.Event()
    call_closed = {"done": False}
    closing_requested = {"done": False}
    closing_in_progress = {"done": False}
    closing_task_ref = {"task": None}
    agent_holder = {"agent": None}
    reply_tracker = {
        "last_user_ts": 0.0,
        "last_assistant_ts": 0.0,
        "empty_spoken": False,
        "pending": None,
        "fallback_say": None,
    }
    # No-response tracking: last time user spoke or agent spoke.
    # `gen` is a monotonically increasing arming generation: every (re)arm or
    # cancel bumps it and each scheduled handler captures its generation, so a
    # stale handler left over from an earlier window can NEVER fire after a
    # cancel/reset (P5: no false no-response while the caller is talking).
    no_response_state = {
        "last_activity": time.time(),
        "task": None,
        "triggered": False,
        "gen": 0,
    }

    @ctx.room.on("disconnected")
    def _on_room_disconnected(*_):
        logger.info("Room disconnected event received")
        _loop_sampler_stop.set()
        _ll = turn_timing.pop("_loop_lag_task", None)
        if _ll is not None:
            try:
                _ll.cancel()
            except Exception:
                pass
        try:
            _cancel_no_response(reason="call_end_room_disconnected")
            _cancel_stall_probe(reason="call_end_room_disconnected")
        except Exception:
            pass
        call_finished.set()

    @session.on("close")
    def _on_session_close(*_):
        logger.info("Session close event received")
        try:
            _cancel_no_response(reason="call_end_session_close")
            _cancel_stall_probe(reason="call_end_session_close")
        except Exception:
            pass
        call_finished.set()

    async def _on_job_shutdown(*_):
        call_finished.set()
        # P2: this job thread's event loop is about to close — release its
        # Prisma client (per-loop registry) so engine processes do not pile
        # up in the worker. Best-effort, never blocks shutdown.
        try:
            from app.db import release_current_loop
            await asyncio.wait_for(release_current_loop(), timeout=6)
        except Exception:
            pass

    ctx.add_shutdown_callback(_on_job_shutdown)

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
    def _cancel_no_response(reason: str = "cancel"):
        t = no_response_state.get("task")
        no_response_state["gen"] = no_response_state.get("gen", 0) + 1  # stale-task guard
        if t is not None and not t.done():
            t.cancel()
            logger.info(f"⏱️ [WATCHDOG_CANCELLED] gen={no_response_state['gen']} reason={reason}")
        no_response_state["task"] = None

    async def _no_response_timeout_handler(gen: int):
        idle_timeout = max(15, int(getattr(cfg, "no_response_timeout_seconds", 30) or 30))
        no_response_msg = (getattr(cfg, "no_response_message", "") or
                           "I did not hear a response, so I will end the call now. Thank you for calling.").strip()
        try:
            await asyncio.sleep(idle_timeout)
        except asyncio.CancelledError:
            return
        # Stale-window guard: if this handler was re-armed/cancelled while it
        # slept, its generation no longer matches — never act on old windows.
        if gen != no_response_state.get("gen"):
            return
        if call_closed["done"] or closing_in_progress["done"] or closing_requested["done"] or no_response_state.get("triggered"):
            return
        ag = agent_holder.get("agent")
        if ag is not None and getattr(ag, "_opening_started", False) and not getattr(ag, "_opening_done", False):
            logger.info("⏱️ No-response timer fired during the opening line — not interrupting it")
            _schedule_no_response()
            return
        elapsed = time.time() - no_response_state.get("last_activity", 0)
        # Defensive double-check against the per-final activity clock: if the
        # user spoke during the sleep window, skip AND re-arm a full window
        # (the old code returned without re-arming, silently disabling the
        # watchdog for the remainder of the call).
        if elapsed < idle_timeout - 0.5:
            logger.info(f"⏱️ No-response timer fired but user spoke {elapsed:.1f}s ago (timeout {idle_timeout}s) — skipping and re-arming")
            _schedule_no_response()
            return
        # Only trigger when waiting for user
        cur_state = state_tracker.get("state")
        if cur_state not in ("listening", None):
            logger.info(f"⏱️ No-response timer fired but state is {cur_state} (not listening) — rescheduling")
            _schedule_no_response()
            return
        no_response_state["triggered"] = True
        logger.info(f"⏱️ [WATCHDOG_FIRED] gen={gen} — no user response for {elapsed:.0f}s (timeout {idle_timeout}s)")
        # Mark call as closing to prevent re-arming watchdog on listening transition
        call_closed["done"] = True
        closing_in_progress["done"] = True
        logger.info(f"⏱️ No user response for {elapsed:.0f}s (timeout {idle_timeout}s) — speaking no-response message and ending call")
        try:
            _cancel_pending()
            fb = reply_tracker.get("fallback_say")
            if fb is not None and not fb.done():
                fb.cancel()
            reply_tracker["fallback_say"] = None
            try:
                session.interrupt()
                await asyncio.sleep(0.15)
            except Exception:
                pass
            usage["tts_chars"] += len(no_response_msg)
            usage["transcripts"].append({"role": "agent", "text": no_response_msg})
            logger.info(f"⏱️ No-response closing TTS: {no_response_msg} — will play fully then auto-cut")
            try:
                await asyncio.wait_for(session.say(no_response_msg, allow_interruptions=False), timeout=20)
                logger.info(f"✅ No-response TTS completed: {no_response_msg}")
            except asyncio.TimeoutError:
                logger.warning(f"⏱️ No-response TTS timed out after 20s: {no_response_msg}")
            except Exception as e:
                if "transport is closed" in str(e).lower() or "no stream" in str(e).lower():
                    logger.warning(f"⚠️ Transport closed during no-response TTS (frontend left early), but message was: {no_response_msg}: {e}")
                else:
                    logger.warning(f"No-response say failed: {e}")
            await asyncio.sleep(2.5)
        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.warning(f"No-response outer failed: {e}")
            await asyncio.sleep(1.0)
        logger.info("[CALL_END_REQUESTED] source=timeout reason=no_response")
        logger.info("✂️ Auto-cutting call after no-response TTS")
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

    def _schedule_no_response(reason: str = "re-arm"):
        # Announcement mode reads a script and hangs up. A silence timer would
        # interrupt that script or start a second goodbye.
        if agent_mode == "announcement":
            return
        if no_response_state.get("triggered") or call_closed["done"] or closing_in_progress["done"] or closing_requested["done"]:
            logger.info("⏱️ Not arming no-response — call already closing/triggered")
            return
        _cancel_no_response(reason=reason)
        idle_timeout = max(15, int(getattr(cfg, "no_response_timeout_seconds", 30) or 30))
        no_response_msg = (getattr(cfg, "no_response_message", "") or
                           "I did not hear a response, so I will end the call now. Thank you for calling.").strip()
        no_response_state["last_activity"] = time.time()
        no_response_state["gen"] = no_response_state.get("gen", 0) + 1
        gen = no_response_state["gen"]
        try:
            no_response_state["task"] = asyncio.ensure_future(_no_response_timeout_handler(gen))
            logger.info(f"⏱️ [WATCHDOG_ARMED] gen={gen} timeout={idle_timeout}s -> '{no_response_msg[:60]}'")
        except Exception as e:
            logger.warning(f"Could not arm no-response watchdog: {e}")

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
    stall_probe = {"task": None, "gen": 0, "armed_for": "", "armed_ts": 0.0, "handle": None}

    def _reply_stall_snapshot() -> str:
        """Deep state dump of LiveKit's scheduling internals at wedge time.

        Distinguishes the three possible stuck points inside
        ``_pipeline_reply_task`` (all produce IDENTICAL silence in logs):
          A. handle never scheduled  -> scheduler didn't pop it (queue/starvation)
          B. scheduled+authorized but user-silence gate open/closed mismatch
          C. handle already interrupted (silent drop path)
        Read-only getattr everywhere; never raises — diagnostics must not
        change call behavior.
        """
        try:
            act = getattr(session, "_activity", None)
            if act is None:
                return "snapshot: activity=None"
            def _ev(e):
                try:
                    return e.is_set()
                except Exception:
                    return "?"
            def _fd(f):
                try:
                    return f.done()
                except Exception:
                    return "?"
            q = list(getattr(act, "_speech_q", None) or [])
            cs = getattr(act, "_current_speech", None)
            parts = [
                f"scheduling_paused={getattr(act, '_scheduling_paused', '?')}",
                f"new_turns_blocked={getattr(act, '_new_turns_blocked', '?')}",
                f"scheduler_task_done={_fd(getattr(act, '_scheduling_atask', None))}",
                f"queue_len={len(q)}",
                f"user_silence_event_set={_ev(getattr(act, '_user_silence_event', None))}",
                f"authorization_allowed={_ev(getattr(act, '_authorization_allowed', None))}",
                f"user_state={getattr(getattr(act, '_session', None), 'user_state', None)}",
            ]
            h = stall_probe.get("handle")
            for label, s in (("pending_reply", h), ("current_speech", cs)):
                if s is None:
                    parts.append(f"{label}=None")
                    continue
                parts.append(
                    f"{label}[id={getattr(s, 'id', '?')} scheduled={getattr(s, 'scheduled', '?')}"
                    f" interrupted={getattr(s, 'interrupted', '?')} done={s.done() if callable(getattr(s, 'done', None)) else '?'}"
                    f" scheduled_fut_done={_fd(getattr(s, '_scheduled_fut', None))}"
                    f" authorized={_ev(getattr(s, '_authorize_event', None))}"
                    f" generations_open={sum(0 if _fd(g) else 1 for g in (getattr(s, '_generations', None) or []))}]"
                )
            if q:
                parts.append("queued=" + ",".join(
                    f"(h={getattr(x[2], 'id', '?')},sched={getattr(x[2], 'scheduled', '?')},int={getattr(x[2], 'interrupted', '?')})"
                    for x in q[:5]
                ))
            age = time.time() - stall_probe.get("armed_ts", time.time())
            parts.append(f"seconds_since_final={age:.1f}")
            return "snapshot: " + " ".join(parts)
        except Exception as e:
            return f"snapshot: unavailable ({e!r})"

    def _cancel_stall_probe(reason: str = "progress"):
        t = stall_probe.get("task")
        stall_probe["gen"] = stall_probe.get("gen", 0) + 1
        if t is not None and not t.done():
            t.cancel()
            logger.debug(f"[REPLY_PROBE_CANCELLED] gen={stall_probe['gen']} reason={reason}")
        stall_probe["task"] = None

    async def _stall_probe_handler(gen: int):
        try:
            await asyncio.sleep(6.0)
        except asyncio.CancelledError:
            return
        if gen != stall_probe.get("gen"):
            return
        if call_closed["done"] or closing_in_progress["done"] or closing_requested["done"]:
            return
        cur = state_tracker.get("state")
        if cur in ("thinking", "speaking"):
            return
        since = time.time() - stall_probe.get("armed_ts", time.time())
        logger.error(
            f"🚨 [REPLY_STALLED] no agent thinking/speaking {since:.1f}s after user final "
            f"'{stall_probe.get('armed_for', '')[:60]}' (agent state={cur}). {_reply_stall_snapshot()}"
        )

    def _arm_stall_probe(text: str) -> None:
        if agent_mode == "announcement":
            return
        _cancel_stall_probe(reason="re-arm")
        stall_probe["gen"] = stall_probe.get("gen", 0) + 1
        gen = stall_probe["gen"]
        stall_probe["armed_for"] = text
        stall_probe["armed_ts"] = time.time()
        try:
            stall_probe["task"] = asyncio.ensure_future(_stall_probe_handler(gen))
        except Exception:
            stall_probe["task"] = None

    def _on_speech_created(ev) -> None:
        try:
            handle = getattr(ev, "speech_handle", None)
            if getattr(ev, "source", "") == "generate_reply":
                # remember the latest pending reply handle so the stall probe
                # can dump its exact wait-state (scheduled/authorized/gate)
                stall_probe["handle"] = handle
            logger.info(
                "🔊 [SPEECH_CREATED] id=%s source=%s user_initiated=%s",
                getattr(handle, "id", "?") if handle is not None else "?",
                getattr(ev, "source", "?"),
                getattr(ev, "user_initiated", "?"),
            )
        except Exception:
            pass

    session.on("speech_created", _instrument_sync_callback("speech_created", _on_speech_created))

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

    # ------------------------------------------------------------------
    # Finalization (idempotent) + call-end watchdog.
    #
    # LiveKit's built-in `close_on_disconnect` only ends a session when the
    # disconnect reason is CLIENT_INITIATED / ROOM_DELETED / USER_REJECTED.
    # Closing the browser tab or a network drop uses a different reason, so the
    # session never closes and the call stays "in-progress" forever. We fix that
    # with a watchdog that ends the job (which runs `finalize_billing`) as soon
    # as the caller leaves for ANY reason.
    # ------------------------------------------------------------------
    _finalized = {"done": False}

    async def finalize_billing(reason=None):
        if _finalized["done"]:
            return
        _finalized["done"] = True
        try:
            duration = int(time.time() - call_start)
            # V2: Use actual LLM provider/model and cached tokens + TTFT for cost tracking - FIXED 0ms telemetry
            # Previous bug: turn_timing reset after each turn, so final billing showed 0ms TTFT/gen_time
            # Fix: Preserve last successful metrics in turn_timing["last_*"] and use them if current is 0
            try:
                # Try current timing first, then last successful, then usage
                llm_provider = turn_timing.get("llm_provider") or turn_timing.get("last_provider") or (cfg.providers.get_primary_llm().resolve_llm_provider_model()[0] if hasattr(cfg.providers, 'get_primary_llm') else cfg.providers.llm.id)
                llm_model = turn_timing.get("llm_model") or turn_timing.get("last_model") or (cfg.providers.get_primary_llm().resolve_llm_provider_model()[1] if hasattr(cfg.providers, 'get_primary_llm') else (cfg.providers.llm.config or {}).get("model", ""))
                
                # FIX: Use aggregated successful provider usage, not last/preserved timing object's token counts
                # Final billing must equal sum of successful requests
                aggregated_input = turn_timing.get("aggregated_input", 0)
                aggregated_output = turn_timing.get("aggregated_output", 0)
                aggregated_cached = turn_timing.get("aggregated_cached", 0)
                successful_count = turn_timing.get("successful_requests", 0)
                failed_count = turn_timing.get("failed_requests", 0)
                all_reqs = turn_timing.get("all_requests", [])
                
                # Calculate total cost from aggregated
                total_llm_cost = 0.0
                try:
                    from app.llm_catalog import get_llm_model, calculate_llm_cost
                    for req in all_reqs:
                        if req.get("success"):
                            m = get_llm_model(req.get("provider",""), req.get("model",""))
                            if m:
                                c = calculate_llm_cost(m, req["input"], req["cached"], req["output"])
                                total_llm_cost += c['total_llm_cost']
                except Exception as e:
                    logger.debug(f"Could not calculate total aggregated cost: {e}")
                
                if aggregated_input > 0 and successful_count > 0:
                    llm_input = aggregated_input
                    llm_output = aggregated_output
                    llm_cached = aggregated_cached
                    logger.info(f"💰 FINAL BILLING using AGGREGATED successful usage: {successful_count} successful, {failed_count} failed/invalidated, input={llm_input} cached={llm_cached} output={llm_output} total_cost=${total_llm_cost:.6f} (from {len(all_reqs)} total requests)")
                    for i, req in enumerate(all_reqs):
                        logger.info(f"  Request {i+1}: input={req['input']} cached={req['cached']} output={req['output']} success={req['success']} is_closing={req.get('is_closing',False)} TTFT={req['ttft']:.0f}ms gen={req['gen_time']:.0f}ms {req['provider']}:{req['model']}")
                    logger.info(f"📊 FINAL AGGREGATED BILLING successful_requests={successful_count} failed_requests={failed_count} total_input_tokens={aggregated_input} total_cached_tokens={aggregated_cached} total_output_tokens={aggregated_output} total_llm_cost=${total_llm_cost:.6f}")
                else:
                    # Fallback to last if no aggregated
                    llm_input = turn_timing.get("input_tokens", 0) or turn_timing.get("last_input", 0) or usage["llm_input_tokens"]
                    llm_cached = turn_timing.get("cached_input_tokens", 0) or turn_timing.get("last_cached", 0)
                    llm_output = turn_timing.get("output_tokens", 0) or turn_timing.get("last_output", 0) or usage["llm_output_tokens"]
                    logger.warning(f"⚠️ FINAL BILLING no aggregated successful usage, fallback to last/word count: input={llm_input} output={llm_output} (successful {successful_count}, failed {failed_count})")
                    logger.info(f"📊 FINAL BILLING FALLBACK successful_requests={successful_count} failed_requests={failed_count} total_input_tokens={llm_input} total_cached_tokens={llm_cached} total_output_tokens={llm_output} total_llm_cost=${total_llm_cost:.6f}")
                
                # TTFT and gen_time: current, then last, preserve actual measured values
                ttft = turn_timing.get("ttft_ms", 0) or turn_timing.get("last_ttft", 0)
                gen_time = turn_timing.get("generation_time_ms", 0) or turn_timing.get("last_gen_time", 0)
                
                # For final billing, also log average TTFT/gen_time across successful
                if all_reqs:
                    successful_reqs = [r for r in all_reqs if r['success']]
                    if successful_reqs:
                        avg_ttft = sum(r['ttft'] for r in successful_reqs) / len(successful_reqs)
                        avg_gen = sum(r['gen_time'] for r in successful_reqs) / len(successful_reqs)
                        logger.info(f"📊 FINAL BILLING averages across {len(successful_reqs)} successful: avg TTFT {avg_ttft:.0f}ms avg gen_time {avg_gen:.0f}ms last TTFT {ttft:.0f}ms last gen {gen_time:.0f}ms")
                # Task 1/2/3 call-level metric summaries (real numbers only).
                try:
                    _ch = int(turn_timing.get("cache_hits", 0) or 0)
                    _cm = int(turn_timing.get("cache_misses", 0) or 0)
                    _cu = int(turn_timing.get("cache_unknown", 0) or 0)
                    _cached_total = sum(int(r.get("cached", 0) or 0) for r in all_reqs if r.get("success"))
                    try:
                        from app.llm_catalog import get_prompt_cache_capability as _gcc_sum
                        _caps = [_gcc_sum(str(r.get("provider", "")), str(r.get("model", ""))) for r in all_reqs]
                        _supported_any = any(c.get("supported") for c in _caps)
                        _mode_set = sorted({c.get("mode", "none") for c in _caps}) if _caps else []
                        _cap_rollup = "/".join(_mode_set) if _mode_set else "none"
                    except Exception:
                        _supported_any = any("openai" in str(r.get("provider", "")).lower() for r in all_reqs)
                        _cap_rollup = "?"
                    if _ch > 0:
                        _cache_verdict = "working"
                    elif _cm > 0:
                        _cache_verdict = "not_engaging (cache-capable path verified; every usage-returning request reported 0 cached — stable prefix vs provider minimum or routing; see per-request [CACHE] lines)"
                    elif _supported_any:
                        _cache_verdict = "unverifiable (no cache-capable request returned usage — failed/invalidated requests are NOT cache misses; re-run when calls succeed)"
                    else:
                        _cache_verdict = "unsupported (every request's provider/model has capability=none — reported honestly, no cache pretended)"
                    logger.info(f"🗄️ [CACHE] summary: requests={len(all_reqs)} capabilities={_cap_rollup} evaluated(hit+miss,usage-only)={_ch + _cm} hits={_ch} misses={_cm} unknown={_cu} cached_tokens_total={_cached_total} verdict={_cache_verdict}")
                    _rle = int(turn_timing.get("rate_limit_events", 0) or 0)
                    _prb = int(turn_timing.get("recovery_probes", 0) or 0)
                    _prf = int(turn_timing.get("probe_failures", 0) or 0)
                    logger.info(f"🔁 [FALLBACK_SUMMARY] rate_limit_429={_rle} recovery_probes={_prb} probe_failures={_prf} overlapping_starts={int(turn_timing.get('overlapping_starts', 0) or 0)} — probes are FallbackAdapter health checks (documented lifecycle, not patched) and are never billed to the call; each 429 produced one clean switch to the configured fallback, no turn-level retry on the failed model")
                    logger.info(f"🔇 [PREEMPTIVE] summary: enabled={globals().get('_PREEMPTIVE_ENABLED_FOR_LOG', False)} started=0 cancelled=0 reused=0 discarded=0 would_cancel={int(turn_timing.get('spec_would_cancel', 0) or 0)} overlapping_llm_starts={int(turn_timing.get('overlapping_starts', 0) or 0)} (gated off by design while per-turn RAG injection exists)")
                    _ls = turn_timing.get("latency_samples", [])
                    if _ls:
                        def _avg(k, _src=_ls):
                            _v = [x[k] for x in _src if isinstance(x, dict) and x.get(k) is not None and x[k] >= 0]
                            return (sum(_v) / len(_v)) if _v else float("nan")
                        logger.info(f"🔊 [LATENCY] summary over {len(_ls)} spoken turns: avg speech_to_first_audio_ms={_avg('speech_end_to_first_audio_ms'):.0f} avg ttft_to_first_audio_ms={_avg('tts_synth_ms'):.0f} avg turn_commit_ms={_avg('turn_commit_ms'):.0f} (first audio measured on the REAL TTS frame stream via Agent.tts_node)")
                except Exception as _le:
                    logger.debug(f"call metric summaries skipped: {_le!r}")
                
                if ttft == 0 and gen_time == 0:
                    logger.warning(f"⚠️ FINAL BILLING TTFT/gen_time still 0 after checking last metrics - using 0, but actual measurements were logged during call")
                
                logger.info(f"💰 FINAL BILLING LLM provider={llm_provider} model={llm_model} input={llm_input} cached={llm_cached} output={llm_output} TTFT={ttft:.0f}ms gen_time={gen_time:.0f}ms successful={successful_count} failed={failed_count} total_cost=${total_llm_cost:.6f} (aggregated authoritative)")
            except Exception as e:
                logger.debug(f"Could not get V2 billing info: {e}")
                llm_provider = cfg.providers.llm.id
                llm_model = (cfg.providers.llm.config or {}).get("model", "")
                llm_input = usage["llm_input_tokens"]
                llm_cached = 0
                llm_output = usage["llm_output_tokens"]
                ttft = turn_timing.get("ttft_ms", 0) or turn_timing.get("last_ttft", 0)
                gen_time = turn_timing.get("generation_time_ms", 0) or turn_timing.get("last_gen_time", 0)

            costs = calculate_call_cost(
                duration_seconds=duration,
                stt_seconds=usage["user_speech_seconds"],
                llm_input_tokens=llm_input,
                llm_output_tokens=llm_output,
                tts_chars=usage["tts_chars"],
                llm_provider_id=llm_provider,
                llm_provider=llm_provider,
                llm_model_id=llm_model,
                llm_cached_input_tokens=llm_cached,
                llm_ttft_ms=ttft,
                llm_generation_time_ms=gen_time,
                stt_provider_id=cfg.providers.stt.id,
                tts_provider_id=cfg.providers.tts.id,
                client_rate_per_min=cfg.client_rate_per_min,
                # Super-Admin pricing layers: per-mode flat rate (announcement/
                # assistant) + concurrency tier & misc fees (billing_rates.py).
                agent_mode=agent_mode,
                max_concurrency=int(getattr(cfg, "max_concurrency", 1) or 1),
            )
            if memory_enabled:
                memory.save(customer_key, usage["transcripts"])

            # Only treat it as a real call if something was said or it ran long
            # enough. Otherwise mark it failed so it isn't billed.
            real_call = (duration >= _FAIL_THRESHOLD_SECONDS) or (usage["user_speech_seconds"] > 0)
            status = "completed" if real_call else "failed"

            # FIX: Pass turn_timing_ref for authoritative billing display
            try:
                print(_billing_report(costs, usage, duration, turn_timing_ref=turn_timing))
            except Exception:
                print(_billing_report(costs, usage, duration))

            # IMPORTANT: Post billing to backend FIRST so wallet deduction happens
            # atomically in main.py (which also updates the call record). This
            # prevents the race where worker marks completed before backend can deduct.
            billing_posted = False
            if real_call:
                try:
                    billing_posted = await _post_billing(call_record["id"], user_id, agent_id, mode, phone,
                                        duration, costs, usage, recording_url, status)
                except Exception as e:
                    logger.warning(f"Billing POST exception, will fallback to direct DB: {e!r}", exc_info=True)
                    billing_posted = False

            # Preserve a failure reason recorded earlier on this call (the
            # setup-failure path writes usage.error into the DB before the
            # shutdown callbacks run — a blind overwrite would wipe it and the
            # UI would lose the "why").
            try:
                from app.db import get_prisma
                prior_row = await get_prisma().call.find_unique(where={"id": call_record["id"]})
                if prior_row is not None:
                    prior_dict = repo._call_dict(prior_row)
                    prior_error = (prior_dict.get("usage") or {}).get("error")
                    if prior_error:
                        usage["error"] = prior_error
                        # A setup failure is a failed, unbilled call. (If a real
                        # conversation had run long before a late failure, keep
                        # the status the duration check produced.)
                        if not real_call:
                            status = "failed"
            except Exception:
                pass

            # Fallback local update (ensures call is marked completed even if backend unreachable)
            try:
                await repo.update_call(call_record["id"], {
                    "status": status,
                    "ended_at": time.strftime("%Y-%m-%d %H:%M"),
                    "duration_seconds": duration,
                    "transcripts": usage["transcripts"][-60:],
                    "usage": usage,
                    "cost": costs if real_call else {},
                    "recording_url": recording_url,
                })
            except Exception as e:
                logger.warning(f"Local call update failed: {e}")

            # Fallback direct wallet deduct only if backend /api/billing/log failed
            if real_call and not billing_posted:
                try:
                    has_spend = False
                    try:
                        has_spend = await repo.has_spend_for_call(call_record.get("user_id", user_id), call_record["id"])
                    except Exception as he:
                        logger.warning(f"has_spend check failed: {he}")
                    if not has_spend:
                        charge = float(costs.get("client_price_inr", 0) or 0)
                        if charge > 0:
                            wallet = await repo.deduct(call_record.get("user_id", user_id), charge, note=f"Call {call_record['id']}")
                            logger.info(f"💸 Wallet fallback deducted ₹{charge} for call {call_record['id']} — remaining balance ₹{wallet.get('balance', 0)}")
                except Exception as de:
                    logger.warning(f"Direct wallet deduct failed for call {call_record['id']}: {de!r}")

        except Exception as e:
            logger.exception(f"finalize_billing error: {e}")

    # Register the shutdown callback BEFORE the session starts, so finalization is
    # always wired even if setup/session errors out or the room closes instantly.
    try:
        ctx.add_shutdown_callback(finalize_billing)
    except Exception:
        pass

    # Watchdog: end the call when the caller leaves for any reason (closing the
    # tab, network drop, or clicking "Leave"). Closing the session unblocks
    # session.start(), which lets the job shut down and run finalize_billing.
    async def watch_call_end():
        """End this job only after the human caller has actually left.

        close_on_disconnect is off so a goodbye can finish. That also meant a
        hung-up browser could leave the only worker process stuck inside
        session.start(). The next call — after the user picked a different
        agent — was dispatched to nobody and stayed silent.

        A caller who is still connected is not idle. Silence is the no-response
        timer's job. This watcher only releases the job once the caller is gone.
        """
        room = ctx.room
        released = {"done": False}
        saw_human = {"yes": False}
        gone_since = {"t": 0.0}

        def _kind(participant) -> int:
            kind = getattr(participant, "kind", 0)
            try:
                return int(kind)
            except Exception:
                return 0

        def _is_human(participant) -> bool:
            if participant is None or participant == getattr(room, "local_participant", None):
                return False
            # 1 ingress, 2 egress, 4 agent — not the person on the call.
            if _kind(participant) in (1, 2, 4):
                return False
            identity = (getattr(participant, "identity", "") or "").lower()
            if identity.startswith("eg_") or "egress" in identity:
                return False
            return True

        def _humans():
            try:
                return [p for p in room.remote_participants.values() if _is_human(p)]
            except Exception:
                return []

        async def _release(reason: str, source: str = "timeout"):
            if released["done"]:
                return
            released["done"] = True
            call_closed["done"] = True
            logger.info(
                "[CALL_END_REQUESTED] source=%s reason=%s room=%s agent_id=%s",
                source, reason, getattr(ctx.room, "name", ""), agent_id,
            )
            _cancel_pending()
            _cancel_no_response()
            fallback_task = reply_tracker.get("fallback_say")
            if fallback_task is not None and not fallback_task.done():
                fallback_task.cancel()
            reply_tracker["fallback_say"] = None
            try:
                session.shutdown(drain=False)
            except Exception as e:
                logger.warning("session.shutdown on caller leave failed: %r", e)

            room_name = getattr(ctx.room, "name", None)
            if room_name:
                try:
                    from app.telephony import end_active_room
                    await end_active_room(room_name)
                except Exception:
                    pass

            try:
                ctx.shutdown()
            except Exception as e:
                logger.warning("ctx.shutdown failed: %r", e)

            logger.info("[CALL_ENDED] room=%s agent_id=%s reason=%s", getattr(ctx.room, "name", ""), agent_id, reason)
            call_finished.set()

        def _on_connected(participant):
            if not _is_human(participant):
                return
            saw_human["yes"] = True
            gone_since["t"] = 0.0
            logger.info("[AGENT_JOINED] room=%s Caller joined: %s", getattr(room, "name", ""), getattr(participant, "identity", "?"))

        def _on_disconnected(participant):
            if not _is_human(participant):
                return
            if _humans():
                return
            gone_since["t"] = time.time()
            logger.info("👤 Caller disconnected: %s (grace period active)", getattr(participant, "identity", "?"))

        room.on("participant_connected", _on_connected)
        room.on("participant_disconnected", _on_disconnected)
        initial_humans = _humans()
        if initial_humans:
            saw_human["yes"] = True
            logger.info("[AGENT_JOINED] room=%s Caller already in room (%d): %s", getattr(room, "name", ""), len(initial_humans), [p.identity for p in initial_humans])

        try:
            while not released["done"]:
                await asyncio.sleep(0.5)
                # Announcement agent manages its own completion — don't interfere while it's playing
                if agent_mode == "announcement":
                    ag = agent_holder.get("agent")
                    if ag is not None and getattr(ag, "_opening_started", False) and not getattr(ag, "_opening_done", False):
                        continue

                humans = _humans()
                if humans:
                    saw_human["yes"] = True
                    gone_since["t"] = 0.0
                    continue
                if not saw_human["yes"]:
                    continue
                if gone_since["t"] == 0.0:
                    gone_since["t"] = time.time()
                    continue
                # Generous 12-second grace period (NOT 1.5s!) before deciding caller is truly gone
                if time.time() - gone_since["t"] >= 12.0:
                    await _release("user_ended", source="timeout")
                    return
        except asyncio.CancelledError:
            return
        finally:
            try:
                room.off("participant_connected", _on_connected)
                room.off("participant_disconnected", _on_disconnected)
            except Exception:
                pass

    async def _backup_opening_line():
        """Speak the greeting/script if on_enter never started.

        A connected browser call that stays silent is the bug this covers.
        """
        try:
            await asyncio.sleep(8)
        except asyncio.CancelledError:
            return
        if call_closed["done"] or closing_in_progress["done"]:
            return
        ag = agent_holder.get("agent")
        if ag is not None and getattr(ag, "_opening_started", False):
            return
        if state_tracker.get("state") == "speaking":
            return
        if any((t.get("text") or "").strip() and t.get("role") == "agent" for t in usage["transcripts"]):
            return
        if agent_mode == "announcement":
            line = (getattr(cfg, "announce_text", "") or greeting or "").strip()
        else:
            line = (greeting or "").strip()
        if not line:
            logger.warning("🛟 No greeting or script configured — nothing to speak")
            return
        logger.warning("🛟 Opening line had not started — speaking it now (%s)", agent_mode)
        try:
            # Assistant-mode greetings must be interruptible (the primary path
            # in agent_builder.speak_opening_line passes True now too); this
            # fallback line was the same hard-protected pattern. Announcements
            # stay one-way.
            handle = session.say(line, allow_interruptions=(agent_mode != "announcement"))
            waiter = getattr(handle, "wait_for_playout", None)
            if callable(waiter):
                await asyncio.wait_for(waiter(), timeout=45)
            elif handle is not None:
                await asyncio.wait_for(handle, timeout=45)
            logger.info("✅ Backup opening line finished")
        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.warning("backup opening line failed: %s: %r", type(e).__name__, e)

    # Deduplication check: if another agent has already connected to this room, exit immediately
    try:
        remote_agents = [
            p for p in ctx.room.remote_participants.values()
            if getattr(p, "kind", None) == 4
            or getattr(p, "is_agent", False)
            or (getattr(p, "identity", "") or "").startswith("agent-")
        ]
        if remote_agents:
            logger.warning(
                "⚠️ Duplicate agent already present in room %s (%s). Exiting this runner to prevent duplicate audio.",
                getattr(ctx.room, "name", ""),
                [getattr(p, "identity", "") for p in remote_agents],
            )
            call_closed["done"] = True
            ctx.shutdown()
            return
    except Exception as e:
        logger.debug("duplicate agent check: %r", e)

    opening_backup = asyncio.create_task(_backup_opening_line())
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


