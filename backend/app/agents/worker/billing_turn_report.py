from __future__ import annotations

import logging
logger = logging.getLogger("voice-agent-saas-worker")


# cross-module imports (auto-generated)
from .dep_imports import BILLING_INTERNAL_TOKEN, aiohttp
from .runtime_env import BILLING_BACKEND_URL


def _display_tokens(usage, turn_timing_ref):
    """Aggregated authoritative token counts (fall back to usage estimates)."""
    try:
        if turn_timing_ref:
            return (turn_timing_ref.get("aggregated_input", usage["llm_input_tokens"]),
                    turn_timing_ref.get("aggregated_output", usage["llm_output_tokens"]),
                    turn_timing_ref.get("successful_requests", 0),
                    turn_timing_ref.get("failed_requests", 0))
        return (usage.get("llm_input_tokens_authoritative", usage["llm_input_tokens"]),
                usage.get("llm_output_tokens_authoritative", usage["llm_output_tokens"]),
                usage.get("successful_requests", 0),
                usage.get("failed_requests", 0))
    except Exception:
        return usage["llm_input_tokens"], usage["llm_output_tokens"], 0, 0


def _billing_report(costs, usage, duration, turn_timing_ref=None) -> str:
    """The end-of-call BILLING block. Every number shown is exactly what the
    Super Admin configured: the rate card composition (per-model ₹/min set on
    the Models page + server ₹/min), the per-mode minimum rate, the never-loss
    floor, and the per-mode minimum billed duration.

    Chargeable legs are mode-aware:
      • assistant    → STT + LLM + TTS + Telephony + Server
      • announcement → TTS + Telephony + Server  (fixed script: no STT/LLM)
    """
    mode = costs.get("agent_mode") or "assistant"
    is_announce = mode == "announcement"
    # Infra cost legs (provider-side spend, actual usage)
    tele_id = costs.get("telephony_provider_id") or ""
    tele_label = tele_id if tele_id and tele_id != "browser" else "none (browser)"
    legs = []
    if not is_announce:
        d_in, d_out, ok, failed = _display_tokens(usage, turn_timing_ref)
        legs.append(f"👂 STT       {round(usage['user_speech_seconds'], 1)}s -> ₹{costs['stt_cost_inr']}")
        legs.append(f"🧠 LLM       {d_in}in/{d_out}out ({ok} ok, {failed} failed) -> ₹{costs['llm_cost_inr']}")
    legs.append(f"🗣️ TTS       {usage['tts_chars']} chars -> ₹{costs['tts_cost_inr']}")
    legs.append(f"📞 Telephony {tele_label} -> ₹{costs.get('telephony_cost_inr', 0)}")
    legs.append(f"🖥️ Server    -> ₹{costs['server_cost_inr']}")

    # Customer rate composition — exactly the super-admin-set numbers.
    margin = costs.get("profit_margin_percent", 0)
    min_call = costs.get("min_client_price", 0)
    floor_val = max(costs["total_cost_inr"] * (1 + margin / 100.0), float(min_call or 0))
    floor_txt = (f"APPLIED ✅ (price raised to ₹{round(floor_val, 2)})"
                 if costs.get("floor_applied") else "not needed")

    # Minimum billed duration (enterprise): customer pays at least min seconds.
    billed_s = costs.get("billed_seconds", duration)
    if costs.get("min_bill_applied"):
        dur_head = f"duration={duration}s actual / {billed_s}s billed"
        bill_note = (f" — {billed_s}s billed (Super-Admin min {costs.get('min_bill_seconds', 0)}s; "
                     f"actual {duration}s)")
    else:
        dur_head = f"duration={duration}s ({costs['duration_mins']} min)"
        bill_note = ""

    return (
        "\n" + "=" * 64 + "\n"
        f"📊 BILLING  mode={mode} {dur_head}\n"
        + "\n".join(legs) + "\n"
        f"💸 YOUR COST ₹{costs['total_cost_inr']} (₹{costs['your_cost_per_min']}/min)\n"
        f"🏷️ RATE CARD models ₹{costs.get('models_rate_per_min', 0)}/min"
        f" + server ₹{costs.get('server_per_min', 0)}/min"
        f" = ₹{costs.get('rate_card_per_min', 0)}/min"
        f" | {mode}-min ₹{costs.get('mode_min_per_min', 0)}/min"
        f" → applied ₹{costs.get('applied_rate_per_min', 0)}/min\n"
        f"🧱 FLOOR max(cost×(1+{margin}%), ₹{min_call}/call) = ₹{round(floor_val, 2)} → {floor_txt}\n"
        f"💳 CUSTOMER BILL ₹{costs['client_price_inr']}"
        f" = ₹{costs.get('applied_rate_per_min', costs.get('client_bill_per_min', 0))}/min"
        f" × {costs.get('billed_mins', costs['duration_mins'])} min{bill_note}\n"
        f"🤑 PROFIT ₹{costs['your_profit_inr']} [{'PROFIT ✅' if costs['is_profit'] else 'LOSS ⚠️'}]\n"
        + "=" * 64
    )


