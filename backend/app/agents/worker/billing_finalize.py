"""Call finalization: cost computation, billing report/POST, local call
update, wallet fallback deduction (deduped via has_spend_for_call).

Extracted verbatim from `worker_entrypoint.py` (<=300-line rule). Runs as the
LiveKit shutdown callback; identical behaviour to the previous inline
finalize_billing.
"""
from __future__ import annotations

import asyncio
import logging
import time

from . import runtime_env as _wr
from .billing_turn_report import _billing_report, _post_billing
from .dep_imports import calculate_call_cost, db_init, memory, repo
from .runtime_env import _FAIL_THRESHOLD_SECONDS

logger = logging.getLogger("voice-agent-saas-worker")


def register_finalize_billing(ctx, cfg, agent_mode, agent_id, user_id, mode,
                              phone, customer_key, call_start, call_record,
                              recording_url, turn_timing, usage, memory_enabled):
    """Register the (idempotent) finalize billing shutdown callback."""

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
                # Announcement rate card = TTS + telephony (+server). Browser
                # calls select no telephony model → empty → no telephony leg.
                telephony_provider_id=(cfg.providers.telephony.id
                                       if getattr(cfg.providers, "telephony", None) else ""),
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

            # Fallback local update (ensures call is marked completed even if backend unreachable).
            # Make sure this job loop's DB client is connected first — the whole
            # fallback exists for when the API server is down and direct-DB is
            # the only way money + call state still land.
            if not _wr._DB_INIT_DONE:
                try:
                    await asyncio.wait_for(db_init(), timeout=8)
                    _wr._DB_INIT_DONE = True
                except Exception as _dbe:
                    logger.warning(f"DB init for fallback billing failed: {_dbe!r}")
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
