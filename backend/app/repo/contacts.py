"""Contact-form submissions from the marketing website."""
from __future__ import annotations

from typing import Any

from ..db import get_prisma
from .common import _ts


def _contact_dict(c: Any) -> dict:
    return {
        "id": c.id,
        "name": c.name or "",
        "phone": c.phone or "",
        "email": c.email or "",
        "message": c.message or "",
        "created_at": c.createdAt or "",
    }


async def create_contact_message(name: str, phone: str, email: str, message: str) -> dict:
    c = await get_prisma().contactmessage.create(
        data={"name": name, "phone": phone, "email": email.lower(),
              "message": message, "createdAt": _ts()}
    )
    return _contact_dict(c)


async def list_contact_messages() -> list[dict]:
    rows = await get_prisma().contactmessage.find_many(order={"createdAt": "desc"})
    return [_contact_dict(c) for c in rows]
