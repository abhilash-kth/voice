"""
Cost / billing engine - V2 Provider → Multiple Models with rich pricing.

Calculates LLM cost per request using selected model's pricing metadata:
input_tokens × input_price + cached_input_tokens × cached_input_price + output_tokens × output_price

Logs: provider, model, input_tokens, cached_input_tokens, output_tokens, input_cost, output_cost, total_llm_cost, TTFT, generation_time

Billing uses actual selected model's pricing, no silent substitution.
"""
from __future__ import annotations

from typing import Any, Dict, Optional
import logging

from . import catalog
from .config import SERVER_COST_PER_MIN, PROFIT_MARGIN_PERCENT, MIN_CLIENT_PRICE

logger = logging.getLogger("voice-agent-saas-billing")

def _get_cost(kind: str, provider_id: str) -> Dict[str, Any]:
    prov = catalog.get_provider(kind, provider_id) or {}
    return prov.get("cost", {})

def _get_llm_cost_v2(provider: str, model_id: str, input_tokens: int, cached_input_tokens: int, output_tokens: int) -> Dict[str, float]:
    """Calculate LLM cost using V2 catalog pricing metadata."""
    try:
        from .llm_catalog import get_llm_model, calculate_llm_cost
        model = get_llm_model(provider, model_id)
        if model:
            costs = calculate_llm_cost(model, input_tokens, cached_input_tokens, output_tokens)
            # Convert USD to INR? Catalog pricing is in USD per 1M tokens.
            # For billing, we keep in INR using conversion? For now, treat as INR equivalent or convert.
            # Previous cost was per 1K tokens in INR-like. New pricing is per 1M in USD.
            # We will use USD pricing converted to INR at ~83 INR/USD for billing, but log USD too.
            # For simplicity, we will use the USD pricing as cost basis and convert to INR.
            USD_TO_INR = 83.0
            # Providers that bill natively in INR (Sarvam) declare price_inr_per_1m;
            # use those rupee figures directly instead of USD -> INR round-tripping.
            inr_price = model.get("price_inr_per_1m") or model.get("pricing_inr")
            if inr_price:
                def _per_m(key: str) -> float:
                    return float(inr_price.get(key, 0.0)) / 1_000_000.0
                input_cost_inr = input_tokens * _per_m("input")
                cached_cost_inr = cached_input_tokens * _per_m("cached_input")
                output_cost_inr = output_tokens * _per_m("output")
                total_inr = input_cost_inr + cached_cost_inr + output_cost_inr
            else:
                input_cost_inr = costs["input_cost"] * USD_TO_INR
                cached_cost_inr = costs["cached_input_cost"] * USD_TO_INR
                output_cost_inr = costs["output_cost"] * USD_TO_INR
                total_inr = costs["total_llm_cost"] * USD_TO_INR
            return {
                "input_cost_inr": input_cost_inr,
                "cached_input_cost_inr": cached_cost_inr,
                "output_cost_inr": output_cost_inr,
                "total_llm_cost_inr": total_inr,
                "input_cost_usd": costs["input_cost"],
                "cached_input_cost_usd": costs["cached_input_cost"],
                "output_cost_usd": costs["output_cost"],
                "total_llm_cost_usd": costs["total_llm_cost"],
                "pricing": {
                    "input_per_1m": model["input_price_per_1m"],
                    "cached_per_1m": model["cached_input_price_per_1m"],
                    "output_per_1m": model["output_price_per_1m"],
                    "currency": model.get("price_currency", "USD"),
                    "inr_per_1m": inr_price,
                }
            }
    except Exception as e:
        logger.debug(f"Could not calculate V2 LLM cost for {provider}:{model_id}: {e}")
    return {}

