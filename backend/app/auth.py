"""
Authentication: password hashing + JWT tokens + a `get_current_user` dependency.

Uses the shared Prisma client (app/db.get_prisma()) for user lookup.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Optional, Any

from fastapi import Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from passlib.context import CryptContext
from jose import jwt, JWTError

from .db import get_prisma
from . import repo

JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret-change-me")
JWT_ALGO = "HS256"
ACCESS_TOKEN_MINUTES = int(os.getenv("ACCESS_TOKEN_MINUTES", str(60 * 24 * 7)))
TOKEN_EXPIRY = timedelta(minutes=ACCESS_TOKEN_MINUTES)

# Session lives in an httpOnly cookie so the JWT is NEVER readable by
# JavaScript (XSS can't exfiltrate it). SameSite=Lax blocks cross-site POSTs
# (CSRF). The Authorization: Bearer header stays accepted for API clients.
SESSION_COOKIE = "va_session"
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "0") in ("1", "true", "TRUE", "yes")
COOKIE_MAX_AGE = ACCESS_TOKEN_MINUTES * 60


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE, token, httponly=True, samesite="lax",
        secure=COOKIE_SECURE, max_age=COOKIE_MAX_AGE, path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
bearer = HTTPBearer(auto_error=False)


# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------
def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return pwd_context.verify(password, hashed)


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------
def create_access_token(user_id: str) -> str:
    expire = datetime.utcnow() + TOKEN_EXPIRY
    payload = {"sub": user_id, "exp": expire}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


def decode_token(token: str) -> str:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
        sub = payload.get("sub")
        if not sub:
            raise ValueError("missing sub")
        return sub
    except JWTError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid token: {e}")


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------
def extract_token(request: Request, credentials: Optional[HTTPAuthorizationCredentials]) -> str:
    """Cookie session first (httpOnly, not JS-readable), Bearer header second
    (API clients). Empty string when neither is present."""
    if credentials is not None and credentials.credentials:
        return credentials.credentials
    return request.cookies.get(SESSION_COOKIE, "")


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer),
) -> Any:
    token = extract_token(request, credentials)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user_id = decode_token(token)
    user = await repo.get_user(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    if getattr(user, "disabled", False):
        # Accounts disabled by a SUPER_ADMIN are blocked even with a still-valid JWT.
        raise HTTPException(status_code=403, detail="This account has been disabled by an administrator.")
    return user


def make_id(prefix: str) -> str:
    import uuid
    return f"{prefix}_{uuid.uuid4().hex[:12]}"
