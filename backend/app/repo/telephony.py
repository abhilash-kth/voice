"""Telephony marketplace records: VoiceLink accounts, phone numbers, and
durable purchase intents.

Public dicts NEVER include the SIP password ciphertext. Internal callers
that must decrypt it (provisioning only) pass ``include_secret=True``.
"""
from __future__ import annotations

from typing import Any, Optional

from ..db import get_prisma
from .agents import _agent_dict
from .common import _dump, _load_dict, _ts


# ---------------------------------------------------------------------------
# VoiceLink accounts (one hidden provider client per SaaS user)
# ---------------------------------------------------------------------------
def _account_dict(a: Any) -> dict:
    return {
        "id": a.id,
        "user_id": a.userId,
        "provider_reseller_id": a.providerResellerId or "",
        "client_id": a.clientId,
        "username": a.username or "",
        "email": a.email or "",
        "name": a.name or "",
        "phone": a.phone or "",
        "status": a.status or "active",
        "kyc_status": a.kycStatus or "not_started",
        "kyc_step": a.kycStep or "register",
        "kyc_meta": _load_dict(a.kycMeta),
        "wallet_balance": float(a.walletBalance or 0),
        "channels_allocated": int(a.channelsAllocated or 0),
        "channels_available": int(a.channelsAvailable or 0),
        "last_error": a.lastError or "",
        "last_synced_at": a.lastSyncedAt or "",
        "created_at": a.createdAt or "",
        "updated_at": a.updatedAt or "",
    }


async def get_account_by_user(user_id: str) -> Optional[dict]:
    a = await get_prisma().voicelinkaccount.find_unique(where={"userId": user_id})
    return _account_dict(a) if a else None


async def get_account(account_id: str) -> Optional[dict]:
    a = await get_prisma().voicelinkaccount.find_unique(where={"id": account_id})
    return _account_dict(a) if a else None


async def get_account_by_client(client_id: str) -> Optional[dict]:
    a = await get_prisma().voicelinkaccount.find_unique(
        where={"clientId": str(client_id)})
    return _account_dict(a) if a else None


async def create_account(user_id: str, data: dict) -> dict:
    now = _ts()
    a = await get_prisma().voicelinkaccount.create(data={
        "userId": user_id,
        "providerResellerId": str(data.get("provider_reseller_id") or ""),
        "clientId": str(data["client_id"]),
        "username": data.get("username") or "",
        "email": data.get("email") or "",
        "name": data.get("name") or "",
        "phone": data.get("phone") or "",
        "status": data.get("status") or "active",
        "channelsAllocated": int(data.get("channels_allocated") or 0),
        "createdAt": now, "updatedAt": now,
    })
    return _account_dict(a)


_ACCOUNT_MAP = {
    "provider_reseller_id": "providerResellerId", "username": "username",
    "email": "email", "name": "name", "phone": "phone", "status": "status",
    "kyc_status": "kycStatus", "kyc_step": "kycStep",
    "wallet_balance": "walletBalance",
    "channels_allocated": "channelsAllocated",
    "channels_available": "channelsAvailable",
    "last_error": "lastError", "last_synced_at": "lastSyncedAt",
}


async def update_account(account_id: str, patch: dict) -> Optional[dict]:
    data = {_ACCOUNT_MAP[k]: v for k, v in patch.items() if k in _ACCOUNT_MAP}
    if "kyc_meta" in patch:
        data["kycMeta"] = _dump(patch["kyc_meta"])
    data["updatedAt"] = _ts()
    try:
        a = await get_prisma().voicelinkaccount.update(
            where={"id": account_id}, data=data)
    except Exception:
        return None
    return _account_dict(a)


async def list_accounts() -> list[dict]:
    rows = await get_prisma().voicelinkaccount.find_many(
        order={"updatedAt": "desc"}, take=500)
    return [_account_dict(a) for a in rows]


