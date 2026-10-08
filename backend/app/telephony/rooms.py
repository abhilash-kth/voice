"""Browser-room lifecycle and room inspection helpers.

Extracted from telephony.py - behavior unchanged (livekit imports stay
lazy inside the functions, exactly as before).
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
from .sip_service import create_agent_dispatch


async def create_browser_room(agent_id: str, phone: str = "", call_id: str = "", user_id: str = "",
                              lead_data: Optional[dict] = None) -> dict:
    """Creates a room + returns a browser participant token configured for automatic agent dispatch on join."""
    from livekit import api

    _req_creds()
    room = make_room_name()
    identity = "caller-" + uuid.uuid4().hex[:6]
    metadata = _metadata(agent_id, "browser", phone, call_id, user_id, lead_data)

    client = api.LiveKitAPI(LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
    server_dispatched = False
    try:
        try:
            await _lk(
                client.room.create_room(
                    api.CreateRoomRequest(
                        name=room,
                        empty_timeout=300,
                        departure_timeout=30,
                        agents=[api.RoomAgentDispatch(agent_name=AGENT_NAME, metadata=metadata)],
                    )
                ),
                timeout=8.0,
                op="CreateRoom",
            )
            server_dispatched = True
            logger.info("[ROOM_CREATED] room=%s agent_id=%s mode=browser (server-dispatched)", room, agent_id)
        except TimeoutError:
            raise
        except Exception as e:
            logger.warning("[CREATE_ROOM_WARN] room=%s: %s", room, e)
            # Room-create with inline agents= failed — fall back to an explicit
            # dispatch (older servers may reject the inline form but accept this).
            if await create_agent_dispatch(room, metadata) is not None:
                server_dispatched = True
    finally:
        await client.aclose()

    token_builder = (
        api.AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
        .with_identity(identity)
        .with_ttl(timedelta(minutes=30))
        .with_grants(
            api.VideoGrants(room=room, room_join=True, can_publish=True, can_subscribe=True)
        )
    )

    if not server_dispatched:
        token_builder = token_builder.with_room_config(
            api.RoomConfiguration(
                agents=[
                    api.RoomAgentDispatch(
                        agent_name=AGENT_NAME,
                        metadata=metadata,
                    )
                ]
            )
        )

    token = token_builder.to_jwt()
    logger.info("[TOKEN_CREATED] room=%s identity=%s", room, identity)

    return {"token": token, "url": LIVEKIT_URL, "room": room, "mode": "browser"}


# ---------------------------------------------------------------------------
# SIP mode: dial a real number through a LiveKit SIP trunk
# ---------------------------------------------------------------------------

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
        resp = await _lk(
            client.room.list_rooms(api.room_service.ListRoomsRequest()),
            timeout=5.0,
            op="ListRooms",
        )
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
        await _lk(
            client.room.delete_room(api.room_service.DeleteRoomRequest(room=room_name)),
            timeout=8.0,
            op="DeleteRoom",
        )
        return True
    except Exception as e:
        logger.warning(f"end_active_room: delete_room failed for {room_name}: {e}")
        return False
    finally:
        try:
            await client.aclose()
        except Exception:
            pass

async def room_agent_joined(room_name: str) -> Optional[bool]:
    """True when a LiveKit **agent** participant is actually inside the room.

    Room creation + agent dispatch succeeding only means the server ACCEPTED the
    dispatch — a worker still has to pick the job up and join. This probe is how
    the API learns that the dispatch realistically failed (worker stopped, busy,
    or a stale second worker window eating jobs), instead of letting the caller
    sit in a silent room. Returns None when LiveKit is unreachable, so callers
    can treat "unknown" differently from a definitive miss.
    """
    if not room_name:
        return None
    try:
        from livekit import api
        _req_creds()
    except Exception:
        return None
    client = api.LiveKitAPI(LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
    try:
        resp = await _lk(
            client.room.list_participants(api.ListParticipantsRequest(room=room_name)),
            timeout=6.0,
            op="ListParticipants",
        )
        Kind = getattr(api.ParticipantInfo, "Kind", None)
        agent_enum = getattr(Kind, "AGENT", None) if Kind else None
        for p in getattr(resp, "participants", []) or []:
            kind = getattr(p, "kind", None)
            if agent_enum is not None and kind == agent_enum:
                return True
            try:  # protobuf open enums are ints in some SDK releases (AGENT=4)
                if int(kind) == 4:
                    return True
            except Exception:
                pass
            if "agent" in str(kind).lower():
                return True
            # defensive fallback for SDKs that do not expose ParticipantInfo.Kind
            ident = (getattr(p, "identity", "") or "").lower()
            if ident.startswith("agent"):
                return True
        return False
    except Exception:
        return None
    finally:
        try:
            await client.aclose()
        except Exception:
            pass
