"""Automatic SIP activation for purchased numbers.

Idempotent, resumable steps (each persisted before the next external call):
  credentials -> VoiceLink SIP trunk -> VoiceLink call routing ->
  LiveKit outbound trunk -> LiveKit inbound trunk -> inbound dispatch rule
  (synced from the assigned agent's purpose).

The voice pipeline is not modified: the dispatch rule passes the same job
metadata JSON (agent_id/mode/user_id) the existing worker already parses.
"""
from __future__ import annotations

import json
import logging
import re
import secrets
import string
from typing import Optional

from .. import repo
from ..telephony import trunks as lk_trunks
from . import telephony_settings
from . import voicelink_client as vl
from .crypto import decrypt_secret, encrypt_secret
from .telephony_policy import TelephonyError, normalize_destination

logger = logging.getLogger("voice-agent-saas-provisioning")


def _short(phone_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]", "", phone_id)[-10:] or "number"


def _new_password() -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(24))


async def _ensure_credentials(phone: dict) -> tuple[str, str]:
    username = phone.get("sip_username") or ""
    password = ""
    if phone.get("_sip_password_enc"):
        try:
            password = decrypt_secret(phone["_sip_password_enc"])
        except Exception:
            password = ""
    patch: dict = {}
    if not username:
        username = "trunk_" + secrets.token_hex(6)
        patch["sip_username"] = username
    if not password:
        password = _new_password()
        enc, masked = encrypt_secret(password)
        patch["sip_password_enc"] = enc
        patch["sip_password_masked"] = masked
    if patch:
        await repo.update_phone_number(phone["id"], patch)
    return username, password


def _record(data: dict) -> dict:
    for key in ("trunk", "sip_trunk", "routing", "call_routing", "data"):
        if isinstance(data.get(key), dict):
            return data[key]
    return data


def _trunk_host(value) -> str:
    host = re.sub(r"^sip:", "", str(value or "").strip().lower())
    return host.split("/", 1)[0].split(":", 1)[0].rstrip(".")


def _trunk_active(row: dict) -> bool:
    return row.get("status") in (1, "1", True) or str(
        row.get("status_label") or "").strip().lower() == "active"


def _find_voicelink_trunk(rows: list[dict], *, trunk_name: str, username: str,
                          host: str, client_id: str,
                          shared: bool = False) -> Optional[dict]:
    """Find this DID's trunk, else the one trunk VoiceLink allows per host."""
    usable: list[dict] = []
    wanted_host = _trunk_host(host)
    for row in rows:
        if not vl.id_of(row, "id", "trunk_id", "sip_trunk_id"):
            continue
        owner = vl.id_of(row, "client_id")
        if not shared and owner and owner != str(client_id):
            continue
        usable.append(row)
        if str(row.get("trunk_name") or row.get("name") or "") == trunk_name \
                or str(row.get("username") or "") == username:
            return row
    host_rows = [row for row in usable
                 if _trunk_host(row.get("sip_server_host")) == wanted_host]
    return next((row for row in host_rows if _trunk_active(row)),
                host_rows[0] if host_rows else None)


async def _sync_voicelink_trunk(found: dict, settings, *, exact: bool,
                                username: str, password: str) -> dict:
    """Repoint/activate a reused trunk without rotating shared credentials."""
    trunk_id = vl.id_of(found, "id", "trunk_id", "sip_trunk_id")
    try:
        port_matches = int(found.get("sip_server_port")) \
            == int(settings.livekit_sip_port)
    except (TypeError, ValueError):
        port_matches = False
    transport = found.get("transport_type")
    needs_update = (
        _trunk_host(found.get("sip_server_host"))
        != _trunk_host(settings.livekit_sip_host)
        or not port_matches
        or (transport not in (None, "")
            and str(transport) != str(settings.voicelink_transport_type))
        or ("status" in found and not _trunk_active(found)))
    if not needs_update or not trunk_id:
        return found
    payload = {
        "trunk_name": str(found.get("trunk_name") or found.get("name")
                          or "voxura-livekit"),
        "status": 1,
        "sip_server_host": settings.livekit_sip_host,
        "sip_server_port": settings.livekit_sip_port,
        "transport_type": settings.voicelink_transport_type,
        "audio_format": list(settings.voicelink_audio_formats),
    }
    if exact:
        payload.update({"username": username,
                        "registration_password": password})
    elif found.get("username") and (found.get("registration_password")
                                     or found.get("password")):
        payload.update({
            "username": str(found["username"]),
            "registration_password": str(
                found.get("registration_password") or found.get("password")),
        })
    updated = _record(await vl.update_sip_trunk(trunk_id, payload))
    merged = dict(found)
    merged.update({key: value for key, value in updated.items()
                   if value not in (None, "")})
    return merged