# ---------------------------------------------------------------------------
# Phone numbers
# ---------------------------------------------------------------------------
def _phone_dict(p: Any, include_secret: bool = False) -> dict:
    out = {
        "id": p.id,
        "user_id": p.userId,
        "voice_link_account_id": p.voiceLinkAccountId or None,
        "number": p.number,
        "country_code": p.countryCode or "+91",
        "status": p.status or "provisioning",
        "provisioning_step": p.provisioningStep or "",
        "source": p.source or "voicelink",
        "channels": int(p.channels or 1),
        "monthly_rate": float(p.monthlyRate or 0),
        "expires_at": p.expiresAt or "",
        "provider_did_id": p.providerDidId or "",
        "provider_purchase_id": p.providerPurchaseId or "",
        "sip_username": p.sipUsername or "",
        "sip_password_masked": p.sipPasswordMasked or "",
        "has_sip_password": bool(p.sipPasswordEnc),
        "voice_link_trunk_id": p.voiceLinkTrunkId or "",
        "voice_link_routing_id": p.voiceLinkRoutingId or "",
        "livekit_outbound_trunk_id": p.livekitOutboundTrunkId or "",
        "livekit_inbound_trunk_id": p.livekitInboundTrunkId or "",
        "livekit_dispatch_rule_id": p.livekitDispatchRuleId or "",
        "inbound_agent_id": p.inboundAgentId or None,
        "dial_prefix": p.dialPrefix or "",
        "last_error": p.lastError or "",
        "meta": _load_dict(p.meta),
        "created_at": p.createdAt or "",
        "updated_at": p.updatedAt or "",
    }
    if include_secret:
        out["_sip_password_enc"] = p.sipPasswordEnc or ""
    return out


async def list_phone_numbers(user_id: Optional[str] = None) -> list[dict]:
    where = {"userId": user_id} if user_id else {}
    rows = await get_prisma().phonenumber.find_many(
        where=where, order={"createdAt": "desc"}, take=500)
    return [_phone_dict(p) for p in rows]


async def get_phone_number(phone_id: str, user_id: Optional[str] = None,
                           include_secret: bool = False) -> Optional[dict]:
    p = await get_prisma().phonenumber.find_unique(where={"id": phone_id})
    if not p or (user_id and p.userId != user_id):
        return None
    return _phone_dict(p, include_secret=include_secret)


async def get_phone_by_number(number: str) -> Optional[dict]:
    p = await get_prisma().phonenumber.find_unique(where={"number": number})
    return _phone_dict(p) if p else None


async def create_phone_number(data: dict) -> dict:
    now = _ts()
    p = await get_prisma().phonenumber.create(data={
        "userId": data["user_id"],
        "voiceLinkAccountId": data.get("voice_link_account_id") or None,
        "number": data["number"],
        "countryCode": data.get("country_code") or "+91",
        "status": data.get("status") or "provisioning",
        "provisioningStep": data.get("provisioning_step") or "created",
        "source": data.get("source") or "voicelink",
        "channels": int(data.get("channels") or 1),
        "monthlyRate": float(data.get("monthly_rate") or 0),
        "expiresAt": data.get("expires_at") or "",
        "providerDidId": str(data.get("provider_did_id") or ""),
        "providerPurchaseId": str(data.get("provider_purchase_id") or ""),
        "sipUsername": data.get("sip_username") or "",
        "sipPasswordEnc": data.get("sip_password_enc") or "",
        "sipPasswordMasked": data.get("sip_password_masked") or "",
        "livekitOutboundTrunkId": data.get("livekit_outbound_trunk_id") or "",
        "livekitInboundTrunkId": data.get("livekit_inbound_trunk_id") or "",
        "dialPrefix": data.get("dial_prefix") or "",
        "meta": _dump(data.get("meta") or {}),
        "createdAt": now, "updatedAt": now,
    })
    return _phone_dict(p)


_PHONE_MAP = {
    "status": "status", "provisioning_step": "provisioningStep",
    "channels": "channels", "monthly_rate": "monthlyRate",
    "expires_at": "expiresAt", "provider_did_id": "providerDidId",
    "provider_purchase_id": "providerPurchaseId",
    "sip_username": "sipUsername", "sip_password_enc": "sipPasswordEnc",
    "sip_password_masked": "sipPasswordMasked",
    "voice_link_trunk_id": "voiceLinkTrunkId",
    "voice_link_routing_id": "voiceLinkRoutingId",
    "livekit_outbound_trunk_id": "livekitOutboundTrunkId",
    "livekit_inbound_trunk_id": "livekitInboundTrunkId",
    "livekit_dispatch_rule_id": "livekitDispatchRuleId",
    "inbound_agent_id": "inboundAgentId", "dial_prefix": "dialPrefix",
    "last_error": "lastError",
    "voice_link_account_id": "voiceLinkAccountId",
}


