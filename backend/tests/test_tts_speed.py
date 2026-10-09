"""Unit tests for the normalized voice_speed → per-provider mapping."""
from __future__ import annotations

from app.services import tts_speed


def test_normalize_clamps_to_admin_range():
    assert tts_speed.normalize_user_speed(2.5, 0.6, 1.6, 1.0) == 1.6
    assert tts_speed.normalize_user_speed(0.1, 0.6, 1.6, 1.0) == 0.6
    assert tts_speed.normalize_user_speed(None, 0.6, 1.6, 1.2) == 1.2
    assert tts_speed.normalize_user_speed("whoops", 0.6, 1.6, 1.0) == 1.0  # type: ignore[arg-type]


def test_map_to_supported_providers():
    assert tts_speed.map_to_provider("sarvam", 1.4) == ("pace", 1.4)
    assert tts_speed.map_to_provider("cartesia", 0.9) == ("speed", 0.9)
    assert tts_speed.map_to_provider("google", 1.3) == ("speaking_rate", 1.3)


def test_map_clamps_to_provider_range():
    assert tts_speed.map_to_provider("cartesia", 0.3) == ("speed", 0.6)   # cartesia floor
    assert tts_speed.map_to_provider("google", 2.5) == ("speaking_rate", 2.0)
    assert tts_speed.map_to_provider("sarvam", 0.1) == ("pace", 0.3)


def test_unsupported_provider_returns_none():
    assert tts_speed.map_to_provider("elevenlabs", 1.4) is None
    assert tts_speed.map_to_provider("some_future_adapter", 1.4) is None


def test_apply_voice_speed_semantics():
    # explicit provider param always wins
    o = tts_speed.apply_voice_speed({"pace": 0.8}, "sarvam", 1.5)
    assert o == {"pace": 0.8}
    # ~1.0 is a no-op (nothing sent to the provider)
    assert tts_speed.apply_voice_speed({}, "sarvam", 1.0) == {}
    assert tts_speed.apply_voice_speed({}, "sarvam", None) == {}
    # injection for supported adapters
    o = tts_speed.apply_voice_speed({}, "sarvam", 1.5)
    assert o == {"pace": 1.5}
    o = tts_speed.apply_voice_speed({"model": "sonic-3"}, "cartesia", 1.5)
    assert o == {"model": "sonic-3", "speed": 1.5}
    # unsupported adapter: unchanged (param never sent)
    o = tts_speed.apply_voice_speed({"voice": "x"}, "elevenlabs", 1.5)
    assert o == {"voice": "x"}


def test_apply_does_not_mutate_input():
    base = {"speed": 0.9}
    out = tts_speed.apply_voice_speed(base, "sarvam", 1.4)
    assert base == {"speed": 0.9}
    assert out == {"speed": 0.9}  # explicit wins, input untouched
