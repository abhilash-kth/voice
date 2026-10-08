"""Stream-error reporting (rate-limit diagnostics) and finalization metrics
for the LLM timing stream wrapper. Extracted 1:1 from `w_llm_timing.py`.
"""
from __future__ import annotations

import asyncio
import logging
import time as _time
import traceback

_logger = logging.getLogger("voice-agent-saas-worker")


async def report_stream_error(self, e):
    from .llm_chat_cm import _rate_limit_fields  # lazy: breaks import cycle llm_chat_cm -> llm_stream_wrapper -> llm_stream_error
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


def finalize_stream_metrics(self, _flush_first_logs):
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