async def _fail(phone_id: str, step: str, exc: Exception):
    msg = str(exc)[:500]
    await repo.update_phone_number(phone_id, {
        "status": "failed", "provisioning_step": step, "last_error": msg})
    status = getattr(exc, "status_code", 502)
    raise TelephonyError(msg, status if isinstance(status, int) else 502)


async def provision_number(phone_id: str,
                           user_id: Optional[str] = None) -> dict:
    phone = await repo.get_phone_number(phone_id, user_id, include_secret=True)
    if not phone:
        raise TelephonyError("Phone number not found.", 404)
    if phone["status"] in ("suspended", "released"):
        raise TelephonyError(f"Number is {phone['status']} and cannot be "
                             "provisioned.", 409)
    if phone["source"] == "manual":
        ready = bool(phone.get("livekit_outbound_trunk_id"))
        phone = await repo.update_phone_number(phone_id, {
            "status": "active" if ready else "provisioning",
            "provisioning_step": "manual_ready" if ready else "manual_pending",
            "last_error": "" if ready else "Manual number has no LiveKit trunk.",
        }) or phone
        await _sync_inbound_best_effort(phone_id)
        return await repo.get_phone_number(phone_id, user_id) or phone

    account = None
    if phone.get("voice_link_account_id"):
        account = await repo.get_account(phone["voice_link_account_id"])
    if not account:
        account = await repo.get_account_by_user(phone["user_id"])
    if not account or not account.get("client_id"):
        await _fail(phone_id, "account_missing",
                    TelephonyError("VoiceLink account is missing for this "
                                   "number. Set up the telephony account first.", 409))
    if account["kyc_status"] != "verified":
        await repo.update_phone_number(phone_id, {
            "status": "provisioning", "provisioning_step": "waiting_kyc",
            "last_error": "KYC must be verified before SIP activation."})
        raise TelephonyError(
            "KYC must be verified before this number can be activated.", 409)
    settings = await telephony_settings.get_settings()
    if not settings.livekit_sip_host:
        await _fail(phone_id, "config_missing", TelephonyError(
            "LiveKit public SIP host is not configured in Super Admin -> "
            "Telephony -> Settings.", 503))

    client_id = account["client_id"]
    step = "credentials"
    await repo.update_phone_number(phone_id, {
        "status": "provisioning", "provisioning_step": step, "last_error": ""})
    try:
        username, password = await _ensure_credentials(phone)

        # 1) VoiceLink SIP trunk -> our LiveKit SIP service.
        step = "voicelink_trunk"
        if not phone.get("voice_link_trunk_id"):
            trunk_name = f"voxura-{_short(phone_id)}"
            found = _find_voicelink_trunk(
                await vl.list_sip_trunks(client_id), trunk_name=trunk_name,
                username=username, host=settings.livekit_sip_host,
                client_id=client_id)
            if found is None:
                # VoiceLink permits one trunk per SIP server host across the
                # reseller account. A trunk already targeting our configured
                # LiveKit SIP host is therefore the platform trunk to reuse,
                # even when VoiceLink records it under another managed client.
                found = _find_voicelink_trunk(
                    await vl.list_sip_trunks(), trunk_name=trunk_name,
                    username=username, host=settings.livekit_sip_host,
                    client_id=client_id, shared=True)
            exact_reuse = bool(found and (
                str(found.get("trunk_name") or found.get("name") or "")
                == trunk_name
                or str(found.get("username") or "") == username))
            if found is not None:
                if not exact_reuse:
                    returned_pw = found.get("registration_password") \
                        or found.get("password")
                    if not found.get("username") or not returned_pw:
                        raise TelephonyError(
                            "VoiceLink already has a SIP trunk for this "
                            "LiveKit host, but did not return its SIP "
                            "credentials needed to reuse it safely. Check the "
                            "existing trunk in VoiceLink; do not buy another "
                            "number.", 502)
                    logger.info(
                        "[PROVISION_TRUNK_REUSE] phone=%s host=%s "
                        "same_client=%s", phone_id,
                        _trunk_host(settings.livekit_sip_host),
                        vl.id_of(found, "client_id") in ("", str(client_id)))
                found = await _sync_voicelink_trunk(
                    found, settings, exact=exact_reuse,
                    username=username, password=password)
            if found is None:
                found = _record(await vl.create_sip_trunk({
                    "trunk_name": trunk_name,
                    "sip_server_host": settings.livekit_sip_host,
                    "sip_server_port": settings.livekit_sip_port,
                    "transport_type": settings.voicelink_transport_type,
                    "audio_format": list(settings.voicelink_audio_formats),
                    "username": username,
                    "registration_password": password,
                    "status": 1,
                    "client_id": vl.int_id(client_id),
                }))
            trunk_id = vl.id_of(found, "id", "trunk_id", "sip_trunk_id")
            if not trunk_id:
                raise TelephonyError(
                    "VoiceLink trunk created but no trunk id was returned. "
                    "Retry activation to reconcile.", 502)
            patch = {"voice_link_trunk_id": trunk_id,
                     "provisioning_step": "voicelink_trunk_ready"}
            if found.get("username") and str(found["username"]) != username:
                username = str(found["username"])
                patch["sip_username"] = username
            returned_pw = found.get("registration_password") or found.get("password")
            if returned_pw and str(returned_pw) != password:
                password = str(returned_pw)
                enc, masked = encrypt_secret(password)
                patch["sip_password_enc"] = enc
                patch["sip_password_masked"] = masked
            prefix = vl.id_of(found, "tech_prefix", "prefix", "dial_prefix",
                              "outbound_prefix")
            patch["dial_prefix"] = prefix or phone.get("dial_prefix") \
                or settings.voicelink_tech_prefix
            await repo.update_phone_number(phone_id, patch)
            phone["voice_link_trunk_id"] = trunk_id

        # 2) VoiceLink call routing: DID <-> SIP trunk, both directions.
        step = "voicelink_routing"
        if not phone.get("voice_link_routing_id"):
            routing_payload = {
                "for_inbound_call": 2,   # SIP trunk
                "for_outbound_call": 2,  # SIP trunk
                "inbound_sip_trunk_id": vl.int_id(phone["voice_link_trunk_id"]),
                "outbound_sip_trunk_id": vl.int_id(phone["voice_link_trunk_id"]),
                "status": 1,
            }
            existing = None
            for row in await vl.list_routing(client_id):
                if str(row.get("did_id") or "") == str(phone.get("provider_did_id")) \
                        or vl.normalize_in_number(row.get("did_number")) == phone["number"]:
                    existing = row
                    break
            if existing:
                routing_id = vl.id_of(existing, "id")
                await vl.update_routing(routing_id, routing_payload)
            else:
                create_payload = dict(routing_payload)
                if str(phone.get("provider_did_id") or "").isdigit():
                    create_payload["did_id"] = int(phone["provider_did_id"])
                else:
                    create_payload["did_number"] = phone["number"].lstrip("+")
                created = _record(await vl.create_routing(create_payload))
                routing_id = vl.id_of(created, "id", "routing_id")
            if routing_id:
                await repo.update_phone_number(phone_id, {
                    "voice_link_routing_id": routing_id,
                    "provisioning_step": "routing_ready"})
                phone["voice_link_routing_id"] = routing_id

        # 3) LiveKit outbound trunk (dial out through VoiceLink).
        step = "livekit_outbound"
        outbound_id = await lk_trunks.ensure_outbound_trunk(
            name=f"voicelink-out-{_short(phone_id)}",
            address=f"{settings.voicelink_sip_host}:{settings.voicelink_sip_port}",
            number=phone["number"], username=username, password=password)
        await repo.update_phone_number(phone_id, {
            "livekit_outbound_trunk_id": outbound_id,
            "provisioning_step": "livekit_outbound_ready"})

        # 4) LiveKit inbound trunk (best effort; outbound stays usable).
        step = "livekit_inbound"
        inbound_error = ""
        try:
            inbound_id = await lk_trunks.ensure_inbound_trunk(
                name=f"voicelink-in-{_short(phone_id)}",
                number=phone["number"], username=username, password=password)
            await repo.update_phone_number(phone_id, {
                "livekit_inbound_trunk_id": inbound_id})
        except Exception as e:
            inbound_error = f"Inbound trunk pending: {e}"[:500]
            logger.warning("[PROVISION_INBOUND_WARN] phone=%s: %s", phone_id, e)
    except TelephonyError as e:
        await _fail(phone_id, step, e)
    except Exception as e:
        await _fail(phone_id, step, e)

    phone = await repo.update_phone_number(phone_id, {
        "status": "active",
        "provisioning_step": "livekit_ready" if not inbound_error
        else "outbound_ready_inbound_pending",
        "last_error": inbound_error,
    }) or phone
    await _sync_inbound_best_effort(phone_id)
    return await repo.get_phone_number(phone_id, user_id) or phone


