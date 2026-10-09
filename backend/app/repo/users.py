"""User records."""
from __future__ import annotations

from typing import Any, Optional

from ..db import get_prisma


async def create_user(email: str, name: str, password_hash: str, role: str = "USER") -> dict:
    """Create a user. `role` is USER by default; SUPER_ADMIN is only ever
    passed by the key-protected one-time bootstrap in
    routes/setup_routes.py — all later promotions go through the audited
    admin service (set_user_role)."""
    db = get_prisma()
    u = await db.user.create(
        data={"email": email.lower(), "name": name, "passwordHash": password_hash, "role": role}
    )
    return _user_dict(u)


async def get_user_by_email(email: str) -> Optional[Any]:
    return await get_prisma().user.find_unique(where={"email": email.lower()})


async def get_user(user_id: str) -> Optional[Any]:
    return await get_prisma().user.find_unique(where={"id": user_id})


def _user_dict(u: Any) -> dict:
    return {
        "id": u.id,
        "email": u.email,
        "name": u.name or "",
        "wallet_balance": round(u.walletBalance or 0, 2),
        "role": getattr(u, "role", "USER") or "USER",
        "disabled": bool(getattr(u, "disabled", False)),
        "created_at": u.createdAt or "",
    }
