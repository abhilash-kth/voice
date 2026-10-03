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


def _create_llm_timing_wrapper(llm_instance, timing_dict, provider_info=None, inst_label=None):
    """Fixed LLM timing wrapper that properly implements async context manager protocol.
    
    LiveKit's LLM.chat returns an async context manager (LLMStream), used as:
        async with llm.chat(chat_ctx=...) as stream:
            async for chunk in stream:
    
    Previous buggy version made chat async def returning StreamWrapper directly,
    causing TypeError: 'coroutine' object does not support async context manager.
    
    Fixed version: chat is sync def returning a custom async CM that wraps inner CM,
    and whose __aenter__ returns a TimingStreamWrapper that measures TTFT.
    """
    import asyncio as _asyncio
    import time as _time
    import re as _re_own
    import logging as _logging
    _logger = _logging.getLogger("voice-agent-saas-worker")

    def _is_recovery_probe() -> bool:
        """True inside livekit's FallbackAdapter background health check.

        1.8.2 marks a failed LLM unavailable and schedules
        _try_recovery._recover_llm_task, which calls llm.chat() on the SAME
        wrapped instance (a real HTTP request) while the fallback stream is
        still answering the caller — the "primary/0-of-2 after fallback/1-of-2
        while previous generation still active" log line. It is intentional
        adapter behavior (lifecycle documented at the builder's
        FallbackAdapter construction). We keep it OUT of turn accounting: no
        generation bump, no shared timing reset, no billing record — it is
        infrastructure cost, not the caller's conversation.
        """
        try:
            _ct = _asyncio.current_task()
            if _ct is None:
                return False
            return "_recover_llm_task" in repr(_ct.get_coro())
        except Exception:
            return False

    def _rate_limit_fields(exc):
        """(is_429, limit, used, requested, retry_after_ms) — ONLY numbers the
        provider actually sent (headers / error body), never invented.
        'unknown' marks what the provider did not report."""
        try:
            status = getattr(exc, "status_code", None)
            msg = str(exc or "")
            _ename = type(exc).__name__
            is429 = (str(status) == "429") or (_ename == "RateLimitError") or (
                "429" in msg and ("rate limit" in msg.lower() or "too many" in msg.lower())
            )
            if not is429:
                return False, None, None, None, None
            headers = {}
            try:
                _r = getattr(exc, "response", None)
                if _r is not None:
                    headers = {str(k).lower(): str(v) for k, v in dict(getattr(_r, "headers", {}) or {}).items()}
            except Exception:
                headers = {}
            def _h(*names):
                for n in names:
                    v = headers.get(n)
                    if v is not None:
                        return v
                return None
            limit = _h("x-ratelimit-limit-tokens-minute", "x-ratelimit-limit-tokens", "x-ratelimit-limit-tokens-minute-uncached")
            used = _h("x-ratelimit-used-tokens-minute", "x-ratelimit-remaining-tokens")
            ra = _h("retry-after", "retry-after-tokens")
            ra_ms = "unknown"
            if ra is not None:
                try:
                    ra_ms = int(float(ra) * 1000)
                except Exception:
                    if str(ra).strip().lower().endswith("s"):
                        try:
                            ra_ms = int(float(str(ra).strip()[:-1]) * 1000)
                        except Exception:
                            pass
            if limit is None:
                m = _re_own.search(r"limit[^0-9]{0,12}([0-9]{3,})", msg, _re_own.IGNORECASE)
                if m:
                    limit = m.group(1)
            if used is None:
                m2 = _re_own.search(r"([0-9]{3,})\s*(?:tokens?\s*)?/\s*([0-9]{3,})", msg)
                if m2:
                    used = m2.group(1)
            req = None
            m3 = _re_own.search(r"request(?:ed)?[^0-9]{0,12}([0-9]{2,})", msg, _re_own.IGNORECASE)
            if m3:
                req = m3.group(1)
            return True, limit or "unknown", used or "unknown", req or "unknown", ra_ms
        except Exception:
            return False, None, None, None, None

    try:
        is_fallback = hasattr(llm_instance, '_llm_instances') or hasattr(llm_instance, 'llm_instances') or 'FallbackAdapter' in str(type(llm_instance))
        if is_fallback:
            inner_list = getattr(llm_instance, '_llm_instances', None) or getattr(llm_instance, 'llm_instances', None) or getattr(llm_instance, '_instances', None)
            if inner_list:
                _logger.info(f"LLM timing wrapper: FallbackAdapter with {len(inner_list)} providers - TTFT tracking enabled (fixed CM protocol)")
                for idx, inner_llm in enumerate(inner_list):
                    # Avoid infinite recursion: only wrap if not already wrapped
                    if 'LLMTimingWrapper' not in str(type(inner_llm)):
                        _lbl = "primary/0-of-%d" % len(inner_list) if idx == 0 else "fallback/%d-of-%d" % (idx, len(inner_list))
                        # 12:28 attribution fix: the builder stamps every LLM
                        # instance with ITS OWN _prov_meta (agent_builder
                        # _pm_attach). Passing the chain HEAD's provider_info to
                        # every inner wrapper is what labelled OpenAI fallback
                        # usage as provider=groq model=qwen3.8 — cached tokens
                        # included, and priced it at the wrong model's rates.
                        _info_i = getattr(inner_llm, "_prov_meta", None) or provider_info
                        inner_list[idx] = _create_llm_timing_wrapper(inner_llm, timing_dict, _info_i, inst_label=_lbl)
                return llm_instance
    except Exception as e:
        _logger.debug(f"Could not wrap FallbackAdapter inner LLMs: {e}")

    original_chat = getattr(llm_instance, 'chat', None)
    if not original_chat:
        return llm_instance

    class _ProbeStreamPassThrough:
        """livekit FallbackAdapter recovery probes: pass chunks through and
        record only the health outcome. No shared-timing writes at all — no
        finally-block state mutation (a bare `return` in a generator's finally
        would SWALLOW the probe's exception and falsely mark a rate-limited
        instance healthy — so the isolation lives in this separate class, not
        in a guard inside TimingStreamWrapper). No generation semantics, no
        all_requests entry, no customer billing."""

        def __init__(self, inner_stream, timing, prov_info, inst, req_start=None):
            self._inner_stream = inner_stream
            self._timing = timing
            self._prov_info = prov_info
            self._inst = inst
            self._req_start = req_start or _time.time()

        def __getattr__(self, name):
            return getattr(self._inner_stream, name)

        async def __aiter__(self):
            try:
                async for _pch in self._inner_stream:
                    yield _pch
                _logger.info("🧪 [LLM_RECOVERY_PROBE] provider=%s model=%s instance=%s result=healthy in %dms — instance stays in rotation; probe usage NOT billed to the call (infra cost, provider-side latency win only)", self._prov_info.get('provider', ''), self._prov_info.get('model_id', ''), self._inst, int((_time.time() - self._req_start) * 1000))
            except Exception as _pex:
                _is429, _lim, _used, _req, _ra = _rate_limit_fields(_pex)
                self._timing["probe_failures"] = int(self._timing.get("probe_failures", 0)) + 1
                if _is429:
                    _logger.warning("🚦 [RATE_LIMIT] provider=%s model=%s limit=%s used=%s requested=%s retry_after_ms=%s instance=%s generation=n/a probe=yes — background health check rate-limited; instance stays unavailable, the configured fallback keeps serving (no auto-retry on this model for turn traffic)", self._prov_info.get('provider', ''), self._prov_info.get('model_id', ''), _lim, _used, _req, _ra, self._inst)
                else:
                    _logger.info("🧪 [LLM_RECOVERY_PROBE] provider=%s model=%s instance=%s result=unhealthy (%s) — instance stays out of rotation until the next real request's all-failed pass", self._prov_info.get('provider', ''), self._prov_info.get('model_id', ''), self._inst, type(_pex).__name__)
                raise

    class TimingStreamWrapper:
        """Wraps LLMStream to measure first_token TTFT and generation_complete."""
        def __init__(self, inner_stream, timing, prov_info, req_start, gen=None, seq=None, probe=False, inst="single/1"):
            self._inner_stream = inner_stream
            self._timing = timing
            self._prov_info = prov_info
            self._req_start = req_start
            self._gen = gen
            # 12:28 ownership: every stream carries the FULL identity of the
            # request that produced it — turn generation, monotonic request
            # sequence (which request currently owns shared timing state), the
            # provider instance label and the probe flag. Usage, billing and
            # cache state are read/written through THESE, never through
            # whoever-last-wrote shared keys.
            self._seq = seq
            self._probe = probe
            self._inst = inst
            self._rid = "n/a"
            self._stale_logged = False
            self._rejected_429 = False
            self._counted = False
            self._first_token = True
            self._input_tokens = 0
            self._output_tokens = 0
            self._cached_tokens = 0
            # True iff the provider actually returned a usage object on this
            # stream. Task 5 (2026-09-24): failed/invalidated requests have
            # input=0 because NO usage came back — they must never be
            # counted as cache misses; cache_status becomes an explicit
            # "unknown" verdict driven by this flag.
            self._usage_seen = False
            # Task 7 (2026-09-24): the FIRST decoded chunk is the critical
            # path to TTS. First-token log LINES are queued here and emitted
            # when the NEXT chunk arrives (long after the pipeline received
            # chunk #1) or in finally — timing dict writes stay immediate so
            # everything downstream (authoritative TTFT, COST, GENERATION
            # COMPLETE) sees real values and real ordering.
            self._pending_first_logs: list = []

        def __getattr__(self, name):
            return getattr(self._inner_stream, name)

        async def __aiter__(self):
            # (recovery probes use _ProbeStreamPassThrough — they never reach
            # this class, so nothing below can be mutated by a background
            # health check.)
            def _flush_first_logs():
                if self._pending_first_logs:
                    for _lvl, _msg in self._pending_first_logs:
                        (_logger.warning if _lvl else _logger.info)(_msg)
                    self._pending_first_logs.clear()

            try:
                async for chunk in self._inner_stream:
                    _flush_first_logs()
                    now = _time.time()
                    if self._first_token:
                        self._first_token = False
                        # Two independent staleness reasons, one gate:
                        #  gen mismatch  → a barge-in/new turn invalidated this
                        #                  generation (unchanged semantics);
                        #  seq mismatch  → this attempt was SUPERSEDED within
                        #                  its turn by the fallback switch (the
                        #                  newer request owns shared state now).
                        # A stream that owns neither may still finish cleanly
                        # for its own billing record, but it never mutates the
                        # live turn's timing.
                        _stale_gen = self._gen is not None and int(self._timing.get("gen", 0)) != self._gen
                        _stale_seq = self._seq is not None and int(self._timing.get("active_req_seq", 0)) != self._seq
                        if _stale_gen or _stale_seq:
                            # This stream no longer owns the live turn:
                            #  _stale_gen → barge-in / new turn invalidated it
                            #               (library still drains/cancels);
                            #  _stale_seq → the FallbackAdapter replaced this
                            #               attempt within the SAME turn.
                            # Either way it must NOT write this turn's timing
                            # or fire TTFT logs that would look like the NEW
                            # owner. Its own per-stream accounting below still
                            # completes honestly (a torn-down 429'd request
                            # ends 0/0, success=False — never billed).
                            self._stale_logged = True
                            if _stale_gen:
                                _logger.info("🗑️ [STALE_GENERATION_DROPPED] callback_generation=%d current_generation=%s — late tokens from an invalidated turn are discarded", self._gen, self._timing.get("gen"))
                            else:
                                _logger.info("🗑️ [STALE_GENERATION_DROPPED] reason=superseded_by_next_attempt instance=%s seq=%s active_seq=%s generation=%s — this request yielded the turn to the fallback/next attempt; its own billing record stays valid", self._inst, self._seq, self._timing.get("active_req_seq"), self._gen)
                        else:
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
                    yield chunk
            except Exception as e:
                # FIX: Log actual exception for 0/0 failures to diagnose root cause
                # Previous 0/0 failures (Request 1 and 5) had no error logged, making root cause invisible
                # FIX: Avoid synchronous traceback.format_exc() on event loop
                # (it triggers linecache -> tokenize.open() -> 176ms block at
                # tokenize.py:447). Offload to thread so agent loop stays free.
                try:
                    _tb_full = await asyncio.to_thread(traceback.format_exc)
                except Exception:
                    _tb_full = f"{type(e).__name__}: {e}"
                _logger.error(f"❌ LLM STREAM EXCEPTION provider={self._prov_info.get('provider','')} model={self._prov_info.get('model_id','')} Error={e} Type={type(e).__name__} input={self._input_tokens} output={self._output_tokens} Traceback={_tb_full[:1000]}")
                _is429, _lim, _used, _req, _ra = _rate_limit_fields(e)
                if _is429:
                    # A 429 that surfaced mid-iteration (after any chunk) still
                    # means the turn was REJECTED by the provider: pin success
                    # False for this stream regardless of partial evidence.
                    self._rejected_429 = True
                    # The 429 itself: provider-reported numbers only. The
                    # adapter now switches to the configured fallback — we do
                    # NOT retry this model for the turn (spec), and this failed
                    # attempt is excluded from successful usage below (zero
                    # chunks → not successful regardless of shared flags).
                    self._timing["rate_limit_events"] = int(self._timing.get("rate_limit_events", 0)) + 1
                    _logger.warning("🚦 [RATE_LIMIT] provider=%s model=%s limit=%s used=%s requested=%s retry_after_ms=%s instance=%s generation=%s rid=%s — request rejected BEFORE any token; excluded from billing; handing over to configured fallback (no retry on this model this turn)", self._prov_info.get('provider',''), self._prov_info.get('model_id',''), _lim, _used, _req, _ra, self._inst, self._gen, self._rid)
                raise
            finally:
                _flush_first_logs()
                try:
                    if getattr(self, "_counted", False):
                        self._timing["inflight_llm"] = max(0, int(self._timing.get("inflight_llm", 1)) - 1)
                        self._counted = False
                except Exception:
                    pass
                gen_complete = _time.time()
                gen_time = (gen_complete - self._req_start) * 1000
                # OWNERSHIP GATE (Task 1): only the request that still owns
                # this turn's shared state — the current turn generation AND
                # the latest sequence — may mutate it. A primary that the
                # FallbackAdapter already replaced (newer active_req_seq) can
                # no longer flip llm_active False or overwrite
                # generation_complete/TTS-facing timing underneath the live
                # fallback stream. Its OWN record below stays complete.
                _own_state = (
                    (self._gen is None or int(self._timing.get("gen", 0)) == self._gen)
                    and (self._seq is None or int(self._timing.get("active_req_seq", 0)) == self._seq)
                )
                if _own_state:
                    self._timing["generation_complete"] = gen_complete
                    self._timing["llm_complete"] = gen_complete
                    self._timing["generation_time_ms"] = gen_time
                    self._timing["input_tokens"] = self._input_tokens
                    self._timing["output_tokens"] = self._output_tokens
                    self._timing["cached_input_tokens"] = self._cached_tokens
                # llm_active DERIVES from the inflight gauge now: on a switch
                # the dying stream must not deactivate while the replacement
                # request is still counted inflight (and vice versa).
                try:
                    self._timing["llm_active"] = int(self._timing.get("inflight_llm", 0)) > 0
                except Exception:
                    self._timing["llm_active"] = False
                prov = self._prov_info.get('provider', '') or self._timing.get('llm_provider', 'unknown')
                model = self._prov_info.get('model_id', '') or self._timing.get('llm_model', 'unknown')
                # FIX: Separate deterministic closing (intentional 0/0) from genuine empty LLM turns
                # Do not report intentional closing request as LLM failure
                is_closing = self._timing.get("is_closing", False)
                is_deterministic_closing = is_closing and self._input_tokens == 0 and self._output_tokens == 0
                # 12:28 fix: success is judged on THIS stream's evidence only.
                # The old shared 'assistant_output_received' flag made a 429'd
                # attempt that yielded ZERO chunks count as SUCCESS whenever a
                # sibling stream (the fallback answering the same turn) had
                # output — rejected requests then polluted
                # successful_requests/last_* state. Per-stream: output tokens
                # reported, or at least one chunk actually streamed through
                # THIS wrapper.
                is_success = (self._output_tokens > 0 or not self._first_token) and not is_deterministic_closing and not self._rejected_429
                # cached-token normalization (Task 4): a capability=none path
                # gets ZERO cached for billing/cost — reported numbers stay in
                # the telemetry but can never mint a discount that provider
                # does not offer for this model. capability is read for THIS
                # request's own provider/model pair (attribution-correct).
                _cached_cost = int(self._cached_tokens or 0)
                try:
                    from app.llm_catalog import get_prompt_cache_capability as _gcc_own
                    _cap_own = _gcc_own(str(prov), str(model))
                    if _cached_cost > 0 and not _cap_own.get("supported"):
                        _logger.warning(
                            "⚠️ [CACHE_OWNERSHIP_MISMATCH] provider=%s model=%s capability=none reported_cached_tokens=%d request_id=%s generation=%s instance=%s — this exact provider/model exposes no prompt cache, so these tokens CANNOT belong to this request. They are excluded from its cost and the aggregated cached total. Usual source (pre-12:28 builds): the fallback instance was labelled with the chain head's provider_info — check [USAGE_OWNERSHIP] lines around request_id=%s for the OpenAI pair.",
                            prov, model, _cached_cost, self._rid, self._gen, self._inst, self._rid,
                        )
                        _cached_cost = 0
                except Exception:
                    _cap_own = None
                if is_success and _own_state:
                    # Preserve last successful turn metrics for final billing
                    try:
                        self._timing["last_ttft"] = self._timing.get("ttft_ms", 0)
                        self._timing["last_gen_time"] = gen_time
                        self._timing["last_input"] = self._input_tokens
                        self._timing["last_output"] = self._output_tokens
                        self._timing["last_cached"] = self._cached_tokens
                    except Exception:
                        pass
                
                # FIX: Aggregated billing using actual successful provider usage
                # Ensure aggregated fields exist
                if "aggregated_input" not in self._timing:
                    self._timing["aggregated_input"] = 0
                    self._timing["aggregated_output"] = 0
                    self._timing["aggregated_cached"] = 0
                    self._timing["successful_requests"] = 0
                    self._timing["failed_requests"] = 0
                    self._timing["all_requests"] = []
                
                request_record = {
                    "input": self._input_tokens,
                    "cached": self._cached_tokens,
                    "cached_for_cost": _cached_cost,
                    "output": self._output_tokens,
                    "success": is_success,
                    "ttft": self._timing.get("ttft_ms", 0),
                    "gen_time": gen_time,
                    "provider": prov,
                    "model": model,
                    "is_closing": is_deterministic_closing,
                    # ownership stamps (Task 1): which request, which instance,
                    # which turn generation, which sequence — a record can only
                    # ever describe the call that produced it.
                    "rid": self._rid,
                    "gen": self._gen,
                    "seq": self._seq,
                    "instance": self._inst,
                }
                self._timing["all_requests"].append(request_record)
                
                if is_success:
                    self._timing["aggregated_input"] += self._input_tokens
                    self._timing["aggregated_output"] += self._output_tokens
                    self._timing["aggregated_cached"] += _cached_cost
                    self._timing["successful_requests"] += 1
                    _logger.info(f"💰 AGGREGATED BILLING +{self._input_tokens}in +{self._output_tokens}out total {self._timing['aggregated_input']}in {self._timing['aggregated_output']}out across {self._timing['successful_requests']} successful, {self._timing['failed_requests']} failed")
                elif is_deterministic_closing:
                    _logger.info(f"👋 Deterministic closing 0/0 not counted as failure (is_closing={is_closing}) - excluded from billing, successful={self._timing.get('successful_requests',0)} failed={self._timing.get('failed_requests',0)}")
                else:
                    self._timing["failed_requests"] += 1
                    _logger.info(f"⚠️ LLM request failed/invalidated: input={self._input_tokens} output={self._output_tokens} success={is_success} closing={is_deterministic_closing} (excluded from aggregated, failed {self._timing['failed_requests']})")
                    _bi_recent = (_time.time() - float(self._timing.get("last_bargein_ts", 0.0))) < 1.0
                    _logger.info("🔇 [LLM_CANCELLED] reason=%s generation=%s — superseded request never billed; the new completed turn owns the one live request", "user_barge_in" if _bi_recent else "user_continued", self._timing.get("gen", 0))
                    # 03:07 K-exam fix: killed BEFORE any token = the caller was
                    # still speaking (VAD split mid-utterance); the question
                    # that was cut off must stay mergeable with its
                    # continuation. Tagged with this request's generation so the
                    # builder only adopts it while that generation is still
                    # current (a late teardown can never contaminate two turns
                    # later). Barge-in DURING an answer is excluded:
                    # first_token is nonzero once any output was streamed.
                    if not self._timing.get("first_token", 0):
                        try:
                            _uxt = str(self._timing.get("req_user_text") or "").strip()
                            if _uxt:
                                self._timing["overwritten_turn"] = {
                                    "text": _uxt, "ts": _time.time(),
                                    "gen": int(self._timing.get("gen", 0) or 0),
                                }
                        except Exception:
                            pass
                
                _logger.info(f"LLM GENERATION COMPLETE provider={prov} model={model} generation_time={gen_time:.0f}ms input={self._input_tokens} cached={self._cached_tokens} output={self._output_tokens} success={is_success} active={bool(self._timing.get('llm_active'))} is_closing={is_deterministic_closing}")
                # Task 1 proof line — ONE per completed usage result, printed
                # by the stream that OWNED the usage object (never by a shared
                # accumulator): which request produced these tokens, from what
                # usage source, and whether they enter billing.
                _logger.info(
                    "\U0001f50e [USAGE_OWNERSHIP] generation=%s request_id=%s provider=%s model=%s instance=%s seq=%s input=%d cached=%d cached_for_cost=%d output=%d usage_source=%s billing=%s owns_shared_state=%s",
                    self._gen, self._rid, prov, model, self._inst, self._seq,
                    self._input_tokens, self._cached_tokens, _cached_cost, self._output_tokens,
                    "own_stream_usage_object" if self._usage_seen else "no_usage_returned_by_provider",
                    "counted" if is_success else "excluded",
                    "yes" if _own_state else "no_superseded",
                )
                try:
                    from app.llm_catalog import get_llm_model, calculate_llm_cost, get_prompt_cache_capability
                    model_meta = get_llm_model(prov, model) if prov and model else None
                    if model_meta:
                        costs = calculate_llm_cost(model_meta, self._input_tokens, _cached_cost, self._output_tokens)
                        total_cost = costs['total_llm_cost']
                        # Calculate total aggregated cost
                        total_agg_cost = 0.0
                        try:
                            # Sum cost of all successful requests — each entry
                            # priced at ITS OWN provider/model (per-instance
                            # _prov_meta), cached discount only up to what that
                            # pair's capability supports (cached_for_cost).
                            for req in self._timing.get("all_requests", []):
                                if req.get("success"):
                                    m = get_llm_model(req.get("provider",""), req.get("model",""))
                                    if m:
                                        c = calculate_llm_cost(m, req["input"], req.get("cached_for_cost", req["cached"]), req["output"])
                                        total_agg_cost += c['total_llm_cost']
                        except Exception:
                            total_agg_cost = total_cost
                        _logger.info(f"LLM COST [LLM_RESPONSE_COMPLETED] provider={prov} model={model} input={self._input_tokens} cached={self._cached_tokens} output={self._output_tokens} input_cost=${costs['input_cost']:.6f} output_cost=${costs['output_cost']:.6f} total=${total_cost:.6f} TTFT={self._timing.get('ttft_ms',0):.0f}ms gen_time={gen_time:.0f}ms success={is_success} aggregated_successful={self._timing.get('successful_requests',0)} total_agg_cost=${total_agg_cost:.6f} is_closing={is_deterministic_closing}")
                        _logger.info(f"📊 BILLING SUMMARY successful={self._timing.get('successful_requests',0)} failed={self._timing.get('failed_requests',0)} total_input={self._timing.get('aggregated_input',0)} total_cached={self._timing.get('aggregated_cached',0)} total_output={self._timing.get('aggregated_output',0)} total_cost=${total_agg_cost:.6f}")
                        # Task 1 (2026-09-24): explicit cache status per
                        # request, derived ONLY from provider usage. hit is
                        # claimed when cached_input_tokens>0 — mere presence
                        # of the key is never claimed; non-OpenAI paths say
                        # unsupported instead of pretending.
                        try:
                            _cached_now = int(self._cached_tokens or 0)
                            _uk = bool(getattr(self, "_usage_seen", False))
                            # Task 2 (11:41 log): four honest states driven by
                            # get_prompt_cache_capability(provider, model) — NOT
                            # by a "provider == openai" guess. capability=none
                            # (e.g. groq qwen3.8: no cached-token usage exists)
                            # reports unsupported and never a "miss"; a
                            # cache-capable request whose usage never arrived
                            # is unknown, never a miss (02:31-call lesson);
                            # hit/miss are claimed ONLY from real provider
                            # usage counts.
                            try:
                                _cap = get_prompt_cache_capability(str(prov), str(model))
                            except Exception:
                                _cap = {"supported": "openai" in str(prov).lower(),
                                        "mode": "native_explicit" if "openai" in str(prov).lower() else "none",
                                        "configuration": None}
                            _cap_mode = _cap.get("mode", "none")
                            _cap_cfg = _cap.get("configuration") or {}
                            if not _cap.get("supported"):
                                _ck_key, _ck_status = "n/a", "unsupported (capability=none for this exact provider/model — nothing invented, nothing to hit or miss)"
                                _cap_lbl = "none"
                            else:
                                _cap_lbl = _cap_mode
                                _ck_key = _cap_cfg.get("prompt_cache_key") or "n/a (automatic — no client field)"
                                if not _uk:
                                    _ck_status = "unknown/error (no usage returned by provider — request failed or was invalidated; NOT counted as miss)"
                                    self._timing["cache_unknown"] = self._timing.get("cache_unknown", 0) + 1
                                elif _cached_now > 0:
                                    _ck_status = "hit"
                                    self._timing["cache_hits"] = self._timing.get("cache_hits", 0) + 1
                                else:
                                    _ck_status = "miss"
                                    self._timing["cache_misses"] = self._timing.get("cache_misses", 0) + 1
                            _uk_s = "yes" if _uk else "NO"
                            _logger.info(f"🗄️ [CACHE] provider={prov} model={model} capability={_cap_lbl} mode={_cap_mode} cache_key={_ck_key} usage_returned={_uk_s} cached_input_tokens={_cached_now} cache_status={_ck_status} stable_head_hash={self._timing.get('head_sha','?')} stable_head_tokens_est={self._timing.get('head_est_tokens','?')} stable_head_chars={self._timing.get('head_chars_log','?')} head_same_as_previous={self._timing.get('head_stable_prev','?')} (status only reflects provider usage; hash is content-free)")
                        except Exception:
                            pass
                except Exception as e:
                    _logger.debug(f"Could not calculate LLM cost: {e}")

    class TimingChatCM:
        """Async context manager that wraps inner LLM chat CM and returns TimingStreamWrapper."""
        def __init__(self, inner_cm_or_coro, timing, prov_info, req_start, gen=None, seq=None, probe=False, inst="single/1", counted=False):
            self._inner_orig = inner_cm_or_coro
            self._timing = timing
            self._prov_info = prov_info
            self._req_start = req_start
            self._gen = gen
            self._seq = seq
            self._probe = probe
            self._inst = inst
            self._counted = counted
            self._inner_cm = None
            self._inner_stream = None

        async def __aenter__(self):
            # Resolve inner if it's a coroutine (some LLM impls have async chat)
            inner = self._inner_orig
            try:
                if _asyncio.iscoroutine(inner):
                    inner = await inner
                self._inner_cm = inner
                # Enter inner CM
                if hasattr(inner, '__aenter__'):
                    stream = await inner.__aenter__()
                else:
                    stream = inner
            except BaseException as e:
                if self._probe:
                    # failed health check: outcome counter + rate-limit line
                    # only; no shared turn state, no billing record.
                    self._timing["probe_failures"] = int(self._timing.get("probe_failures", 0)) + 1
                    _ok429, _l4, _u4, _r4, _ra4 = _rate_limit_fields(e)
                    if _ok429:
                        _logger.warning("🚦 [RATE_LIMIT] provider=%s model=%s limit=%s used=%s requested=%s retry_after_ms=%s instance=%s generation=n/a probe=yes — background health check rate-limited at connect; instance stays unavailable, fallback keeps serving", self._prov_info.get('provider',''), self._prov_info.get('model_id',''), _l4, _u4, _r4, _ra4, self._inst)
                    raise
                # P6 root-cause hardening: a request that dies BEFORE streaming
                # (provider/client raised, e.g. the observed
                # "APIStatusError.__init__() missing 2 required positional
                # arguments" crash) used to leave llm_active=True forever —
                # TimingStreamWrapper's finally never ran. The stale flag
                # suppressed empty-turn diagnostics (state held "thinking") and
                # made wedges invisible. Clear per-request state, log loudly,
                # re-raise unchanged so LiveKit's own error path proceeds.
                # 12:28: this path used to bypass ALL accounting (no inflight
                # release, no failed record, failed_requests stayed 0 even for
                # a 429 rejected at connect). Fixed: release what chat()
                # counted, record the attempt as a genuine failure (never
                # successful, never billed), and surface the rate limit.
                _fail_now = _time.time()
                try:
                    if self._counted:
                        self._timing["inflight_llm"] = max(0, int(self._timing.get("inflight_llm", 1)) - 1)
                        self._counted = False
                except Exception:
                    pass
                self._timing["llm_active"] = int(self._timing.get("inflight_llm", 0)) > 0
                self._timing["generation_complete"] = _fail_now
                self._timing["llm_complete"] = _fail_now
                _ok429, _l4, _u4, _r4, _ra4 = _rate_limit_fields(e)
                if _ok429:
                    self._timing["rate_limit_events"] = int(self._timing.get("rate_limit_events", 0)) + 1
                    _logger.warning("🚦 [RATE_LIMIT] provider=%s model=%s limit=%s used=%s requested=%s retry_after_ms=%s instance=%s generation=%s — rejected BEFORE any token at connect; excluded from billing; configured fallback takes over (no retry on this model this turn)", self._prov_info.get('provider',''), self._prov_info.get('model_id',''), _l4, _u4, _r4, _ra4, self._inst, self._gen)
                try:
                    _own = (self._gen is None or int(self._timing.get("gen", 0)) == self._gen) and (self._seq is None or int(self._timing.get("active_req_seq", 0)) == self._seq)
                    if _own:
                        self._timing["failed_requests"] = int(self._timing.get("failed_requests", 0)) + 1
                    self._timing.setdefault("all_requests", []).append({
                        "input": 0, "cached": 0, "cached_for_cost": 0, "output": 0,
                        "success": False, "ttft": 0.0,
                        "gen_time": (_fail_now - self._req_start) * 1000,
                        "provider": self._prov_info.get('provider', ''), "model": self._prov_info.get('model_id', ''),
                        "is_closing": False, "rid": "n/a", "gen": self._gen, "seq": self._seq,
                        "instance": self._inst, "failed_before_stream": True,
                    })
                except Exception:
                    pass
                _logger.error(
                    "❌ LLM REQUEST FAILED BEFORE STREAM [LLM_RESPONSE_COMPLETED] "
                    f"provider={self._prov_info.get('provider','')} model={self._prov_info.get('model_id','')} "
                    f"error={type(e).__name__}: {e} — recorded failed (not billed), turn not dropped"
                )
                _logger.info(
                    "\U0001f50e [USAGE_OWNERSHIP] generation=%s request_id=%s provider=%s model=%s instance=%s seq=%s input=0 cached=0 cached_for_cost=0 output=0 usage_source=no_usage_returned_by_provider billing=excluded owns_shared_state=%s",
                    self._gen, "n/a", self._prov_info.get('provider',''), self._prov_info.get('model_id',''), self._inst, self._seq,
                    "yes" if ((self._gen is None or int(self._timing.get("gen", 0)) == self._gen) and (self._seq is None or int(self._timing.get("active_req_seq", 0)) == self._seq)) else "no_superseded",
                )
                raise
            self._inner_stream = stream
            if self._probe:
                return _ProbeStreamPassThrough(stream, self._timing, self._prov_info, self._inst, self._req_start)
            _sw = TimingStreamWrapper(stream, self._timing, self._prov_info, self._req_start, self._gen, seq=self._seq, inst=self._inst)
            _sw._counted = self._counted  # ownership of the inflight gauge moves to the stream
            self._counted = False
            return _sw

        async def __aexit__(self, exc_type, exc, tb):
            try:
                if self._inner_cm and hasattr(self._inner_cm, '__aexit__'):
                    return await self._inner_cm.__aexit__(exc_type, exc, tb)
            except Exception as e:
                _logger.debug(f"Error in inner CM __aexit__: {e}")
            return False

    class LLMTimingWrapper:
        def __init__(self, inner, timing, prov_info):
            self._inner = inner
            self._timing = timing
            self._prov_info = prov_info or {}
            try:
                self._model = getattr(inner, '_model', None) or getattr(inner, 'model', None) or prov_info.get('model_id', '') if prov_info else ''
                self._label = getattr(inner, '_label', None) or getattr(inner, 'label', None)
            except Exception:
                self._model = prov_info.get('model_id', '') if prov_info else ''
                self._label = None

        def __getattr__(self, name):
            # Delegate everything except chat
            if name == 'chat':
                return self.chat
            return getattr(self._inner, name)

        def chat(self, *args, **kwargs):
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
                    _mf = getattr(_cc, "messages", None)
                    # livekit-agents 1.8.2: ChatContext.messages is a METHOD
                    # (returns list[ChatMessage]) — the previous direct getattr
                    # produced a bound method, list() raised TypeError, and the
                    # whole block died in a debug-level except: every production
                    # request logged stable_head_chars=?/head_sha=?/inflight 0.
                    _msgs = list(_mf() if callable(_mf) else (_mf or []))
                    def _mtext(m):
                        c = getattr(m, "content", "")
                        if isinstance(c, str):
                            return c
                        if isinstance(c, list):
                            return " ".join(str(getattr(p, "text", p)) for p in c)
                        return str(c or "")
                    _head: list = []
                    _hist_chars = 0
                    _hist_msgs = 0
                    _rag_chars = 0
                    _user_last_chars = 0
                    _user_last_text = ""
                    _dyn_before_head = 0
                    _seen_user = False
                    _user_last_is_final = False
                    _first_sys = None
                    for _i, _m in enumerate(_msgs):
                        _r = getattr(_m, "role", "") or ""
                        _t = _mtext(_m)
                        _mid = getattr(_m, "id", "") or ""
                        # Cache fix: ONLY the behavioral instructions (id=lk.agent_task.instructions)
                        # are the stable cacheable prefix. All other system messages (prior_memory,
                        # lead_data, RAG) are dynamic and must be counted as dynamic, not stable,
                        # even if they appear before first user in older contexts. This makes the
                        # logged stable_head reflect the TRUE provider-bound cacheable prefix.
                        _is_stable = (_mid == "lk.agent_task.instructions") or (_r == "system" and _first_sys is None and not _seen_user and "[RAG]" not in _t[:80] and "Prior conversation" not in _t[:80] and "contact list" not in _t[:80].lower())
                        # For first_sys detection, only stable instructions count as head start
                        if _r == "system" and _first_sys is None and _is_stable:
                            _first_sys = _i
                        if _r == "system" and _is_stable and not _seen_user:
                            _head.append(_t)
                        elif _r == "system":
                            _rag_chars += len(_t)
                        else:
                            _seen_user = True
                            if _r == "user":
                                # last USER message wherever it sits — the TEXT
                                # feeds the continuation-merge. 11:41 fix: the
                                # CHAR COUNT no longer requires the message to be
                                # final (the old positional gate is what made
                                # final_user=0c ambiguous between "question
                                # missing" and "question present but not last").
                                # Position is reported separately as question_is_last.
                                _user_last_text = _t
                                _user_last_chars = len(_t)
                                _user_last_is_final = _i == len(_msgs) - 1
                            else:
                                _hist_chars += len(_t)
                                _hist_msgs += 1
                    _tools = kwargs.get("tools")
                    if _tools is None and len(args) > 1:
                        _tools = args[1]
                    _tools = _tools or []
                    _dyn_before_head = int(_first_sys or 0)
                    # 03:07 K-exam fix: remember this request's question so the
                    # builder can merge it into the caller's immediate
                    # continuation if the request is superseded pre-output.
                    self._timing["req_user_text"] = _user_last_text[:600]
                    _token_estimate_start_ns = _time.perf_counter_ns()
                    _tools_chars = sum(len(str(getattr(_t0, "name", _t0))) + len(str(getattr(_t0, "parameters", ""))) for _t0 in _tools)
                    _head_chars = sum(len(_h) for _h in _head)
                    _sha = _hl.sha256(("\x1f".join(_head) + "#tools=" + repr(_tools_chars)).encode("utf-8", "ignore")).hexdigest()[:12]
                    _prev_sha = self._timing.get("head_sha") or ""
                    _stable = "yes" if (not _prev_sha or _prev_sha == _sha) else "NO"
                    self._timing["head_sha"] = _sha
                    self._timing["head_sha_prev"] = _prev_sha
                    self._timing["head_stable_prev"] = _stable
                    self._timing["head_chars_log"] = _head_chars
                    _head_est_t = int(_head_chars / 4.0)
                    self._timing["head_est_tokens"] = _head_est_t
                    _total_chars = _head_chars + _hist_chars + _rag_chars + _user_last_chars
                    _dyn_rag_est_t = int(_rag_chars / 4.0)
                    _total_est_t = int(_total_chars / 4.0)
                    _token_estimate_ns = _time.perf_counter_ns() - _token_estimate_start_ns
                    _logger.info(
                        "\U0001f9ee [PROMPT] chars=%d est_total_tokens=%d tokens: stable_prompt=%d dynamic_rag=%d total_input_est=%d | sections: stable_head=%dc(~%dt) same_as_previous_turn=%s dynamic_prefix_before_stable_head=%d | history=%dc/%dmsg | rag_inject=%dc | final_user=%dc question_is_last=%s | tools_meta=%dc | head_sha=%s",
                        _total_chars, _total_est_t, _head_est_t, _dyn_rag_est_t, _total_est_t, _head_chars, _head_est_t, _stable, _dyn_before_head, _hist_chars, _hist_msgs, _rag_chars, _user_last_chars, "yes" if _user_last_is_final else "NO", _tools_chars, _sha,
                    )
                    # 11:41 log Task 1: PROVE the request shape instead of
                    # inferring it. The [PROMPT] section line cannot distinguish
                    # "question present but not last" from "question missing"
                    # without this; the preview shows the real last message, the
                    # counts show how many user messages arrived, and ack_mode /
                    # incomplete_turn echo the governor flags on the SHARED turn
                    # dict (a deterministic-ack turn never reaches chat(), so
                    # ack_mode=yes here would mean a stale flag hijacked a real
                    # request — the one failure mode the pop-on-entry guards are
                    # supposed to make impossible). 60-char previews only: no
                    # full customer content, no secrets.
                    _last_m = _msgs[-1] if _msgs else None
                    _dbg_prov = self._prov_info.get("provider", "") or self._timing.get("llm_provider", "") or "unknown"
                    _dbg_model = self._prov_info.get("model_id", "") or getattr(self._inner, "model", "unknown") or "unknown"
                    _cache_metadata_start_ns = _time.perf_counter_ns()
                    try:
                        from app.llm_catalog import get_prompt_cache_capability as _gcc_dbg
                        _dbg_cap = _gcc_dbg(str(_dbg_prov), str(_dbg_model)).get("mode", "?")
                    except Exception:
                        _dbg_cap = "?"
                    _cache_metadata_ns = _time.perf_counter_ns() - _cache_metadata_start_ns
                    _logger.info(
                        "\U0001f52c [LLM_INPUT_DEBUG] generation=%s provider=%s model=%s capability=%s messages_count=%d last_message_role=%s last_message_preview='%s' current_user_turn='%s' user_messages=%d question_is_last=%s rag_present=%s rag_chars=%d ack_mode=%s incomplete_turn=%s",
                        _gen, _dbg_prov, _dbg_model, _dbg_cap, len(_msgs),
                        str(getattr(_last_m, "role", "?") or "?") if _last_m is not None else "?",
                        (_mtext(_last_m)[:60].replace("\n", " ") if _last_m is not None else ""),
                        _user_last_text[:60].replace("\n", " "),
                        sum(1 for _m2 in _msgs if getattr(_m2, "role", "") == "user"),
                        "yes" if _user_last_is_final else "NO",
                        "yes" if _rag_chars else "no", _rag_chars,
                        "yes" if self._timing.get("ack_reply") else "no",
                        "yes" if self._timing.get("gov_turn_state") == "suppress" else "no",
                    )
                    # --- Provider-bound fingerprint for cache diagnosis (safe, no PII) ---
                    # Latency fix: avoid duplicate ChatContext -> provider format
                    # serialization on the event loop (to_provider_format does a
                    # full copy/transform of ~10k chars). Use the already-parsed
                    # _msgs list directly — same data, zero extra serialization.
                    # No cache logic changed, only diagnostic path.
                    _fingerprint_start_ns = _time.perf_counter_ns()
                    try:
                        _prov_msgs = _msgs  # use existing parsed messages, not to_provider_format
                        _prov_role_seq = "?"
                        _prov_len_seq = "?"
                        _prov_first_hash = "?"
                        _prov_prefix_hash = "?"
                        _prov_prefix_same = "?"
                        if _prov_msgs:
                            _prov_role_seq = ",".join([str(getattr(m, "role", "?")) for m in _prov_msgs])
                            _prov_len_seq = ",".join([str(len(_mtext(m))) for m in _prov_msgs])
                            _first_c = _mtext(_prov_msgs[0]) if _prov_msgs else ""
                            _prov_first_hash = _hl.sha256(_first_c.encode("utf-8", "ignore")).hexdigest()[:12] if _first_c else "?"
                            _pref_c = "".join([_mtext(m) for m in _prov_msgs[:2]])
                            _prov_prefix_hash = _hl.sha256(_pref_c.encode("utf-8", "ignore")).hexdigest()[:12] if _pref_c else "?"
                            _prev_pref = self._timing.get("prov_prefix_hash", "")
                            _prov_prefix_same = "yes" if (not _prev_pref or _prev_pref == _prov_prefix_hash) else "NO"
                            self._timing["prov_prefix_hash"] = _prov_prefix_hash
                            self._timing["prov_prefix_hash_prev"] = _prev_pref
                        _pck = getattr(getattr(self._inner, "_opts", None), "prompt_cache_key", None) or getattr(self._inner, "prompt_cache_key", None) or "?"
                        # Never log full content, only hashes/lengths/roles
                        # Cache diagnostics: show stable_head size to prove >1024 eligibility
                        _stable_chars_log = self._timing.get("head_chars_log", "?")
                        _stable_tokens_log = self._timing.get("head_est_tokens", "?")
                        _logger.info(
                            "\U0001f50d [PROVIDER_BOUND] provider=%s model=%s prompt_cache_key=%s prov_messages=%d role_seq=%s len_seq=%s first_hash=%s prefix_hash=%s prefix_same_as_previous=%s app_head_sha=%s app_head_same=%s stable_head_chars=%s stable_head_tokens_est=%s",
                            _dbg_prov, _dbg_model, _pck, len(_prov_msgs), _prov_role_seq, _prov_len_seq, _prov_first_hash, _prov_prefix_hash, _prov_prefix_same, _sha, _stable, _stable_chars_log, _stable_tokens_log,
                        )
                    except Exception as _pb_e:
                        _logger.debug(f"[PROVIDER_BOUND] fingerprint failed: {_pb_e!r}")
                    finally:
                        _fingerprint_ns = _time.perf_counter_ns() - _fingerprint_start_ns
                    # inflight gauge for spike forensics (Task 5)
                    self._timing["inflight_llm"] = int(self._timing.get("inflight_llm", 0)) + 1
                    # Per-request ownership (12:28): this used to be the shared
                    # "_inflight_counted" flag — with two overlapping streams
                    # (fallback switch / barge-in) whichever finished first
                    # consumed the flag and the OTHER skipped its own decrement,
                    # pinning llm_active=True. The counter is owned by THIS
                    # request now and travels on the CM/stream objects.
                    _req_inflight = True
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

    _w = LLMTimingWrapper(llm_instance, timing_dict, provider_info)
    try:
        _w._inst_label = inst_label or "single/1"
    except Exception:
        pass
    return _w
