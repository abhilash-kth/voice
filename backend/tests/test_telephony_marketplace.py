"""Telephony marketplace: purpose rules, assignment, and secret hygiene."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app import repo
from app.models import AgentCreate
from app.models.telephony_models import (
    ManualNumberBody,
    ManualNumberUpdateBody,
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


def test_voicelink_trunk_reuse_matches_unique_sip_host():
    from app.services.telephony_provisioning import (
        _find_trunk_by_id, _find_voicelink_trunk)

    rows = [
        {"id": 11, "client_id": 99, "trunk_name": "manual",
         "sip_server_host": "SIP.EXAMPLE.COM.", "status": 0},
        {"id": 12, "client_id": 99, "trunk_name": "livekit",
         "sip_server_host": "sip.example.com", "status": 1},
        {"id": 13, "client_id": 42, "trunk_name": "other-host",
         "sip_server_host": "other.example.com", "status": 1},
    ]
    assert _find_voicelink_trunk(
        rows, trunk_name="voxura-new", username="trunk_new",
        host="sip.example.com", client_id="42") is None

    rows.append({"id": 15, "client_id": 42, "trunk_name": "client-host",
                  "sip_server_host": "sip.example.com", "status": 1})
    same_client = _find_voicelink_trunk(
        rows, trunk_name="voxura-new", username="trunk_new",
        host="sip.example.com", client_id="42")
    assert same_client["id"] == 15

    rows.append({"id": 14, "client_id": 42, "username": "trunk_new",
                  "sip_server_host": "old.example.com", "status": 1})
    exact = _find_voicelink_trunk(
        rows, trunk_name="voxura-new", username="trunk_new",
        host="sip.example.com", client_id="42")
    assert exact["id"] == 14
    assert _find_trunk_by_id(rows, "12")["client_id"] == 99


def test_voicelink_shared_trunk_credentials_fallback_is_guarded():
    from types import SimpleNamespace

    from app.services.telephony_provisioning import _resolve_trunk_credentials

    settings = SimpleNamespace(
        voicelink_shared_trunk_username="shared-user",
        voicelink_shared_trunk_password="shared-secret")
    assert _resolve_trunk_credentials(
        {"username": "shared-user", "registration_password": "********"},
        settings, local_username="local-user", local_password="local-secret",
        exact=False) == ("shared-user", "shared-secret", "super_admin")
    assert _resolve_trunk_credentials(
        {"username": "different-user"}, settings,
        local_username="local-user", local_password="local-secret",
        exact=False) is None
    assert _resolve_trunk_credentials(
        {"auth_username": "provider-user", "sip_password": "provider-secret"},
        settings, local_username="local-user", local_password="local-secret",
        exact=False) == ("provider-user", "provider-secret", "provider")


def test_voicelink_phone_payload_is_digits_only():
    from app.services.telephony_account import _indian_phone_forms
    from app.services.telephony_policy import TelephonyError

    # Screenshot regression: the customer entered +91XXXXXXXXXX and
    # VoiceLink rejected the '+' because its phone rule accepts digits only.
    assert _indian_phone_forms("+918114402203") == (
        "918114402203", "+918114402203")
    assert _indian_phone_forms("81144 02203") == (
        "918114402203", "+918114402203")
    assert _indian_phone_forms("08114402203") == (
        "918114402203", "+918114402203")
    assert _indian_phone_forms("") == ("", "")
    with pytest.raises(TelephonyError):
        _indian_phone_forms("12345")


def test_kyc_step1_payload_and_safe_provider_validation():
    from types import SimpleNamespace

    from app.services.telephony_account import _kyc_register_fields
    from app.services.voicelink_client import (
        _safe_error_shape, _safe_validation_message)

    body = SimpleNamespace(
        account_type="individual", full_name="Fixture Person",
        phone="+919876543210", billing_address="Synthetic test address",
        state="Kerala", city="Kochi", pincode="682001", business_name="")
    assert _kyc_register_fields(body, "customer@example.test") == {
        "term_and_condition": "1",
        "account_type": "individual",
        "full_name": "Fixture Person",
        "phone": "919876543210",
        "billing_address": "Synthetic test address",
        "state": "Kerala",
        "city": "Kochi",
        "pincode": "682001",
        "email": "customer@example.test",
    }

    detail = _safe_validation_message({"errors": {
        "full_name": [
            "The full name field is invalid for ABCDE1234F, "
            "+919876543210 and customer@example.test."],
        "unknown_secret": ["must not be returned"],
    }})
    assert detail.startswith("Full legal name: The full name field is invalid")
    assert "ABCDE1234F" not in detail
    assert "919876543210" not in detail
    assert "customer@example.test" not in detail
    assert "must not be returned" not in detail

    # Current VoiceLink portal prerequisites may be returned either as a
    # field error or only as a top-level business-rule message. Expose the
    # missing step in our wording, but never the raw provider value/text.
    assert _safe_validation_message({"errors": {
        "live_photo": ["The live photo field is required."]}}).startswith(
            "Live photo:")
    reason = _safe_validation_message({
        "message": "Please verify email for customer@example.test first."})
    assert "Email verification" in reason
    assert "customer@example.test" not in reason
    assert "already verified" in _safe_validation_message({
        "message": "Email already verified."})
    shape = _safe_error_shape({
        "status": False, "message": "do not log this value",
        "errors": {"mystery_field": ["also do not log this value"]}})
    assert "mystery_field" in shape
    assert "do not log this value" not in shape
    assert "also do not log this value" not in shape


def test_kyc_state_distinguishes_ready_submitted_and_verified():
    from types import SimpleNamespace

    from app.services.telephony_account import (
        _safe_kyc_completion_shape, kyc_state)

    settings = SimpleNamespace(
        kyc_finalize_verified=False, voicelink_kyc_terms_url="")
    raw = {
        "account_type": "individual", "is_complete": False,
        "kyc_status": 0, "current_step": "aadhaar",
        "pan_verified": True, "aadhaar_verified": True,
        "documents": {
            "pan": {"uploaded": True}, "aadhaar": {"uploaded": True}},
        "live_photo_verified": False,
        "email": "customer@example.test",
        "full_name": "Fixture Person",
    }

    ready = kyc_state(raw, settings)
    assert ready["ready_for_submission"] is True
    assert ready["provider_complete"] is False
    # A rejected final-submit leaves the account here; calling this
    # "submitted" made the shop lock look like a purchase bug.
    assert ready["status"] == "ready_to_submit"

    submitted = kyc_state({**raw, "is_complete": True}, settings)
    assert submitted["provider_complete"] is True
    assert submitted["status"] == "submitted"

    verified = kyc_state({
        **raw, "is_complete": True, "kyc_status": 1,
        "current_step": "complete"}, settings)
    assert verified["status"] == "verified"

    # Laravel serializers may encode the same final state as ints/strings
    # rather than JSON booleans and the literal step "complete".
    scalar_verified = kyc_state({
        **raw, "is_complete": 1, "kyc_status": "verified",
        "current_step": "completed", "pan_verified": 1,
        "aadhaar_verified": "true", "documents": {
            "pan": {"uploaded": 1}, "aadhaar": {"uploaded": "1"}}},
        settings)
    assert scalar_verified["status"] == "verified"
    assert scalar_verified["step"] == "complete"

    # Live regression from the VoiceLink reseller dashboard: its client
    # record showed KYC Verified while the customer's dashboard stayed
    # locked. An explicit verified signal on that exact client row is
    # authoritative when the status endpoint corroborates both documents.
    client_verified = kyc_state(
        raw, settings,
        {"is_verified": 1, "email": "customer@example.test",
         "username": "private-username"})
    assert client_verified["status"] == "verified"
    assert client_verified["provider_complete"] is True
    assert client_verified["step"] == "complete"

    shape = _safe_kyc_completion_shape(
        raw, ready,
        {"is_verified": 0, "kyc_status": "pending",
         "email": "customer@example.test", "username": "private-username"})
    assert "is_complete" in shape and "live_photo_verified" in shape
    assert "is_verified" in shape and "kyc_status" in shape
    assert "customer@example.test" not in shape
    assert "private-username" not in shape
    assert "Fixture Person" not in shape


def test_digilocker_redirect_allowlist_includes_official_hosts():
    from types import SimpleNamespace

    from app.services.telephony_account import validate_digilocker_redirect

    settings = SimpleNamespace(voicelink_kyc_redirect_hosts=[])
    for url in (
        "https://api.digitallocker.gov.in/public/oauth2/1/authorize?state=x",
        "https://digilocker.meripehchaan.gov.in/public/oauth2/1/authorize",
        "https://www.digilocker.gov.in/signin",
        "https://digilocker.gov.in/signin",
    ):
        assert validate_digilocker_redirect(url, settings) == url

    custom = SimpleNamespace(
        voicelink_kyc_redirect_hosts=["id.example.com"])
    assert validate_digilocker_redirect(
        "https://id.example.com/verify", custom) == (
            "https://id.example.com/verify")

    for url in (
        "https://api.digitallocker.gov.in.evil.test/authorize",
        "http://api.digitallocker.gov.in/public/oauth2/1/authorize",
        "https://user:pass@api.digitallocker.gov.in/authorize",
        "https://api.digitallocker.gov.in:8443/authorize",
    ):
        with pytest.raises(policy.TelephonyError):
            validate_digilocker_redirect(url, settings)

    with pytest.raises(policy.TelephonyError) as exc:
        validate_digilocker_redirect(
            "https://idp.example.com/authorize?state=do-not-show", settings)
    assert "idp.example.com" in str(exc.value)
    assert "do-not-show" not in str(exc.value)


def test_manual_number_update_body_and_effective_concurrency():
    from app.routes.calls_routes import _effective_concurrency

    body = ManualNumberUpdateBody(channels=2, dial_prefix="45454")
    assert body.channels == 2
    with pytest.raises(ValidationError):
        ManualNumberUpdateBody(channels=0)
    with pytest.raises(ValidationError):
        ManualNumberUpdateBody(user_id="another-tenant")
    with pytest.raises(ValidationError):
        ManualNumberUpdateBody(sip_password="never-accept-this")

    # An assigned DID's purchased channels are authoritative; the old
    # separate plan-lines value must not shrink them a second time.
    assert _effective_concurrency(5, 1, 3) == 3
    assert _effective_concurrency(5, 4, 2) == 2
    assert _effective_concurrency(1, 4, 2) == 1
    # Legacy shared-trunk calls still use the workspace channel entitlement.
    assert _effective_concurrency(3, 4, None) == 3
    assert _effective_concurrency(5, 2, None) == 2


def test_plan_channels_pricing_and_purchase_body():
    from app.routes.subscription_routes import PurchaseBody
    from app.services import subscription_service as subscriptions

    # Channels granted by plan selection, VoiceLink allocation, a purchased
    # DID, or a manual DID are one entitlement—the highest grant wins.
    assert subscriptions.effective_channel_count(1, 0, 0) == 1
    assert subscriptions.effective_channel_count(1, 2, 0) == 2
    assert subscriptions.effective_channel_count(1, 0, 3) == 3
    assert subscriptions.effective_channel_count(
        1, 0, 0, phone_channels=2) == 2

    # The Super Admin's per-extra-channel monthly price replaces the former
    # extra-line price: two channels beyond the included first cost 2 x ₹250.
    assert subscriptions.price_selection(
        capacity_tier=None, extra_channels=2, telephony=False,
        kb_packs=[], channel_price=250, telephony_rent=0) == 500

    # Regression: plan_tiers._plan_dict() returns `price_per_month`, while
    # the old pricing code looked only for `pricePerMonth` and therefore
    # stored purchased agent/KB plans with monthly_total=0.
    assert subscriptions.price_selection(
        capacity_tier={"price_per_month": 4999}, extra_channels=0,
        telephony=False, kb_packs=[{"price_per_month": 1000}],
        channel_price=250, telephony_rent=0) == 5999

    body = PurchaseBody(channels=3)
    assert body.channels == 3
    with pytest.raises(ValidationError):
        PurchaseBody(channels=0)

    # Same-number upgrades charge only capacity above every existing grant,
    # prorated to the current subscription cycle.
    from datetime import datetime, timezone

    assert subscriptions.billable_channel_increase(2, 5) == 3
    assert subscriptions.billable_channel_increase(5, 3) == 0
    due, days = subscriptions.prorated_charge(
        300, "2026-11-15T00:00:00Z",
        now=datetime(2026, 10, 31, tzinfo=timezone.utc))
    assert (due, days) == (150.0, 15)

    from app.models.telephony_models import ChannelUpgradeBody

    upgrade = ChannelUpgradeBody(
        target_channels=3, accept_charge=True, expected_due_now=100,
        expected_monthly_increment=250)
    assert upgrade.target_channels == 3
    with pytest.raises(ValidationError):
        ChannelUpgradeBody(
            target_channels=1, accept_charge=True, expected_due_now=0,
            expected_monthly_increment=0)
    with pytest.raises(ValidationError):
        ChannelUpgradeBody(
            target_channels=3, accept_charge=True, expected_due_now=0,
            expected_monthly_increment=0, sip_trunk_id="ST_hidden")


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
    shared_enc, shared_masked = encrypt_secret("shared-trunk-secret")
    settings = settings_svc._settings_from_record({
        "default_sip_trunk_id": "ST_default",
        "voicelink_api_base_url": "https://app.voicelink.co.in/api/v1",
        "voicelink_api_token_enc": token_enc,
        "voicelink_api_token_masked": token_masked,
        "voicelink_username": "reseller@example.com",
        "voicelink_password_enc": password_enc,
        "voicelink_password_masked": password_masked,
        "voicelink_shared_trunk_username": "shared-user",
        "voicelink_shared_trunk_password_enc": shared_enc,
        "voicelink_shared_trunk_password_masked": shared_masked,
        "voicelink_sip_host": "sip.voicelink.co.in",
        "voicelink_sip_port": 3300,
        "voicelink_tech_prefix": "45454",
        "voicelink_transport_type": 1,
        "voicelink_audio_formats": "alaw,ulaw",
        "voicelink_inbound_allowed_addresses": (
            "203.0.113.10,198.51.100.0/24"),
        "voicelink_wallet_bypass": True,
        "voicelink_kyc_terms_url": "",
        "voicelink_kyc_redirect_hosts": "id.example.com",
        "kyc_finalize_verified": False,
        "livekit_sip_host": "c{client_id}.sip.example.com",
        "livekit_sip_port": 5060,
        "frontend_url": "https://agents.example.com",
        "public_api_url": "",
        "updated_at": "2026-10-29T00:00:00",
    })

    assert settings.voicelink_api_token == "vl-token-1234567890"
    assert settings.voicelink_password == "vl-password-9876"
    assert settings.voicelink_shared_trunk_password == "shared-trunk-secret"
    assert settings.livekit_sip_host == "c{client_id}.sip.example.com"
    assert settings.voicelink_inbound_allowed_addresses == [
        "203.0.113.10/32", "198.51.100.0/24"]
    assert settings_svc.resolve_livekit_sip_host(
        settings.livekit_sip_host, "42") == "c42.sip.example.com"
    view = settings_svc.public_view(settings)
    rendered = repr(view)
    assert view["configured"] is True
    assert view["voicelink_api_token_configured"] is True
    assert view["voicelink_password_configured"] is True
    assert view["voicelink_shared_trunk_password_configured"] is True
    for forbidden in ("vl-token-1234567890", "vl-password-9876",
                      "shared-trunk-secret", token_enc, password_enc,
                      shared_enc):
        assert forbidden not in rendered


def test_telephony_settings_patch_validates_and_encrypts(telephony_crypto):
    from app.services import telephony_settings as settings_svc
    from app.services.crypto import decrypt_secret

    with pytest.raises(ValidationError):
        TelephonySettingsBody(sip_password="not-a-setting")

    patch = settings_svc._normalize_patch({
        "voicelink_api_base_url": "https://app.voicelink.co.in/api/v1/",
        "voicelink_api_token": "rotated-token-4321",
        "voicelink_shared_trunk_username": "shared-user",
        "voicelink_shared_trunk_password": "shared-secret-8765",
        "voicelink_audio_formats": ["ALAW", "ulaw", "alaw"],
        "voicelink_inbound_allowed_addresses": [
            "203.0.113.10", "198.51.100.37/24", "203.0.113.10/32"],
        "voicelink_kyc_redirect_hosts": ["ID.Example.COM"],
        "livekit_sip_host": "SIP.Example.com",
    })
    assert patch["voicelink_api_base_url"] == (
        "https://app.voicelink.co.in/api/v1")
    assert decrypt_secret(patch["voicelink_api_token_enc"]) == (
        "rotated-token-4321")
    assert decrypt_secret(
        patch["voicelink_shared_trunk_password_enc"]) == "shared-secret-8765"
    assert "rotated-token-4321" not in repr(patch)
    assert "shared-secret-8765" not in repr(patch)
    assert patch["voicelink_audio_formats"] == "alaw,ulaw"
    assert patch["voicelink_inbound_allowed_addresses"] == (
        "203.0.113.10/32,198.51.100.0/24")
    assert patch["voicelink_kyc_redirect_hosts"] == "id.example.com"
    assert patch["livekit_sip_host"] == "sip.example.com"

    alias_patch = settings_svc._normalize_patch({
        "livekit_sip_host": "C{CLIENT_ID}.SIP.Example.com",
    })
    assert alias_patch["livekit_sip_host"] == "c{client_id}.sip.example.com"
    assert settings_svc.resolve_livekit_sip_host(
        alias_patch["livekit_sip_host"], "42") == "c42.sip.example.com"
    with pytest.raises(policy.TelephonyError):
        settings_svc._normalize_patch({
            "livekit_sip_host": "c{phone_id}.sip.example.com"})

    with pytest.raises(policy.TelephonyError):
        settings_svc._normalize_patch({
            "voicelink_api_base_url": "http://provider.example.com/api"})
    with pytest.raises(policy.TelephonyError):
        settings_svc._normalize_patch({"voicelink_tech_prefix": "45A54"})
    with pytest.raises(policy.TelephonyError):
        settings_svc._normalize_patch({
            "livekit_sip_host": "https://sip.example.com:5060"})
    with pytest.raises(policy.TelephonyError):
        settings_svc._normalize_patch({
            "voicelink_inbound_allowed_addresses": ["0.0.0.0/0"]})
    with pytest.raises(policy.TelephonyError):
        settings_svc._normalize_patch({
            "voicelink_inbound_allowed_addresses": ["sip.example.com"]})

    cleared = settings_svc._normalize_patch({
        "clear_voicelink_api_token": True,
        "voicelink_api_token": "must-not-win-over-clear",
    })
    assert cleared["voicelink_api_token_enc"] == ""
    assert cleared["voicelink_api_token_masked"] == ""


def test_inbound_trunk_reconciliation_clears_voicelink_digest_auth():
    from types import SimpleNamespace

    from app.telephony import trunks

    legacy = SimpleNamespace(
        numbers=["+919876543210"], allowed_addresses=[],
        auth_username="trunk_example", auth_password="must-be-cleared")
    assert trunks._inbound_reconcile_update(
        legacy, "+919876543210", ["203.0.113.10/32"]) == {
            "numbers": ["+919876543210", "919876543210"],
            "allowed_addresses": ["203.0.113.10/32"],
            "auth_username": "",
            "auth_password": "",
        }

    reconciled = SimpleNamespace(
        numbers=["+919876543210", "919876543210"],
        allowed_addresses=["203.0.113.10/32"],
        auth_username="", auth_password="")
    assert trunks._inbound_reconcile_update(
        reconciled, "+919876543210", ["203.0.113.10/32"]) is None


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
        "phone_channels": 1,
    }


async def test_assigned_did_channels_override_legacy_one_line_plan(normal_user):
    from app.services import subscription_service as subscriptions

    _, user = normal_user
    phone = await _active_phone(user["id"])
    phone = await repo.update_phone_number(
        phone["id"], {"channels": 2}) or phone

    entitlement = await subscriptions.get_subscription(user["id"])
    assert entitlement["plan_channels"] == 1
    assert entitlement["number_channels"] == 2
    assert entitlement["channels"] == 2

    # The exact regression from the UI: DID has 2 channels, old plan row has
    # 1, and saving the agent at max_concurrency=2 must now be allowed.
    await subscriptions.ensure_concurrency_allowed(
        user["id"], 2, phone_number_id=phone["id"])
    with pytest.raises(subscriptions.SubscriptionError):
        await subscriptions.ensure_concurrency_allowed(
            user["id"], 3, phone_number_id=phone["id"])

    # Plan-first flow: selecting three total channels on Billing stores that
    # target for the later KYC/DID purchase and raises the workspace cap.
    purchased = await subscriptions.purchase(user["id"], channels=3)
    assert purchased["plan_channels"] == 3
    assert purchased["channels"] == 3
    await subscriptions.ensure_concurrency_allowed(user["id"], 3)


async def test_super_admin_subscription_crud_reflects_in_customer_view(
        normal_user):
    from app.services import subscription_service as subscriptions

    _, user = normal_user
    created = await subscriptions.admin_create_subscription(
        user["id"], status="active", agent_limit=3, channels=2,
        telephony_rented=True, kb_extra_chars=10_000, kb_extra_faqs=20,
        monthly_total=4999, renews_at="2026-11-19")
    assert created["agent_limit"] == 3
    assert created["plan_channels"] == 2
    assert created["channels"] == 2
    assert created["kb_char_limit"] == 30_000
    assert created["kb_faq_limit"] == 70
    assert created["monthly_total"] == 4999
    assert created["renews_at"].startswith("2026-11-19")

    # The Super Admin Edit form loads this exact stored row through the
    # single-subscription endpoint helper before allowing edits.
    from app.admin.plan_routes import _subscription_item_for_user

    item = await _subscription_item_for_user(user["id"])
    assert item is not None
    assert item["agent_limit"] == 3
    assert item["plan_channels"] == 2
    assert item["kb_extra_chars"] == 10_000
    assert item["kb_extra_faqs"] == 20
    assert item["monthly_total"] == 4999

    with pytest.raises(subscriptions.SubscriptionError):
        await subscriptions.admin_create_subscription(user["id"])

    updated = await subscriptions.admin_update_subscription(
        user["id"], status="active", agent_limit=5, channels=4,
        monthly_total=5999)
    assert updated is not None
    assert updated["agent_limit"] == 5
    assert updated["plan_channels"] == 4
    assert updated["channels"] == 4
    assert updated["monthly_total"] == 5999

    # A blank renewal date in an update preserves the stored DB date.
    updated = await subscriptions.admin_update_subscription(
        user["id"], renews_at="")
    assert updated is not None
    assert updated["renews_at"].startswith("2026-11-19")

    assert await subscriptions.admin_delete_subscription(user["id"]) is True
    deleted = await subscriptions.get_subscription(user["id"])
    assert deleted["status"] == "inactive"
    assert deleted["agent_limit"] == 0


async def test_subscription_purchase_stores_plan_and_kb_amounts(normal_user):
    from app.db import get_prisma
    from app.services import subscription_service as subscriptions

    _, user = normal_user
    db = get_prisma()
    topped_up = await repo.recharge(user["id"], 9000)
    assert topped_up["balance"] == 9000
    capacity = await db.plantier.create(data={
        "kind": "capacity", "label": f"3 agents {user['id']}",
        "units": 3, "faqs": 0, "pricePerMonth": 4999,
        "enabled": True, "sortOrder": 0, "createdAt": ""})
    pack = await db.plantier.create(data={
        "kind": "kb_pack", "label": f"KB {user['id']}",
        "units": 10_000, "faqs": 20, "pricePerMonth": 1000,
        "enabled": True, "sortOrder": 0, "createdAt": ""})

    entitlement = await subscriptions.purchase(
        user["id"], capacity_tier_id=capacity.id,
        kb_pack_ids=[pack.id], channels=1)
    assert entitlement["agent_limit"] == 3
    assert entitlement["kb_char_limit"] == 30_000
    assert entitlement["kb_faq_limit"] == 70
    # This is the screenshot regression: purchased plans must not be stored
    # as ₹0/month merely because _plan_dict uses snake_case price keys.
    assert entitlement["monthly_total"] == 5999
    wallet = await repo.get_wallet(user["id"])
    assert wallet["balance"] == 3001


async def test_paid_same_number_channel_upgrade_updates_did_and_plan(
        normal_user, monkeypatch):
    from app.db import get_prisma
    from app.services import subscription_service as subscriptions
    from app.services import telephony_channels as channel_service

    _, user = normal_user
    await get_prisma().user.update(
        where={"id": user["id"]}, data={"walletBalance": 1000})
    account = await repo.create_account(user["id"], {
        "client_id": f"client-{user['id']}", "email": user["email"],
        "name": "Channel test", "channels_allocated": 1})
    phone = await repo.create_phone_number({
        "user_id": user["id"], "voice_link_account_id": account["id"],
        "number": "+919876543210", "status": "active",
        "source": "voicelink", "channels": 1,
        "livekit_outbound_trunk_id": "ST_channel_test"})
    await subscriptions.admin_create_subscription(
        user["id"], status="active", agent_limit=3, channels=1,
        monthly_total=100)

    monkeypatch.setattr(channel_service, "_channel_price", lambda: 250.0)
    provider_targets = []

    async def fake_ensure_provider(account_arg, target):
        provider_targets.append(target)
        await repo.update_account(
            account_arg["id"], {"channels_allocated": target})
        return 1

    monkeypatch.setattr(
        channel_service, "_ensure_provider_channels", fake_ensure_provider)

    quote = await channel_service.quote_channel_upgrade(
        user["id"], phone["id"], 3)
    assert quote["added_phone_channels"] == 2
    assert quote["billable_added_channels"] == 2
    assert quote["monthly_increment"] == 500
    assert 490 < quote["due_now"] <= 500

    out = await channel_service.upgrade_phone_channels(
        user["id"], phone["id"], target_channels=3, accept_charge=True,
        expected_due_now=quote["due_now"],
        expected_monthly_increment=quote["monthly_increment"])
    assert provider_targets == [3]
    assert out["phone_number"]["channels"] == 3
    assert out["entitlement"]["plan_channels"] == 3
    assert out["entitlement"]["channels"] == 3
    assert out["entitlement"]["monthly_total"] == 600
    assert out["charged_now"] == quote["due_now"]
    assert out["wallet"]["balance"] == round(1000 - quote["due_now"], 2)
    refreshed_account = await repo.get_account(account["id"])
    assert refreshed_account["channels_allocated"] == 3


async def test_super_admin_can_edit_and_delete_only_manual_numbers(normal_user):
    from app.services import telephony_provisioning as provisioning

    _, user = normal_user
    phone = await _active_phone(user["id"])
    agent = await repo.create_agent(user["id"], {
        "name": "Manual number owner",
        "purpose": "outbound",
        "phone_number_id": phone["id"],
    })

    updated = await provisioning.update_manual_number(phone["id"], {
        "channels": 2,
        "dial_prefix": "45454",
        "expires_at": "2027-10-31",
    })
    assert updated["channels"] == 2
    assert updated["status"] == "active"
    assert updated["provisioning_step"] == "manual_ready"
    assert updated["expires_at"] == "2027-10-31"

    with pytest.raises(policy.TelephonyError):
        await provisioning.update_manual_number(
            phone["id"], {"dial_prefix": "45A54"})

    purchased = await repo.create_phone_number({
        "user_id": user["id"],
        "number": "+919876543210",
        "status": "active",
        "source": "voicelink",
        "livekit_outbound_trunk_id": "ST_purchased",
    })
    with pytest.raises(policy.TelephonyError) as exc:
        await provisioning.update_manual_number(
            purchased["id"], {"channels": 2})
    assert exc.value.status_code == 409
    with pytest.raises(policy.TelephonyError) as exc:
        await provisioning.delete_manual_number(purchased["id"])
    assert exc.value.status_code == 409

    deleted = await provisioning.delete_manual_number(phone["id"])
    assert deleted["number"] == phone["number"]
    assert deleted["unassigned_agent_ids"] == [agent["id"]]
    assert await repo.get_phone_number(phone["id"], user["id"]) is None
    refreshed_agent = await repo.get_agent(agent["id"], user["id"])
    assert refreshed_agent["phone_number_id"] is None


async def test_manual_number_delete_is_blocked_during_an_active_call(normal_user):
    from app.services import telephony_provisioning as provisioning

    _, user = normal_user
    phone = await _active_phone(user["id"])
    agent = await repo.create_agent(user["id"], {
        "name": "Busy manual agent",
        "purpose": "outbound",
        "phone_number_id": phone["id"],
    })
    await repo.create_call({
        "user_id": user["id"], "agent_id": agent["id"], "mode": "sip",
        "room": "manual-delete-active", "status": "in-progress",
    })

    with pytest.raises(policy.TelephonyError) as exc:
        await provisioning.delete_manual_number(phone["id"])
    assert exc.value.status_code == 409
    assert "active call" in str(exc.value)


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
            "voicelink_shared_trunk_username": "shared-user",
            "voicelink_shared_trunk_password": "panel-shared-secret-445566",
            "voicelink_sip_host": "sip.voicelink.co.in",
            "voicelink_sip_port": 3300,
            "livekit_sip_host": "sip.example.com",
            "livekit_sip_port": 5060,
            "frontend_url": "https://agents.example.com",
        })
    assert resp.status_code == 200, resp.text
    assert "panel-token-998877" not in resp.text
    assert "panel-password-112233" not in resp.text
    assert "panel-shared-secret-445566" not in resp.text
    settings = resp.json()["settings"]
    assert settings["source"] == "super_admin"
    assert settings["configured"] is True
    assert settings["voicelink_api_token_configured"] is True
    assert settings["voicelink_shared_trunk_password_configured"] is True

    stored = await repo.get_telephony_config(include_secrets=True)
    assert stored is not None
    assert stored["voicelink_api_token_enc"] != "panel-token-998877"
    assert decrypt_secret(stored["voicelink_api_token_enc"]) == (
        "panel-token-998877")
    assert decrypt_secret(stored["voicelink_password_enc"]) == (
        "panel-password-112233")
    assert decrypt_secret(
        stored["voicelink_shared_trunk_password_enc"]) == (
            "panel-shared-secret-445566")
