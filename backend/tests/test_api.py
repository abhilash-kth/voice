"""HTTP-level tests for the public + Super Admin APIs (httpx ASGITransport,
real SQLite DB). Lifespan is driven manually so the same loop owns Prisma."""
from __future__ import annotations

import pytest
import pytest_asyncio

from app.main import app


pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest_asyncio.fixture(loop_scope="session")
async def live_client(api_client, clean_db, seeded):
    # drive the FastAPI lifespan (already-inited DB + config snapshot) manually
    async with app.router.lifespan_context(app):
        yield api_client


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


async def test_register_login_me(live_client):
    r = await live_client.post("/api/auth/register", json={
        "email": "api1@test.dev", "password": "pw123456", "name": "Api One"})
    assert r.status_code == 201, r.text
    token = r.json()["token"]
    me = await live_client.get("/api/auth/me", headers=_auth(token))
    assert me.status_code == 200
    assert me.json()["role"] == "USER"


async def test_login_disabled_user_rejected(live_client):
    from app.db import get_prisma
    r = await live_client.post("/api/auth/register", json={
        "email": "api2@test.dev", "password": "pw123456", "name": "Api Two"})
    uid = r.json()["user"]["id"]
    await get_prisma().user.update(where={"id": uid}, data={"disabled": True})
    login = await live_client.post("/api/auth/login", json={
        "email": "api2@test.dev", "password": "pw123456"})
    assert login.status_code == 403


class TestSuperAdminSetup:
    """POST /api/setup/super-admin — key-protected one-time bootstrap."""

    async def test_public_register_never_creates_admin(self, live_client):
        # Even if a caller sends a role field, public register must ignore it.
        r = await live_client.post("/api/auth/register", json={
            "email": "sneaky@test.dev", "password": "pw123456",
            "name": "Sneaky", "role": "SUPER_ADMIN"})
        assert r.status_code == 201, r.text
        assert r.json()["user"]["role"] == "USER"

    async def test_setup_disabled_without_env_key(self, live_client, monkeypatch):
        monkeypatch.delenv("SUPER_ADMIN_SETUP_KEY", raising=False)
        r = await live_client.post("/api/setup/super-admin", json={
            "email": "a@test.dev", "password": "pw123456"})
        assert r.status_code == 403, r.text

    async def test_setup_rejects_wrong_key(self, live_client, monkeypatch):
        monkeypatch.setenv("SUPER_ADMIN_SETUP_KEY", "right-key")
        r = await live_client.post("/api/setup/super-admin",
            json={"email": "a@test.dev", "password": "pw123456"},
            headers={"X-Setup-Key": "wrong-key"})
        assert r.status_code == 403, r.text

    async def test_setup_rejects_missing_key(self, live_client, monkeypatch):
        monkeypatch.setenv("SUPER_ADMIN_SETUP_KEY", "right-key")
        r = await live_client.post("/api/setup/super-admin", json={
            "email": "a@test.dev", "password": "pw123456"})
        assert r.status_code == 403, r.text

    async def test_setup_creates_first_super_admin(self, live_client, monkeypatch):
        monkeypatch.setenv("SUPER_ADMIN_SETUP_KEY", "right-key")
        r = await live_client.post("/api/setup/super-admin",
            json={"email": "boss@test.dev", "password": "pw123456", "name": "Boss"},
            headers={"X-Setup-Key": "right-key"})
        assert r.status_code == 201, r.text
        assert r.json()["user"]["role"] == "SUPER_ADMIN"
        me = await live_client.get("/api/auth/me", headers=_auth(r.json()["token"]))
        assert me.json()["role"] == "SUPER_ADMIN"

    async def test_setup_closed_once_admin_exists(self, live_client, monkeypatch):
        monkeypatch.setenv("SUPER_ADMIN_SETUP_KEY", "right-key")
        first = await live_client.post("/api/setup/super-admin",
            json={"email": "first@test.dev", "password": "pw123456"},
            headers={"X-Setup-Key": "right-key"})
        assert first.status_code == 201
        # Even with the CORRECT key, the bootstrap door is now shut forever.
        second = await live_client.post("/api/setup/super-admin",
            json={"email": "second@test.dev", "password": "pw123456"},
            headers={"X-Setup-Key": "right-key"})
        assert second.status_code == 403, second.text


class TestCatalog:
    async def test_catalog_shape_and_temperature_free(self, live_client):
        r = await live_client.get("/api/catalog")
        assert r.status_code == 200
        body = r.json()
        for key in ("catalog", "llm_providers", "llm_models", "llm_models_all",
                    "llm_legacy_providers", "llm_by_provider", "walletTopupAmounts",
                    "server_cost_per_min", "voice_speed"):
            assert key in body, f"missing {key}"
        assert "temperature" not in r.text  # strict: no temperature anywhere
        assert body["voice_speed"] == {"min": 0.6, "max": 1.6, "default": 1.0}
        assert "openrouter" not in [p["id"] for p in body["llm_providers"]]

    async def test_llm_providers_endpoint_shape(self, live_client):
        r = await live_client.get("/api/llm/providers")
        assert r.status_code == 200
        body = r.json()
        assert set(body.keys()) == {"providers", "legacy_providers", "by_provider"}
        assert all("temperature" not in str(m) for m in body["by_provider"].values())

    async def test_validate_endpoint(self, live_client):
        r = await live_client.post("/api/llm/validate", json={
            "provider": "openai", "model_id": "gpt-4.1-mini"})
        assert r.status_code == 200 and r.json()["valid"] is True
        r = await live_client.post("/api/llm/validate", json={
            "provider": "openai", "model_id": "does-not-exist"})
        assert r.status_code == 400


