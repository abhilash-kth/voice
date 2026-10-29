"""Telephony marketplace: purpose rules, assignment, and secret hygiene."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app import repo
from app.models import AgentCreate
from app.models.telephony_models import (
    ManualNumberBody,
    QuoteBody,
    TelephonySettingsBody,
)
from app.services import telephony_policy as policy


@pytest.fixture
def telephony_crypto(monkeypatch):
    from cryptography.fernet import Fernet

    from app.services import crypto

    monkeypatch.setenv("ADMIN_CONFIG_ENC_KEY", Fernet.generate_key().decode())
    monkeypatch.delenv("ADMIN_CONFIG_ENC_KEYS", raising=False)
    crypto.reset_cache_for_tests()
    yield
    crypto.reset_cache_for_tests()


def test_agent_create_requires_a_valid_purpose():
    with pytest.raises(ValidationError):
        AgentCreate(name="No purpose", providers={})

    with pytest.raises(ValidationError):
        AgentCreate(name="Bad purpose", providers={}, purpose="sideways")

    body = AgentCreate(name="Reception", providers={}, purpose="inbound")
    assert body.purpose == "inbound"
    assert body.phone_number_id is None


def test_telephony_bodies_reject_customer_supplied_trunks_and_passwords():
    with pytest.raises(ValidationError):
        QuoteBody(
            did_id="42",
            number="+919876543210",
            idempotency_key="quote-key-1",
            sip_trunk_id="ST_someone_else",
        )

    with pytest.raises(ValidationError):
        ManualNumberBody(
            user_id="user-1",
            number="+919876543210",
            sip_password="never-accept-this",
        )


def test_destination_and_carrier_dial_normalization():
    assert policy.normalize_destination("98765 43210") == "+919876543210"
    assert policy.normalize_destination("09876543210") == "+919876543210"
    assert policy.carrier_dial_number("+919876543210", "45454") == (
        "45454919876543210"
    )
    assert policy.carrier_dial_number("45454919876543210", "45454") == (
        "45454919876543210"
    )


def test_customer_views_hide_provider_ids_trunks_and_sip_secrets():
    from app.routes.telephony_routes import (
        _public_account,
        _public_phone,
        _public_purchase,
    )

    account = _public_account({
        "id": "acct-1", "email": "owner@example.com", "name": "Owner",
        "client_id": "hidden-client", "provider_reseller_id": "hidden",
        "username": "hidden-user", "kyc_meta": {"documents": {}},
        "status": "active", "wallet_balance": 10,
    })
    phone = _public_phone({
        "id": "phone-1", "number": "+919876543210", "status": "active",
        "sip_username": "hidden", "sip_password_masked": "••••1234",
        "has_sip_password": True, "voice_link_trunk_id": "vl-trunk",
        "livekit_outbound_trunk_id": "ST_hidden",
        "livekit_inbound_trunk_id": "ST_hidden_in",
        "livekit_dispatch_rule_id": "SDR_hidden", "dial_prefix": "45454",
        "provider_did_id": "provider-did", "meta": {"secret": "no"},
    })
    purchase = _public_purchase({
        "id": "purchase-1", "number": "+919876543210", "state": "active",
        "provider_did_id": "provider-did", "provider_order_id": "order",
        "provider_purchase_id": "provider-purchase",
        "voice_link_account_id": "acct-1", "phone_number": phone,
    })

    rendered = repr((account, phone, purchase))
    for forbidden in (
        "hidden-client", "hidden-user", "vl-trunk", "ST_hidden",
        "SDR_hidden", "provider-did", "provider-purchase", "••••1234",
    ):
        assert forbidden not in rendered
    assert account["email"] == "owner@example.com"
    assert phone["number"] == "+919876543210"
    assert purchase["phone_number"]["id"] == "phone-1"


def test_campaign_customer_view_hides_derived_trunk_without_mutating_store():
    from app.routes.campaigns_routes import _public_campaign

    stored = {
        "id": "campaign-1", "sip_trunk_id": "ST_hidden",
        "dial_prefix": "45454", "caller_id": "+919876543210",
    }
    public = _public_campaign(stored)

    assert public == {"id": "campaign-1", "caller_id": "+919876543210"}
    assert stored["sip_trunk_id"] == "ST_hidden"
    assert stored["dial_prefix"] == "45454"


def test_super_admin_telephony_settings_view_never_exposes_secrets(
        telephony_crypto):
    from app.services import telephony_settings as settings_svc
    from app.services.crypto import encrypt_secret

    token_enc, token_masked = encrypt_secret("vl-token-1234567890")
    password_enc, password_masked = encrypt_secret("vl-password-9876")
    settings = settings_svc._settings_from_record({
        "default_sip_trunk_id": "ST_default",
        "voicelink_api_base_url": "https://app.voicelink.co.in/api/v1",
        "voicelink_api_token_enc": token_enc,
        "voicelink_api_token_masked": token_masked,
        "voicelink_username": "reseller@example.com",
        "voicelink_password_enc": password_enc,
        "voicelink_password_masked": password_masked,
        "voicelink_sip_host": "sip.voicelink.co.in",
        "voicelink_sip_port": 3300,
        "voicelink_tech_prefix": "45454",
        "voicelink_transport_type": 1,
        "voicelink_audio_formats": "alaw,ulaw",
        "voicelink_wallet_bypass": True,
        "voicelink_kyc_terms_url": "",
        "voicelink_kyc_redirect_hosts": "id.example.com",
        "kyc_finalize_verified": False,
        "livekit_sip_host": "sip.example.com",
        "livekit_sip_port": 5060,
        "frontend_url": "https://agents.example.com",
        "public_api_url": "",
        "updated_at": "2026-10-29T00:00:00",
    })

    assert settings.voicelink_api_token == "vl-token-1234567890"
    assert settings.voicelink_password == "vl-password-9876"
    view = settings_svc.public_view(settings)
    rendered = repr(view)
    assert view["configured"] is True
    assert view["voicelink_api_token_configured"] is True
    assert view["voicelink_password_configured"] is True
    for forbidden in ("vl-token-1234567890", "vl-password-9876",
                      token_enc, password_enc):
        assert forbidden not in rendered


def test_telephony_settings_patch_validates_and_encrypts(telephony_crypto):
    from app.services import telephony_settings as settings_svc
    from app.services.crypto import decrypt_secret

    with pytest.raises(ValidationError):
        TelephonySettingsBody(sip_password="not-a-setting")

    patch = settings_svc._normalize_patch({
        "voicelink_api_base_url": "https://app.voicelink.co.in/api/v1/",
        "voicelink_api_token": "rotated-token-4321",
        "voicelink_audio_formats": ["ALAW", "ulaw", "alaw"],
        "voicelink_kyc_redirect_hosts": ["ID.Example.COM"],
        "livekit_sip_host": "SIP.Example.com",
    })
    assert patch["voicelink_api_base_url"] == (
        "https://app.voicelink.co.in/api/v1")
    assert decrypt_secret(patch["voicelink_api_token_enc"]) == (
        "rotated-token-4321")
    assert "rotated-token-4321" not in repr(patch)
    assert patch["voicelink_audio_formats"] == "alaw,ulaw"
    assert patch["voicelink_kyc_redirect_hosts"] == "id.example.com"
    assert patch["livekit_sip_host"] == "sip.example.com"

    with pytest.raises(policy.TelephonyError):
        settings_svc._normalize_patch({
            "voicelink_api_base_url": "http://provider.example.com/api"})
    with pytest.raises(policy.TelephonyError):
        settings_svc._normalize_patch({"voicelink_tech_prefix": "45A54"})
    with pytest.raises(policy.TelephonyError):
        settings_svc._normalize_patch({
            "livekit_sip_host": "https://sip.example.com:5060"})

    cleared = settings_svc._normalize_patch({
        "clear_voicelink_api_token": True,
        "voicelink_api_token": "must-not-win-over-clear",
    })
    assert cleared["voicelink_api_token_enc"] == ""
    assert cleared["voicelink_api_token_masked"] == ""


async def _active_phone(user_id: str) -> dict:
    return await repo.create_phone_number({
        "user_id": user_id,
        "number": "+919429399159",
        "status": "active",
        "source": "manual",
        "livekit_outbound_trunk_id": "ST_assigned",
        "livekit_inbound_trunk_id": "ST_inbound",
        "dial_prefix": "45454",
        "sip_password_enc": "ciphertext-only",
        "sip_password_masked": "••••1234",
    })


async def test_phone_repo_never_returns_sip_password_ciphertext(normal_user):
    _, user = normal_user
    phone = await _active_phone(user["id"])
    loaded = await repo.get_phone_number(phone["id"], user["id"])

    assert loaded is not None
    assert loaded["has_sip_password"] is True
    assert loaded["sip_password_masked"] == "••••1234"
    assert "_sip_password_enc" not in loaded
    assert "sip_password_enc" not in loaded


async def test_one_inbound_agent_per_number_but_outbound_may_share(normal_user):
    _, user = normal_user
    phone = await _active_phone(user["id"])
    await repo.create_agent(user["id"], {
        "name": "Inbound owner",
        "purpose": "inbound",
        "phone_number_id": phone["id"],
    })

    # A second outbound-only agent may use the same caller ID.
    assert await policy.validate_agent_phone_assignment(
        user["id"], "outbound", phone["id"]) is not None

    # A second inbound-capable agent would make DID routing ambiguous.
    with pytest.raises(policy.TelephonyError) as exc:
        await policy.validate_agent_phone_assignment(
            user["id"], "both", phone["id"])
    assert exc.value.status_code == 409


async def test_assigned_number_derives_trunk_and_ignores_requested_one(normal_user):
    _, user = normal_user
    phone = await _active_phone(user["id"])
    agent = await repo.create_agent(user["id"], {
        "name": "Sales",
        "purpose": "both",
        "phone_number_id": phone["id"],
    })

    route = await policy.resolve_outbound(
        agent, user["id"], requested_trunk_id="ST_other_tenant")

    assert route == {
        "sip_trunk_id": "ST_assigned",
        "caller_id": "+919429399159",
        "dial_prefix": "45454",
        "phone_number_id": phone["id"],
        "phone_number": "+919429399159",
    }


async def test_inbound_only_agent_cannot_resolve_an_outbound_route(normal_user):
    _, user = normal_user
    agent = await repo.create_agent(user["id"], {
        "name": "Reception only",
        "purpose": "inbound",
    })

    with pytest.raises(policy.TelephonyError) as exc:
        await policy.resolve_outbound(agent, user["id"])
    assert exc.value.status_code == 400
    assert "inbound-only" in str(exc.value)


async def test_customer_overview_starts_without_an_account(api_client, normal_user):
    token, _ = normal_user
    resp = await api_client.get(
        "/api/telephony/overview",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["account"] is None
    assert body["numbers"] == []
    assert "configured" in body


async def test_super_admin_saves_telephony_settings_encrypted(
        api_client, super_admin, normal_user, telephony_crypto):
    from app.services.crypto import decrypt_secret

    admin_token, _ = super_admin
    user_token, _ = normal_user
    denied = await api_client.get(
        "/api/admin/telephony/settings",
        headers={"Authorization": f"Bearer {user_token}"})
    assert denied.status_code == 403

    resp = await api_client.put(
        "/api/admin/telephony/settings",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "voicelink_api_token": "panel-token-998877",
            "voicelink_password": "panel-password-112233",
            "voicelink_sip_host": "sip.voicelink.co.in",
            "voicelink_sip_port": 3300,
            "livekit_sip_host": "sip.example.com",
            "livekit_sip_port": 5060,
            "frontend_url": "https://agents.example.com",
        })
    assert resp.status_code == 200, resp.text
    assert "panel-token-998877" not in resp.text
    assert "panel-password-112233" not in resp.text
    settings = resp.json()["settings"]
    assert settings["source"] == "super_admin"
    assert settings["configured"] is True
    assert settings["voicelink_api_token_configured"] is True

    stored = await repo.get_telephony_config(include_secrets=True)
    assert stored is not None
    assert stored["voicelink_api_token_enc"] != "panel-token-998877"
    assert decrypt_secret(stored["voicelink_api_token_enc"]) == (
        "panel-token-998877")
    assert decrypt_secret(stored["voicelink_password_enc"]) == (
        "panel-password-112233")