async def _sync_inbound_best_effort(phone_id: str) -> None:
    try:
        await sync_inbound_dispatch(phone_id)
    except Exception as e:
        logger.warning("[INBOUND_SYNC_WARN] phone=%s: %s", phone_id, e)
        try:
            await repo.update_phone_number(
                phone_id, {"last_error": f"Inbound sync pending: {e}"[:500]})
        except Exception:
            pass


async def sync_inbound_dispatch(phone_id: str,
                                user_id: Optional[str] = None) -> dict:
    """Make the LiveKit dispatch rule match the number's inbound agent
    (the single enabled inbound|both agent assigned to it), or remove it."""
    phone = await repo.get_phone_number(phone_id, user_id, include_secret=True)
    if not phone:
        raise TelephonyError("Phone number not found.", 404)
    targets = await repo.find_inbound_agents_for_phone(phone_id, phone["user_id"])
    if len(targets) > 1:
        msg = ("More than one inbound agent is assigned to this number. "
               "Keep only one inbound/both agent on it.")
        await repo.update_phone_number(phone_id, {"last_error": msg})
        raise TelephonyError(msg, 409)
    if not targets or phone["status"] in ("suspended", "released"):
        if phone.get("livekit_dispatch_rule_id"):
            await lk_trunks.delete_dispatch_rule(phone["livekit_dispatch_rule_id"])
            phone = await repo.update_phone_number(phone_id, {
                "livekit_dispatch_rule_id": "", "inbound_agent_id": None}) or phone
        return await repo.get_phone_number(phone_id, user_id) or phone
    if phone["status"] != "active":
        raise TelephonyError(
            f"Number {phone['number']} is {phone['status']}, not active; "
            "inbound routing starts after activation.", 409)

    target = targets[0]
    inbound_trunk = phone.get("livekit_inbound_trunk_id") or ""
    if not inbound_trunk:
        if phone["source"] != "voicelink":
            raise TelephonyError(
                "This manual number has no LiveKit inbound trunk configured.", 400)
        username, password = await _ensure_credentials(phone)
        inbound_trunk = await lk_trunks.ensure_inbound_trunk(
            name=f"voicelink-in-{_short(phone_id)}", number=phone["number"],
            username=username, password=password)
        await repo.update_phone_number(
            phone_id, {"livekit_inbound_trunk_id": inbound_trunk})

    desired_name = f"voicelink-in-{_short(phone_id)}"
    if phone.get("livekit_dispatch_rule_id") \
            and phone.get("inbound_agent_id") == target["id"]:
        try:
            live = {str(getattr(r, "sip_dispatch_rule_id", "") or "")
                    for r in await lk_trunks.list_dispatch_rules()}
            if phone["livekit_dispatch_rule_id"] in live:
                return await repo.get_phone_number(phone_id, user_id) or phone
        except Exception:
            return await repo.get_phone_number(phone_id, user_id) or phone
    # Remove any stale rule for this trunk/name before creating the new one.
    try:
        for r in await lk_trunks.list_dispatch_rules():
            rid = str(getattr(r, "sip_dispatch_rule_id", "") or "")
            if rid and (getattr(r, "name", "") == desired_name
                        or inbound_trunk in list(getattr(r, "trunk_ids", []) or [])):
                await lk_trunks.delete_dispatch_rule(rid)
    except Exception as e:
        logger.warning("[INBOUND_SYNC_CLEANUP_WARN] phone=%s: %s", phone_id, e)
    if phone.get("livekit_dispatch_rule_id"):
        await lk_trunks.delete_dispatch_rule(phone["livekit_dispatch_rule_id"])

    metadata = json.dumps({
        "agent_id": target["id"], "mode": "sip", "phone": "",
        "call_id": "", "user_id": phone["user_id"], "lead_data": None,
        "direction": "inbound", "phone_number_id": phone_id,
        "did": phone["number"],
    })
    rule_id = await lk_trunks.create_dispatch_rule(
        name=desired_name, trunk_id=inbound_trunk, metadata=metadata,
        room_prefix=f"in-{_short(phone_id)}-")
    phone = await repo.update_phone_number(phone_id, {
        "livekit_dispatch_rule_id": rule_id, "inbound_agent_id": target["id"],
        "provisioning_step": "inbound_ready", "last_error": ""}) or phone
    return await repo.get_phone_number(phone_id, user_id) or phone


