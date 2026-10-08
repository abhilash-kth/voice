"""First-token instrumentation + per-chunk usage extraction for the LLM
timing stream wrapper. Extracted 1:1 from `llm_timing_factory.py` (__aiter__).
"""
from __future__ import annotations

import logging
import time as _time

_logger = logging.getLogger("voice-agent-saas-worker")


def record_first_token_events(self, now):
    first_token = now
    self._timing["first_token"] = first_token
    _first_token_mono_ns = _time.perf_counter_ns()
    self._timing["first_token_mono"] = _first_token_mono_ns
    self._timing["pipeline_stage"] = "llm_first_token"
    ttft = (first_token - self._req_start) * 1000
    self._timing["ttft_ms"] = ttft
    prov = self._prov_info.get('provider', '') or self._timing.get('llm_provider', 'unknown')
    model = self._prov_info.get('model_id', '') or self._timing.get('llm_model', 'unknown')
    self._pending_first_logs.append((0, f"LLM TTFT [LLM_FIRST_TOKEN] provider={prov} model={model} TTFT={ttft:.0f}ms (first_token - request_start)"))
    # Task 2 boundaries: join the two httpx hook
    # timestamps for THIS attempt (rid) to the first
    # decoded stream chunk, measured here — without
    # consuming or touching the stream (the stream
    # continues through this loop normally).
    try:
        from ..http_timing import pop_for_model as _pop_ht
        _hrec = _pop_ht(str(model))
        if _hrec:
            self._rid = str(_hrec.get("rid", "n/a")) or "n/a"
        if _hrec:
            _t0 = _hrec["send_mono_ns"]; _t1 = _hrec["headers_mono_ns"]
            # pop+format stay here (µs; keeps rid
            # attribution race-free), only the log IO
            # is deferred off the chunk-1 hop
            self._pending_first_logs.append((0,
                "⏱️ [HTTP_CHUNK] rid=%s model=%s request_start->first_stream_chunk=%.0fms response_headers->first_stream_chunk=%.0fms monotonic_ns=%d (first chunk = first SSE delta decoded by the SDK — application-level boundary, NOT to be quoted as provider TTFB)" % (
                    _hrec.get("rid", "?"), model,
                    (_first_token_mono_ns - _t0) / 1e6, (_first_token_mono_ns - _t1) / 1e6, _first_token_mono_ns,
                )))
    except Exception:
        pass
    if ttft > 1800:
        # Task 5 forensics: what was around this request?
        self._pending_first_logs.append((1, f"🐢 [TTFT_SPIKE_CONTEXT] TTFT={ttft:.0f}ms inflight_llm={self._timing.get('inflight_llm',0)} overlapping_starts={self._timing.get('overlapping_starts',0)} head_sha={self._timing.get('head_sha','?')} — cross-check openai._base_client retry lines (429/timeout backoff) and [LOOP_LAG] events"))
    if self._timing.get("llm_start", 0) > 0:
        self._pending_first_logs.append((0, f"TIMING LLM_start->first_token: {(first_token-self._timing['llm_start'])*1000:.0f}ms (TTFT)"))
    if self._timing.get("speech_end", 0) > 0:
        self._pending_first_logs.append((0, f"TIMING speech_end->first_token: {(first_token-self._timing['speech_end'])*1000:.0f}ms"))


def extract_chunk_usage(self, chunk):
    try:
        usage = getattr(chunk, 'usage', None)
        if usage:
            self._usage_seen = True
            self._input_tokens = getattr(usage, 'prompt_tokens', 0) or getattr(usage, 'input_tokens', 0) or self._input_tokens
            self._output_tokens = getattr(usage, 'completion_tokens', 0) or getattr(usage, 'output_tokens', 0) or self._output_tokens
            # ROOT CAUSE of "cached=0 on every request" (real call
            # 2026-09-24 01:55): livekit 1.8 maps OpenAI's
            # usage.prompt_tokens_details.cached_tokens into
            # CompletionUsage.prompt_cached_tokens at the inference
            # layer (livekit/agents/inference/llm.py:475-486) and
            # that details attribute is GONE from the object we
            # receive. Reading only prompt_tokens_details made
            # cached silently 0 even if the provider reported hits.
            # Read the mapped field first; keep the raw-shape and
            # dict fallbacks for other adapters.
            _cached_v = getattr(usage, 'prompt_cached_tokens', None)
            if _cached_v is None and isinstance(usage, dict):
                _pd = usage.get('prompt_tokens_details') or usage.get('input_tokens_details') or {}
                _cached_v = _pd.get('cached_tokens') if isinstance(_pd, dict) else getattr(_pd, 'cached_tokens', None)
            if _cached_v is None:
                prompt_details = getattr(usage, 'prompt_tokens_details', None)
                if prompt_details is not None:
                    _cached_v = getattr(prompt_details, 'cached_tokens', 0)
            self._cached_tokens = int(_cached_v or 0)
    except Exception:
        pass
