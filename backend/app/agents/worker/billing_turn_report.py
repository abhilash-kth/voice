from __future__ import annotations

import logging
logger = logging.getLogger("voice-agent-saas-worker")


# cross-module imports (auto-generated)
from .dep_imports import BILLING_INTERNAL_TOKEN, aiohttp
from .runtime_env import BILLING_BACKEND_URL

def _billing_report(costs, usage, duration, turn_timing_ref=None) -> str:
    # FIX: Use aggregated authoritative values for all billing displays, not word-count estimates
    # Authoritative is 69,461 input / 572 output, not 139in/361out from usage word count
    # Make every billing display use same aggregated authoritative values
    try:
        if turn_timing_ref:
            display_input = turn_timing_ref.get("aggregated_input", usage['llm_input_tokens'])
            display_output = turn_timing_ref.get("aggregated_output", usage['llm_output_tokens'])
            successful = turn_timing_ref.get("successful_requests", 0)
            failed = turn_timing_ref.get("failed_requests", 0)
        else:
            # Fallback to usage if no turn_timing_ref, but try to get authoritative from usage if it has been updated
            display_input = usage.get('llm_input_tokens_authoritative', usage['llm_input_tokens'])
            display_output = usage.get('llm_output_tokens_authoritative', usage['llm_output_tokens'])
            successful = usage.get('successful_requests', 0)
            failed = usage.get('failed_requests', 0)
    except Exception:
        display_input = usage['llm_input_tokens']
        display_output = usage['llm_output_tokens']
        successful = 0
        failed = 0
    
    return (
        "\n" + "=" * 64 + "\n"
        f"📊 BILLING  duration={duration}s ({costs['duration_mins']} min)\n"
        f"👂 STT {round(usage['user_speech_seconds'],1)}s -> ₹{costs['stt_cost_inr']}\n"
        f"🧠 LLM {display_input}in/{display_output}out (authoritative aggregated {successful} successful, {failed} failed) -> ₹{costs['llm_cost_inr']}\n"
        f"🗣️ TTS {usage['tts_chars']} chars -> ₹{costs['tts_cost_inr']}\n"
        f"🖥️ Server -> ₹{costs['server_cost_inr']}\n"
        f"💸 YOUR COST ₹{costs['total_cost_inr']} (₹{costs['your_cost_per_min']}/min)\n"
        f"💳 CUSTOMER BILL ₹{costs['client_price_inr']} (₹{costs['client_bill_per_min']}/min)\n"
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


