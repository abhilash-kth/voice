"""DB-backed tests: per-mode billing + concurrency/misc layers + per-model
TTS speed ranges (Kept separate to respect the ≤300-line per-file rule).
"""
from __future__ import annotations

import pytest

from app import billing
from app.services import admin_service, config_store, tts_speed

pytestmark = pytest.mark.asyncio(loop_scope="session")

ADMIN = {"id": "a", "email": "a@t"}


class TestModePricing:
    async def test_flat_mode_rate_plus_concurrency_and_misc(self, seeded):
        await admin_service.update_billing({
            "announcement_price_per_min": 2.0,
            "misc_fee_per_min": 0.25,
            "concurrency_addons": [
                {"up_to": 5, "addon_per_min": 0.5},
                {"up_to": 10, "addon_per_min": 1.0},
            ],
        }, admin=ADMIN)
        await config_store.refresh_if_stale(force=True)
        out = billing.calculate_call_cost(
            duration_seconds=60, stt_seconds=30, llm_input_tokens=1000,
            llm_output_tokens=1000, tts_chars=800,
            llm_provider_id="groq_llama_3_3_70b", stt_provider_id="deepgram_nova2",
            tts_provider_id="google_wavenet_hi",
            agent_mode="announcement", max_concurrency=8,
        )
        # flat ₹2.00/min + tier "up to 10" ₹1.00/min + misc ₹0.25 = ₹3.25 for 1 min
        assert out["client_price_inr"] == 3.25
        assert out["applied_flat_rate_per_min"] == 2.0
        assert out["concurrency_addon_per_min"] == 1.0
        assert out["misc_fee_per_min"] == 0.25
        # Concurrency picks the first tier whose up_to covers the value.
        out2 = billing.calculate_call_cost(
            duration_seconds=60, stt_seconds=30, llm_input_tokens=1000,
            llm_output_tokens=1000, tts_chars=800,
            llm_provider_id="groq_llama_3_3_70b", stt_provider_id="deepgram_nova2",
            tts_provider_id="google_wavenet_hi",
            agent_mode="announcement", max_concurrency=3,
        )
        assert out2["concurrency_addon_per_min"] == 0.5
        assert out2["client_price_inr"] == 2.75

    async def test_legacy_pricing_unchanged_when_layers_off(self, seeded):
        consts = billing._billing_consts()
        out = billing.calculate_call_cost(
            duration_seconds=60, stt_seconds=30, llm_input_tokens=1000,
            llm_output_tokens=1000, tts_chars=800,
            llm_provider_id="groq_llama_3_3_70b", stt_provider_id="deepgram_nova2",
            tts_provider_id="google_wavenet_hi", agent_mode="assistant", max_concurrency=1,
        )
        assert out["applied_flat_rate_per_min"] == 0.0
        assert out["concurrency_addon_per_min"] == 0.0
        floor = max(out["total_cost_inr"] * (1 + consts["profit_margin_percent"] / 100.0),
                    consts["min_client_price"])
        assert abs(out["client_price_inr"] - max(round(floor, 2), consts["min_client_price"])) < 0.011

    async def test_concurrency_addons_validation(self, seeded):
        with pytest.raises(ValueError):      # not ascending
            await admin_service.update_billing({"concurrency_addons": [
                {"up_to": 10, "addon_per_min": 1.0}, {"up_to": 5, "addon_per_min": 2.0}]}, admin=ADMIN)
        with pytest.raises(ValueError):      # negative addon
            await admin_service.update_billing(
                {"concurrency_addons": [{"up_to": 5, "addon_per_min": -1.0}]}, admin=ADMIN)
        with pytest.raises(ValueError):      # not a list
            await admin_service.update_billing({"concurrency_addons": "fast"}, admin=ADMIN)


class TestModelSpeedRange:
    async def test_per_model_speed_range_reaches_picker_and_normalizer(self, seeded):
        models = (await admin_service.list_models(kind="tts"))["items"]
        m = models[0]
        await admin_service.update_model(
            m["id"], {"meta": {"speed_min": 0.5, "speed_max": 3.0, "speed_default": 1.25}}, admin=ADMIN)
        await config_store.refresh_if_stale(force=True)
        # worker-side lookup (ab_tts_select uses this for the selected model)
        assert tts_speed.model_speed_range(m["catalog_id"]) == (0.5, 3.0, 1.25)
        # customer picker entry exposes the same bounds for the slider
        picker = [p for p in config_store.get_providers_of("tts") if p["id"] == m["catalog_id"]]
        assert picker and picker[0].get("speed_min") == 0.5 and picker[0].get("speed_max") == 3.0

    async def test_model_without_meta_uses_global_range(self, seeded):
        models = (await admin_service.list_models(kind="tts"))["items"]
        m = models[0]
        assert tts_speed.model_speed_range(m["catalog_id"]) is None
        b = config_store.get_billing()
        v = tts_speed.normalize_user_speed(9.9, b["voice_speed_min"], b["voice_speed_max"], b["voice_speed_default"])
        assert v == b["voice_speed_max"]
