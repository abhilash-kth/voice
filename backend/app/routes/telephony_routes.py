"""Customer telephony marketplace routes (/api/telephony/*).

Everything a customer does on the website — set up the hidden VoiceLink
account, complete KYC, move calling balance, browse/buy numbers, watch
automatic activation — goes through here. Provider client ids are derived
from the logged-in user; no endpoint accepts or returns SIP passwords,
provider tokens, or customer-supplied trunk ids.
"""
from __future__ import annotations

import logging

from fastapi import (APIRouter, Depends, File, Form, HTTPException, Request,
                     UploadFile)
from fastapi.responses import RedirectResponse

from .. import auth, repo
from ..models.telephony_models import (AccountSetupBody, AllocateWalletBody,
                                       ChannelUpgradeBody,
                                       ChannelUpgradeQuoteBody, ConfirmBody,
                                       KycActionBody, QuoteBody)
from ..services import config_store, subscription_service
from ..services import telephony_account as accounts
from ..services import telephony_channels as channels
from ..services import telephony_provisioning as provisioning
from ..services import telephony_purchase as purchases
from ..services import telephony_settings
from ..services import voicelink_client as vl
from ..services.telephony_policy import TelephonyError

logger = logging.getLogger("voice-agent-saas-api")
router = APIRouter(tags=["telephony"])


def _raise(e: Exception):
    if isinstance(e, TelephonyError):
        raise HTTPException(e.status_code, str(e)) from None
    if isinstance(e, vl.VoiceLinkError):
        # Never surface a provider 401/403 as our own auth status (the
        # frontend treats 401 as "session expired" and would log out).
        status = e.status_code
        if status in (401, 403):
            status = 503
        elif status >= 500:
            status = 502
        elif status not in (400, 402, 404, 409, 413, 422):
            status = 400
        raise HTTPException(status, str(e)) from None
    raise e


def _kyc_from_account(account: dict, settings=None) -> dict:
    effective = settings or telephony_settings.env_fallback_settings()
    meta = account.get("kyc_meta") or {}
    return {
        "status": account.get("kyc_status") or "not_started",
        "step": account.get("kyc_step") or meta.get("step") or "register",
        "account_type": meta.get("account_type") or "individual",
        "documents": meta.get("documents") or {
            "pan": {"verified": False, "uploaded": False},
            "aadhaar": {"verified": False, "uploaded": False}},
        "ready_for_submission": bool(meta.get("ready_for_submission")),
        "provider_complete": bool(meta.get("provider_complete")),
        "agreement_needs_acceptance": bool(
            meta.get("agreement_needs_acceptance")),
        "final_submission_available": bool(effective.kyc_finalize_verified),
        "terms_url": accounts.terms_url(effective.voicelink_kyc_terms_url),
    }


# Customer responses are an allow-list, never raw repo rows: the hidden
# VoiceLink client id, every provider/LiveKit trunk id, the SIP username and
# even the masked SIP password stay server-side. (Admin routes use the full
# masked-secret views.)
_ACCOUNT_PUBLIC = (
    "id", "email", "name", "phone", "status", "kyc_status", "kyc_step",
    "wallet_balance", "channels_allocated", "channels_available",
    "last_error", "last_synced_at", "created_at", "updated_at",
)
_PHONE_PUBLIC = (
    "id", "number", "country_code", "status", "provisioning_step", "source",
    "channels", "monthly_rate", "expires_at", "inbound_agent_id",
    "last_error", "created_at", "updated_at",
)
_PURCHASE_PUBLIC = (
    "id", "phone_number_id", "number", "months", "channels", "quote_total",
    "monthly_rate", "customer_charge", "state", "error", "expires_at",
    "created_at", "updated_at", "confirmation_available", "warning",
)


def _pick(row, fields):
    return {k: row.get(k) for k in fields} if row else None


def _public_account(account):
    return _pick(account, _ACCOUNT_PUBLIC)


def _public_phone(phone):
    return _pick(phone, _PHONE_PUBLIC)


def _public_purchase(purchase):
    out = _pick(purchase, _PURCHASE_PUBLIC)
    if out is not None:
        out["phone_number"] = _public_phone(purchase.get("phone_number"))
    return out


