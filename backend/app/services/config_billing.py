"""Sync billing-config getter (split from config_merge.py; ≤300-line rule).

Read by billing.py / billing_rates.py on the hot path — snapshot-backed with
code/env fallbacks for every key, never touches the DB synchronously.
"""
from __future__ import annotations

import json
from typing import Any, Dict

from .config_core import get_snapshot


def get_billing() -> Dict[str, Any]:
    """Billing config with code/env fallbacks for every key."""
    from .. import config as _cfg

    b = dict(get_snapshot().billing or {})
    out: Dict[str, Any] = {
        "server_cost_per_min": float(b.get("serverCostPerMin") if b.get("serverCostPerMin") is not None else _cfg.SERVER_COST_PER_MIN),
        "min_client_price": float(b.get("minClientPrice") if b.get("minClientPrice") is not None else _cfg.MIN_CLIENT_PRICE),
        "profit_margin_percent": float(b.get("profitMarginPercent") if b.get("profitMarginPercent") is not None else _cfg.PROFIT_MARGIN_PERCENT),
        "wallet_topup_amounts": list(b.get("wallet_topup_amounts") or _cfg.WALLET_TOPUP_AMOUNT),
        "voice_speed_min": float(b.get("voiceSpeedMin") if b.get("voiceSpeedMin") is not None else 0.6),
        "voice_speed_max": float(b.get("voiceSpeedMax") if b.get("voiceSpeedMax") is not None else 1.6),
        "voice_speed_default": float(b.get("voiceSpeedDefault") if b.get("voiceSpeedDefault") is not None else 1.0),
        # Per-mode customer pricing + surcharges (see app/billing_rates.py).
        "announcement_price_per_min": float(b.get("announcementPricePerMin") or 0),
        "assistant_price_per_min": float(b.get("assistantPricePerMin") or 0),
        "misc_fee_per_min": float(b.get("miscFeePerMin") or 0),
        # Monthly subscription economics + per-mode rate-card minimums.
        "concurrency_line_price_per_month": float(b.get("concurrencyLinePricePerMonth") or 0),
        "telephony_rent_per_month": float(b.get("telephonyRentPerMonth") or 0),
        "assistant_min_per_min": float(b.get("assistantMinPerMin") or 1.0),
        "announcement_min_per_min": float(b.get("announcementMinPerMin") or 1.0),
    }
    try:
        tiers = json.loads(b.get("concurrencyAddons") or "[]")
        out["concurrency_addons"] = tiers if isinstance(tiers, list) else []
    except Exception:
        out["concurrency_addons"] = []
    return out
