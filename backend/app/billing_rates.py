"""Customer-price composition (split from billing.py; ≤300-line rule).

Per-minute rate card — the customer pays, per call:

  ₹/min = Σ customer_price_per_min of the call's selected models
          (Super-Admin per-model prices on the Models page):
            • assistant mode    → LLM + STT + TTS
            • announcement mode → TTS + telephony (fixed script: LLM/STT
              never run; announcements are phone blasts so the telephony
              leg is part of the price — + server below)
        + server_cost_per_min (platform infra component, also admin-set)
  floored at the per-mode minimum (assistant_min / announcement_min ₹/min),
  then per-call at max(infra_cost × (1+margin), min_client_price) so a call
  can NEVER bill below cost.

Concurrency is NOT billed per minute here: extra concurrent lines are a
monthly subscription item (services/subscription_service.py), as is the
telephony rent and the per-agent-count platform fee.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from .config import SERVER_COST_PER_MIN, PROFIT_MARGIN_PERCENT, MIN_CLIENT_PRICE


# ---------------------------------------------------------------------------
# Snapshot-backed constants (DB wins, env/code are fallbacks)
# ---------------------------------------------------------------------------
def billing_consts() -> Dict[str, Any]:
    """All BillingConfig numbers with DB snapshot precedence + .env fallback.

    Sync-only (the pipeline's hot path never touches the DB); the snapshot is
    refreshed on every admin mutation.
    """
    out: Dict[str, Any] = {
        "server_cost_per_min": SERVER_COST_PER_MIN,
        "min_client_price": MIN_CLIENT_PRICE,
        "profit_margin_percent": PROFIT_MARGIN_PERCENT,
        "assistant_min_per_min": MIN_CLIENT_PRICE,
        "announcement_min_per_min": MIN_CLIENT_PRICE,
        "concurrency_line_price_per_month": 0.0,
        "telephony_rent_per_month": 0.0,
    }
    try:
        from .services import config_store

        b = config_store.get_billing()
        for k in out:
            if b.get(k) is not None:
                out[k] = float(b[k])
    except Exception:
        pass
    return out


# ---------------------------------------------------------------------------
# The call's selected models' rate card (₹/min)
# ---------------------------------------------------------------------------
def _snapshot_model_price(kind: str, key: str, model_id: str = "") -> float:
    """Super-Admin rate card: a model's customer_price_per_min from the DB
    snapshot (0 when unset / snapshot unavailable). key = catalogId for
    stt/tts, providerSlug+model_id for llm."""
    try:
        from .services.config_core import get_snapshot

        for m in (get_snapshot().models.get(kind) or []):
            if kind == "llm":
                if m.get("providerSlug") == key and (m.get("modelId") or "") == (model_id or ""):
                    return float(m.get("customerPricePerMin") or 0)
            elif (m.get("catalogId") or "") == key:
                return float(m.get("customerPricePerMin") or 0)
    except Exception:
        pass
    return 0.0


def selected_models_rate_per_min(*, llm_provider: str = "", llm_model_id: str = "",
                                 stt_id: str = "", tts_id: str = "",
                                 telephony_id: str = "",
                                 agent_mode: str = "assistant") -> float:
    """Rate card total (₹/min) for the call's selected models.

    Mode decides which legs are chargeable:
      • assistant    → LLM + STT + TTS (+ server, added by the caller)
      • announcement → TTS + telephony (announcements always go out over the
        phone network, so the selected telephony model's ₹/min is part of the
        announcement price; LLM/STT legs never run, so they are never priced)
    A browser call has no telephony model selected → telephony_id is empty →
    no telephony leg is priced (rate falls to TTS + server only).
    """
    total = 0.0
    if agent_mode == "announcement":
        if telephony_id:
            total += _snapshot_model_price("telephony", telephony_id)
    else:
        if llm_provider:
            total += _snapshot_model_price("llm", llm_provider, llm_model_id)
        if stt_id:
            total += _snapshot_model_price("stt", stt_id)
    if tts_id:
        total += _snapshot_model_price("tts", tts_id)
    return round(total, 4)


def customer_price(*, total_cost_inr: float, duration_mins: float,
                   agent_mode: str = "assistant", models_rate_per_min: float = 0.0,
                   consts: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Compose the final customer price for one call. Returns the price plus a
    transparent breakdown (each component visible in the usage/cost record)."""
    c = consts or billing_consts()
    models_rate = float(models_rate_per_min or 0.0)
    server_per_min = float(c["server_cost_per_min"])
    rate_card = models_rate + server_per_min
    mode_min = (c["announcement_min_per_min"] if (agent_mode or "assistant") == "announcement"
                else c["assistant_min_per_min"])
    applied_rate = max(rate_card, float(mode_min))
    price = applied_rate * duration_mins
    # Never-loss floor: customer pays at least infra cost × (1+margin), and at
    # least the configured absolute minimum per call.
    floor_price = max(total_cost_inr * (1.0 + (c["profit_margin_percent"] / 100.0)),
                      c["min_client_price"])
    floor_applied = price < floor_price
    if floor_applied:
        price = floor_price
    return {
        "client_price_inr": round(price, 2),
        "models_rate_per_min": round(models_rate, 4),
        "server_per_min": round(server_per_min, 4),
        "rate_card_per_min": round(rate_card, 4),
        "mode_min_per_min": round(float(mode_min), 4),
        "applied_rate_per_min": round(applied_rate, 4),
        "floor_applied": bool(floor_applied),
    }
