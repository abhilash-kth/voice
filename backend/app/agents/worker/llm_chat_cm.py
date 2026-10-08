"""Probe-helper predicates + probe/chat-context-manager wrappers for the
LLM timing instrumentation. Extracted verbatim from `llm_timing_factory.py`
(<=300-line rule).
"""
from __future__ import annotations

import asyncio as _asyncio
import logging
import time as _time

_logger = logging.getLogger("voice-agent-saas-worker")

from .llm_stream_wrapper import TimingStreamWrapper


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
    import re as _re_own
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
