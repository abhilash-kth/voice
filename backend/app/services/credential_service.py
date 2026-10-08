"""Provider credential service — the ONLY module that sees raw provider keys.

* Every write encrypts via services/crypto before touching the DB.
* Every read-for-UI returns only the masked value. The single exception is
  ``reveal_credential`` — an audited, SUPER_ADMIN-only endpoint that returns
  the plaintext to the panel (the key's owner). The value is NEVER logged.
* Rotation = create a new active credential + mark the old one ``rotated``;
  decryption of new calls uses the new key immediately (snapshot refresh).
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from ..db import get_prisma
from . import crypto

logger = logging.getLogger("voice-agent-saas-credentials")

_MASK_RE = re.compile(r"(^[\s\*•]+|(?<=.{4})[A-Za-z0-9+/=]+$)")


def mask_secret(value: str) -> str:
    """Strategy from product spec: `************ABCD` (last 4 chars visible)."""
    value = (value or "").strip()
    if not value:
        return ""
    tail = value[-4:]
    return f"************{tail}"


def _row_public(c) -> Dict[str, Any]:
    """Safe public shape — no ciphertext, no plaintext."""
    return {
        "id": c.id,
        "provider_id": c.providerId,
        "provider_slug": c.providerSlug,
        "kind": c.kind or "",
        "label": c.label or "",
        "masked_value": c.maskedValue or "",
        "status": c.status,
        "created_at": c.createdAt or "",
        "updated_at": c.updatedAt or "",
    }


async def list_credentials(provider_id: Optional[str] = None, kind: Optional[str] = None) -> List[Dict[str, Any]]:
    db = get_prisma()
    where: Dict[str, Any] = {}
    if provider_id:
        where["providerId"] = provider_id
    if kind is not None:
        where["kind"] = kind
    rows = await db.providercredential.find_many(where=where, order={"createdAt": "desc"})
    return [_row_public(c) for c in rows]


async def get_credential(cid: str) -> Optional[Dict[str, Any]]:
    db = get_prisma()
    c = await db.providercredential.find_unique(where={"id": cid})
    return _row_public(c) if c else None


async def reveal_credential(cid: str, *, admin: Optional[dict] = None) -> Optional[str]:
    """Return the PLAINTEXT key for the super-admin panel (audited).

    Never log the returned value. Decryption failures surface the exception
    TYPE only — the ciphertext/plaintext must never land in a log line.
    """
    db = get_prisma()
    c = await db.providercredential.find_unique(where={"id": cid})
    if not c:
        return None
    try:
        value = crypto.decrypt_secret(c.encValue)
    except Exception as e:
        logger.error(
            f"🔑 credential {cid} ({c.providerSlug}) could not be decrypted: {type(e).__name__}"
        )
        raise
    await _audit(admin, "api_key_revealed", "credential", cid,
                 {"provider": c.providerSlug, "masked": c.maskedValue})
    logger.info(f"🔑 credential revealed to super admin for {c.kind}:{c.providerSlug} ({c.maskedValue})")
    return value


async def create_credential(*, provider_id: str, value: str, label: str = "",
                            admin: Optional[dict] = None,
                            _replace_id: Optional[str] = None) -> Dict[str, Any]:
    db = get_prisma()
    p = await db.provider.find_unique(where={"id": provider_id})
    if not p:
        raise LookupError("provider not found")
    value = (value or "").strip()
    if not value:
        raise ValueError("API key value required")
    # One ACTIVE key per provider SLUG, across all kinds — the same key serves
    # every service of the provider (sarvam STT+LLM, openai LLM+TTS, …).
    # Rotation of another active row for the same slug is allowed via _replace_id.
    dupes = await db.providercredential.find_many(
        where={"providerSlug": p.slug, "status": "active"}
    )
    dupe = next((c for c in dupes if c.id != _replace_id), None)
    if dupe is not None:
        raise ValueError(
            f"A key for '{p.slug}' already exists (…{(dupe.maskedValue or '')[-4:]}). "
            "Rotate it instead — one key per provider is enforced."
        )
    enc, masked = crypto.encrypt_secret(value)
    from .config_store import _now_fallback
    now = _now_fallback()
    # Stored as SHARED (kind ""): resolution prefers a kind-specific row for its
    # own kind and otherwise uses this shared key (see config_merge.get_api_key).
    c = await db.providercredential.create(data={
        "providerId": p.id, "providerSlug": p.slug, "kind": "",
        "label": (label or "").strip(), "encValue": enc,
        "maskedValue": masked, "createdAt": now, "updatedAt": now,
    })
    await _audit(admin, "api_key_created", "credential", c.id,
                 {"provider": p.slug, "kind": "shared", "masked": masked, "label": label})
    _invalidate()
    logger.info(f"🔑 credential created for {p.kind}:{p.slug} [shared] ({masked})")
    return _row_public(c)


async def update_credential(cid: str, *, value: Optional[str] = None,
                            label: Optional[str] = None,
                            admin: Optional[dict] = None) -> Optional[Dict[str, Any]]:
    db = get_prisma()
    c = await db.providercredential.find_unique(where={"id": cid})
    if not c:
        return None
    data: Dict[str, Any] = {}
    if label is not None:
        data["label"] = label.strip()
    if value:
        enc, masked = crypto.encrypt_secret(value.strip())
        data["encValue"] = enc
        data["maskedValue"] = masked
    if not data:
        return _row_public(c)
    from .config_store import _now_fallback
    data["updatedAt"] = _now_fallback()
    c = await db.providercredential.update(where={"id": cid}, data=data)
    await _audit(admin, "api_key_updated", "credential", cid,
                 {"provider": c.providerSlug, "rotated_in_place": bool(value)})
    _invalidate()
    return _row_public(c)


async def set_status(cid: str, status: str, *, admin: Optional[dict] = None) -> Optional[Dict[str, Any]]:
    db = get_prisma()
    c = await db.providercredential.find_unique(where={"id": cid})
    if not c:
        return None
    from .config_store import _now_fallback
    c = await db.providercredential.update(
        where={"id": cid}, data={"status": status, "updatedAt": _now_fallback()}
    )
    await _audit(admin, f"api_key_{status}", "credential", cid, {"provider": c.providerSlug})
    _invalidate()
    return _row_public(c)


async def rotate_credential(cid: str, *, new_value: str, label: str = "",
                            admin: Optional[dict] = None) -> Dict[str, Any]:
    """Create replacement active credential; old one is marked ``rotated``."""
    db = get_prisma()
    old = await db.providercredential.find_unique(where={"id": cid})
    if not old:
        raise LookupError("credential not found")
    created = await create_credential(
        provider_id=old.providerId, value=new_value,
        label=label or f"rotated from {old.label or old.id}",
        admin=admin, _replace_id=cid,
    )
    from .config_store import _now_fallback
    await db.providercredential.update(
        where={"id": cid}, data={"status": "rotated", "updatedAt": _now_fallback()}
    )
    await _audit(admin, "api_key_rotated", "credential", cid,
                 {"provider": old.providerSlug, "new_id": created["id"]})
    _invalidate()
    return created


async def delete_credential(cid: str, *, admin: Optional[dict] = None) -> bool:
    """Delete a credential row entirely. Deleting the ACTIVE key for a provider
    makes calls fall back to the provider's env-var key (if set)."""
    db = get_prisma()
    c = await db.providercredential.find_unique(where={"id": cid})
    if not c:
        return False
    await db.providercredential.delete(where={"id": cid})
    await _audit(admin, "api_key_deleted", "credential", cid,
                 {"provider": c.providerSlug, "kind": c.kind or "shared",
                  "masked": c.maskedValue, "was_status": c.status})
    _invalidate()
    logger.info(f"🔑 credential DELETED for {c.kind}:{c.providerSlug} ({c.maskedValue})")
    return True


async def _audit(admin: Optional[dict], action: str, target_type: str, target_id: str, detail: dict) -> None:
    try:
        from . import admin_service

        await admin_service.audit(admin or {}, action, target_type=target_type,
                                  target_id=target_id, detail=detail)
    except Exception as e:
        logger.warning(f"audit write failed for {action}: {e!r}")


def _invalidate() -> None:
    try:
        from . import config_store

        config_store.invalidate()
    except Exception:
        pass
