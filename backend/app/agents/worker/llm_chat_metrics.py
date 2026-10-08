"""Request-level LLM timing metrics: the outer `chat()` of `LLMTimingWrapper`
(chat-context extraction, stable-head fingerprinting, span classification).
Extracted 1:1 from `llm_timing_factory.py`.
"""
from __future__ import annotations

import hashlib as _hl
import logging
import time as _time
import traceback

from .llm_chat_cm import TimingChatCM, _is_recovery_probe

_logger = logging.getLogger("voice-agent-saas-worker")


def timed_chat_outer(self, *args, **kwargs):
    _wrapper_entry_ns = _time.perf_counter_ns()
    _logger.info("[TURN_TRACE] stage=llm_wrapper_enter monotonic_ns=%d call_id=%s turn_id=%s generation_id=%s", _wrapper_entry_ns, self._timing.get("call_id", "N/A"), self._timing.get("turn_id", "N/A"), self._timing.get("gen", "N/A"))
    # Recovery-probe bypass (Task 2, 12:28): FallbackAdapter's
    # background health check reaches this SAME wrapped instance while
    # the fallback stream is still answering the caller. It must not be
    # treated as a turn: no overlap warning, no active-flag churn, no
    # generation/sequence ownership, no shared counter resets, no
    # billing record — the isolated _ProbeStreamPassThrough only counts
    # its outcome. (Intentional adapter behavior; lifecycle documented
    # at the builder's FallbackAdapter construction — not patched.)
    if _is_recovery_probe():
        # Count EVERY probe attempt (started), outcome separately — the
        # [FALLBACK_SUMMARY] line needs both to explain the overlap.
        self._timing["recovery_probes"] = int(self._timing.get("recovery_probes", 0)) + 1
        try:
            _logger.info("🧪 [LLM_RECOVERY_PROBE] provider=%s model=%s instance=%s starting — background health check, isolated from turn accounting", self._prov_info.get('provider', ''), self._prov_info.get('model_id', ''), getattr(self, '_inst_label', 'single/1'))
            return TimingChatCM(self._inner.chat(*args, **kwargs), self._timing, self._prov_info, _time.time(), None, probe=True, inst=getattr(self, '_inst_label', 'single/1'))
        except Exception:
            self._timing["probe_failures"] = int(self._timing.get("probe_failures", 0)) + 1
            raise
    # This is the critical fix: chat is SYNC, returns async CM, not coroutine
    # So `async with llm.chat(...) as stream` works
    # FIX: Prevent duplicate/invalidated LLM requests - exactly one REQUEST START per completed user turn
    # Previous bug: Request 1 and 5 had input=0 output=0 success=False even though preemptive disabled
    # Root cause: New REQUEST START while previous llm_active True, causing previous to be cancelled and return 0/0
    # Fix: Check if previous LLM still active, if so log and ensure previous not counted as failed duplicate
    if self._timing.get("llm_active", False):
        prev_start = self._timing.get("request_start", 0)
        elapsed = _time.time() - prev_start if prev_start else 0
        _logger.warning(f"⚠️ LLM REQUEST START while previous still active (elapsed {elapsed:.2f}s) - previous will be cancelled and return 0/0, this is duplicate/invalidated request. Ensuring exactly one valid per turn by marking previous as invalidated, not failed.")
        self._timing["overlapping_starts"] = self._timing.get("overlapping_starts", 0) + 1
        # Mark previous as invalidated, not failed, to prevent duplicate counting
        # Don't increment failed_requests for superseded preemptive/invalidated
        # The new request will be the valid one for this turn

    request_start = _time.time()
    self._timing["request_start_mono"] = _time.perf_counter_ns()
    self._timing["pipeline_stage"] = "llm_request_start"
    self._timing["request_start"] = request_start
    self._timing["llm_start"] = request_start
    self._timing["llm_request_start_ts"] = request_start
    _request_mono = self._timing["request_start_mono"]
    _callback_enter_mono = int(self._timing.get("callback_enter_mono_ns", 0) or 0)
    _commit_to_request = (
        f"{(_request_mono - _callback_enter_mono) / 1_000_000:.0f}ms"
        if _callback_enter_mono > 0 and _request_mono >= _callback_enter_mono
        else "N/A"
    )
    _logger.info("⏱️ [TURN_TIMING] callback_enter_to_llm_request_start_ms=%s", _commit_to_request)
    self._timing["llm_active"] = True
    # Generation token: "gen" is the TURN/barge-in epoch — only the
    # interruption path bumps it (see [GENERATION_INVALIDATED]). The old
    # per-chat() +1 here made a fallback switch or a health probe LOOK
    # like a stale generation: the live fallback stream got
    # [STALE_GENERATION_DROPPED] mid-answer and stopped publishing its
    # own TTFT — the "stale-generation cancellation" of the 12:28 logs.
    # Attempts belonging to ONE turn share its gen; per-request
    # supersession is tracked by active_req_seq (which stream may write
    # shared state) instead.
    _gen = int(self._timing.get("gen", 0))
    _seq = int(self._timing.get("llm_req_seq", 0)) + 1
    self._timing["llm_req_seq"] = _seq
    self._timing["active_req_seq"] = _seq
    self._timing["assistant_output_received"] = False
    # Task 2 (2026-09-24): log what actually builds the ~2900-token
    # request and PROVE prefix stability instead of assuming it. The
    # hash covers the stable head (leading system messages + tool
    # defs); OpenAI caches on shared prefixes >=1024 tokens, so a
    # stable hash with cached=0 points at the provider/account, while
    # a changing hash is our bug and the diff names the section.
    _req_inflight = False
    _prompt_prepare_start_ns = _time.perf_counter_ns()
    _token_estimate_ns = _fingerprint_ns = _cache_metadata_ns = 0
    _token_estimate_start_ns = _fingerprint_start_ns = _cache_metadata_start_ns = 0
    try:
        _cc = kwargs.get("chat_ctx")
        if _cc is None and args:
            _cc = args[0]
        if _cc is not None:
            from .llm_chat_inspect import _inspect_chat_ctx
            _token_estimate_ns, _fingerprint_ns, _cache_metadata_ns, _req_inflight = _inspect_chat_ctx(self, args, kwargs)
    except Exception as _pe:
        # never silent again: one visible line per call is cheap and this
        # exact silence is what hid the head_sha instrumentation failure in
        # the 02:12 call.
        if not self._timing.get("prompt_acct_warned"):
            self._timing["prompt_acct_warned"] = True
            _logger.warning("[PROMPT] section accounting failed (once): %r", _pe)
        _logger.debug(f"[PROMPT] section accounting skipped: {_pe!r}")
    _prompt_prepare_ns = _time.perf_counter_ns() - _prompt_prepare_start_ns
    # Reset per-request metrics but preserve provider/model and aggregated billing
    # Preserve aggregated and is_closing
    preserved_aggregated = {
        "aggregated_input": self._timing.get("aggregated_input", 0),
        "aggregated_output": self._timing.get("aggregated_output", 0),
        "aggregated_cached": self._timing.get("aggregated_cached", 0),
        "successful_requests": self._timing.get("successful_requests", 0),
        "failed_requests": self._timing.get("failed_requests", 0),
        "all_requests": self._timing.get("all_requests", []),
        "is_closing": self._timing.get("is_closing", False),
    }
    self._timing["first_token"] = 0.0
    self._timing["generation_complete"] = 0.0
    self._timing["llm_complete"] = 0.0
    self._timing["ttft_ms"] = 0.0
    self._timing["generation_time_ms"] = 0.0
    self._timing["input_tokens"] = 0
    self._timing["output_tokens"] = 0
    self._timing["cached_input_tokens"] = 0
    # Restore preserved aggregated
    self._timing["aggregated_input"] = preserved_aggregated["aggregated_input"]
    self._timing["aggregated_output"] = preserved_aggregated["aggregated_output"]
    self._timing["aggregated_cached"] = preserved_aggregated["aggregated_cached"]
    self._timing["successful_requests"] = preserved_aggregated["successful_requests"]
    self._timing["failed_requests"] = preserved_aggregated["failed_requests"]
    self._timing["all_requests"] = preserved_aggregated["all_requests"]
    self._timing["is_closing"] = preserved_aggregated["is_closing"]
    prov = self._prov_info.get('provider', '') or self._timing.get('llm_provider', '') or 'unknown'
    model = self._prov_info.get('model_id', '') or self._timing.get('llm_model', '') or getattr(self._inner, 'model', 'unknown') or 'unknown'
    base_url = self._prov_info.get('base_url', '') or 'https://api.openai.com/v1'
    _logger.info(f"LLM REQUEST START [LLM_RESPONSE_STARTED] provider={prov} model={model} base_url={base_url} llm_instance={getattr(self, '_inst_label', 'single/1')} request_start={request_start} — a new line here on a DIFFERENT model+instance = LiveKit FallbackAdapter switching (mechanism B), NOT an SDK retry; duplicates on the same instance = invalidated-generation overlap (mechanism C)")
    try:
        _request_build_start_ns = _time.perf_counter_ns()
        inner_result = self._inner.chat(*args, **kwargs)
        _request_build_ns = _time.perf_counter_ns() - _request_build_start_ns
        _wrapper_total_ns = _time.perf_counter_ns() - _wrapper_entry_ns
        _logger.info("[LLM_LOCAL_TIMING] prompt_prepare_ms=%.3f token_estimate_ms=%.3f fingerprint_ms=%.3f cache_metadata_ms=%.3f request_build_ms=%.3f wrapper_total_ms=%.3f call_id=%s turn_id=%s generation_id=%s", _prompt_prepare_ns/1e6, _token_estimate_ns/1e6, _fingerprint_ns/1e6, _cache_metadata_ns/1e6, _request_build_ns/1e6, _wrapper_total_ns/1e6, self._timing.get("call_id", "N/A"), self._timing.get("turn_id", "N/A"), _gen)
        # inner_result may be coroutine or CM - handle both in TimingChatCM
        return TimingChatCM(inner_result, self._timing, self._prov_info, request_start, _gen, seq=_seq, inst=getattr(self, '_inst_label', 'single/1'), counted=_req_inflight)
    except Exception as e:
        error_time = _time.time()
        prov = self._prov_info.get('provider', '') or 'unknown'
        model = self._prov_info.get('model_id', '') or 'unknown'
        base_url = self._prov_info.get('base_url', '') or 'unknown'
        _logger.error(f"LLM API ERROR provider={prov} model={model} base_url={base_url} Error={e} Type={type(e).__name__} After {(error_time-request_start)*1000:.0f}ms")
        # Avoid synchronous traceback.format_exc() on event loop (tokenize.open 176ms block)
        # This is sync chat() path — cannot await. Log minimal now, schedule full traceback off-loop.
        try:
            import asyncio as _aio_tb
            _loop_tb = _aio_tb.get_event_loop()
            def _log_tb_async():
                try:
                    _tb = traceback.format_exc()
                    _logger.error(f"Full traceback: {_tb[:2000]}")
                except Exception:
                    pass
            # Schedule traceback logging off the critical path via thread
            _loop_tb.call_soon_threadsafe(lambda: _aio_tb.create_task(_aio_tb.to_thread(_log_tb_async)) if _loop_tb.is_running() else None)
        except Exception:
            pass
        raise
