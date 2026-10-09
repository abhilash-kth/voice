"""Super Admin provider-credential endpoints (`/api/admin/credentials/*`).

Mounted from admin/routes.py via ``router.include_router`` (split to keep
every module under the 300-line file budget). The parent router supplies the
``/api/admin`` prefix and the SUPER_ADMIN + snapshot-refresh dependencies.

Secrets are write-only by default: create/update/rotate accept plaintext but
only ever return the masked value. The single exception is
``POST /credentials/{id}/reveal`` — it returns the plaintext ONCE per request
to the already-authenticated super admin (the key's owner), writes an
``api_key_revealed`` audit entry, and never logs the value.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from ..services import credential_service
from . import deps, schemas

router = APIRouter()

ADMIN = Depends(deps.get_super_admin)


def _err(e: Exception) -> HTTPException:
    if isinstance(e, LookupError):
        return HTTPException(404, str(e))
    if isinstance(e, HTTPException):
        return e
    return HTTPException(400, str(e))


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


@router.delete("/credentials/{credential_id}", status_code=204)
async def credential_delete(credential_id: str, admin=ADMIN):
    ok = await credential_service.delete_credential(credential_id, admin=admin)
    if not ok:
        raise HTTPException(404, "Credential not found")


@router.post("/credentials/{credential_id}/reveal")
async def credential_reveal(credential_id: str, admin=ADMIN):
    """Return the plaintext key to the super-admin panel.

    POST (not GET) so it is never cached or triggered by a prefetch. Audited
    as ``api_key_revealed``; the value itself is never written to any log.
    """
    try:
        value = await credential_service.reveal_credential(credential_id, admin=admin)
    except Exception as e:
        raise _err(e)
    if value is None:
        raise HTTPException(404, "Credential not found")
    return {"value": value}