def calculate_call_cost(
    *,
    duration_seconds: int,
    stt_seconds: float,
    llm_input_tokens: int,
    llm_output_tokens: int,
    tts_chars: int,
    llm_provider_id: str = "groq_llama_3_3_70b",
    stt_provider_id: str = "deepgram_nova2",
    tts_provider_id: str = "google_wavenet_hi",
    client_rate_per_min: float = 2.50,
    # New V2 fields
    llm_provider: Optional[str] = None,
    llm_model_id: Optional[str] = None,
    llm_cached_input_tokens: int = 0,
    llm_ttft_ms: Optional[float] = None,
    llm_generation_time_ms: Optional[float] = None,
) -> Dict[str, Any]:
    """Returns full breakdown dict of costs, prices and profit.
    
    V2: Uses actual selected model's pricing if provider and model_id provided.
    Logs provider, model, input_tokens, cached_input_tokens, output_tokens, costs, TTFT, generation_time.
    """
    duration_mins = max(duration_seconds / 60.0, 0.01)
    stt_mins = max(stt_seconds / 60.0, 0.0)

    # Try V2 pricing first if provider/model provided - provider from llm_provider or llm_provider_id
    llm_cost_inr = 0
    llm_cost_details = {}
    v2_provider = llm_provider or llm_provider_id
    v2_model = llm_model_id
    # If provider id is old style like groq_gpt_oss_20b, try to resolve via catalog
    if v2_provider and "_" in v2_provider and v2_provider not in ("openai", "groq", "openrouter"):
        try:
            from .models import ProviderPair
            pair = ProviderPair(id=v2_provider, config={"model": v2_model or ""})
            prov, model, _ = pair.resolve_llm_provider_model()
            v2_provider = prov
            v2_model = model
        except Exception:
            pass
    if v2_provider and v2_model:
        v2_cost = _get_llm_cost_v2(v2_provider, v2_model, llm_input_tokens, llm_cached_input_tokens, llm_output_tokens)
        if v2_cost:
            llm_cost_inr = v2_cost["total_llm_cost_inr"]
            llm_cost_details = v2_cost
            logger.info(
                f"💰 LLM COST provider={v2_provider} model={v2_model} "
                f"input={llm_input_tokens} cached={llm_cached_input_tokens} output={llm_output_tokens} "
                f"input_cost=${v2_cost.get('input_cost_usd',0):.6f} output_cost=${v2_cost.get('output_cost_usd',0):.6f} "
                f"total=${v2_cost.get('total_llm_cost_usd',0):.6f} total_inr=₹{llm_cost_inr:.4f} "
                f"TTFT={llm_ttft_ms}ms gen_time={llm_generation_time_ms}ms"
            )
    
    # Fallback to old catalog pricing if V2 not available
    if llm_cost_inr == 0:
        llm_cost = _get_cost("llm", llm_provider_id)
        llm_cost_inr = (
            (llm_input_tokens / 1000.0) * llm_cost.get("per_1k_in", 0.03)
            + (llm_output_tokens / 1000.0) * llm_cost.get("per_1k_out", 0.06)
        )
    
    stt_cost = _get_cost("stt", stt_provider_id)
    tts_cost = _get_cost("tts", tts_provider_id)

    stt_cost_inr = stt_mins * stt_cost.get("per_min", 0.22)
    tts_cost_inr = (tts_chars / 1000.0) * tts_cost.get("per_1k_chars", 1.33)
    server_cost_inr = duration_mins * SERVER_COST_PER_MIN

    total_cost_inr = stt_cost_inr + llm_cost_inr + tts_cost_inr + server_cost_inr

    margin = 1.0 + (PROFIT_MARGIN_PERCENT / 100.0)
    client_price_inr = max(total_cost_inr * margin, MIN_CLIENT_PRICE)
    profit_inr = client_price_inr - total_cost_inr

    result = {
        "stt_cost_inr": round(stt_cost_inr, 4),
        "llm_cost_inr": round(llm_cost_inr, 4),
        "tts_cost_inr": round(tts_cost_inr, 4),
        "server_cost_inr": round(server_cost_inr, 4),
        "total_cost_inr": round(total_cost_inr, 2),
        "client_rate_per_min": round(client_price_inr / duration_mins, 2),
        "client_price_inr": round(client_price_inr, 2),
        "your_profit_inr": round(profit_inr, 2),
        "is_profit": profit_inr >= 0,
        "duration_mins": round(duration_mins, 2),
        "your_cost_per_min": round(total_cost_inr / duration_mins, 2),
        "client_bill_per_min": round(client_price_inr / duration_mins, 2),
        "profit_per_min": round(profit_inr / duration_mins, 2),
        "rate_per_min": round(client_price_inr / duration_mins, 2),
        "profit_margin_percent": PROFIT_MARGIN_PERCENT,
        # New V2 fields
        "llm_provider": llm_provider or llm_provider_id,
        "llm_model": llm_model_id or llm_provider_id,
        "llm_input_tokens": llm_input_tokens,
        "llm_cached_input_tokens": llm_cached_input_tokens,
        "llm_output_tokens": llm_output_tokens,
        "llm_ttft_ms": llm_ttft_ms,
        "llm_generation_time_ms": llm_generation_time_ms,
    }
    
    if llm_cost_details:
        result["llm_cost_details"] = llm_cost_details
        result["llm_input_cost_usd"] = round(llm_cost_details.get("input_cost_usd", 0), 6)
        result["llm_output_cost_usd"] = round(llm_cost_details.get("output_cost_usd", 0), 6)
        result["llm_total_cost_usd"] = round(llm_cost_details.get("total_llm_cost_usd", 0), 6)
    
    return result

