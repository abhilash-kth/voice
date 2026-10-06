"""Customer-price composition (split from billing.py; ≤300-line rule).

Industry model — a transparent rate card with a never-loss floor:

  Customer ₹/min = (per-mode flat rate, else Σ customer_price_per_min of the
                    call's selected LLM+STT+TTS models — the Super Admin's
                    rate card on the Models page)
                   + concurrency surcharge (agent's Max-concurrent tier)
                   + miscellaneous fee
  Final price    = max(rate_card × minutes, infra_cost × (1+margin),
                       min_client_price)   ← gross margin can never go
                       negative and the floor always applies.

All knobs are Super-Admin-controlled via BillingConfig (0/[] = off → legacy).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .config import SERVER_COST_PER_MIN, PROFIT_MARGIN_PERCENT, MIN_CLIENT_PRICE


def billing_consts() -> Dict[str, Any]:
    """All BillingConfig numbers with DB snapshot precedence + .env fallback.

    Sync-only (the pipeline's hot path never touches the DB); the snapshot is
    refreshed on every admin mutation.
    """
    out: Dict[str, Any] = {
        "server_cost_per_min": SERVER_COST_PER_MIN,
        "min_client_price": MIN_CLIENT_PRICE,
        "profit_margin_percent": PROFIT_MARGIN_PERCENT,
        "announcement_price_per_min": 0.0,
        "assistant_price_per_min": 0.0,
        "misc_fee_per_min": 0.0,
        "concurrency_addons": [],
    }
    try:
        from .services import config_store

        b = config_store.get_billing()
        for k in ("server_cost_per_min", "min_client_price", "profit_margin_percent",
                  "announcement_price_per_min", "assistant_price_per_min", "misc_fee_per_min"):
            if b.get(k) is not None:
                out[k] = float(b[k])
        tiers = b.get("concurrency_addons")
        if isinstance(tiers, list):
            out["concurrency_addons"] = tiers
    except Exception:
        pass
    return out


def concurrency_addon_for(tiers: List[Dict[str, Any]], max_concurrency: int) -> float:
    """₹/min surcharge for an agent whose Max-concurrent is `max_concurrency`.

    Tiers are ascending by `up_to`; the first tier with up_to >= value applies.
    A value above every tier uses the LAST tier (by design — never free).
    """
    try:
        mc = max(int(max_concurrency), 1)
    except (TypeError, ValueError):
        mc = 1
    best = None
    for t in sorted((t for t in tiers or [] if isinstance(t, dict)),
                    key=lambda t: t.get("up_to", 0)):
        best = t
        if mc <= int(t.get("up_to", 0) or 0):
            return float(t.get("addon_per_min", 0) or 0)
    return float(best.get("addon_per_min", 0) or 0) if best else 0.0


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
                                 stt_id: str = "", tts_id: str = "") -> float:
    """Rate card total (₹/min) for the call's selected LLM+STT+TTS models."""
    total = 0.0
    if llm_provider:
        total += _snapshot_model_price("llm", llm_provider, llm_model_id)
    if stt_id:
        total += _snapshot_model_price("stt", stt_id)
    if tts_id:
        total += _snapshot_model_price("tts", tts_id)
    return round(total, 4)


def customer_price(*, total_cost_inr: float, duration_mins: float,
                   agent_mode: str = "assistant", max_concurrency: int = 1,
                   models_rate_per_min: float = 0.0,
                   consts: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Compose the final customer price for one call. Returns the price plus a
    transparent breakdown (each layer visible in the usage/cost record)."""
    c = consts or billing_consts()
    flat = (c["announcement_price_per_min"] if (agent_mode or "assistant") == "announcement"
            else c["assistant_price_per_min"])
    applied_flat = flat if flat and flat > 0 else 0.0
    rate_card = (applied_flat if applied_flat else float(models_rate_per_min or 0.0))
    addon_per_min = concurrency_addon_for(c["concurrency_addons"], max_concurrency)
    misc_per_min = float(c["misc_fee_per_min"])
    rate_card += addon_per_min + misc_per_min
    price = rate_card * duration_mins
    # Never-loss floor: customer pays at least infra cost × (1+margin), and at
    # least the configured minimum per call.
    floor_price = max(total_cost_inr * (1.0 + (c["profit_margin_percent"] / 100.0)),
                      c["min_client_price"])
    floor_applied = price < floor_price
    if floor_applied:
        price = floor_price
    return {
        "client_price_inr": round(price, 2),
        "rate_card_per_min": round(rate_card, 4),
        "models_rate_per_min": round(float(models_rate_per_min or 0.0), 4),
        "applied_flat_rate_per_min": round(applied_flat, 4),
        "concurrency_addon_per_min": round(addon_per_min, 4),
        "misc_fee_per_min": round(misc_per_min, 4),
        "addon_fees_inr": round((addon_per_min + misc_per_min) * duration_mins, 4),
        "floor_applied": bool(floor_applied),
    }
