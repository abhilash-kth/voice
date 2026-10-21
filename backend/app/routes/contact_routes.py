"""Contact form (/api/contact): public submission from the website landing
page, admin-only read-back (submissions contain personal data)."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from ..models import ContactBody
from .. import repo
from ..admin.deps import get_super_admin

router = APIRouter(tags=["contact"])


@router.post("/api/contact", status_code=201)
async def submit_contact(body: ContactBody):
    # shortcut: no rate-limit/captcha — add one if the form attracts spam.
    contact = await repo.create_contact_message(
        body.name.strip(), body.phone.strip(), body.email.strip(), body.message.strip()
    )
    return {"ok": True, "contact": contact}


@router.get("/api/contact")
async def list_contacts(_admin=Depends(get_super_admin)):
    return {"contacts": await repo.list_contact_messages()}
