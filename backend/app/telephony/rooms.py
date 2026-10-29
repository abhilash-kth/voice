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

def _participant_kind_value(participant: Any) -> Optional[int]:
    kind = getattr(participant, "kind", None)
    try:
        return int(kind)
    except Exception:
        text = str(kind or "").lower()
        if "agent" in text:
            return 4
        if "sip" in text:
            return 3
        if "egress" in text:
            return 2
        if "ingress" in text:
            return 1
        if "standard" in text:
            return 0
        return None


def _is_agent_participant(participant: Any) -> bool:
    if _participant_kind_value(participant) == 4:
        return True
    identity = (getattr(participant, "identity", "") or "").lower()
    return identity.startswith("agent")


def _is_caller_participant(participant: Any) -> bool:
    """True for the human side of a room (browser or SIP), not infrastructure."""
    if _is_agent_participant(participant):
        return False
    kind = _participant_kind_value(participant)
    if kind in (0, 3):  # STANDARD browser participant or SIP participant
        return True
    if kind in (1, 2, 4):  # ingress / egress / agent
        return False
    identity = (getattr(participant, "identity", "") or "").lower()
    if identity.startswith(("eg_", "ingress", "egress")):
        return False
    return identity.startswith(("phone-", "sip", "caller-"))


async def room_caller_state(room_name: str) -> Optional[dict]:
    """Inspect who is currently in a room.

    Returns None when LiveKit cannot be reached / the answer is unknown.
    A definitive room-not-found answer is returned as an empty state because,
    for a dispatched SIP call, that means the phone participant and room are
    gone. `has_caller` is the management-plane signal used to notice that a
    phone-side hangup happened even if the worker has not finalized the DB
    row yet.
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
        participants = list(getattr(resp, "participants", []) or [])
        return {
            "exists": True,
            "participant_count": len(participants),
            "has_agent": any(_is_agent_participant(p) for p in participants),
            "has_caller": any(_is_caller_participant(p) for p in participants),
            "identities": [
                str(getattr(p, "identity", "") or "") for p in participants
            ],
        }
    except Exception as e:
        text = (
            f"{type(e).__name__} {e} {getattr(e, 'code', '')} "
            f"{getattr(e, 'status', '')}"
        ).lower()
        if any(marker in text for marker in (
                "not found", "not_found", "does not exist", "room not exist",
                "could not find", " 404")):
            return {
                "exists": False,
                "participant_count": 0,
                "has_agent": False,
                "has_caller": False,
                "identities": [],
            }
        return None
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
    state = await room_caller_state(room_name)
    if state is None:
        return None
    return bool(state.get("has_agent"))