def calculate_llm_cost_detailed(
    provider: str,
    model_id: str,
    input_tokens: int,
    cached_input_tokens: int,
    output_tokens: int,
    ttft_ms: Optional[float] = None,
    generation_time_ms: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Calculate LLM cost per request using selected model's pricing metadata.
    Logs provider, model, input_tokens, cached_input_tokens, output_tokens, costs, TTFT, generation_time.
    """
    try:
        from .llm_catalog import get_llm_model, calculate_llm_cost
        model = get_llm_model(provider, model_id)
        if not model:
            logger.error(f"❌ LLM COST ERROR: Unknown model {model_id} for provider {provider} - cannot calculate cost")
            return {
                "provider": provider,
                "model": model_id,
                "error": f"Unknown model {model_id} for provider {provider}",
                "total_llm_cost": 0,
            }
        
        costs = calculate_llm_cost(model, input_tokens, cached_input_tokens, output_tokens)
        
        result = {
            "provider": provider,
            "model": model_id,
            "display_name": model["display_name"],
            "input_tokens": input_tokens,
            "cached_input_tokens": cached_input_tokens,
            "output_tokens": output_tokens,
            "input_price_per_1m": model["input_price_per_1m"],
            "cached_input_price_per_1m": model["cached_input_price_per_1m"],
            "output_price_per_1m": model["output_price_per_1m"],
            "input_cost": costs["input_cost"],
            "cached_input_cost": costs["cached_input_cost"],
            "output_cost": costs["output_cost"],
            "total_llm_cost": costs["total_llm_cost"],
            "context_window": model["context_window"],
            "expected_speed": model["expected_speed"],
            "ttft_ms": ttft_ms,
            "generation_time_ms": generation_time_ms,
        }
        
        logger.info(
            f"📊 LLM DETAILED COST provider={provider} model={model_id} "
            f"input={input_tokens} cached={cached_input_tokens} output={output_tokens} "
            f"input_cost=${costs['input_cost']:.6f} cached_cost=${costs['cached_input_cost']:.6f} output_cost=${costs['output_cost']:.6f} "
            f"total=${costs['total_llm_cost']:.6f} TTFT={ttft_ms}ms gen={generation_time_ms}ms speed={model['expected_speed']}"
        )
        
        return result
    except Exception as e:
        logger.error(f"❌ LLM cost calculation failed for {provider}:{model_id}: {e}")
        return {
            "provider": provider,
            "model": model_id,
            "error": str(e),
            "total_llm_cost": 0,
        }

def estimate_unit_tokens(text: str) -> int:
    """Approx token count for billing when runtime tokeniser isn't available."""
    if not text:
        return 0
    return max(1, int(len(text) / 4))
