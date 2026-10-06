"""Customer-price composition (split from billing.py; ≤300-line rule).

Layers, all Super-Admin-controlled via BillingConfig (0/[] = off → legacy):
  1. Base   — announcement/assistant flat ₹/min when set, else infra cost × margin.
  2. Addon  — concurrency surcharge for the agent's Max-concurrent tier, ₹/min.
  3. Misc   — flat miscellaneous fee, ₹/min, on top of every billed call.
Final price is floored at min_client_price as before.
"""
from __future__ import annotations

from typing import Any, Dict, List

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


def customer_price(*, total_cost_inr: float, duration_mins: float,
                   agent_mode: str = "assistant", max_concurrency: int = 1,
                   consts: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Compose the final customer price for one call. Returns the price plus a
    transparent breakdown (each layer visible in the usage/cost record)."""
    c = consts or billing_consts()
    flat = (c["announcement_price_per_min"] if (agent_mode or "assistant") == "announcement"
            else c["assistant_price_per_min"])
    if flat and flat > 0:
        base = flat * duration_mins
        applied_flat = flat
    else:
        base = total_cost_inr * (1.0 + (c["profit_margin_percent"] / 100.0))
        applied_flat = 0.0
    addon_per_min = concurrency_addon_for(c["concurrency_addons"], max_concurrency)
    addon_fees_inr = (addon_per_min + float(c["misc_fee_per_min"])) * duration_mins
    price = max(base + addon_fees_inr, c["min_client_price"])
    return {
        "client_price_inr": round(price, 2),
        "applied_flat_rate_per_min": round(applied_flat, 4),
        "concurrency_addon_per_min": round(addon_per_min, 4),
        "misc_fee_per_min": round(float(c["misc_fee_per_min"]), 4),
        "addon_fees_inr": round(addon_fees_inr, 4),
    }
