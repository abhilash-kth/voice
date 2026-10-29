"""Agent purpose rules + outbound trunk derivation.

The rules the whole marketplace hangs on:
* purpose outbound|both  -> may place SIP calls and run campaigns
* purpose inbound|both   -> may receive DID calls via a dispatch rule
* an assigned purchased number fully determines the outbound LiveKit trunk,
  caller ID and carrier dial prefix — a client-supplied trunk id is ignored
  for such agents, so one tenant can never dial through another's trunk.
"""
from __future__ import annotations

import re
from typing import Optional

from .. import repo

PURPOSES = ("outbound", "inbound", "both")


class TelephonyError(Exception):
    """User-visible telephony problem; routes map it to an HTTP status."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def agent_purpose(agent: Optional[dict]) -> str:
    p = str((agent or {}).get("purpose") or "outbound").lower()
    return p if p in PURPOSES else "outbound"


def can_outbound(agent: Optional[dict]) -> bool:
    return agent_purpose(agent) in ("outbound", "both")


def can_inbound(agent: Optional[dict]) -> bool:
    return agent_purpose(agent) in ("inbound", "both")


def require_outbound(agent: dict, action: str = "place outbound calls") -> None:
    if not can_outbound(agent):
        raise TelephonyError(
            f"Agent '{agent.get('name', '')}' is an inbound-only agent and "
            f"cannot {action}. Change its purpose to Outbound or Both first.",
            400)


def normalize_destination(phone: str) -> str:
    """Customer-visible destination as E.164-ish (+91 default for bare
    Indian numbers, matching campaign lead files)."""
    digits = re.sub(r"\D", "", str(phone or ""))
    if not digits:
        return str(phone or "")
    if len(digits) == 10:
        digits = "91" + digits
    elif len(digits) == 11 and digits.startswith("0"):
        digits = "91" + digits[1:]
    return "+" + digits


def carrier_dial_number(phone: str, dial_prefix: str = "") -> str:
    """VoiceLink dial string: <tech-prefix><country><number>, digits only
    (proven format 45454+91+10-digit). No prefix -> plain E.164."""
    digits = re.sub(r"\D", "", normalize_destination(phone))
    prefix = re.sub(r"\D", "", str(dial_prefix or ""))
    if not prefix:
        return "+" + digits if digits else str(phone or "")
    if digits.startswith(prefix):
        return digits
    return prefix + digits


async def validate_agent_phone_assignment(
        user_id: str, purpose: str, phone_number_id: Optional[str],
        current_agent_id: str = "") -> Optional[dict]:
    """Validate an agent create/update purpose+number pairing.

    Returns the PhoneNumber dict (or None). Raises TelephonyError when the
    number is not the user's, is not active, or another inbound-capable
    agent already receives calls on it (one inbound target per DID).
    """
    if purpose not in PURPOSES:
        raise TelephonyError("Purpose must be outbound, inbound, or both.", 400)
    if not phone_number_id:
        return None
    phone = await repo.get_phone_number(phone_number_id, user_id)
    if not phone:
        raise TelephonyError(
            "Selected phone number was not found in your numbers.", 400)
    if phone["status"] != "active":
        raise TelephonyError(
            f"Phone number {phone['number']} is {phone['status']}, not active. "
            "Finish its activation on the Phone Numbers page first.", 400)
    if purpose in ("inbound", "both"):
        others = await repo.list_agents_for_phone(phone_number_id, user_id)
        for other in others:
            if other["id"] == current_agent_id:
                continue
            if can_inbound(other):
                raise TelephonyError(
                    f"{phone['number']} already receives inbound calls for "
                    f"agent '{other.get('name', '')}'. A number can route "
                    "inbound calls to only one agent.", 409)
    return phone


async def resolve_outbound(agent: dict, user_id: str,
                           requested_trunk_id: str = "") -> dict:
    """Server-side outbound routing for one agent.

    Assigned number -> its stored LiveKit trunk/caller-ID/prefix (requested
    trunk ignored). No assigned number -> legacy requested/default trunk so
    the original single-trunk setup keeps working.
    """
    require_outbound(agent)
    phone_id = agent.get("phone_number_id")
    if phone_id:
        phone = await repo.get_phone_number(phone_id, user_id)
        if not phone:
            raise TelephonyError(
                "This agent's assigned phone number no longer exists. "
                "Edit the agent and choose another number.", 400)
        if phone["status"] != "active":
            raise TelephonyError(
                f"Assigned number {phone['number']} is {phone['status']}, "
                "not active, so it cannot place calls yet.", 400)
        trunk = phone.get("livekit_outbound_trunk_id") or ""
        if not trunk:
            raise TelephonyError(
                f"Assigned number {phone['number']} has no activated SIP "
                "trunk yet. Retry activation on the Phone Numbers page.", 400)
        if phone.get("voice_link_account_id"):
            account = await repo.get_account(phone["voice_link_account_id"])
            if account and account["status"] == "suspended":
                raise TelephonyError(
                    "Your telephony account is suspended. Contact support.", 403)
        return {
            "sip_trunk_id": trunk,
            "caller_id": phone["number"],
            "dial_prefix": phone.get("dial_prefix") or "",
            "phone_number_id": phone["id"],
            "phone_number": phone["number"],
        }
    from . import telephony_settings
    settings = await telephony_settings.get_settings()
    return {
        "sip_trunk_id": (requested_trunk_id
                         or settings.default_sip_trunk_id or ""),
        "caller_id": "",
        "dial_prefix": "",
        "phone_number_id": None,
        "phone_number": "",
    }
