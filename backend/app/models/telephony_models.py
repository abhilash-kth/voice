"""Request bodies for the self-service telephony marketplace.

Security rules baked into these models:
* No body accepts a VoiceLink ``client_id``, a LiveKit trunk id, or a SIP
  password from a customer. The account is derived from the logged-in user
  and trunks are derived from the assigned PhoneNumber row server-side.
* Identity fields (PAN/GST/OTP) are forwarded to VoiceLink in memory only;
  they are never persisted or logged by the service layer.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class AccountSetupBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field("", max_length=150)
    phone: str = Field("", max_length=20)


class KycActionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal[
        "register", "pan", "aadhaar", "gst", "submit",
        "verify_email", "resend_email",
    ]
    # register
    accept_terms: bool = False
    account_type: Optional[Literal["individual", "business"]] = None
    full_name: str = Field("", max_length=150)
    business_name: str = Field("", max_length=150)
    phone: str = Field("", max_length=20)
    billing_address: str = Field("", max_length=500)
    state: str = Field("", max_length=100)
    city: str = Field("", max_length=100)
    pincode: str = Field("", max_length=6)
    # pan / gst / email OTP — forwarded in memory, never stored
    pan_number: str = Field("", max_length=10)
    pan_holder_name: str = Field("", max_length=150)
    gst_number: str = Field("", max_length=15)
    otp: str = Field("", max_length=6)


class QuoteBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    did_id: str = Field(..., min_length=1, max_length=32)
    number: str = Field(..., min_length=3, max_length=20)
    months: int = Field(1, ge=1, le=12)
    channels: int = Field(1, ge=1, le=20)
    idempotency_key: str = Field(..., min_length=8, max_length=80)


class ConfirmBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # VoiceLink purchase-confirm makes auto-renew mandatory; the customer
    # must explicitly accept that before any money moves.
    accept_auto_renew: bool = False


class AllocateWalletBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    amount: float = Field(..., gt=0, le=1_000_000)
    description: str = Field("", max_length=200)


class ChannelUpgradeQuoteBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_channels: int = Field(..., ge=2, le=100)


class ChannelUpgradeBody(ChannelUpgradeQuoteBody):
    # The customer must confirm the exact quote shown to them; the backend
    # recalculates it and refuses if pricing/capacity changed meanwhile.
    accept_charge: bool = False
    expected_due_now: float = Field(..., ge=0, le=10_000_000)
    expected_monthly_increment: float = Field(..., ge=0, le=10_000_000)


class TelephonyStatusBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["active", "suspended"]


class ManualNumberBody(BaseModel):
    """Super Admin: register an already-provisioned DID for a customer
    (e.g. the original single-tenant VoiceLink number + its LiveKit trunk)."""
    model_config = ConfigDict(extra="forbid")
    user_id: str = Field(..., min_length=1, max_length=64)
    number: str = Field(..., min_length=3, max_length=20)
    livekit_outbound_trunk_id: str = Field("", max_length=64)
    livekit_inbound_trunk_id: str = Field("", max_length=64)
    dial_prefix: str = Field("", max_length=20)
    channels: int = Field(1, ge=1, le=100)
    expires_at: str = Field("", max_length=40)


class ManualNumberUpdateBody(BaseModel):
    """Super Admin: edit a manually registered DID's local routing record.

    Ownership is intentionally immutable here; moving a number between
    customers must be done by deleting/re-registering it so assignments and
    provider routing cannot silently cross tenants.
    """
    model_config = ConfigDict(extra="forbid")
    number: Optional[str] = Field(default=None, min_length=3, max_length=20)
    livekit_outbound_trunk_id: Optional[str] = Field(
        default=None, max_length=64)
    livekit_inbound_trunk_id: Optional[str] = Field(
        default=None, max_length=64)
    dial_prefix: Optional[str] = Field(default=None, max_length=20)
    channels: Optional[int] = Field(default=None, ge=1, le=100)
    expires_at: Optional[str] = Field(default=None, max_length=40)


class TelephonySettingsBody(BaseModel):
    """Super Admin telephony settings.

    Secret fields are write-only: omit them or send "" to keep the stored
    value; send a non-empty value to rotate; use the matching clear flag to
    remove it. Responses never return plaintext or ciphertext.
    """
    model_config = ConfigDict(extra="forbid")

    default_sip_trunk_id: Optional[str] = Field(default=None, max_length=64)
    voicelink_api_base_url: Optional[str] = Field(default=None, max_length=300)
    voicelink_api_token: Optional[str] = Field(default=None, max_length=4096)
    clear_voicelink_api_token: bool = False
    voicelink_username: Optional[str] = Field(default=None, max_length=200)
    voicelink_password: Optional[str] = Field(default=None, max_length=1024)
    clear_voicelink_password: bool = False
    voicelink_sip_host: Optional[str] = Field(default=None, max_length=253)
    voicelink_sip_port: Optional[int] = Field(default=None, ge=1, le=65535)
    voicelink_tech_prefix: Optional[str] = Field(default=None, max_length=20)
    voicelink_transport_type: Optional[int] = Field(default=None, ge=1, le=10)
    voicelink_audio_formats: Optional[list[str]] = Field(default=None, max_length=10)
    voicelink_wallet_bypass: Optional[bool] = None
    voicelink_kyc_terms_url: Optional[str] = Field(default=None, max_length=1000)
    voicelink_kyc_redirect_hosts: Optional[list[str]] = Field(default=None, max_length=20)
    kyc_finalize_verified: Optional[bool] = None
    livekit_sip_host: Optional[str] = Field(default=None, max_length=253)
    livekit_sip_port: Optional[int] = Field(default=None, ge=1, le=65535)
    frontend_url: Optional[str] = Field(default=None, max_length=500)
    public_api_url: Optional[str] = Field(default=None, max_length=500)
