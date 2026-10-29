"""LiveKit SIP trunk + inbound dispatch-rule provisioning.

This is management-plane code only: it creates the SIP resources that route
calls into rooms. The voice pipeline (app/agents/*) is untouched — inbound
calls reach the existing worker through the standard dispatch-rule
``room_config.agents[].metadata`` JSON the worker already parses
(agent_id / mode / user_id).

SDK method names differ slightly across livekit versions
(create_sip_outbound_trunk vs create_outbound_trunk, ...), so every call
goes through a first-available-method helper.
"""
from __future__ import annotations

from typing import Any, Optional

from ..config import LIVEKIT_API_KEY, LIVEKIT_API_SECRET, LIVEKIT_URL
from .core import AGENT_NAME, _lk, _req_creds, logger


def _client():
    from livekit import api
    _req_creds()
    return api, api.LiveKitAPI(LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET)


def _method(obj: Any, *names: str):
    for n in names:
        m = getattr(obj, n, None)
        if callable(m):
            return m
    raise RuntimeError(f"LiveKit SDK is missing one of: {', '.join(names)}")


def _items(resp: Any) -> list:
    for attr in ("items", "trunks", "rules", "dispatch_rules"):
        v = getattr(resp, attr, None)
        if v is not None:
            return list(v)
    return []


async def _list_outbound(client, api) -> list:
    resp = await _lk(
        _method(client.sip, "list_outbound_trunk", "list_sip_outbound_trunk")(
            api.ListSIPOutboundTrunkRequest()),
        timeout=10.0, op="ListSIPOutboundTrunk")
    return _items(resp)


async def _list_inbound(client, api) -> list:
    resp = await _lk(
        _method(client.sip, "list_inbound_trunk", "list_sip_inbound_trunk")(
            api.ListSIPInboundTrunkRequest()),
        timeout=10.0, op="ListSIPInboundTrunk")
    return _items(resp)


def _find(trunks: list, name: str, number: str = "") -> Optional[Any]:
    for t in trunks:
        if getattr(t, "name", "") == name:
            return t
    if number:
        for t in trunks:
            if number in list(getattr(t, "numbers", []) or []):
                return t
    return None


def _number_variants(number: str) -> list[str]:
    """VoiceLink presents Indian DIDs as 91... while our DB uses +91...

    LiveKit currently normalizes both forms when matching, but keep both
    explicit so older/self-hosted builds do not depend on that detail.
    """
    raw = str(number or "").strip()
    digits = raw[1:] if raw.startswith("+") else raw
    variants = [raw]
    if digits.isdigit():
        variants.extend([f"+{digits}", digits])
    return list(dict.fromkeys(v for v in variants if v))


def _inbound_reconcile_update(existing: Any, number: str,
                              allowed_addresses: Optional[list[str]]):
    """Return field updates that make an inbound trunk VoiceLink-safe.

    VoiceLink delivers inbound INVITEs by source-IP trust and does not
    answer LiveKit's 407 digest challenge, so inbound auth must be blank.
    ``allowed_addresses=None`` preserves any restriction already present;
    a list (including empty) is the operator-configured desired state.
    """
    existing_numbers = [str(v) for v in list(
        getattr(existing, "numbers", []) or [])]
    numbers = list(existing_numbers)
    for value in _number_variants(number):
        if value not in numbers:
            numbers.append(value)

    existing_allowed = [str(v).strip() for v in list(
        getattr(existing, "allowed_addresses", []) or []) if str(v).strip()]
    desired_allowed = (
        list(existing_allowed) if allowed_addresses is None
        else [str(v).strip() for v in allowed_addresses if str(v).strip()])
    has_auth = bool(
        str(getattr(existing, "auth_username", "") or "")
        or str(getattr(existing, "auth_password", "") or ""))
    if (not has_auth and numbers == existing_numbers
            and set(desired_allowed) == set(existing_allowed)):
        return None
    return {
        "numbers": numbers,
        "allowed_addresses": desired_allowed,
        "auth_username": "",
        "auth_password": "",
    }


async def ensure_outbound_trunk(*, name: str, address: str, number: str,
                                username: str, password: str) -> str:
    """Create (or reuse by name/number) the LiveKit outbound trunk that dials
    through VoiceLink. Returns the ST_... id."""
    api, client = _client()
    try:
        existing = _find(await _list_outbound(client, api), name, number)
        if existing is not None:
            return str(getattr(existing, "sip_trunk_id", "") or "")
        kwargs = {"name": name, "address": address, "numbers": [number],
                  "auth_username": username, "auth_password": password}
        transport = getattr(getattr(api, "SIPTransport", None),
                            "SIP_TRANSPORT_UDP", None)
        try:
            info = api.SIPOutboundTrunkInfo(
                **({**kwargs, "transport": transport} if transport is not None
                   else kwargs))
        except Exception:
            info = api.SIPOutboundTrunkInfo(**kwargs)
        resp = await _lk(
            _method(client.sip, "create_outbound_trunk",
                    "create_sip_outbound_trunk")(
                api.CreateSIPOutboundTrunkRequest(trunk=info)),
            timeout=15.0, op="CreateSIPOutboundTrunk")
        trunk_id = str(getattr(resp, "sip_trunk_id", "") or "")
        if not trunk_id:
            raise RuntimeError("LiveKit did not return an outbound trunk id")
        logger.info("[SIP_TRUNK_CREATED] kind=outbound name=%s id=%s", name, trunk_id)
        return trunk_id
    finally:
        await client.aclose()