async def update_phone_number(phone_id: str, patch: dict) -> Optional[dict]:
    data = {_PHONE_MAP[k]: v for k, v in patch.items() if k in _PHONE_MAP}
    if "meta" in patch:
        data["meta"] = _dump(patch["meta"])
    data["updatedAt"] = _ts()
    try:
        p = await get_prisma().phonenumber.update(
            where={"id": phone_id}, data=data)
    except Exception:
        return None
    return _phone_dict(p)


async def list_agents_for_phone(phone_id: str, user_id: str) -> list[dict]:
    rows = await get_prisma().agent.find_many(
        where={"userId": user_id, "phoneNumberId": phone_id})
    return [_agent_dict(a) for a in rows]


async def find_inbound_agents_for_phone(phone_id: str, user_id: str) -> list[dict]:
    """Agents allowed to receive inbound calls on this number (0 or 1 once
    the agents-route validation has run; >1 means legacy/conflicting data)."""
    rows = await get_prisma().agent.find_many(where={
        "userId": user_id, "phoneNumberId": phone_id,
        "callDirection": {"in": ["inbound", "both"]}, "enabled": True,
    })
    return [_agent_dict(a) for a in rows]


# ---------------------------------------------------------------------------
# Purchase intents
# ---------------------------------------------------------------------------
def _purchase_dict(p: Any) -> dict:
    return {
        "id": p.id,
        "user_id": p.userId,
        "voice_link_account_id": p.voiceLinkAccountId,
        "phone_number_id": p.phoneNumberId or None,
        "provider_did_id": p.providerDidId or "",
        "number": p.number or "",
        "months": int(p.months or 1),
        "channels": int(p.channels or 1),
        "provider_order_id": p.providerOrderId or "",
        "provider_purchase_id": p.providerPurchaseId or "",
        "quote_total": float(p.quoteTotal or 0),
        "monthly_rate": float(p.monthlyRate or 0),
        "customer_charge": float(p.customerCharge or 0),
        "state": p.state or "draft",
        "error": p.error or "",
        "expires_at": p.expiresAt or "",
        "created_at": p.createdAt or "",
        "updated_at": p.updatedAt or "",
    }


async def create_purchase(data: dict) -> dict:
    now = _ts()
    p = await get_prisma().phonepurchase.create(data={
        "userId": data["user_id"],
        "voiceLinkAccountId": data["voice_link_account_id"],
        "providerDidId": str(data.get("provider_did_id") or ""),
        "number": data.get("number") or "",
        "months": int(data.get("months") or 1),
        "channels": int(data.get("channels") or 1),
        "state": data.get("state") or "draft",
        "idempotencyKey": data["idempotency_key"],
        "createdAt": now, "updatedAt": now,
    })
    return _purchase_dict(p)


async def get_purchase(purchase_id: str, user_id: Optional[str] = None) -> Optional[dict]:
    p = await get_prisma().phonepurchase.find_unique(where={"id": purchase_id})
    if not p or (user_id and p.userId != user_id):
        return None
    return _purchase_dict(p)


async def get_purchase_by_idempotency(user_id: str, key: str) -> Optional[dict]:
    p = await get_prisma().phonepurchase.find_first(
        where={"userId": user_id, "idempotencyKey": key})
    return _purchase_dict(p) if p else None


async def latest_purchase(user_id: str) -> Optional[dict]:
    p = await get_prisma().phonepurchase.find_first(
        where={"userId": user_id}, order={"createdAt": "desc"})
    return _purchase_dict(p) if p else None


async def list_purchases(user_id: Optional[str] = None,
                         account_id: Optional[str] = None) -> list[dict]:
    where: dict = {}
    if user_id:
        where["userId"] = user_id
    if account_id:
        where["voiceLinkAccountId"] = account_id
    rows = await get_prisma().phonepurchase.find_many(
        where=where, order={"createdAt": "desc"}, take=500)
    return [_purchase_dict(p) for p in rows]


_PURCHASE_MAP = {
    "phone_number_id": "phoneNumberId", "provider_order_id": "providerOrderId",
    "provider_purchase_id": "providerPurchaseId", "quote_total": "quoteTotal",
    "monthly_rate": "monthlyRate", "customer_charge": "customerCharge",
    "state": "state", "error": "error", "expires_at": "expiresAt",
    "number": "number", "provider_did_id": "providerDidId",
}


async def update_purchase(purchase_id: str, patch: dict) -> Optional[dict]:
    data = {_PURCHASE_MAP[k]: v for k, v in patch.items() if k in _PURCHASE_MAP}
    data["updatedAt"] = _ts()
    try:
        p = await get_prisma().phonepurchase.update(
            where={"id": purchase_id}, data=data)
    except Exception:
        return None
    return _purchase_dict(p)


