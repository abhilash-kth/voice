"""Super Admin REST API (`/api/admin/*`).

Every endpoint requires `role == SUPER_ADMIN` (see admin.deps.get_super_admin)
and every mutation writes an AdminAuditLog entry via the service layer.
Secrets are write-only: API-key endpoints accept plaintext but only ever
return the masked value.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from ..services import admin_service, credential_service, catalog_service, config_store
from . import deps, schemas

router = APIRouter(
    prefix="/api/admin",
    tags=["super-admin"],
    dependencies=[Depends(deps.get_super_admin), Depends(deps.refresh_snapshot)],
)

ADMIN = Depends(deps.get_super_admin)


def _err(e: Exception) -> HTTPException:
    if isinstance(e, LookupError):
        return HTTPException(404, str(e))
    if isinstance(e, HTTPException):
        return e
    return HTTPException(400, str(e))


# ---------------------------------------------------------------------------
# Health / stats
# ---------------------------------------------------------------------------
@router.get("/health")
async def admin_health(admin=ADMIN):
    return {
        "ok": True,
        "snapshot_source": config_store.get_snapshot().source,
        "snapshot_ts": config_store.get_snapshot().ts,
        "snapshot_error": config_store.get_snapshot().error,
    }


@router.get("/stats")
async def stats(admin=ADMIN):
    return await admin_service.stats_overview()


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------
@router.get("/users")
async def list_users(admin=ADMIN, page: int = Query(1, ge=1),
                     page_size: int = Query(25, ge=1, le=200),
                     q: Optional[str] = None, role: Optional[str] = None,
                     disabled: Optional[bool] = None):
    return await admin_service.list_users(page=page, page_size=page_size, q=q,
                                          role=role, disabled=disabled)


@router.get("/users/{user_id}")
async def user_detail(user_id: str, admin=ADMIN):
    detail = await admin_service.user_detail(user_id)
    if not detail:
        raise HTTPException(404, "User not found")
    return detail


@router.put("/users/{user_id}/role")
async def set_role(user_id: str, body: schemas.RoleUpdateBody, admin=ADMIN):
    try:
        out = await admin_service.set_user_role(user_id, body.role, admin=admin)
    except Exception as e:
        raise _err(e)
    if not out:
        raise HTTPException(404, "User not found")
    return out


@router.put("/users/{user_id}/disabled")
async def set_disabled(user_id: str, body: schemas.DisabledBody, admin=ADMIN):
    try:
        out = await admin_service.set_user_disabled(user_id, body.disabled, admin=admin)
    except Exception as e:
        raise _err(e)
    if not out:
        raise HTTPException(404, "User not found")
    return out


@router.post("/users/{user_id}/wallet")
async def wallet_adjust(user_id: str, body: schemas.WalletAdjustBody, admin=ADMIN):
    try:
        return await admin_service.admin_add_wallet(user_id, body.amount, body.note, admin=admin)
    except Exception as e:
        raise _err(e)


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------
@router.get("/providers")
async def list_providers(admin=ADMIN, kind: Optional[str] = None):
    return {"items": await admin_service.list_providers(kind)}


@router.post("/providers", status_code=201)
async def create_provider(body: schemas.ProviderCreateBody, admin=ADMIN):
    try:
        return await admin_service.create_provider(body.model_dump(), admin=admin)
    except Exception as e:
        raise _err(e)


@router.put("/providers/{provider_id}")
async def update_provider(provider_id: str, body: schemas.ProviderUpdateBody, admin=ADMIN):
    patch = body.model_dump(exclude_none=True)
    if not patch:
        raise HTTPException(400, "No fields to update")
    try:
        out = await admin_service.update_provider(provider_id, patch, admin=admin)
    except Exception as e:
        raise _err(e)
    if not out:
        raise HTTPException(404, "Provider not found")
    return out


@router.delete("/providers/{provider_id}", status_code=204)
async def delete_provider(provider_id: str, admin=ADMIN,
                          cascade: bool = Query(False, description="Also delete its catalog models")):
    # Destructive; the UI must have the admin confirm first. Without `cascade`
    # a provider that still has models is rejected so it can't be removed by accident.
    models = await admin_service.list_models(provider_id=provider_id)
    if models["total"] > 0 and not cascade:
        raise HTTPException(
            409,
            f"Provider still owns {models['total']} catalog model(s). Re-run with "
            "cascade=true after confirming — or disable it instead.",
        )
    ok = await admin_service.delete_provider(provider_id, admin=admin)
    if not ok:
        raise HTTPException(404, "Provider not found")


# ---------------------------------------------------------------------------
# Catalog models
# ---------------------------------------------------------------------------
@router.get("/models")
async def list_models(admin=ADMIN, kind: Optional[str] = None,
                      provider_id: Optional[str] = None,
                      page: int = Query(1, ge=1), page_size: int = Query(200, ge=1, le=500)):
    return await admin_service.list_models(kind=kind, provider_id=provider_id,
                                           page=page, page_size=page_size)


@router.get("/models/{model_id}")
async def get_model(model_id: str, admin=ADMIN):
    out = await admin_service.get_model(model_id)
    if not out:
        raise HTTPException(404, "Model not found")
    return out


@router.post("/models", status_code=201)
async def create_model(body: schemas.ModelCreateBody, admin=ADMIN):
    try:
        return await admin_service.create_model(body.model_dump(), admin=admin)
    except Exception as e:
        raise _err(e)


@router.put("/models/{model_id}")
async def update_model(model_id: str, body: schemas.ModelUpdateBody, admin=ADMIN):
    patch = body.model_dump(exclude_none=True)
    if not patch:
        raise HTTPException(400, "No fields to update")
    try:
        out = await admin_service.update_model(model_id, patch, admin=admin)
    except Exception as e:
        raise _err(e)
    if not out:
        raise HTTPException(404, "Model not found")
    return out


@router.delete("/models/{model_id}", status_code=204)
async def delete_model(model_id: str, admin=ADMIN):
    ok = await admin_service.delete_model(model_id, admin=admin)
    if not ok:
        raise HTTPException(404, "Model not found")


# ---------------------------------------------------------------------------
# Provider credentials (secrets write-only)
# ---------------------------------------------------------------------------
@router.get("/credentials")
async def list_credentials(admin=ADMIN, provider_id: Optional[str] = None,
                           kind: Optional[str] = None):
    return {"items": await credential_service.list_credentials(provider_id=provider_id, kind=kind)}


@router.post("/credentials", status_code=201)
async def create_credential(body: schemas.CredentialCreateBody, admin=ADMIN):
    try:
        return await credential_service.create_credential(
            provider_id=body.provider_id, value=body.value, label=body.label, admin=admin)
    except Exception as e:
        raise _err(e)


@router.put("/credentials/{credential_id}")
async def update_credential(credential_id: str, body: schemas.CredentialUpdateBody, admin=ADMIN):
    try:
        out = await credential_service.update_credential(
            credential_id, value=body.value, label=body.label, admin=admin)
    except Exception as e:
        raise _err(e)
    if not out:
        raise HTTPException(404, "Credential not found")
    return out


@router.put("/credentials/{credential_id}/status")
async def credential_status(credential_id: str, body: schemas.CredentialStatusBody, admin=ADMIN):
    out = await credential_service.set_status(credential_id, body.status, admin=admin)
    if not out:
        raise HTTPException(404, "Credential not found")
    return out


@router.post("/credentials/{credential_id}/rotate", status_code=201)
async def credential_rotate(credential_id: str, body: schemas.CredentialRotateBody, admin=ADMIN):
    try:
        return await credential_service.rotate_credential(
            credential_id, new_value=body.new_value, label=body.label, admin=admin)
    except Exception as e:
        raise _err(e)


# ---------------------------------------------------------------------------
# Billing configuration
# ---------------------------------------------------------------------------
@router.get("/billing")
async def get_billing(admin=ADMIN):
    return await admin_service.get_billing()


@router.put("/billing")
async def update_billing(body: schemas.BillingUpdateBody, admin=ADMIN):
    patch = body.model_dump(exclude_none=True)
    if not patch:
        raise HTTPException(400, "No fields to update")
    try:
        return await admin_service.update_billing(patch, admin=admin)
    except Exception as e:
        raise _err(e)


# ---------------------------------------------------------------------------
# Usage analytics + audit logs
# ---------------------------------------------------------------------------
@router.get("/usage")
async def usage(admin=ADMIN):
    return {"items": await admin_service.usage_rows()}


@router.get("/audit-logs")
async def audit_logs(admin=ADMIN, page: int = Query(1, ge=1),
                     page_size: int = Query(50, ge=1, le=200),
                     action: Optional[str] = None,
                     target_type: Optional[str] = None,
                     q: Optional[str] = None):
    return await admin_service.list_audit_logs(page=page, page_size=page_size,
                                               action=action, target_type=target_type, q=q)


@router.post("/config/reload")
async def reload_config(admin=ADMIN):
    snap = await config_store.refresh_if_stale(force=True)
    return {"ok": True, "source": snap.source, "ts": snap.ts}


@router.post("/config/reseed", status_code=202)
async def reseed_config(admin=ADMIN):
    """Idempotent scaffold — safe because seed only runs on an EMPTY Provider table."""
    await catalog_service.seed_defaults_if_empty()
    await admin_service.audit(admin, "config_reseed", target_type="models")
    snap = await config_store.refresh_if_stale(force=True)
    return {"ok": True, "source": snap.source}
