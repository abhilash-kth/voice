"""Turn-detection latency metric logging (EOU → turn decision).

Extracted verbatim from `worker_entrypoint.py` (<=300-line rule). Recovers
final-to-turn-decision time from LiveKit EOUMetrics and correlates event-
loop blockage samples over the decision window. Observability only.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("voice-agent-saas-worker")


def attach_turn_metrics(session, turn_timing, _sync_callback_records,
                        _turn_task_wait_samples, _loop_stack_samples):

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


def new_turn_timing(ctx) -> dict:
    """Fresh per-call turn-timing record (latency tracing + aggregated
    billing counters). Extracted verbatim from `_entrypoint_body`."""
    tt = {
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
    return tt