# ==========================================================================
# TelephonyConfig — single-row Super Admin settings
# ==========================================================================

TELEPHONY_CONFIG_ID = "global"
_CONFIG_FIELDS = {
    "default_sip_trunk_id": "defaultSipTrunkId",
    "voicelink_api_base_url": "voicelinkApiBaseUrl",
    "voicelink_api_token_enc": "voicelinkApiTokenEnc",
    "voicelink_api_token_masked": "voicelinkApiTokenMasked",
    "voicelink_username": "voicelinkUsername",
    "voicelink_password_enc": "voicelinkPasswordEnc",
    "voicelink_password_masked": "voicelinkPasswordMasked",
    "voicelink_sip_host": "voicelinkSipHost",
    "voicelink_sip_port": "voicelinkSipPort",
    "voicelink_tech_prefix": "voicelinkTechPrefix",
    "voicelink_transport_type": "voicelinkTransportType",
    "voicelink_audio_formats": "voicelinkAudioFormats",
    "voicelink_wallet_bypass": "voicelinkWalletBypass",
    "voicelink_kyc_terms_url": "voicelinkKycTermsUrl",
    "voicelink_kyc_redirect_hosts": "voicelinkKycRedirectHosts",
    "kyc_finalize_verified": "kycFinalizeVerified",
    "livekit_sip_host": "livekitSipHost",
    "livekit_sip_port": "livekitSipPort",
    "frontend_url": "frontendUrl",
    "public_api_url": "publicApiUrl",
}


def _config_dict(c, *, include_secrets: bool = False) -> Optional[dict]:
    if not c:
        return None
    out = {
        "id": c.id,
        "default_sip_trunk_id": c.defaultSipTrunkId or "",
        "voicelink_api_base_url": c.voicelinkApiBaseUrl or "",
        "voicelink_api_token_masked": c.voicelinkApiTokenMasked or "",
        "voicelink_username": c.voicelinkUsername or "",
        "voicelink_password_masked": c.voicelinkPasswordMasked or "",
        "voicelink_sip_host": c.voicelinkSipHost or "",
        "voicelink_sip_port": int(c.voicelinkSipPort or 3300),
        "voicelink_tech_prefix": c.voicelinkTechPrefix or "",
        "voicelink_transport_type": int(c.voicelinkTransportType or 1),
        "voicelink_audio_formats": c.voicelinkAudioFormats or "alaw,ulaw",
        "voicelink_wallet_bypass": bool(c.voicelinkWalletBypass),
        "voicelink_kyc_terms_url": c.voicelinkKycTermsUrl or "",
        "voicelink_kyc_redirect_hosts": c.voicelinkKycRedirectHosts or "",
        "kyc_finalize_verified": bool(c.kycFinalizeVerified),
        "livekit_sip_host": c.livekitSipHost or "",
        "livekit_sip_port": int(c.livekitSipPort or 5060),
        "frontend_url": c.frontendUrl or "http://localhost:3000",
        "public_api_url": c.publicApiUrl or "",
        "updated_at": c.updatedAt or "",
    }
    if include_secrets:
        out["voicelink_api_token_enc"] = c.voicelinkApiTokenEnc or ""
        out["voicelink_password_enc"] = c.voicelinkPasswordEnc or ""
    return out


async def get_telephony_config(*, include_secrets: bool = False) -> Optional[dict]:
    c = await get_prisma().telephonyconfig.find_unique(
        where={"id": TELEPHONY_CONFIG_ID})
    return _config_dict(c, include_secrets=include_secrets)


async def create_telephony_config(data: dict) -> Optional[dict]:
    payload = {_CONFIG_FIELDS[k]: v for k, v in data.items() if k in _CONFIG_FIELDS}
    payload.update({"id": TELEPHONY_CONFIG_ID, "updatedAt": _ts()})
    c = await get_prisma().telephonyconfig.create(data=payload)
    return _config_dict(c, include_secrets=True)


async def update_telephony_config(patch: dict) -> Optional[dict]:
    payload = {_CONFIG_FIELDS[k]: v for k, v in patch.items() if k in _CONFIG_FIELDS}
    payload["updatedAt"] = _ts()
    try:
        c = await get_prisma().telephonyconfig.update(
            where={"id": TELEPHONY_CONFIG_ID}, data=payload)
    except Exception:
        return None
    return _config_dict(c, include_secrets=True)