@router.get("/api/telephony/overview")
async def overview(user=Depends(auth.get_current_user)):
    await config_store.refresh_if_stale()
    settings = await telephony_settings.get_settings()
    account = await repo.get_account_by_user(user.id)
    numbers = await repo.list_phone_numbers(user.id)
    entitlement = await subscription_service.get_subscription(user.id)
    latest = await purchases.purchase_view(await repo.latest_purchase(user.id))
    provider = None
    provider_error = ""
    if settings.configured:
        try:
            p = accounts.safe_profile(await vl.profile())
            provider = {"did_type_rates": p["did_type_rates"],
                        "monthly_channel_rate": p["monthly_channel_rate"],
                        "plan_name": p["plan_name"]}
        except Exception as e:
            provider_error = str(e)[:300]
    return {
        "configured": settings.configured,
        "provider": provider,
        "provider_error": provider_error,
        "plan_channels": entitlement.get("plan_channels") or 1,
        "effective_channels": entitlement.get("channels") or 1,
        "channel_price_per_month": float(
            config_store.get_billing().get(
                "concurrency_line_price_per_month") or 0),
        "account": _public_account(account),
        "kyc": _kyc_from_account(account, settings) if account else None,
        "numbers": [_public_phone(n) for n in numbers],
        "latest_purchase": _public_purchase(latest),
        "wallet": await repo.get_wallet(user.id),
    }


@router.post("/api/telephony/account/setup", status_code=201)
async def setup_account(body: AccountSetupBody,
                        user=Depends(auth.get_current_user)):
    try:
        account = await accounts.setup_account(
            user.id, user.email, body.name or getattr(user, "name", "") or "",
            body.phone)
    except Exception as e:
        _raise(e)
    settings = await telephony_settings.get_settings()
    return {"account": _public_account(account),
            "kyc": _kyc_from_account(account, settings)}


@router.post("/api/telephony/account/sync")
async def sync_account(user=Depends(auth.get_current_user)):
    try:
        account = await accounts.require_account(user.id)
        account = await accounts.sync_account(account)
        synced = await purchases.sync_purchased_numbers(account)
    except Exception as e:
        _raise(e)
    settings = await telephony_settings.get_settings()
    return {"account": _public_account(account),
            "kyc": _kyc_from_account(account, settings),
            "numbers": [_public_phone(n) for n in synced["numbers"]],
            "imported": synced["imported"]}


@router.get("/api/telephony/kyc")
async def get_kyc(user=Depends(auth.get_current_user)):
    try:
        account = await accounts.require_account(user.id)
        state = await accounts.sync_kyc(account)
        account = await repo.get_account(account["id"]) or account
    except Exception as e:
        _raise(e)
    return {"kyc": state, "account": _public_account(account)}


@router.post("/api/telephony/kyc/action")
async def kyc_action(body: KycActionBody, request: Request,
                     user=Depends(auth.get_current_user)):
    settings = await telephony_settings.get_settings()
    base = settings.public_api_url or str(request.base_url).rstrip("/")
    redirect_url = f"{base}/api/telephony/kyc/return"
    try:
        out = await accounts.act_kyc(user.id, body, redirect_url)
        account = await repo.get_account_by_user(user.id)
    except Exception as e:
        _raise(e)
    return {**out, "account": _public_account(account),
            "kyc": out.get("kyc") or (_kyc_from_account(account, settings)
                                      if account else None)}


@router.post("/api/telephony/kyc/upload")
async def kyc_upload(document_type: str = Form(...),
                     document: UploadFile = File(...),
                     user=Depends(auth.get_current_user)):
    content = await document.read(3 * 1024 * 1024 + 1)
    try:
        out = await accounts.upload_kyc_document(
            user.id, document_type, content,
            document.content_type or "application/octet-stream")
        account = await repo.get_account_by_user(user.id)
    except Exception as e:
        _raise(e)
    return {**out, "account": _public_account(account)}