class TestAdminGating:
    async def test_unauthenticated_admin_rejected(self, live_client):
        r = await live_client.get("/api/admin/stats")
        assert r.status_code == 401

    async def test_normal_user_cannot_access_admin(self, live_client, normal_user):
        token, _ = normal_user
        for path in ("/api/admin/stats", "/api/admin/users", "/api/admin/billing"):
            r = await live_client.get(path, headers=_auth(token))
            assert r.status_code == 403, f"{path} should be 403 for normal users"

    async def test_normal_user_cannot_mutate_admin(self, live_client, normal_user):
        token, _ = normal_user
        r = await live_client.put("/api/admin/billing", headers=_auth(token),
                                  json={"server_cost_per_min": 99})
        assert r.status_code == 403

    async def test_super_admin_access(self, live_client, super_admin):
        token, _ = super_admin
        r = await live_client.get("/api/admin/stats", headers=_auth(token))
        assert r.status_code == 200, r.text
        assert r.json()["models"] > 0


class TestAdminFlows:
    async def test_billing_update_and_invalidation(self, live_client, super_admin):
        token, _ = super_admin
        r = await live_client.put("/api/admin/billing", headers=_auth(token),
                                  json={"server_cost_per_min": 0.11, "wallet_topup_amounts": [50, 100]})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["server_cost_per_min"] == 0.11
        assert body["wallet_topup_amounts"] == [50.0, 100.0]
        # user catalog reflects the override
        cat = await live_client.get("/api/catalog")
        assert cat.json()["walletTopupAmounts"] == [50.0, 100.0]
        assert cat.json()["server_cost_per_min"] == 0.11

    async def test_billing_validation_errors(self, live_client, super_admin):
        token, _ = super_admin
        r = await live_client.put("/api/admin/billing", headers=_auth(token),
                                  json={"profit_margin_percent": -5})
        assert r.status_code == 400

    async def test_model_disable_hides_from_users(self, live_client, super_admin):
        token, _ = super_admin
        models = (await live_client.get("/api/admin/models?kind=llm", headers=_auth(token))).json()["items"]
        target = next((m for m in models if m["model_id"] == "gpt-4.1-mini"), None)
        assert target is not None
        r = await live_client.put(f"/api/admin/models/{target['id']}", headers=_auth(token),
                                  json={"enabled": False})
        assert r.status_code == 200
        cat = (await live_client.get("/api/catalog")).json()
        assert not any(m["model_id"] == "gpt-4.1-mini" and m["provider"] == "openai"
                       for m in cat["llm_models"])
        assert any(m["model_id"] == "gpt-4.1-mini" and m["provider"] == "openai"
                   for m in cat["llm_models_all"])
        # re-enable (leave clean state)
        r = await live_client.put(f"/api/admin/models/{target['id']}", headers=_auth(token),
                                  json={"enabled": True})
        assert r.status_code == 200

    async def test_credential_flow_never_leaks_secret(self, live_client, super_admin):
        token, _ = super_admin
        provs = (await live_client.get("/api/admin/providers?kind=stt", headers=_auth(token))).json()["items"]
        dg = next(p for p in provs if p["slug"] == "deepgram")
        SECRET = "dg-top-secret-8888"
        r = await live_client.post("/api/admin/credentials", headers=_auth(token),
                                   json={"provider_id": dg["id"], "value": SECRET, "label": "prod"})
        assert r.status_code == 201, r.text
        cred = r.json()
        assert SECRET not in r.text
        assert cred["masked_value"].endswith("8888")
        listed = (await live_client.get("/api/admin/credentials", headers=_auth(token))).json()
        assert SECRET not in str(listed)

    async def test_audit_log_records_actions(self, live_client, super_admin):
        token, _ = super_admin
        # perform an admin mutation and verify it landed in the audit log
        upd = await live_client.put("/api/admin/billing", headers=_auth(token),
                                    json={"min_client_price": 1.5})
        assert upd.status_code == 200
        r = await live_client.get("/api/admin/audit-logs", headers=_auth(token))
        assert r.status_code == 200
        entries = [i for i in r.json()["items"] if i["action"] == "billing_config_changed"]
        assert entries, "billing mutation must be audited"
        assert entries[0]["admin_email"] == "admin@test.dev"

    async def test_users_pagination_search_filter(self, live_client, super_admin):
        token, _ = super_admin
        r = await live_client.get("/api/admin/users?role=SUPER_ADMIN", headers=_auth(token))
        assert r.status_code == 200
        body = r.json()
        assert set(body.keys()) == {"items", "total", "page", "page_size"}
        assert all(u["role"] == "SUPER_ADMIN" for u in body["items"])
        r = await live_client.get("/api/admin/users?q=api", headers=_auth(token))
        assert all("api" in (u["email"] + u["name"]).lower() for u in r.json()["items"])
