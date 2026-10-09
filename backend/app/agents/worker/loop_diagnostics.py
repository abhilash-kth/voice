"""Event-loop stall diagnostics for the active call.

Extracted verbatim from `worker_entrypoint.py` (<=300-line rule). Read-only
observability: measures event-loop drift during active calls, dumps
blocked-callback stacks, and can wrap slow sync callbacks.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import threading
import time

logger = logging.getLogger("voice-agent-saas-worker")


def build_loop_diagnostics(ctx, turn_timing):
    """Start the loop-lag task + blocked-stack sampler thread and return the
    shared record map (sync-callback records, task-wait samples, stack
    samples, heartbeat, stop event, instrument wrapper). State ownership moved
    here from `_entrypoint_body`; behaviour identical."""

    # Separate call-time loop stalls from worker startup/idle/shutdown stalls.
    _sync_callback_records = []
    _turn_task_wait_samples = []
    _loop_stack_samples = []
    _loop_heartbeat = {"ns": time.monotonic_ns(), "active": False}
    _loop_sampler_stop = threading.Event()
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
    return {
        "sync_callback_records": _sync_callback_records,
        "turn_task_wait_samples": _turn_task_wait_samples,
        "loop_stack_samples": _loop_stack_samples,
        "heartbeat": _loop_heartbeat,
        "sampler_stop": _loop_sampler_stop,
        "instrument": _instrument_sync_callback,
    }
