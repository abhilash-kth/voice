"""DB-backed service + repository tests (SQLite via Prisma)."""
from __future__ import annotations

import pytest

from app import repo, auth
from app.services import admin_service, catalog_service, config_store, credential_service
from app import billing


pytestmark = pytest.mark.asyncio(loop_scope="session")


class TestSeedingAndSnapshot:
    async def test_seed_from_code_defaults(self, seeded):
        snap = await config_store.refresh_if_stale(force=True)
        assert snap.source == "db"
        assert "openai" in snap.providers["llm"]
        assert "deepgram" in snap.providers["stt"]
        assert any(m["modelId"] == "gpt-4.1-mini" for m in snap.models["llm"])
        assert snap.billing["serverCostPerMin"] == 0.05

    async def test_seed_is_idempotent(self, seeded):
        await catalog_service.seed_defaults_if_empty()  # second time
        from app.db import get_prisma
        assert await get_prisma().provider.count() > 0
        count1 = await get_prisma().catalogmodel.count()
        await catalog_service.seed_defaults_if_empty()  # third time
        assert await get_prisma().catalogmodel.count() == count1

    async def test_code_fallback_snapshot_has_zero_db_state(self, clean_db):
        from app.services.config_store import _code_fallback_snapshot
        snap = _code_fallback_snapshot()
        assert snap.source == "code"
        # fallback billing == env defaults
        b = config_store.get_billing()
        assert b["server_cost_per_min"] == 0.05

    async def test_temperature_absent_from_all_catalog_metas(self, seeded):
        uc = catalog_service.build_user_catalog()
        for m in uc["llm_models"] + uc["llm_models_all"]:
            assert "supports_temperature" not in m
            assert "default_temperature" not in m


class TestBilling:
    async def test_dynamic_billing_override_flows_into_engine(self, seeded):
        before = billing._billing_consts()
        assert before["server_cost_per_min"] == 0.05
        await admin_service.update_billing({"server_cost_per_min": 0.07}, admin={"id": "a", "email": "a@t"})
        await config_store.refresh_if_stale(force=True)
        consts = billing._billing_consts()
        assert consts["server_cost_per_min"] == 0.07

    async def test_billing_update_validation(self, seeded):
        with pytest.raises(ValueError):
            await admin_service.update_billing({"profit_margin_percent": -1}, admin={"id": "a", "email": "a@t"})
        with pytest.raises(ValueError):
            await admin_service.update_billing({"wallet_topup_amounts": []}, admin={"id": "a", "email": "a@t"})
        with pytest.raises(ValueError):
            await admin_service.update_billing(
                {"voice_speed_min": 1.4, "voice_speed_max": 1.2}, admin={"id": "a", "email": "a@t"})

    async def test_billing_unknown_model_falls_back(self, seeded):
        out = billing.calculate_call_cost(
            duration_seconds=60, stt_seconds=30, llm_input_tokens=1000,
            llm_output_tokens=1000, tts_chars=800,
            llm_provider_id="groq_llama_3_3_70b", stt_provider_id="deepgram_nova2",
            tts_provider_id="google_wavenet_hi", client_rate_per_min=2.5,
        )
        assert out["client_price_inr"] >= out["total_cost_inr"]
        assert out["profit_margin_percent"] == 50.0


class TestUserCatalogFiltering:
    async def test_disabled_model_hidden_from_pickers(self, seeded):
        uc1 = catalog_service.build_user_catalog()
        assert any(m["model_id"] == "gpt-4.1-nano" for m in uc1["llm_models"])
        nano = next(m for m in (await admin_service.list_models(kind="llm"))["items"]
                    if m["model_id"] == "gpt-4.1-nano")
        await admin_service.update_model(nano["id"], {"enabled": False}, admin={"id": "a", "email": "a@t"})
        await config_store.refresh_if_stale(force=True)
        uc2 = catalog_service.build_user_catalog()
        assert not any(m["model_id"] == "gpt-4.1-nano" and m["provider"] == "openai" for m in uc2["llm_models"])
        assert any(m["model_id"] == "gpt-4.1-nano" and m["provider"] == "openai" for m in uc2["llm_models_all"])

    async def test_deprecated_provider_not_in_providers(self, seeded):
        uc = catalog_service.build_user_catalog()
        assert "openrouter" not in [p["id"] for p in uc["llm_providers"]]
        assert "openrouter" in [p["id"] for p in uc["llm_legacy_providers"]]

    async def test_validate_llm_respects_enabled_flags(self, seeded):
        ok, _ = catalog_service.validate_llm("openai", "gpt-4.1-mini")
        assert ok
        ok, msg = catalog_service.validate_llm("qwen", "qwen3.6-27b")
        assert not ok and "disabled" in msg.lower()

    async def test_admin_added_tts_appears_when_enabled(self, seeded):
        provs = await admin_service.list_providers(kind="tts")
        fish = next(p for p in provs if p["slug"] == "fish")
        await admin_service.update_provider(fish["id"], {"enabled": True}, admin={"id": "a", "email": "a@t"})
        fm = next(m for m in (await admin_service.list_models(kind="tts"))["items"]
                  if m["provider_slug"] == "fish")
        await admin_service.update_model(fm["id"], {"enabled": True}, admin={"id": "a", "email": "a@t"})
        await config_store.refresh_if_stale(force=True)
        uc = catalog_service.build_user_catalog()
        ids = [p["id"] for p in uc["catalog"]["tts"]]
        assert "fish" in ids


