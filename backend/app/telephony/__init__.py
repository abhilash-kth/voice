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

# Facade: keeps the full import surface of the old app/telephony.py.
from .core import AGENT_NAME, _lk, _metadata, _req_creds, logger, make_room_name
from .rooms import (
    create_browser_room,
    end_active_room,
    list_live_active_rooms,
    room_agent_joined,
)
from .sip_service import create_agent_dispatch, create_sip_call
