"""Normalized user-side voice speed → per-TTS-provider mapping.

Users get ONE normalized slider (``voice_speed`` on the agent, default 1.0,
range from BillingConfig — typically 0.6–1.6). Each TTS adapter that natively
supports a pace/rate knob translates the normalized value into its own units
and clamps to its own safe range. Providers without a native knob are left
untouched (exactly: the parameter is NOT sent), per product spec.

Provider support matrix (LiveKit plugin constructors):

| adapter            | param           | provider range     | meaning            |
|--------------------|-----------------|--------------------|--------------------|
| sarvam             | pace            | 0.3 - 3.0          | 1.0 = normal       |
| cartesia (sonic 3) | speed           | 0.6 - 2.0          | 1.0 = normal       |
| google             | speaking_rate   | 0.25 - 4.0 (clamp 2.0) | 1.0 = normal  |
| openai-compat      | speed           | 0.25 - 4.0         | 1.0 = normal       |
| elevenlabs         | — (not exposed) | —                  | DO NOT send        |

An explicit per-provider override already stored in the agent's provider
config (``pace``/``speed``/``speaking_rate``) always wins over the normalized
value — saved agents keep sounding exactly the same.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

# adapter -> (param name, min, max)
SPEED_SUPPORT: Dict[str, Tuple[str, float, float]] = {
    "sarvam": ("pace", 0.3, 3.0),
    "cartesia": ("speed", 0.6, 2.0),
    "google": ("speaking_rate", 0.25, 2.0),
    "openai_tts": ("speed", 0.25, 4.0),
    "openai_compat_tts": ("speed", 0.25, 4.0),
    "elevenlabs": (),  # type: ignore[assignment]  # no speed knob -> skip
}

DEFAULT_RANGE = (0.6, 1.6)
DEFAULT_VALUE = 1.0


def normalize_user_speed(value: Optional[float], min_v: float, max_v: float, default: float) -> float:
    """Clamp the user-side value to the admin-configured range; None -> default."""
    try:
        lo, hi = float(min_v), float(max_v)
    except Exception:
        lo, hi = DEFAULT_RANGE
    if lo > hi:
        lo, hi = hi, lo
    if value is None:
        value = default if default else DEFAULT_VALUE
    try:
        v = float(value)
    except (TypeError, ValueError):
        v = default or DEFAULT_VALUE
    return min(max(v, lo), hi)


def map_to_provider(adapter: str, normalized: float) -> Optional[Tuple[str, float]]:
    """Return ``(param_name, provider_value)`` for the adapter, or None when the
    adapter has no native speed control (the value must NOT be sent)."""
    spec = SPEED_SUPPORT.get(adapter)
    if not spec:
        return None
    name, lo, hi = spec
    v = min(max(float(normalized), lo), hi)
    return name, round(v, 3)


def apply_voice_speed(overrides: Dict[str, Any], adapter: str, normalized: Optional[float]) -> Dict[str, Any]:
    """Inject the provider speed param into provider overrides (new dict).

    * ``normalized`` None or ~1.0 → unchanged overrides (nothing sent).
    * An existing explicit provider param (pace/speed/speaking_rate) wins.
    * Unsupported adapter → unchanged overrides.
    """
    out = dict(overrides or {})
    if normalized is None:
        return out
    try:
        n = float(normalized)
    except (TypeError, ValueError):
        return out
    if abs(n - 1.0) < 1e-6:
        return out
    mapped = map_to_provider(adapter, n)
    if mapped is None:
        return out
    name, value = mapped
    for existing in ("pace", "speed", "speaking_rate"):
        if existing in out and out[existing] is not None:
            return out
    out[name] = value
    return out
