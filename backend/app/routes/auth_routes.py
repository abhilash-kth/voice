"""Auth routes (/api/auth/*): register, login, me.
Extracted from the old monolithic main.py — behavior unchanged.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Depends

from ..models import RegisterBody, LoginBody
from .. import auth
from .. import repo

logger = logging.getLogger("voice-agent-saas-api")

router = APIRouter(tags=["auth"])


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
# One-time bootstrap rule: a registration may request role="SUPER_ADMIN" only
# while NO super admin exists in the DB. The moment the first one is created,
# the public endpoint refuses the field (403) and all further promotions go
# through /api/admin/users/{id}/role (existing admins only, audited).
@router.post("/api/auth/register", status_code=201)
async def register(body: RegisterBody):
    if not body.email or not body.password:
        raise HTTPException(400, "Email and password required")
    role = (body.role or "USER").strip().upper()
    if role not in ("USER", "SUPER_ADMIN"):
        raise HTTPException(400, "role must be USER or SUPER_ADMIN")
    if await repo.get_user_by_email(body.email):
        raise HTTPException(409, "Email already registered")
    if role == "SUPER_ADMIN":
        from ..db import get_prisma

        admins = await get_prisma().user.count(where={"role": "SUPER_ADMIN"})
        if admins > 0:
            raise HTTPException(
                403,
                "A Super Admin already exists. Register without a role, then ask "
                "an existing SUPER_ADMIN to promote you (Super Admin -> Users).",
            )
    user = await repo.create_user(
        body.email, body.name, auth.hash_password(body.password), role=role
    )
    token = auth.create_access_token(user["id"])
    return {"token": token, "user": user}


@router.post("/api/auth/login")
async def login(body: LoginBody):
    user = await repo.get_user_by_email(body.email)
    if not user:
        raise HTTPException(401, "Invalid credentials")
    if not auth.verify_password(body.password, user.passwordHash):
        raise HTTPException(401, "Invalid credentials")
    if getattr(user, "disabled", False):
        raise HTTPException(403, "This account has been disabled by an administrator.")
    user_dict = repo._user_dict(user)
    token = auth.create_access_token(user.id)
    return {"token": token, "user": user_dict}


@router.get("/api/auth/me")
async def me(user=Depends(auth.get_current_user)):
    return repo._user_dict(user)


# ---------------------------------------------------------------------------