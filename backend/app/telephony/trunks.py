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


async def ensure_inbound_trunk(*, name: str, number: str,
                               username: str, password: str) -> str:
    """Create (or reuse) the LiveKit inbound trunk accepting VoiceLink calls
    for this DID. Returns the ST_... id."""
    api, client = _client()
    try:
        existing = _find(await _list_inbound(client, api), name, number)
        if existing is not None:
            return str(getattr(existing, "sip_trunk_id", "") or "")
        info = api.SIPInboundTrunkInfo(
            name=name, numbers=[number],
            auth_username=username, auth_password=password)
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
        logger.info("[SIP_TRUNK_CREATED] kind=inbound name=%s id=%s", name, trunk_id)
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
