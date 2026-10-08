"""Access control for the Super Admin API.

Every `/api/admin/*` route depends on `get_super_admin`. It reuses the
existing JWT auth (HTTP Bearer, same token the dashboard issues) and adds:
  1. `user.disabled` → 403 ("account disabled")
  2. `role != SUPER_ADMIN` → 403 ("admin access required")

The user dict is also refreshed into `config_store` staleness checks here so
admin mutations are observed by the pipeline quickly.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from .. import auth, repo

bearer = HTTPBearer(auto_error=False)


def as_user_dict(user: Any) -> dict:
    return {
        "id": user.id,
        "email": getattr(user, "email", "") or "",
        "name": getattr(user, "name", "") or "",
        "role": getattr(user, "role", "USER") or "USER",
        "disabled": bool(getattr(user, "disabled", False)),
    }


def check_not_disabled(user: Any) -> None:
    if getattr(user, "disabled", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account has been disabled by an administrator.",
        )


async def get_super_admin(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer),
) -> dict:
    token = auth.extract_token(request, credentials)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user_id = auth.decode_token(token)
    user = await repo.get_user(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    check_not_disabled(user)
    role = getattr(user, "role", "USER") or "USER"
    if role != "SUPER_ADMIN":
        # Do not leak whether the user exists: same error for every non-admin.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Super Admin privileges required.",
        )
    return as_user_dict(user)


# Cheap staleness hook so every admin request refreshes an outdated snapshot.
async def refresh_snapshot() -> None:
    try:
        from ..services import config_store

        await config_store.refresh_if_stale()
    except Exception:
        pass
