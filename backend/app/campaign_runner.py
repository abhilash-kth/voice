"""
Bulk-call campaign runner.

Ticks every few seconds: for each *running* campaign it
  1. reconciles leads whose call ended (marks them done/failed), and
  2. dials the next queued leads up to the campaign's concurrency limit,
     substituting each lead's columns into the dynamic script.

Stops a campaign when the user's wallet runs out (so no unbounded spend) or when
there is nothing left to dial.
"""
from __future__ import annotations

import logging

from . import campaign as campaign_store
from . import repo
from . import telephony
from . import leadfile

logger = logging.getLogger("voice-agent-saas-campaigns")


async def _refetch(campaign_id: str, user_id: str) -> dict | None:
    return campaign_store.get(user_id, campaign_id)


async def reconcile_and_dispatch(cmp: dict) -> None:
    cid = cmp["id"]
    user_id = cmp["user_id"]
    agent_id = cmp["agent_id"]
    sip_trunk_id = cmp.get("sip_trunk_id") or None
    phone_column = cmp.get("phone_column") or "phone"

    # --- 1. Reconcile: did any "calling" lead's call finish? -----------------
    calling = [l for l in cmp["leads"] if l["status"] == "calling"]
    for lead in calling:
        call_id = lead.get("call_id") or ""
        if not call_id:
            campaign_store.update_lead(cid, lead["index"], {"status": "failed", "error": "no call id"})
            continue
        try:
            rec = await repo.get_call(call_id, user_id)
        except Exception as e:
            logger.warning(f"campaign {cid}: could not read call {call_id}: {e}")
            continue
        if not rec:
            campaign_store.update_lead(cid, lead["index"], {"status": "failed", "error": "call not found"})
            continue
        status = rec.get("status", "")
        if status == "completed":
            campaign_store.update_lead(cid, lead["index"], {"status": "done"})
        elif status in ("failed", "cancelled", "error"):
            campaign_store.update_lead(cid, lead["index"], {
                "status": "failed",
                "error": rec.get("status", "call failed"),
            })
        # status == planned / in-progress -> still live, keep as "calling"

    # --- 2. Wallet guard -----------------------------------------------------
    try:
        wallet = await repo.get_wallet(user_id)
        if (wallet.get("balance") or 0) <= 0:
            campaign_store.set_status(user_id, cid, "paused")
            logger.warning(f"campaign {cid}: paused — wallet balance depleted.")
            return
    except Exception as e:
        logger.warning(f"campaign {cid}: wallet check failed {e}")

    # --- 3. Dispatch next queued leads up to concurrency ---------------------
    c = await _refetch(cid, user_id)
    if not c:
        return
    queued = [l for l in c["leads"] if l["status"] == "queued"]
    calling_now = len([l for l in c["leads"] if l["status"] == "calling"])
    free = max(0, c["concurrency"] - calling_now)
    to_dispatch = queued[:free]

    for lead in to_dispatch:
        data = lead["data"] or {}
        phone = leadfile.build_phone(data, phone_column)
        if not phone:
            campaign_store.update_lead(cid, lead["index"], {"status": "failed", "error": "no phone"})
            continue
        try:
            call = await repo.create_call({
                "user_id": user_id,
                "agent_id": agent_id,
                "mode": "sip",
                "phone": phone,
                "status": "planned",
            })
            result = await telephony.create_sip_call(
                agent_id, phone, sip_trunk_id, call["id"], user_id, lead_data=data,
            )
            await repo.update_call(call["id"], {"room": result.get("room", "")})
            campaign_store.update_lead(cid, lead["index"], {"status": "calling", "call_id": call["id"]})
            logger.info(f"campaign {cid}: dialled {phone} → call {call['id']}")
        except Exception as e:
            logger.warning(f"campaign {cid}: dial failed for {phone}: {e}")
            campaign_store.update_lead(cid, lead["index"], {"status": "failed", "error": str(e)})

    # --- 4. Nothing left? Mark the campaign done ----------------------------
    c = await _refetch(cid, user_id)
    if c:
        remaining = [l for l in c["leads"] if l["status"] in ("queued", "calling")]
        if not remaining:
            campaign_store.set_status(user_id, cid, "done")


async def run_tick() -> None:
    """One dispatch pass over every running campaign."""
    for cmp in campaign_store.list_running():
        try:
            await reconcile_and_dispatch(cmp)
        except Exception as e:
            logger.exception(f"campaign {cmp.get('id')}: tick error {e}")