@router.get("/api/telephony/kyc/return")
async def kyc_return():
    # DigiLocker return parameters are intentionally ignored: a redirect
    # never proves verification. The dashboard re-polls provider KYC status.
    settings = await telephony_settings.get_settings()
    resp = RedirectResponse(
        url=f"{settings.frontend_url}/phone-numbers?kyc=returned",
        status_code=303)
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Cache-Control"] = "private, no-store"
    return resp


@router.get("/api/telephony/numbers")
async def list_numbers(user=Depends(auth.get_current_user)):
    return {"numbers": [_public_phone(n)
                        for n in await repo.list_phone_numbers(user.id)]}


@router.get("/api/telephony/numbers/search")
async def search_numbers(type: str = "3", months: int = 1, number: str = "",
                         page: int = 1, user=Depends(auth.get_current_user)):
    try:
        return await purchases.search_numbers(
            user.id, did_type=type, months=months, number=number, page=page)
    except Exception as e:
        _raise(e)


@router.post("/api/telephony/numbers/quote", status_code=201)
async def create_quote(body: QuoteBody, user=Depends(auth.get_current_user)):
    try:
        purchase = await purchases.create_quote(user.id, body)
    except Exception as e:
        _raise(e)
    return {"purchase": _public_purchase(purchase)}


@router.get("/api/telephony/purchases/latest")
async def latest_purchase(user=Depends(auth.get_current_user)):
    return {"purchase": _public_purchase(await purchases.purchase_view(
        await repo.latest_purchase(user.id)))}


@router.post("/api/telephony/purchases/{purchase_id}/confirm")
async def confirm_purchase(purchase_id: str, body: ConfirmBody,
                           user=Depends(auth.get_current_user)):
    try:
        purchase = await purchases.confirm_purchase(
            user.id, purchase_id, body.accept_auto_renew)
    except Exception as e:
        _raise(e)
    return {"purchase": _public_purchase(purchase),
            "numbers": [_public_phone(n)
                        for n in await repo.list_phone_numbers(user.id)],
            "wallet": await repo.get_wallet(user.id)}


@router.post("/api/telephony/numbers/{phone_id}/channels/quote")
async def quote_channel_upgrade(phone_id: str,
                                body: ChannelUpgradeQuoteBody,
                                user=Depends(auth.get_current_user)):
    await config_store.refresh_if_stale()
    try:
        quote = await channels.quote_channel_upgrade(
            user.id, phone_id, body.target_channels)
    except Exception as e:
        _raise(e)
    phone = await repo.get_phone_number(phone_id, user.id)
    return {"quote": quote, "phone_number": _public_phone(phone)}


@router.post("/api/telephony/numbers/{phone_id}/channels/upgrade")
async def upgrade_phone_channels(phone_id: str, body: ChannelUpgradeBody,
                                 user=Depends(auth.get_current_user)):
    await config_store.refresh_if_stale()
    try:
        out = await channels.upgrade_phone_channels(
            user.id, phone_id, target_channels=body.target_channels,
            accept_charge=body.accept_charge,
            expected_due_now=body.expected_due_now,
            expected_monthly_increment=body.expected_monthly_increment)
    except Exception as e:
        _raise(e)
    return {**out, "phone_number": _public_phone(out.get("phone_number"))}


@router.post("/api/telephony/numbers/{phone_id}/retry-provision")
async def retry_provision(phone_id: str, user=Depends(auth.get_current_user)):
    try:
        phone = await provisioning.provision_number(phone_id, user.id)
    except Exception as e:
        _raise(e)
    return {"phone_number": _public_phone(phone)}


@router.post("/api/telephony/numbers/{phone_id}/sync-inbound")
async def sync_inbound(phone_id: str, user=Depends(auth.get_current_user)):
    try:
        phone = await provisioning.sync_inbound_dispatch(phone_id, user.id)
    except Exception as e:
        _raise(e)
    return {"phone_number": _public_phone(phone)}


@router.post("/api/telephony/wallet/allocate")
async def allocate_wallet(body: AllocateWalletBody,
                          user=Depends(auth.get_current_user)):
    try:
        out = await accounts.allocate_from_wallet(
            user.id, body.amount, body.description)
    except Exception as e:
        _raise(e)
    return {**out, "account": _public_account(out.get("account"))}
