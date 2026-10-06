"""Super Admin billing configuration.\n\nExtracted from the old monolithic admin_service — behavior unchanged.\n"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from ..db import get_prisma
from .admin_shared import _now, _invalidate, audit

logger = logging.getLogger("voice-agent-saas-admin")


# ---------------------------------------------------------------------------
# Billing config
# ---------------------------------------------------------------------------
def _validate_concurrency_addons(raw: Any) -> List[Dict[str, float]]:
    """Concurrency surcharge tiers: list of {"up_to": int, "addon_per_min": float},
    ascending, max 20 tiers. up_to must be a positive int; addon >= 0."""
    if not isinstance(raw, list):
        raise ValueError("concurrency_addons must be a list of {up_to, addon_per_min}")
    if len(raw) > 20:
        raise ValueError("concurrency_addons: at most 20 tiers")
    out: List[Dict[str, float]] = []
    prev = 0
    for i, t in enumerate(raw):
        if not isinstance(t, dict):
            raise ValueError(f"concurrency_addons[{i}] must be an object")
        try:
            up_to = int(t.get("up_to"))
            addon = float(t.get("addon_per_min"))
        except (TypeError, ValueError):
            raise ValueError(f"concurrency_addons[{i}]: up_to must be an integer and addon_per_min a number") from None
        if up_to < 1 or up_to > 10000:
            raise ValueError(f"concurrency_addons[{i}]: up_to must be between 1 and 10000")
        if addon < 0 or addon > 10000:
            raise ValueError(f"concurrency_addons[{i}]: addon_per_min must be between 0 and 10000")
        if up_to <= prev:
            raise ValueError("concurrency_addons must be sorted ascending by up_to (no duplicates)")
        prev = up_to
        out.append({"up_to": up_to, "addon_per_min": addon})
    return out


async def get_billing() -> Dict[str, Any]:
    db = get_prisma()
    b = await db.billingconfig.find_unique(where={"id": "global"})
    if not b:
        # seed with current env defaults — audit-free idempotent read path
        from .. import config as _cfg

        b = await db.billingconfig.create(data={
            "id": "global", "serverCostPerMin": _cfg.SERVER_COST_PER_MIN,
            "minClientPrice": _cfg.MIN_CLIENT_PRICE,
            "profitMarginPercent": _cfg.PROFIT_MARGIN_PERCENT,
            "walletTopupAmounts": json.dumps(_cfg.WALLET_TOPUP_AMOUNT),
            "updatedAt": _now(),
        })
    try:
        topups = json.loads(b.walletTopupAmounts or "[]")
    except Exception:
        topups = []
    try:
        tiers = json.loads(getattr(b, "concurrencyAddons", "[]") or "[]")
        if not isinstance(tiers, list):
            tiers = []
    except Exception:
        tiers = []
    return {
        "id": b.id,
        "server_cost_per_min": float(b.serverCostPerMin),
        "min_client_price": float(b.minClientPrice),
        "profit_margin_percent": float(b.profitMarginPercent),
        "wallet_topup_amounts": topups,
        "voice_speed_min": float(b.voiceSpeedMin),
        "voice_speed_max": float(b.voiceSpeedMax),
        "voice_speed_default": float(b.voiceSpeedDefault),
        "announcement_price_per_min": float(getattr(b, "announcementPricePerMin", 0) or 0),
        "assistant_price_per_min": float(getattr(b, "assistantPricePerMin", 0) or 0),
        "misc_fee_per_min": float(getattr(b, "miscFeePerMin", 0) or 0),
        "concurrency_addons": tiers,
        "updated_at": b.updatedAt or "",
    }


async def update_billing(patch: Dict[str, Any], *, admin: Dict[str, Any]) -> Dict[str, Any]:
    db = get_prisma()
    cur = await get_billing()
    data: Dict[str, Any] = {}

    def _flt(key: str, lo: float, hi: float, name: str) -> Optional[float]:
        v = patch.get(key)
        if v is None:
            return None
        try:
            f = float(v)
        except (TypeError, ValueError):
            raise ValueError(f"{name} must be a number") from None
        if not (lo <= f <= hi):
            raise ValueError(f"{name} must be between {lo} and {hi}")
        return f

    if (v := _flt("server_cost_per_min", 0, 1000, "server_cost_per_min")) is not None:
        data["serverCostPerMin"] = v
    if (v := _flt("min_client_price", 0, 10000, "min_client_price")) is not None:
        data["minClientPrice"] = v
    if (v := _flt("profit_margin_percent", 0, 1000, "profit_margin_percent")) is not None:
        data["profitMarginPercent"] = v
    if patch.get("wallet_topup_amounts") is not None:
        amounts = patch["wallet_topup_amounts"]
        if not isinstance(amounts, list) or not amounts or any(
                not isinstance(a, (int, float)) or a <= 0 or a > 10_000_000 for a in amounts):
            raise ValueError("wallet_topup_amounts must be a non-empty list of positive numbers")
        data["walletTopupAmounts"] = json.dumps([float(a) for a in amounts])
    if (v := _flt("voice_speed_min", 0.25, 4.0, "voice_speed_min")) is not None:
        data["voiceSpeedMin"] = v
    if (v := _flt("voice_speed_max", 0.25, 4.0, "voice_speed_max")) is not None:
        data["voiceSpeedMax"] = v
    if (v := _flt("voice_speed_default", 0.25, 4.0, "voice_speed_default")) is not None:
        data["voiceSpeedDefault"] = v
    if (v := _flt("announcement_price_per_min", 0, 10000, "announcement_price_per_min")) is not None:
        data["announcementPricePerMin"] = v
    if (v := _flt("assistant_price_per_min", 0, 10000, "assistant_price_per_min")) is not None:
        data["assistantPricePerMin"] = v
    if (v := _flt("misc_fee_per_min", 0, 10000, "misc_fee_per_min")) is not None:
        data["miscFeePerMin"] = v
    if patch.get("concurrency_addons") is not None:
        tiers = _validate_concurrency_addons(patch["concurrency_addons"])
        data["concurrencyAddons"] = json.dumps(tiers)
    if data:
        lo = data.get("voiceSpeedMin", cur["voice_speed_min"])
        hi = data.get("voiceSpeedMax", cur["voice_speed_max"])
        dflt = data.get("voiceSpeedDefault", cur["voice_speed_default"])
        if not (lo <= dflt <= hi):
            raise ValueError("voice_speed_default must lie within [voice_speed_min, voice_speed_max]")
        data["updatedAt"] = _now()
        await db.billingconfig.update(where={"id": "global"}, data=data)
        await audit(admin, "billing_config_changed", target_type="billing", target_id="global",
                    detail={k: ("***" if "key" in k else v) for k, v in patch.items()})
        _invalidate()
    return await get_billing()


# ---------------------------------------------------------------------------
# Stats / analytics
# ---------------------------------------------------------------------------