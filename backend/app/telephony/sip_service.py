"""Outbound PSTN (SIP) call + explicit agent dispatch helpers.

Extracted from telephony.py - behavior unchanged.
"""
from __future__ import annotations


import uuid
from datetime import timedelta
from typing import Any, Optional
from ..config import (
    LIVEKIT_URL,
    LIVEKIT_API_KEY,
    LIVEKIT_API_SECRET,
    DEFAULT_SIP_TRUNK_ID,
)

from .core import AGENT_NAME, _lk, _metadata, _req_creds, logger, make_room_name


async def create_sip_call(
    agent_id: str, phone: str, sip_trunk_id: Optional[str] = None, call_id: str = "", user_id: str = "",
    lead_data: Optional[dict] = None,
) -> dict:
    """Places an outbound SIP call to `phone` and returns the room/token info.

    The agent is dispatched into the room via the room's ``agents`` (agent
    dispatch) config, and the number is dialed by an outbound SIP participant.
    ``lead_data`` is passed through the room metadata so the worker can fill the
    dynamic script placeholders for this specific lead.
    """
    from livekit import api

    _req_creds()
    trunk = sip_trunk_id or DEFAULT_SIP_TRUNK_ID
    if not trunk:
        raise ValueError("No SIP trunk configured. Set DEFAULT_SIP_TRUNK_ID or pass sip_trunk_id.")

    room = make_room_name()
    metadata = _metadata(agent_id, "sip", phone, call_id, user_id, lead_data)

    client = api.LiveKitAPI(LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
    try:
        # 1) Create the room and auto-dispatch the LiveKit worker into it.
        await _lk(
            client.room.create_room(
                api.CreateRoomRequest(
                    name=room,
                    empty_timeout=300,   # seconds before an empty room auto-closes
                    agents=[api.RoomAgentDispatch(agent_name=AGENT_NAME, metadata=metadata)],
                )
            ),
            timeout=8.0,
            op="CreateRoom",
        )

        # 2) Dial the number through the SIP trunk. If this fails the room would
        # otherwise sit with an agent dispatch and no caller — clean it up.
        try:
            resp = await _lk(
                client.sip.create_sip_participant(
                    api.CreateSIPParticipantRequest(
                        room_name=room,
                        participant_identity="phone-" + uuid.uuid4().hex[:6],
                        sip_call_to=phone,          # e.g. +9180XXXXXXX
                        krisp_enabled=False,
                    ),
                    trunk_id=trunk,
                ),
                timeout=15.0,
                op="CreateSIPParticipant",
            )
        except Exception:
            try:
                await _lk(
                    client.room.delete_room(api.room_service.DeleteRoomRequest(room=room)),
                    timeout=5.0,
                    op="DeleteRoom",
                )
            except Exception:
                pass
            raise
    finally:
        await client.aclose()

    logger.info("[ROOM_CREATED] room=%s agent_id=%s mode=sip phone=%s", room, agent_id, phone)

    return {
        "room": room,
        "url": LIVEKIT_URL,
        "mode": "sip",
        "agent_token": None,   # agent is dispatched via the room's agents config
        "sip_participant": getattr(resp, "participant_id", ""),
        "sip_trunk_id": trunk,
    }

async def create_agent_dispatch(room_name: str, metadata: str) -> Optional[str]:
    """Explicitly dispatch the agent into an EXISTING room; returns the dispatch id.

    This is the self-healing path for "the server accepted the dispatch at room
    creation but no worker ever got offered the job": self-hosted LiveKit drops
    an agent dispatch when no worker is registered for the agent name at that
    instant, and (server-version dependent) may not retry it when the worker
    registers seconds later. Creating the dispatch again — once the worker IS
    registered — is the exact, minimal remediation.
    """
    try:
        from livekit import api
        _req_creds()
    except Exception:
        return None
    if not hasattr(api, "CreateAgentDispatchRequest"):
        return None
    client = api.LiveKitAPI(LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
    try:
        if not hasattr(client, "agent_dispatch"):
            return None
        resp = await _lk(
            client.agent_dispatch.create_dispatch(
                api.CreateAgentDispatchRequest(
                    agent_name=AGENT_NAME,
                    room=room_name,
                    metadata=metadata,
                )
            ),
            timeout=6.0,
            op="CreateAgentDispatch",
        )
        dispatch_id = getattr(getattr(resp, "agent_dispatch", resp), "id", "") or ""
        logger.info(
            "[AGENT_DISPATCH_SENT] room=%s agent=%s dispatch_id=%s",
            room_name, AGENT_NAME, dispatch_id or "?",
        )
        return dispatch_id
    except Exception as e:
        logger.warning("[AGENT_DISPATCH_WARN] room=%s: %s", room_name, e)
        return None
    finally:
        try:
            await client.aclose()
        except Exception:
            pass