async def set_number_status(phone_id: str, status: str) -> dict:
    phone = await repo.get_phone_number(phone_id)
    if not phone:
        raise TelephonyError("Phone number not found.", 404)
    if status == "suspended":
        if phone.get("livekit_dispatch_rule_id"):
            await lk_trunks.delete_dispatch_rule(phone["livekit_dispatch_rule_id"])
        return await repo.update_phone_number(phone_id, {
            "status": "suspended", "livekit_dispatch_rule_id": "",
            "inbound_agent_id": None, "provisioning_step": "suspended"}) or phone
    if status == "active":
        if not phone.get("livekit_outbound_trunk_id"):
            raise TelephonyError(
                "Number has no LiveKit outbound trunk; retry provisioning "
                "instead of forcing active.", 400)
        phone = await repo.update_phone_number(
            phone_id, {"status": "active", "last_error": ""}) or phone
        await _sync_inbound_best_effort(phone_id)
        return await repo.get_phone_number(phone_id) or phone
    raise TelephonyError("Status must be active or suspended.", 400)


async def create_manual_number(user_id: str, data: dict) -> dict:
    number = normalize_destination(data.get("number") or "")
    if not number or len(re.sub(r"\D", "", number)) < 10:
        raise TelephonyError("Enter a valid phone number (E.164).", 400)
    if await repo.get_phone_by_number(number):
        raise TelephonyError(f"{number} is already registered.", 409)
    trunk = data.get("livekit_outbound_trunk_id") or ""
    settings = await telephony_settings.get_settings()
    return await repo.create_phone_number({
        "user_id": user_id, "number": number, "source": "manual",
        "status": "active" if trunk else "provisioning",
        "provisioning_step": "manual_ready" if trunk else "manual_pending",
        "channels": int(data.get("channels") or 1),
        "expires_at": data.get("expires_at") or "",
        "livekit_outbound_trunk_id": trunk,
        "livekit_inbound_trunk_id": data.get("livekit_inbound_trunk_id") or "",
        "dial_prefix": data.get("dial_prefix") or settings.voicelink_tech_prefix,
    })