async def _post_billing(call_id, user_id, agent_id, mode, phone, duration, costs, usage,
                       recording_url, status="completed", turn_timing_ref=None) -> bool:
    # FIX: Use authoritative aggregated billing values, not undefined llm_input variable
    # Authoritative is from turn_timing_ref aggregated_input/output or usage authoritative
    try:
        if turn_timing_ref:
            auth_input = turn_timing_ref.get("aggregated_input", usage.get("llm_input_tokens", 0))
            auth_output = turn_timing_ref.get("aggregated_output", usage.get("llm_output_tokens", 0))
            auth_cached = turn_timing_ref.get("aggregated_cached", 0)
            successful = turn_timing_ref.get("successful_requests", 0)
            failed = turn_timing_ref.get("failed_requests", 0)
        else:
            auth_input = usage.get("llm_input_tokens_authoritative", usage.get("llm_input_tokens", 0))
            auth_output = usage.get("llm_output_tokens_authoritative", usage.get("llm_output_tokens", 0))
            auth_cached = usage.get("llm_cached_input_tokens", 0)
            successful = usage.get("successful_requests", 0)
            failed = usage.get("failed_requests", 0)
    except Exception:
        auth_input = usage.get("llm_input_tokens", 0)
        auth_output = usage.get("llm_output_tokens", 0)
        auth_cached = 0
        successful = 0
        failed = 0
    headers = {"Content-Type": "application/json"}
    if BILLING_INTERNAL_TOKEN:
        headers["X-Internal-Token"] = BILLING_INTERNAL_TOKEN
    payload = {
        "callId": call_id,
        "userId": user_id,
        "agentId": agent_id,
        "mode": mode,
        "phone": phone,
        "duration": duration,
        "costs": costs,
        "usage": {
            "sttSeconds": round(usage["user_speech_seconds"], 1),
            "ttsChars": usage["tts_chars"],
            "llmInputTokens": auth_input,
            "llmOutputTokens": auth_output,
            "llmInputTokensAuthoritative": auth_input,
            "llmOutputTokensAuthoritative": auth_output,
            "llmCachedTokens": auth_cached,
            "successfulRequests": successful,
            "failedRequests": failed,
            "totalInputTokens": auth_input,
            "totalCachedTokens": auth_cached,
            "totalOutputTokens": auth_output,
            "totalLlmCost": costs.get("total_cost", 0) if isinstance(costs, dict) else 0,
        },
        "recordingUrl": recording_url,
        "status": status,
        "transcripts": usage["transcripts"][-30:],
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{BILLING_BACKEND_URL}/api/billing/log",
                                    json=payload, headers=headers, timeout=8) as resp:
                body = await resp.text()
                logger.info(f"✅ Billing posted HTTP {resp.status} for call {call_id} — billed ₹{costs['client_price_inr']} — backend will deduct wallet")
                if resp.status >= 400:
                    logger.warning(f"⚠️ Billing POST returned {resp.status}: {body[:500]}")
                    return False
                return True
    except Exception as e:
        logger.warning(f"⚠️ Billing POST failed for call {call_id} to {BILLING_BACKEND_URL}: {e!r} — will fallback to direct DB deduct", exc_info=True)
        return False
