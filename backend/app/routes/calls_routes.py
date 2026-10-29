"""Call lifecycle routes (/api/calls*): browser/SIP call start, list, end, delete.
Extracted from the old monolithic main.py — behavior unchanged. The agent-join
watchdog lives in calls_watchdog.py (300-line file budget).
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends

from .. import auth
from .. import repo
from .. import telephony
from ..config import LIVEKIT_URL
from ..services.telephony_policy import (TelephonyError, carrier_dial_number,
                                         normalize_destination,
                                         resolve_outbound)
from .calls_watchdog import (agent_join_watchdog, reconcile_active_sip_calls,
                             reconcile_sip_call)

logger = logging.getLogger("voice-agent-saas-api")

router = APIRouter(tags=["calls"])


def _effective_concurrency(agent_limit: int, workspace_channels: int,
                           phone_channels: Optional[int]) -> int:
    """Concurrent-call ceiling for one SIP start request.

    An assigned DID's own purchased/manual channels are authoritative for
    calls on that DID. The plan-selected/workspace channel entitlement is
    only the fallback for the legacy shared-trunk path with no assigned DID;
    it is no longer a second, separate cap on a number that already has
    channels.
    """
    agent_cap = max(1, int(agent_limit or 1))
    if phone_channels is not None:
        return min(agent_cap, max(1, int(phone_channels or 1)))
    return min(agent_cap, max(1, int(workspace_channels or 1)))


# ---------------------------------------------------------------------------
# Start a call (browser or SIP)
# ---------------------------------------------------------------------------


@router.post("/api/calls")
async def start_call(body: dict, user=Depends(auth.get_current_user)):
    agent_id = body.get("agent_id")
    mode = body.get("mode", "browser")
    phone = body.get("phone") or ""
    sip_trunk_id = body.get("sip_trunk_id")

    rec = await repo.get_agent(agent_id, user.id)
    if not rec:
        raise HTTPException(404, "Agent not found")
    if not rec["enabled"]:
        raise HTTPException(400, "This agent is disabled")

    # Purpose gate + trunk derivation for real phone calls. Inbound-only
    # agents can still be browser-tested, but may never dial out. When the
    # agent has an assigned purchased number, its stored trunk/caller-ID
    # wins and any client-supplied sip_trunk_id is ignored.
    outbound_route = None
    if mode == "sip":
        try:
            outbound_route = await resolve_outbound(
                rec, user.id, sip_trunk_id or "")
        except TelephonyError as e:
            raise HTTPException(e.status_code, str(e)) from None

    # PREFLIGHT: run the worker's exact config→runtime path BEFORE creating the
    # room. A saved agent whose config no longer builds (model removed from the
    # catalog, missing API key, unknown provider) used to crash the worker job
    # after the room existed — the caller sat in a silent room forever with no
    # error anywhere. Now the call fails here, immediately, with the real
    # reason the UI can show.
    from .. import preflight as _preflight
    cfg_err = await _preflight.preflight_agent_config(rec)
    if cfg_err:
        logger.error(
            "[CALL_BLOCKED] agent_id=%s name=%s: config would crash the worker: %s",
            agent_id, rec.get("name"), cfg_err,
        )
        raise HTTPException(
            400,
            f"Agent '{rec.get('name', agent_id)}' is not ready to take calls: {cfg_err}. "
            "Open the agent, re-save its LLM/STT/TTS selection (and check the API keys in backend/.env), then retry.",
        )

    logger.info("[CALL_START] agent_id=%s mode=%s user_id=%s", agent_id, mode, user.id)
    logger.info("[AGENT_SELECTED] agent_id=%s name=%s mode=%s", agent_id, rec.get("name"), rec.get("agent_mode", "assistant"))

    # Concurrency = calls that are ACTUALLY live right now (LiveKit rooms with real
    # participants), NOT rows stuck in "in-progress". Falls back to the DB count if
    # LiveKit is unreachable. Stuck calls are cleared automatically by the sweeper.
    if mode == "browser":
        try:
            existing_calls = await repo.list_calls(user.id, limit=20)
            for prev in existing_calls:
                if prev.get("mode") == "browser" and prev.get("status") in ("planned", "in-progress"):
                    prev_room = prev.get("room")
                    if prev_room:
                        try:
                            await telephony.end_active_room(prev_room)
                        except Exception:
                            pass
                    await repo.update_call(prev["id"], {
                        # "planned" = the agent never joined → that is a FAILED
                        # call (0s, unbilled), not a completed one.
                        "status": "failed" if prev.get("status") == "planned" else "completed",
                        "ended_at": time.strftime("%Y-%m-%d %H:%M"),
                    })
        except Exception as e:
            logger.warning("Error auto-cleaning prior browser calls: %s", e)

    agent_limit = max(1, int(rec.get("max_concurrency") or 1))
    plan_channels = agent_limit
    workspace_channels = agent_limit
    phone_channels: Optional[int] = None
    phone_active = 0
    effective_limit = agent_limit

    if mode == "sip":
        route_for_limit = outbound_route or {}
        if route_for_limit.get("phone_channels") is not None:
            phone_channels = max(
                1, int(route_for_limit.get("phone_channels") or 1))
        try:
            from ..services import subscription_service
            subscription = await subscription_service.get_subscription(user.id)
            plan_channels = max(
                1, int(subscription.get("plan_channels") or agent_limit))
            workspace_channels = max(
                1, int(subscription.get("channels") or plan_channels))
        except Exception as e:
            logger.debug("channel entitlement lookup skipped: %r", e)
        effective_limit = _effective_concurrency(
            agent_limit, workspace_channels, phone_channels)

        phone_number_id = route_for_limit.get("phone_number_id")
        if phone_number_id:
            # A DID's channels are shared by every agent assigned to it, so
            # count live SIP calls across those agents—not just this one.
            phone_agent_ids = [agent_id]
            try:
                for assigned in await repo.list_agents_for_phone(
                        phone_number_id, user.id):
                    if assigned.get("id") not in phone_agent_ids:
                        phone_agent_ids.append(assigned["id"])
            except Exception as e:
                logger.debug("assigned-phone agent lookup skipped: %r", e)
            active_by_id: dict[str, dict] = {}
            for assigned_agent_id in phone_agent_ids:
                for row in await reconcile_active_sip_calls(
                        user.id, assigned_agent_id):
                    active_by_id[row["id"]] = row
            active = sum(
                1 for row in active_by_id.values()
                if row.get("agent_id") == agent_id)
            phone_active = len(active_by_id)
            if phone_channels is not None and phone_active >= phone_channels:
                raise HTTPException(
                    409,
                    f"Assigned number {route_for_limit.get('phone_number') or ''} "
                    f"has {phone_channels} channel(s) and already has "
                    f"{phone_active} live call(s). Wait for a call to end or "
                    "increase the number's channels.",
                )
        else:
            active = len(await reconcile_active_sip_calls(user.id, agent_id))
    else:
        live_rooms = await telephony.list_live_active_rooms()
        active = await repo.count_live_calls(agent_id, active_rooms=live_rooms)

    # The configured limit is enforced for BOTH browser and SIP starts. For
    # SIP on an assigned DID, the effective ceiling is the smaller of the
    # agent limit and that DID's channels; plan-selected channels are not a
    # second cap on the same purchased capacity.
    if active >= effective_limit:
        if mode == "sip":
            detail = (
                f"Channel limit reached: {active} live call(s) "
                f"(agent limit {agent_limit}, workspace channels "
                f"{workspace_channels}"
                + (f", assigned-number channels {phone_channels}"
                   if phone_channels is not None else "")
                + "). Wait for a call to end or increase the applicable channels.")
        else:
            detail = (
                f"This agent is already on {active} live call(s) "
                f"(limit {agent_limit}). Wait for a call to end, or raise "
                "the 'Max concurrent calls' limit.")
        raise HTTPException(409, detail)

    wallet = await repo.get_wallet(user.id)
    if wallet["balance"] <= 0:
        raise HTTPException(402, "Wallet balance is ₹0. Recharge to place a call.")

    if mode == "sip" and not phone:
        raise HTTPException(400, "SIP mode requires a phone number")

    # Cache the active agent config locally so worker can load in 0ms without DB delay
    try:
        from ..config import DATA_DIR
        cache_file = DATA_DIR / f"agent_{agent_id}.json"
        cache_file.write_text(json.dumps(rec))
    except Exception as e:
        logger.warning("Could not cache agent config to data dir: %s", e)

    call = await repo.create_call({
        "user_id": user.id,
        "agent_id": agent_id,
        "mode": mode,
        "phone": normalize_destination(phone) if (mode == "sip" and phone) else (phone or None),
        "status": "planned",
    })

    try:
        if mode == "sip":
            route = outbound_route or {}
            result = await telephony.create_sip_call(
                agent_id, normalize_destination(phone),
                route.get("sip_trunk_id") or sip_trunk_id,
                call["id"], user.id,
                sip_call_to=carrier_dial_number(
                    phone, route.get("dial_prefix") or ""),
                sip_number=route.get("caller_id") or None)
            result["phone_number"] = route.get("phone_number") or ""
            result["purpose"] = rec.get("purpose") or "outbound"
            # The trunk is a server-managed routing detail, not customer data.
            result.pop("sip_trunk_id", None)
        else:
            result = await telephony.create_browser_room(agent_id, phone, call["id"], user.id)
    except ModuleNotFoundError:
        raise HTTPException(503, "livekit not installed on the backend. Run `pip install -r requirements.txt` to enable calls.")
    except ValueError as e:
        raise HTTPException(400, str(e))
    except TimeoutError as e:
        # LiveKit itself did not answer. Mark the call failed so the UI and the
        # Calls tab show the truth instead of a stale "planned" row.
        try:
            await repo.update_call(call["id"], {
                "status": "failed",
                "ended_at": time.strftime("%Y-%m-%d %H:%M"),
            })
        except Exception:
            pass
        raise HTTPException(503, f"LiveKit server did not respond: {e}. Check that the LiveKit server is running and reachable, then retry.")
    except Exception as e:
        raise HTTPException(400, f"Call setup failed: {e}")

    await repo.update_call(call["id"], {"room": result["room"]})
    result["call_id"] = call["id"]
    result["concurrency"] = {
        "active_calls": active + 1,
        "limit": effective_limit,
        "remaining": max(effective_limit - active - 1, 0),
        "agent_limit": agent_limit,
        "plan_channels": plan_channels,
        "workspace_channels": workspace_channels,
        "phone_channels": phone_channels,
        "phone_active_calls": (phone_active + 1) if mode == "sip" else 0,
    }

    # The room + dispatch are now accepted by LiveKit, but "accepted" is not
    # "a worker actually joined". Watch it in the background so a dead/absent
    # worker turns into a precise call failure (visible in the UI within ~2s
    # via the waiting poll) instead of 30s of silence in an empty room.
    try:
        asyncio.create_task(
            agent_join_watchdog(call["id"], result["room"], user.id, agent_id, mode, phone)
        )
    except Exception as e:
        logger.debug("agent-join watchdog not scheduled: %r", e)

    return result


@router.get("/api/calls")
async def list_calls(agent_id: Optional[str] = None, user=Depends(auth.get_current_user)):
    rows = await repo.list_calls(user.id, agent_id=agent_id)
    out = []
    for row in rows:
        if row.get("mode") == "sip" and row.get("status") in (
                "planned", "in-progress"):
            row = await reconcile_sip_call(row)
        out.append(row)
    return {"calls": out}


@router.get("/api/calls/{call_id}")
async def get_call(call_id: str, user=Depends(auth.get_current_user)):
    rec = await repo.get_call(call_id, user.id)
    if not rec:
        raise HTTPException(404, "Call not found")
    if rec.get("mode") == "sip":
        rec = await reconcile_sip_call(rec)
    return rec


@router.post("/api/calls/{call_id}/end")
async def end_call(call_id: str, user=Depends(auth.get_current_user)):
    logger.info("[CALL_END_REQUESTED] source=user call_id=%s user_id=%s", call_id, user.id)
    rec = await repo.get_call(call_id, user.id)
    if not rec:
        raise HTTPException(404, "Call not found")
    room = rec.get("room")
    if room:
        try:
            await telephony.end_active_room(room)
        except Exception as e:
            logger.warning(f"Could not close room before ending call {call_id}: {e}")
    if rec.get("status") == "planned":
        # The agent never joined — honestly a failed, unbilled call.
        await repo.update_call(call_id, {
            "status": "failed",
            "ended_at": time.strftime("%Y-%m-%d %H:%M"),
            "usage": {"error": "ended before the agent joined the room — no charge"},
        })
    elif rec.get("status") == "in-progress":
        # A live call the user hung up on. The worker's finalize_billing still
        # runs when its session closes and overwrites this row with the real
        # duration/usage/cost, then deducts the wallet.
        await repo.update_call(call_id, {
            "status": "completed",
            "ended_at": time.strftime("%Y-%m-%d %H:%M"),
        })
    logger.info("[CALL_ENDED] call_id=%s reason=user_ended", call_id)
    return {"ok": True, "call_id": call_id}


@router.delete("/api/calls/{call_id}", status_code=204)
async def delete_call(call_id: str, user=Depends(auth.get_current_user)):
    rec = await repo.get_call(call_id, user.id)
    if not rec:
        raise HTTPException(404, "Call not found")
    # If the selected row is still live, close its room before deleting the row.
    if rec.get("status") in ("planned", "in-progress") and rec.get("room"):
        try:
            await telephony.end_active_room(rec["room"])
        except Exception as e:
            logger.warning(f"Could not close room before deleting call {call_id}: {e}")
    if not await repo.delete_call(call_id, user.id):
        raise HTTPException(404, "Call not found")


# ---------------------------------------------------------------------------
# Bulk-call campaigns (upload leads -> dial up to concurrency)
# ---------------------------------------------------------------------------