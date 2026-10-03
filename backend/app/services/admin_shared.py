"""Super Admin shared helpers: timestamps, config invalidation, audit.\n\nExtracted from the old monolithic admin_service — behavior unchanged.\n"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from ..db import get_prisma

logger = logging.getLogger("voice-agent-saas-admin")


def _now() -> str:
    from datetime import datetime

    return datetime.utcnow().isoformat(timespec="seconds")


def _invalidate() -> None:
    try:
        from . import config_store

        config_store.invalidate()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------
async def audit(admin: Dict[str, Any], action: str, *, target_type: str = "",
                target_id: str = "", detail: Optional[Dict[str, Any]] = None) -> None:
    """Write an AdminAuditLog row. Never log secrets — `detail` is sanitized."""
    try:
        safe = _sanitize_detail(detail or {})
        await get_prisma().adminauditlog.create(data={
            "adminId": admin.get("id", ""),
            "adminEmail": admin.get("email", ""),
            "action": action,
            "targetType": target_type,
            "targetId": target_id,
            "detail": json.dumps(safe, ensure_ascii=False),
            "createdAt": _now(),
        })
    except Exception as e:
        logger.warning(f"admin audit write failed ({action}): {e!r}")


def _sanitize_detail(detail: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, v in detail.items():
        lk = k.lower()
        if any(s in lk for s in ("key", "secret", "password", "token", "value")) \
                and "masked" not in lk and "old_" not in lk:
            out[k] = "***redacted***"
        else:
            out[k] = v
    return out


async def list_audit_logs(*, page: int = 1, page_size: int = 50,
                          action: Optional[str] = None,
                          target_type: Optional[str] = None,
                          q: Optional[str] = None) -> Dict[str, Any]:
    db = get_prisma()
    where: Dict[str, Any] = {}
    if action:
        where["action"] = action
    if target_type:
        where["targetType"] = target_type
    rows = await db.adminauditlog.find_many(where=where, order={"createdAt": "desc"})
    items = [_audit_dict(r) for r in rows]
    if q:
        ql = q.lower()
        items = [i for i in items if ql in (i.get("admin_email", "") + i.get("action", "") + i.get("target_id", "")).lower()]
    total = len(items)
    start = (max(page, 1) - 1) * page_size
    return {"items": items[start:start + page_size], "total": total, "page": page, "page_size": page_size}


def _audit_dict(r) -> Dict[str, Any]:
    try:
        detail = json.loads(r.detail or "{}")
    except Exception:
        detail = {}
    return {
        "id": r.id, "admin_id": r.adminId, "admin_email": r.adminEmail,
        "action": r.action, "target_type": r.targetType or "",
        "target_id": r.targetId or "", "detail": detail, "created_at": r.createdAt or "",
    }


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------