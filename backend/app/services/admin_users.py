"""Super Admin user management (roles, disable, wallet adjustments, detail).\n\nExtracted from the old monolithic admin_service — behavior unchanged.\n"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from ..db import get_prisma
from .. import repo
from .admin_shared import _now, audit

logger = logging.getLogger("voice-agent-saas-admin")


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------
def _user_public(u) -> Dict[str, Any]:
    return {
        "id": u.id, "email": u.email, "name": u.name or "",
        "role": getattr(u, "role", "USER") or "USER",
        "disabled": bool(getattr(u, "disabled", False)),
        "wallet_balance": round(u.walletBalance or 0, 2),
        "created_at": u.createdAt or "",
    }


async def list_users(*, page: int = 1, page_size: int = 25,
                     q: Optional[str] = None, role: Optional[str] = None,
                     disabled: Optional[bool] = None) -> Dict[str, Any]:
    db = get_prisma()
    where: Dict[str, Any] = {}
    if role:
        where["role"] = role
    if disabled is not None:
        where["disabled"] = disabled
    rows = await db.user.find_many(where=where, order={"createdAt": "desc"})
    items = [_user_public(u) for u in rows]
    if q:
        ql = q.lower()
        items = [i for i in items if ql in (i["email"] + i["name"]).lower()]
    total = len(items)
    start = (max(page, 1) - 1) * page_size
    return {"items": items[start:start + page_size], "total": total, "page": page, "page_size": page_size}


async def set_user_role(user_id: str, role: str, *, admin: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if role not in ("USER", "SUPER_ADMIN"):
        raise ValueError("role must be USER or SUPER_ADMIN")
    db = get_prisma()
    u = await db.user.find_unique(where={"id": user_id})
    if not u:
        return None
    old_role = getattr(u, "role", "USER") or "USER"
    if old_role == role:
        return _user_public(u)
    # Safety: never demote the last SUPER_ADMIN.
    if old_role == "SUPER_ADMIN" and role == "USER":
        admins = await db.user.count(where={"role": "SUPER_ADMIN", "disabled": False})
        if admins <= 1:
            raise ValueError("Cannot demote the last active SUPER_ADMIN")
    u = await db.user.update(where={"id": user_id}, data={"role": role})
    await audit(admin, f"user_role_{role.lower()}", target_type="user", target_id=user_id,
                detail={"email": u.email, "old_role": old_role})
    return _user_public(u)


async def set_user_disabled(user_id: str, disabled: bool, *, admin: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    db = get_prisma()
    u = await db.user.find_unique(where={"id": user_id})
    if not u:
        return None
    if (getattr(u, "role", "USER") or "USER") == "SUPER_ADMIN" and u.id == admin.get("id"):
        raise ValueError("You cannot disable your own SUPER_ADMIN account")
    if (getattr(u, "role", "USER") or "USER") == "SUPER_ADMIN" and disabled:
        admins = await db.user.count(where={"role": "SUPER_ADMIN", "disabled": False})
        if admins <= 1:
            raise ValueError("Cannot disable the last active SUPER_ADMIN")
    u = await db.user.update(where={"id": user_id}, data={"disabled": bool(disabled)})
    await audit(admin, "user_disabled" if disabled else "user_enabled",
                target_type="user", target_id=user_id, detail={"email": u.email})
    return _user_public(u)


async def user_detail(user_id: str) -> Optional[Dict[str, Any]]:
    db = get_prisma()
    u = await db.user.find_unique(where={"id": user_id})
    if not u:
        return None
    agents = await repo.list_agents(user_id)
    calls = await repo.list_calls(user_id)
    wallet = await repo.get_wallet(user_id)
    usage = await repo.get_usage(user_id)
    return {
        "user": _user_public(u),
        "agents": agents,
        "calls": calls,
        "wallet": wallet,
        "usage": usage,
    }


async def admin_add_wallet(user_id: str, amount: float, note: str = "",
                           *, admin: Dict[str, Any]) -> Dict[str, Any]:
    if amount <= 0:
        raise ValueError("amount must be positive")
    db = get_prisma()
    u = await db.user.find_unique(where={"id": user_id})
    if not u:
        raise LookupError("user not found")
    new_balance = round((u.walletBalance or 0) + amount, 2)
    async with db.tx() as tx:
        await tx.user.update(where={"id": user_id}, data={"walletBalance": new_balance})
        await tx.transaction.create(data={
            "userId": user_id, "kind": "recharge", "amount": amount,
            "note": note or "Admin top-up", "ts": _now(),
        })
    await audit(admin, "wallet_adjusted", target_type="user", target_id=user_id,
                detail={"amount": amount, "note": note, "new_balance": new_balance})
    return await repo.get_wallet(user_id)


# ---------------------------------------------------------------------------
# Providers (DB platform level)
# ---------------------------------------------------------------------------