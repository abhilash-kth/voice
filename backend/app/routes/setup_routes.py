"""One-time, key-protected endpoint to create the FIRST Super Admin.

The public ``/api/auth/register`` must NEVER create privileged accounts —
anyone on the internet can call it. The very first ``SUPER_ADMIN`` is created
here instead, behind TWO gates:

1. ``SUPER_ADMIN_SETUP_KEY`` (server env var, known only to the operator who
   deploys the backend). Callers must send it in the ``X-Setup-Key`` header;
   it is compared in constant time. If the env var is unset/blank, the
   endpoint is disabled entirely (403) — no key, no setup, ever.
2. Bootstrap rule: only while ZERO super admins exist in the DB. Once the
   first one exists, this endpoint is permanently closed (403); every later
   promotion goes through the audited ``/api/admin/users/{id}/role`` path
   (Super Admin → Users). A leaked key is therefore useless after setup.

The router is excluded from the OpenAPI schema so it does not show up in
``/docs``.
"""
from __future__ import annotations

import hmac
import logging
import os

from fastapi import APIRouter, Header, HTTPException

from .. import auth, repo
from ..models import RegisterBody

logger = logging.getLogger("voice-agent-saas-api")

router = APIRouter(tags=["setup"], include_in_schema=False)

SETUP_KEY_ENV = "SUPER_ADMIN_SETUP_KEY"


@router.post("/api/setup/super-admin", status_code=201)
async def create_first_super_admin(
    body: RegisterBody, x_setup_key: str = Header(default="")
):
    # Gate 1: operator setup key (checked FIRST so unauthenticated probing
    # learns nothing about DB state).
    expected = os.environ.get(SETUP_KEY_ENV, "").strip()
    if not expected:
        raise HTTPException(
            403, "Super-admin setup is disabled: SUPER_ADMIN_SETUP_KEY is not set on the server."
        )
    if not x_setup_key or not hmac.compare_digest(x_setup_key.strip(), expected):
        raise HTTPException(403, "Invalid setup key.")

    if not body.email or not body.password:
        raise HTTPException(400, "Email and password required")
    if await repo.get_user_by_email(body.email):
        raise HTTPException(409, "Email already registered")

    # Gate 2: bootstrap only — refuse once any super admin exists.
    from ..db import get_prisma

    admins = await get_prisma().user.count(where={"role": "SUPER_ADMIN"})
    if admins > 0:
        raise HTTPException(
            403,
            "A Super Admin already exists. Promote additional admins from "
            "Super Admin -> Users instead.",
        )

    user = await repo.create_user(
        body.email, body.name, auth.hash_password(body.password), role="SUPER_ADMIN"
    )
    logger.warning("BOOTSTRAP: first SUPER_ADMIN created (%s)", body.email.lower())
    token = auth.create_access_token(user["id"])
    return {"token": token, "user": user}
