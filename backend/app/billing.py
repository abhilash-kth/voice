"""
Cost / billing engine.

Computes, per component, the provider cost (what you pay) vs. the customer
price (what they're billed) using the selected provider's unit pricing + the
agent's chosen client rate. This mirrors and generalises the calculator found
in the original customer_support agent.
"""
from __future__ import annotations

from typing import Any

from . import catalog
from .config import SERVER_COST_PER_MIN, PROFIT_MARGIN_PERCENT, MIN_CLIENT_PRICE


def _get_cost(kind: str, provider_id: str) -> dict[str, Any]:
    prov = catalog.get_provider(kind, provider_id) or {}
    return prov.get("cost", {})


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
) -> dict[str, Any]:
    """Returns a full breakdown dict of costs, prices and profit."""
    duration_mins = max(duration_seconds / 60.0, 0.01)
    stt_mins = max(stt_seconds / 60.0, 0.0)

    llm_cost = _get_cost("llm", llm_provider_id)
    stt_cost = _get_cost("stt", stt_provider_id)
    tts_cost = _get_cost("tts", tts_provider_id)

    stt_cost_inr = stt_mins * stt_cost.get("per_min", 0.22)
    llm_cost_inr = (
        (llm_input_tokens / 1000.0) * llm_cost.get("per_1k_in", 0.03)
        + (llm_output_tokens / 1000.0) * llm_cost.get("per_1k_out", 0.06)
    )
    tts_cost_inr = (tts_chars / 1000.0) * tts_cost.get("per_1k_chars", 1.33)
    server_cost_inr = duration_mins * SERVER_COST_PER_MIN

    total_cost_inr = stt_cost_inr + llm_cost_inr + tts_cost_inr + server_cost_inr

    # The customer is charged the ACTUAL provider cost plus a platform margin
    # (set in `.env` via PROFIT_MARGIN_PERCENT). The client only ever sees the
    # resulting total and per-minute cost — they never enter a price.
    margin = 1.0 + (PROFIT_MARGIN_PERCENT / 100.0)
    client_price_inr = max(total_cost_inr * margin, MIN_CLIENT_PRICE)
    profit_inr = client_price_inr - total_cost_inr

    return {
        "stt_cost_inr": round(stt_cost_inr, 4),
        "llm_cost_inr": round(llm_cost_inr, 4),
        "tts_cost_inr": round(tts_cost_inr, 4),
        "server_cost_inr": round(server_cost_inr, 4),
        "total_cost_inr": round(total_cost_inr, 2),
        # Effective per-minute customer price = total / duration.
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
    }


def estimate_unit_tokens(text: str) -> int:
    """Approx token count for billing when the runtime tokeniser isn't available."""
    if not text:
        return 0
    return max(1, int(len(text) / 4))
