"""TimingStreamWrapper: TTFT / usage / chargefinalisation instrumentation
around a single LLM stream. Extracted 1:1 from `w_llm_timing.py`.
"""
from __future__ import annotations

import logging
import time as _time

from .llm_stream_events import record_first_token_events, extract_chunk_usage
from .llm_stream_error import report_stream_error, finalize_stream_metrics

_logger = logging.getLogger("voice-agent-saas-worker")


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
                        record_first_token_events(self, now)
                extract_chunk_usage(self, chunk)
                yield chunk
        except Exception as e:
            await report_stream_error(self, e)
            raise
        finally:
            finalize_stream_metrics(self, _flush_first_logs)