class TestCredentials:
    async def test_create_mask_snapshot_decrypt(self, seeded):
        provs = await admin_service.list_providers(kind="stt")
        dg = next(p for p in provs if p["slug"] == "deepgram")
        cred = await credential_service.create_credential(
            provider_id=dg["id"], value="dg-api-key-2026", label="prod", admin={"id": "a", "email": "a@t"})
        assert cred["masked_value"].endswith("2026")
        assert "dg-api-key-2026" not in str(cred)
        await config_store.refresh_if_stale(force=True)
        assert config_store.get_api_key("stt", "deepgram") == "dg-api-key-2026"

    async def test_rotation(self, seeded):
        provs = await admin_service.list_providers(kind="stt")
        dg = next(p for p in provs if p["slug"] == "deepgram")
        cred = await credential_service.create_credential(
            provider_id=dg["id"], value="dg-old-key-AAAA", admin={"id": "a", "email": "a@t"})
        new = await credential_service.rotate_credential(
            cred["id"], new_value="dg-new-key-BBBB", admin={"id": "a", "email": "a@t"})
        await config_store.refresh_if_stale(force=True)
        assert config_store.get_api_key("stt", "deepgram") == "dg-new-key-BBBB"
        old = await credential_service.get_credential(cred["id"])
        assert old["status"] == "rotated"

    async def test_disabled_credential_not_used(self, seeded):
        provs = await admin_service.list_providers(kind="stt")
        dg = next(p for p in provs if p["slug"] == "deepgram")
        cred = await credential_service.create_credential(
            provider_id=dg["id"], value="dg-key-x", admin={"id": "a", "email": "a@t"})
        await credential_service.set_status(cred["id"], "disabled", admin={"id": "a", "email": "a@t"})
        await config_store.refresh_if_stale(force=True)
        assert config_store.get_api_key("stt", "deepgram") is None


class TestUsersAndAudit:
    async def test_role_guard_refuses_demote_last_admin(self, seeded):
        u = await repo.create_user("solo-admin@t.dev", "Solo", auth.hash_password("pw"))
        from app.db import get_prisma
        await get_prisma().user.update(where={"id": u["id"]}, data={"role": "SUPER_ADMIN"})
        with pytest.raises(ValueError):
            await admin_service.set_user_role(u["id"], "USER", admin={"id": "other", "email": "o@t"})

    async def test_disable_self_admin_refused(self, seeded):
        u = await repo.create_user("self@t.dev", "Self", auth.hash_password("pw"))
        from app.db import get_prisma
        await get_prisma().user.update(where={"id": u["id"]}, data={"role": "SUPER_ADMIN"})
        with pytest.raises(ValueError):
            await admin_service.set_user_disabled(u["id"], True, admin={"id": u["id"], "email": "self@t.dev"})

    async def test_every_mutation_is_audited(self, seeded):
        await admin_service.update_billing({"min_client_price": 2.0}, admin={"id": "a", "email": "auditor@t"})
        logs = await admin_service.list_audit_logs(q="billing_config_changed")
        assert logs["total"] >= 1
        entry = logs["items"][0]
        assert entry["admin_email"] == "auditor@t"
        assert entry["target_type"] == "billing"


class TestWallet:
    async def test_recharge_and_deduct_atomic(self, clean_db):
        u = await repo.create_user("w@t.dev", "W", auth.hash_password("pw"))
        w = await repo.recharge(u["id"], 250.0)
        assert w["balance"] == 250.0
        w = await repo.deduct(u["id"], 20.0, note="Call abc123")
        assert w["balance"] == 230.0
        # idempotent: same note never double-charges
        w = await repo.deduct(u["id"], 20.0, note="Call abc123")
        assert w["balance"] == 230.0

    async def test_deduct_floors_at_zero(self, clean_db):
        u = await repo.create_user("w2@t.dev", "W2", auth.hash_password("pw"))
        w = await repo.deduct(u["id"], 99.0, note="Call zero")
        assert w["balance"] == 0.0
