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
# This PUBLIC endpoint only ever creates USER accounts — NEVER admins.
# The first SUPER_ADMIN is created via the key-protected, one-time
# /api/setup/super-admin (see routes/setup_routes.py); later promotions go
# through the audited /api/admin/users/{id}/role path.
@router.post("/api/auth/register", status_code=201)
async def register(body: RegisterBody):
    if not body.email or not body.password:
        raise HTTPException(400, "Email and password required")
    if await repo.get_user_by_email(body.email):
        raise HTTPException(409, "Email already registered")
    user = await repo.create_user(body.email, body.name, auth.hash_password(body.password))
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