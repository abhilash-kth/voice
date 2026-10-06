"""DB-backed service + repository tests (SQLite via Prisma)."""
from __future__ import annotations

from datetime import datetime

import pytest

from app import repo, auth
from app.db import get_prisma
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

    async def test_one_shared_key_serves_every_kind_of_the_provider(self, seeded):
        """A key stored for a provider is shared (kind ""): the same OpenAI key
        serves openai-LLM and openai-TTS alike (config_merge.get_api_key)."""
        provs = await admin_service.list_providers(kind="tts")
        ot = next(p for p in provs if p["slug"] == "openai")
        cred = await credential_service.create_credential(
            provider_id=ot["id"], value="sk-shared-openai-42", admin={"id": "a", "email": "a@t"})
        assert cred["kind"] == "", "panel keys are stored as shared (kind '')"
        await config_store.refresh_if_stale(force=True)
        assert config_store.get_api_key("tts", "openai") == "sk-shared-openai-42"
        assert config_store.get_api_key("llm", "openai") == "sk-shared-openai-42"

    async def test_duplicate_active_key_rejected_but_rotation_allowed(self, seeded):
        provs = await admin_service.list_providers(kind="stt")
        dg = next(p for p in provs if p["slug"] == "deepgram")
        first = await credential_service.create_credential(
            provider_id=dg["id"], value="dg-one", admin={"id": "a", "email": "a@t"})
        with pytest.raises(ValueError, match="one key per provider"):
            await credential_service.create_credential(
                provider_id=dg["id"], value="dg-two", admin={"id": "a", "email": "a@t"})
        # Rotation is the intended replace path and must still work.
        new = await credential_service.rotate_credential(
            first["id"], new_value="dg-two", admin={"id": "a", "email": "a@t"})
        await config_store.refresh_if_stale(force=True)
        assert config_store.get_api_key("stt", "deepgram") == "dg-two"
        assert (await credential_service.get_credential(first["id"]))["status"] == "rotated"

    async def test_delete_credential_removes_key_and_audits(self, seeded):
        provs = await admin_service.list_providers(kind="stt")
        dg = next(p for p in provs if p["slug"] == "deepgram")
        cred = await credential_service.create_credential(
            provider_id=dg["id"], value="dg-delete-me", admin={"id": "a", "email": "a@t"})
        assert await credential_service.delete_credential(
            cred["id"], admin={"id": "a", "email": "a@t"}) is True
        assert await credential_service.delete_credential(cred["id"]) is False
        await config_store.refresh_if_stale(force=True)
        assert config_store.get_api_key("stt", "deepgram") is None
        logs = await admin_service.list_audit_logs(action="api_key_deleted")
        assert any(i["target_id"] == cred["id"] for i in logs["items"])

    async def test_reveal_returns_plaintext_and_is_audited(self, seeded):
        provs = await admin_service.list_providers(kind="stt")
        dg = next(p for p in provs if p["slug"] == "deepgram")
        cred = await credential_service.create_credential(
            provider_id=dg["id"], value="dg-reveal-me-9999", admin={"id": "a", "email": "a@t"})
        assert await credential_service.reveal_credential(
            cred["id"], admin={"id": "a", "email": "a@t"}) == "dg-reveal-me-9999"
        assert await credential_service.reveal_credential("no-such-id") is None
        logs = await admin_service.list_audit_logs(action="api_key_revealed")
        entries = [i for i in logs["items"] if i["target_id"] == cred["id"]]
        assert entries, "reveal must be audited"
        assert "dg-reveal-me-9999" not in str(entries[0]["detail"])


class TestCallLifecycle:
    """startedAt stamping + the stale-call sweeper (bug: rows with startedAt=''
    aged 0 forever, so stuck 'in-progress' calls were immortal)."""

    async def test_create_call_stamps_started_at(self, seeded):
        u = await repo.create_user("lc1@t.dev", "LC1", auth.hash_password("pw"))
        a = await repo.create_agent(u["id"], {"name": "A1"})
        c = await repo.create_call({"user_id": u["id"], "agent_id": a["id"], "room": "r1"})
        assert c["started_at"], "startedAt must be auto-stamped so the sweeper can age rows"
        # and the stamp must parse with the sweeper's format
        datetime.strptime(c["started_at"], "%Y-%m-%d %H:%M")

    async def test_sweeper_fails_legacy_stuck_rows_but_never_live_ones(self, seeded):
        u = await repo.create_user("lc2@t.dev", "LC2", auth.hash_password("pw"))
        a = await repo.create_agent(u["id"], {"name": "A2"})
        db = get_prisma()
        # Legacy-style row exactly as old code produced it: in-progress, no timestamp.
        await db.call.create(data={
            "userId": u["id"], "agentId": a["id"], "mode": "browser",
            "room": "dead-room", "status": "in-progress", "startedAt": "", "transcripts": "[]"})
        # Genuinely live call (fresh timestamp, room still live in LiveKit).
        await repo.create_call({"user_id": u["id"], "agent_id": a["id"], "room": "live-room",
                                "status": "in-progress"})
        # Freshly dispatched agent still joining (in-progress but brand new,
        # room not yet live) — the grace window must protect it.
        await repo.create_call({"user_id": u["id"], "agent_id": a["id"], "room": "fresh-room",
                                "status": "in-progress"})

        n = await repo.fail_stale_calls(15, active_rooms={"live-room"})
        assert n == 1
        by_room = {r["room"]: r["status"] for r in await repo.list_calls(u["id"], a["id"])}
        assert by_room["dead-room"] == "failed"
        assert by_room["live-room"] == "in-progress"   # live room → never touched
        assert by_room["fresh-room"] == "in-progress"  # grace window

    async def test_sweeper_age_fallback_when_livekit_down(self, seeded):
        u = await repo.create_user("lc3@t.dev", "LC3", auth.hash_password("pw"))
        a = await repo.create_agent(u["id"], {"name": "A3"})
        db = get_prisma()
        await db.call.create(data={
            "userId": u["id"], "agentId": a["id"], "mode": "browser",
            "room": "ghost", "status": "in-progress", "startedAt": "", "transcripts": "[]"})
        n = await repo.fail_stale_calls(15, active_rooms=None)  # LiveKit unreachable
        assert n == 1
        by_room = {r["room"]: r["status"] for r in await repo.list_calls(u["id"], a["id"])}
        assert by_room["ghost"] == "failed"


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