async def _require_manual_phone(phone_id: str) -> dict:
    phone = await repo.get_phone_number(phone_id)
    if not phone:
        raise TelephonyError("Phone number not found.", 404)
    if phone.get("source") != "manual":
        raise TelephonyError(
            "Only manually registered numbers can be edited or deleted here. "
            "Purchased numbers remain provider-managed.", 409)
    return phone


async def update_manual_number(phone_id: str, data: dict) -> dict:
    """Edit a manual DID record (number/trunks/prefix/channels/expiry)."""
    phone = await _require_manual_phone(phone_id)
    allowed = {
        "number", "livekit_outbound_trunk_id", "livekit_inbound_trunk_id",
        "dial_prefix", "channels", "expires_at",
    }
    patch = {k: v for k, v in (data or {}).items() if k in allowed}
    if not patch:
        raise TelephonyError("No manual-number fields to update.", 400)

    if "number" in patch:
        number = normalize_destination(patch.get("number") or "")
        if not number or len(re.sub(r"\D", "", number)) < 10:
            raise TelephonyError("Enter a valid phone number (E.164).", 400)
        existing = await repo.get_phone_by_number(number)
        if existing and existing["id"] != phone_id:
            raise TelephonyError(f"{number} is already registered.", 409)
        patch["number"] = number

    for key in ("livekit_outbound_trunk_id", "livekit_inbound_trunk_id",
                "dial_prefix", "expires_at"):
        if key in patch:
            patch[key] = str(patch.get(key) or "").strip()
    if "dial_prefix" in patch and not re.fullmatch(
            r"\d*", patch["dial_prefix"]):
        raise TelephonyError("Carrier tech prefix must contain digits only.", 400)
    if "channels" in patch:
        try:
            channels = int(patch["channels"])
        except Exception:
            raise TelephonyError("Channels must be a whole number.", 400) from None
        if channels < 1 or channels > 100:
            raise TelephonyError("Channels must be between 1 and 100.", 400)
        patch["channels"] = channels

    outbound_trunk = patch.get(
        "livekit_outbound_trunk_id", phone.get("livekit_outbound_trunk_id") or "")
    if phone.get("status") == "suspended":
        patch.update({"status": "suspended", "provisioning_step": "suspended"})
    elif outbound_trunk:
        patch.update({
            "status": "active", "provisioning_step": "manual_ready",
            "last_error": "",
        })
    else:
        patch.update({
            "status": "provisioning", "provisioning_step": "manual_pending",
            "last_error": "Manual number has no LiveKit outbound trunk.",
        })

    old_rule_id = phone.get("livekit_dispatch_rule_id") or ""
    number_changed = patch.get("number", phone["number"]) != phone["number"]
    inbound_trunk_changed = patch.get(
        "livekit_inbound_trunk_id",
        phone.get("livekit_inbound_trunk_id") or "") != (
            phone.get("livekit_inbound_trunk_id") or "")

    updated = await repo.update_phone_number(phone_id, patch) or phone
    if old_rule_id and (
            updated.get("status") != "active" or number_changed
            or inbound_trunk_changed):
        await lk_trunks.delete_dispatch_rule(old_rule_id)
        updated = await repo.update_phone_number(phone_id, {
            "livekit_dispatch_rule_id": "", "inbound_agent_id": None,
        }) or updated
    if updated.get("status") == "active" and (
            number_changed or inbound_trunk_changed):
        await _sync_inbound_best_effort(phone_id)
    return await repo.get_phone_number(phone_id) or updated