async def ensure_inbound_trunk(
        *, name: str, number: str,
        allowed_addresses: Optional[list[str]] = None) -> str:
    """Create or reconcile the LiveKit inbound trunk for this VoiceLink DID.

    The VoiceLink trunk password is only for our outbound leg *to*
    VoiceLink. It must not be copied into LiveKit inbound auth: VoiceLink
    sends the inbound INVITE without a Proxy-Authorization header, causing
    LiveKit to return 407 and the caller to hear one ring then disconnect.
    Returns the ST_... id.
    """
    api, client = _client()
    try:
        trunks = await _list_inbound(client, api)
        existing = None
        for candidate in _number_variants(number):
            existing = _find(trunks, name, candidate)
            if existing is not None:
                break
        if existing is not None:
            trunk_id = str(getattr(existing, "sip_trunk_id", "") or "")
            if not trunk_id:
                raise RuntimeError("LiveKit inbound trunk is missing its id")
            update = _inbound_reconcile_update(
                existing, number, allowed_addresses)
            if update is not None:
                await _lk(
                    _method(client.sip, "update_inbound_trunk_fields",
                            "update_sip_inbound_trunk_fields")(
                        trunk_id, **update),
                    timeout=15.0, op="UpdateSIPInboundTrunk")
                logger.info(
                    "[SIP_TRUNK_UPDATED] kind=inbound name=%s id=%s "
                    "auth=cleared allowed_addresses=%d",
                    name, trunk_id, len(update["allowed_addresses"]))
            return trunk_id

        desired_allowed = [] if allowed_addresses is None else [
            str(v).strip() for v in allowed_addresses if str(v).strip()]
        info = api.SIPInboundTrunkInfo(
            name=name, numbers=_number_variants(number),
            allowed_addresses=desired_allowed)
        if hasattr(info, "krisp_enabled"):
            try:
                info.krisp_enabled = False
            except Exception:
                pass
        resp = await _lk(
            _method(client.sip, "create_inbound_trunk",
                    "create_sip_inbound_trunk")(
                api.CreateSIPInboundTrunkRequest(trunk=info)),
            timeout=15.0, op="CreateSIPInboundTrunk")
        trunk_id = str(getattr(resp, "sip_trunk_id", "") or "")
        if not trunk_id:
            raise RuntimeError("LiveKit did not return an inbound trunk id")
        logger.info(
            "[SIP_TRUNK_CREATED] kind=inbound name=%s id=%s auth=none "
            "allowed_addresses=%d",
            name, trunk_id, len(desired_allowed))
        return trunk_id
    finally:
        await client.aclose()


async def list_dispatch_rules() -> list:
    api, client = _client()
    try:
        resp = await _lk(
            _method(client.sip, "list_dispatch_rule", "list_sip_dispatch_rule")(
                api.ListSIPDispatchRuleRequest()),
            timeout=10.0, op="ListSIPDispatchRule")
        return _items(resp)
    finally:
        await client.aclose()


async def create_dispatch_rule(*, name: str, trunk_id: str, metadata: str,
                               room_prefix: str) -> str:
    """Route every call on this inbound trunk into its own room and dispatch
    the existing voice worker with `metadata` (agent_id/mode/user_id JSON)."""
    api, client = _client()
    try:
        info = api.SIPDispatchRuleInfo(
            rule=api.SIPDispatchRule(
                dispatch_rule_individual=api.SIPDispatchRuleIndividual(
                    room_prefix=room_prefix)),
            name=name,
            trunk_ids=[trunk_id],
            room_config=api.RoomConfiguration(agents=[
                api.RoomAgentDispatch(agent_name=AGENT_NAME, metadata=metadata)]),
        )
        resp = await _lk(
            _method(client.sip, "create_dispatch_rule",
                    "create_sip_dispatch_rule")(
                api.CreateSIPDispatchRuleRequest(dispatch_rule=info)),
            timeout=15.0, op="CreateSIPDispatchRule")
        rule_id = str(getattr(resp, "sip_dispatch_rule_id", "") or "")
        if not rule_id:
            raise RuntimeError("LiveKit did not return a dispatch rule id")
        logger.info("[SIP_DISPATCH_CREATED] name=%s id=%s trunk=%s",
                    name, rule_id, trunk_id)
        return rule_id
    finally:
        await client.aclose()


async def delete_dispatch_rule(rule_id: str) -> bool:
    if not rule_id:
        return False
    api, client = _client()
    try:
        await _lk(
            _method(client.sip, "delete_dispatch_rule",
                    "delete_sip_dispatch_rule")(
                api.DeleteSIPDispatchRuleRequest(sip_dispatch_rule_id=rule_id)),
            timeout=10.0, op="DeleteSIPDispatchRule")
        return True
    except Exception as e:
        logger.warning("[SIP_DISPATCH_DELETE_WARN] id=%s: %s", rule_id, e)
        return False
    finally:
        await client.aclose()


async def delete_trunk(trunk_id: str) -> bool:
    if not trunk_id:
        return False
    api, client = _client()
    try:
        await _lk(
            _method(client.sip, "delete_trunk", "delete_sip_trunk")(
                api.DeleteSIPTrunkRequest(sip_trunk_id=trunk_id)),
            timeout=10.0, op="DeleteSIPTrunk")
        return True
    except Exception as e:
        logger.warning("[SIP_TRUNK_DELETE_WARN] id=%s: %s", trunk_id, e)
        return False
    finally:
        await client.aclose()
