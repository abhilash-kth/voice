"""
Telephony helpers for the LiveKit **v1** server SDK.

Two modes:
  * browser  : the browser joins a LiveKit room; the room is created with an
               agent dispatch rule so the LiveKit worker is dispatched into the
               room automatically when it is created. Fully free, no carrier.
  * sip      : real PSTN outbound. We create the room (with agent dispatch), then
               create an outbound SIP participant that dials the number through
               a LiveKit SIP trunk (Telnyx / Twilio). Requires a registered SIP
               trunk and the customer's SIP creds.

All ``livekit`` imports are lazy so the management API can boot without them
being installed in that interpreter.
"""
from __future__ import annotations

import uuid
import logging
from datetime import timedelta
from typing import Optional

from .config import (
    LIVEKIT_URL,
    LIVEKIT_API_KEY,
    LIVEKIT_API_SECRET,
    DEFAULT_SIP_TRUNK_ID,
)

logger = logging.getLogger("voice-agent-saas-telephony")

AGENT_NAME = "voice-agent-saas"


def make_room_name() -> str:
    return f"saas-{uuid.uuid4().hex[:10]}"


def _metadata(agent_id: str, mode: str, phone: str = "", call_id: str = "",
              user_id: str = "", lead_data: Optional[dict] = None) -> str:
    import json
    return json.dumps({
        "agent_id": agent_id, "mode": mode, "phone": phone,
        "call_id": call_id, "user_id": user_id,
        "lead_data": lead_data or None,   # for dynamic-script substitution in the worker
    })


# ---------------------------------------------------------------------------
# Browser mode: return a join token that also dispatches the agent into the room
# ---------------------------------------------------------------------------
def create_browser_room(agent_id: str, phone: str = "", call_id: str = "", user_id: str = "",
                        lead_data: Optional[dict] = None) -> dict:
    """Creates a room + a browser participant token, dispatching the agent."""
    from livekit import api

    _req_creds()
    room = make_room_name()
    identity = "caller-" + uuid.uuid4().hex[:6]

    token = (
        api.AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
        .with_identity(identity)
        .with_ttl(timedelta(minutes=30))
        .with_grants(
            api.VideoGrants(room=room, room_join=True, can_publish=True, can_subscribe=True)
        )
        .with_room_config(
            api.RoomConfiguration(
                agents=[
                    api.RoomAgentDispatch(
                        agent_name=AGENT_NAME,
                        metadata=_metadata(agent_id, "browser", phone, call_id, user_id, lead_data),
                    )
                ]
            )
        )
        .to_jwt()
    )

    return {"token": token, "url": LIVEKIT_URL, "room": room, "mode": "browser"}


# ---------------------------------------------------------------------------
# SIP mode: dial a real number through a LiveKit SIP trunk
# ---------------------------------------------------------------------------
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
        await client.room.create_room(
            api.CreateRoomRequest(
                name=room,
                empty_timeout=300,   # seconds before an empty room auto-closes
                agents=[api.RoomAgentDispatch(agent_name=AGENT_NAME, metadata=metadata)],
            )
        )

        # 2) Dial the number through the SIP trunk.
        resp = await client.sip.create_sip_participant(
            api.CreateSIPParticipantRequest(
                room_name=room,
                participant_identity="phone-" + uuid.uuid4().hex[:6],
                sip_call_to=phone,          # e.g. +9180XXXXXXX
                krisp_enabled=False,
            ),
            trunk_id=trunk,
        )
    finally:
        await client.aclose()

    return {
        "room": room,
        "url": LIVEKIT_URL,
        "mode": "sip",
        "agent_token": None,   # agent is dispatched via the room's agents config
        "sip_participant": getattr(resp, "participant_id", ""),
        "sip_trunk_id": trunk,
    }


async def list_live_active_rooms() -> Optional[set]:
    """Return the set of rooms that currently have at least one participant.

    This is the source of truth for "is a call actually live right now". Used by:
      * the concurrency gate (count real concurrent calls, not stuck DB rows), and
      * the stale-call sweeper (only fail calls whose room has already ended).

    Returns None if LiveKit can't be reached, so callers can fall back to a
    conservative DB-based estimate.
    """
    try:
        from livekit import api
        _req_creds()
    except Exception:
        return None
    client = api.LiveKitAPI(LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
    try:
        resp = await client.room.list_rooms(api.room_service.ListRoomsRequest())
    except Exception:
        return None
    finally:
        try:
            await client.aclose()
        except Exception:
            pass
    return {r.name for r in resp.rooms if int(getattr(r, "num_participants", 0) or 0) > 0}


async def end_active_room(room_name: str) -> bool:
    """Delete a LiveKit room, force-disconnecting every participant (caller + agent).

    This is what physically *cuts* a call that the agent decided to end — without
    it the browser/SIP participant would stay connected (silent) even after the
    agent session ends. Returns True on success.
    """
    if not room_name:
        return False
    try:
        from livekit import api
        _req_creds()
    except Exception as e:
        logger.warning(f"end_active_room: creds error {e}")
        return False
    client = api.LiveKitAPI(LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
    try:
        await client.room.delete_room(api.room_service.DeleteRoomRequest(room=room_name))
        return True
    except Exception as e:
        logger.warning(f"end_active_room: delete_room failed for {room_name}: {e}")
        return False
    finally:
        try:
            await client.aclose()
        except Exception:
            pass


def _req_creds() -> None:
    if not (LIVEKIT_API_KEY and LIVEKIT_API_SECRET):
        raise RuntimeError("LIVEKIT_API_KEY / LIVEKIT_API_SECRET not configured")