async def delete_manual_number(phone_id: str) -> dict:
    """Delete a manual DID record after removing its local assignments.

    This does not delete the carrier DID or shared LiveKit trunks—manual
    numbers are externally provisioned and those resources may be shared.
    The LiveKit inbound dispatch rule owned by this record is removed.
    """
    phone = await _require_manual_phone(phone_id)
    agents = await repo.list_agents_for_phone(phone_id, phone["user_id"])
    for agent in agents:
        calls = await repo.list_calls(phone["user_id"], agent_id=agent["id"])
        if any(c.get("status") in ("planned", "in-progress") for c in calls):
            raise TelephonyError(
                f"Agent '{agent.get('name', '')}' has an active call on "
                "this number. End the call before deleting the number.", 409)

    rule_id = phone.get("livekit_dispatch_rule_id") or ""
    if rule_id and not await lk_trunks.delete_dispatch_rule(rule_id):
        raise TelephonyError(
            "Could not remove this number's LiveKit inbound routing. "
            "Check LiveKit and retry before deleting it.", 503)

    unassigned_agent_ids: list[str] = []
    for agent in agents:
        await repo.update_agent(
            agent["id"], phone["user_id"], {"phone_number_id": None})
        unassigned_agent_ids.append(agent["id"])

    if not await repo.delete_phone_number(phone_id):
        raise TelephonyError(
            "Manual number could not be deleted; it may already be gone or "
            "still referenced by another record.", 409)
    return {
        "ok": True,
        "id": phone_id,
        "number": phone["number"],
        "unassigned_agent_ids": unassigned_agent_ids,
    }
