"""DB-backed tests: rate-card billing, never-loss floor, concurrency/misc
layers (kept separate to respect the ≤300-line per-file rule).
"""
from __future__ import annotations

import pytest

from app import billing
from app.services import admin_service, config_store

pytestmark = pytest.mark.asyncio(loop_scope="session")

ADMIN = {"id": "a", "email": "a@t"}

RESET_LAYERS = {
    "announcement_price_per_min": 0.0,
    "assistant_price_per_min": 0.0,
    "misc_fee_per_min": 0.0,
    "concurrency_addons": [],
}


async def _refresh() -> None:
    await config_store.refresh_if_stale(force=True)


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
        await _refresh()
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
        assert out["is_profit"] is True
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
        # Deterministic regardless of test order: switch all layers off first.
        await admin_service.update_billing(RESET_LAYERS, admin=ADMIN)
        await _refresh()
        consts = billing._billing_consts()
        out = billing.calculate_call_cost(
            duration_seconds=60, stt_seconds=30, llm_input_tokens=1000,
            llm_output_tokens=1000, tts_chars=800,
            llm_provider_id="groq_llama_3_3_70b", stt_provider_id="deepgram_nova2",
            tts_provider_id="google_wavenet_hi", agent_mode="assistant", max_concurrency=1,
        )
        assert out["applied_flat_rate_per_min"] == 0.0
        assert out["concurrency_addon_per_min"] == 0.0
        # With no rate card priced, the never-loss floor rules the price.
        floor = max(out["total_cost_inr"] * (1 + consts["profit_margin_percent"] / 100.0),
                    consts["min_client_price"])
        assert abs(out["client_price_inr"] - max(round(floor, 2), consts["min_client_price"])) < 0.011
        assert out["floor_applied"] is True
        assert out["is_profit"] is True

    async def test_selected_models_rate_card(self, seeded):
        await admin_service.update_billing(RESET_LAYERS, admin=ADMIN)
        llms = (await admin_service.list_models(kind="llm"))["items"]
        stts = (await admin_service.list_models(kind="stt"))["items"]
        lm, sm = llms[0], stts[0]
        await admin_service.update_model(lm["id"], {"customer_price_per_min": 2.0}, admin=ADMIN)
        await admin_service.update_model(sm["id"], {"customer_price_per_min": 0.5}, admin=ADMIN)
        await _refresh()
        try:
            out = billing.calculate_call_cost(
                duration_seconds=60, stt_seconds=30, llm_input_tokens=1000,
                llm_output_tokens=1000, tts_chars=800,
                llm_provider=lm["provider_slug"], llm_model_id=lm["model_id"],
                stt_provider_id=sm["catalog_id"], tts_provider_id="",
                agent_mode="assistant", max_concurrency=1,
            )
            # Rate card = llm ₹2.00 + stt ₹0.50 (no tiers/misc) → ₹2.50/min.
            assert out["models_rate_per_min"] == 2.5
            assert out["client_price_inr"] == 2.5
            assert out["is_profit"] is True
            # Never-loss: even a ₹0 rate card floors at cost × (1+margin).
            await admin_service.update_model(lm["id"], {"customer_price_per_min": 0.0}, admin=ADMIN)
            await admin_service.update_model(sm["id"], {"customer_price_per_min": 0.0}, admin=ADMIN)
            await _refresh()
            out2 = billing.calculate_call_cost(
                duration_seconds=60, stt_seconds=30, llm_input_tokens=1000,
                llm_output_tokens=1000, tts_chars=800,
                llm_provider=lm["provider_slug"], llm_model_id=lm["model_id"],
                stt_provider_id=sm["catalog_id"], tts_provider_id="",
                agent_mode="assistant", max_concurrency=1,
            )
            assert out2["models_rate_per_min"] == 0.0
            assert out2["floor_applied"] is True
            assert out2["client_price_inr"] >= out2["total_cost_inr"]
            assert out2["is_profit"] is True
        finally:
            await admin_service.update_model(lm["id"], {"customer_price_per_min": 0.0}, admin=ADMIN)
            await admin_service.update_model(sm["id"], {"customer_price_per_min": 0.0}, admin=ADMIN)
            await _refresh()

    async def test_concurrency_addons_validation(self, seeded):
        with pytest.raises(ValueError):      # not ascending
            await admin_service.update_billing({"concurrency_addons": [
                {"up_to": 10, "addon_per_min": 1.0}, {"up_to": 5, "addon_per_min": 2.0}]}, admin=ADMIN)
        with pytest.raises(ValueError):      # negative addon
            await admin_service.update_billing(
                {"concurrency_addons": [{"up_to": 5, "addon_per_min": -1.0}]}, admin=ADMIN)
        with pytest.raises(ValueError):      # not a list
            await admin_service.update_billing({"concurrency_addons": "fast"}, admin=ADMIN)
