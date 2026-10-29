"""Super Admin telephony marketplace routes (/api/admin/telephony/*).

Mounted under the admin router's prefix + SUPER_ADMIN dependencies. Every
mutation is audited. SIP passwords stay masked; the reseller credential is
reported only as configured/not.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from ..models.telephony_models import (AllocateWalletBody, ManualNumberBody,
                                       ManualNumberUpdateBody,
                                       TelephonySettingsBody,
                                       TelephonyStatusBody)
from ..services import (admin_service, telephony_admin, telephony_provisioning,
                        telephony_settings)
from ..services import voicelink_client as vl
from ..services.telephony_policy import TelephonyError
from . import deps

router = APIRouter()
ADMIN = Depends(deps.get_super_admin)


def _raise(e: Exception):
    if isinstance(e, TelephonyError):
        # The admin frontend treats 401/403 as "session expired"; a domain
        # 403 (e.g. suspended account) must not log the operator out.
        status = 409 if e.status_code in (401, 403) else e.status_code
        raise HTTPException(status, str(e)) from None
    if isinstance(e, vl.VoiceLinkError):
        status = e.status_code
        if status in (401, 403):
            status = 503
        elif status >= 500:
            status = 502
        elif status not in (400, 402, 404, 409, 413, 422):
            status = 400
        raise HTTPException(status, str(e)) from None
    raise HTTPException(400, str(e)) from None


@router.get("/telephony/settings")
async def get_settings(admin=ADMIN):
    try:
        settings = await telephony_settings.ensure_settings_row()
    except Exception as e:
        _raise(e)
    return {"settings": telephony_settings.public_view(settings)}


@router.put("/telephony/settings")
async def update_settings(body: TelephonySettingsBody, admin=ADMIN):
    patch = body.model_dump(exclude_unset=True, exclude_none=True)
    try:
        settings = await telephony_settings.update_settings(patch)
    except Exception as e:
        _raise(e)
    detail = {}
    for key, value in patch.items():
        if key in ("voicelink_api_token", "voicelink_password"):
            detail[key] = "rotated" if value else "unchanged"
        else:
            detail[key] = value
    await admin_service.audit(
        admin, "telephony_settings_updated", target_type="telephony_config",
        target_id="global", detail=detail)
    return {"settings": telephony_settings.public_view(settings)}


@router.post("/telephony/settings/test")
async def test_settings(admin=ADMIN):
    try:
        await telephony_settings.ensure_settings_row()
        out = await telephony_settings.test_connection()
    except Exception as e:
        _raise(e)
    await admin_service.audit(
        admin, "telephony_settings_tested", target_type="telephony_config",
        target_id="global",
        detail={"ok": True,
                "provider_id": (out.get("profile") or {}).get("id", "")})
    return out


@router.get("/telephony/overview")
async def overview(admin=ADMIN):
    try:
        return await telephony_admin.overview()
    except Exception as e:
        _raise(e)


@router.get("/telephony/accounts")
async def list_accounts(admin=ADMIN, page: int = Query(1, ge=1),
                        page_size: int = Query(25, ge=1, le=200),
                        q: Optional[str] = None,
                        kyc_status: Optional[str] = None,
                        status: Optional[str] = None):
    return await telephony_admin.list_accounts_admin(
        q=q or "", kyc_status=kyc_status or "", status=status or "",
        page=page, page_size=page_size)


@router.get("/telephony/accounts/{account_id}")
async def account_detail(account_id: str, admin=ADMIN):
    detail = await telephony_admin.account_detail(account_id)
    if not detail:
        raise HTTPException(404, "Telephony account not found")
    return detail


@router.post("/telephony/accounts/{account_id}/sync")
async def sync_account(account_id: str, admin=ADMIN):
    try:
        out = await telephony_admin.sync_account_admin(account_id)
    except Exception as e:
        _raise(e)
    await admin_service.audit(admin, "telephony_account_synced",
                              target_type="telephony_account",
                              target_id=account_id)
    return out


@router.post("/telephony/accounts/{account_id}/allocate-wallet")
async def allocate_wallet(account_id: str, body: AllocateWalletBody, admin=ADMIN):
    try:
        out = await telephony_admin.allocate_admin(
            account_id, body.amount, body.description)
    except Exception as e:
        _raise(e)
    await admin_service.audit(
        admin, "telephony_wallet_allocated", target_type="telephony_account",
        target_id=account_id,
        detail={"amount": body.amount, "description": body.description})
    return out


@router.put("/telephony/accounts/{account_id}/status")
async def set_account_status(account_id: str, body: TelephonyStatusBody,
                             admin=ADMIN):
    try:
        out = await telephony_admin.set_account_status(account_id, body.status)
    except Exception as e:
        _raise(e)
    await admin_service.audit(admin, "telephony_account_status",
                              target_type="telephony_account",
                              target_id=account_id,
                              detail={"status": body.status})
    return out


@router.get("/telephony/numbers")
async def list_numbers(admin=ADMIN, page: int = Query(1, ge=1),
                       page_size: int = Query(25, ge=1, le=200),
                       q: Optional[str] = None, status: Optional[str] = None,
                       user_id: Optional[str] = None):
    return await telephony_admin.list_numbers_admin(
        q=q or "", status=status or "", user_id=user_id or "",
        page=page, page_size=page_size)


@router.post("/telephony/numbers/manual", status_code=201)
async def create_manual_number(body: ManualNumberBody, admin=ADMIN):
    try:
        out = await telephony_admin.create_manual_number_admin(body)
    except Exception as e:
        _raise(e)
    await admin_service.audit(admin, "telephony_manual_number_created",
                              target_type="phone_number", target_id=out["id"],
                              detail={"number": out["number"],
                                      "user_id": body.user_id})
    return out


@router.put("/telephony/numbers/{phone_id}/manual")
async def update_manual_number(phone_id: str, body: ManualNumberUpdateBody,
                               admin=ADMIN):
    patch = body.model_dump(exclude_unset=True, exclude_none=True)
    try:
        out = await telephony_provisioning.update_manual_number(phone_id, patch)
    except Exception as e:
        _raise(e)
    await admin_service.audit(admin, "telephony_manual_number_updated",
                              target_type="phone_number", target_id=phone_id,
                              detail={"number": out["number"], "patch": patch})
    return out


@router.delete("/telephony/numbers/{phone_id}/manual")
async def delete_manual_number(phone_id: str, admin=ADMIN):
    try:
        out = await telephony_provisioning.delete_manual_number(phone_id)
    except Exception as e:
        _raise(e)
    await admin_service.audit(admin, "telephony_manual_number_deleted",
                              target_type="phone_number", target_id=phone_id,
                              detail={
                                  "number": out["number"],
                                  "unassigned_agent_ids": out[
                                      "unassigned_agent_ids"],
                              })
    return out


@router.post("/telephony/numbers/{phone_id}/retry-provision")
async def retry_provision(phone_id: str, admin=ADMIN):
    try:
        out = await telephony_provisioning.provision_number(phone_id)
    except Exception as e:
        _raise(e)
    await admin_service.audit(admin, "telephony_number_provision_retried",
                              target_type="phone_number", target_id=phone_id,
                              detail={"status": out["status"]})
    return out


@router.post("/telephony/numbers/{phone_id}/sync-inbound")
async def sync_inbound(phone_id: str, admin=ADMIN):
    try:
        out = await telephony_provisioning.sync_inbound_dispatch(phone_id)
    except Exception as e:
        _raise(e)
    await admin_service.audit(admin, "telephony_number_inbound_synced",
                              target_type="phone_number", target_id=phone_id,
                              detail={"inbound_agent_id": out.get("inbound_agent_id")})
    return out


@router.put("/telephony/numbers/{phone_id}/status")
async def set_number_status(phone_id: str, body: TelephonyStatusBody, admin=ADMIN):
    try:
        out = await telephony_provisioning.set_number_status(phone_id, body.status)
    except Exception as e:
        _raise(e)
    await admin_service.audit(admin, "telephony_number_status",
                              target_type="phone_number", target_id=phone_id,
                              detail={"status": body.status})
    return out


@router.get("/telephony/purchases")
async def list_purchases(admin=ADMIN, page: int = Query(1, ge=1),
                         page_size: int = Query(25, ge=1, le=200),
                         state: Optional[str] = None):
    return await telephony_admin.list_purchases_admin(
        state=state or "", page=page, page_size=page_size)
