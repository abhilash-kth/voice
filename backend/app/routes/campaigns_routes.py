"""Bulk-call campaign routes (/api/campaigns*).
Extracted from the old monolithic main.py — behavior unchanged.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Form

from .. import auth
from .. import repo
from .. import campaign as campaign_store
from .. import campaign_runner
from .. import leadfile

logger = logging.getLogger("voice-agent-saas-api")

router = APIRouter(tags=["campaigns"])


# ---------------------------------------------------------------------------
@router.post("/api/campaigns", status_code=201)
async def create_campaign(
    name: str = Form(...),
    agent_id: str = Form(...),
    concurrency: int = Form(1),
    sip_trunk_id: Optional[str] = Form(None),
    phone_column: Optional[str] = Form(None),
    autostart: str = Form("true"),
    file: UploadFile = File(...),
    user=Depends(auth.get_current_user),
):
    rec = await repo.get_agent(agent_id, user.id)
    if not rec:
        raise HTTPException(404, "Agent not found")
    if not rec["enabled"]:
        raise HTTPException(400, "This agent is disabled")

    raw = await file.read()
    try:
        parsed = leadfile.parse_lead_file(file.filename or "leads.csv", raw, phone_column=phone_column)
    except ValueError as e:
        raise HTTPException(400, str(e))

    if parsed["count"] == 0:
        raise HTTPException(400, "No valid lead rows found (each row needs a phone number).")

    created = campaign_store.create(
        user_id=user.id,
        agent_id=agent_id,
        name=name or "Untitled campaign",
        concurrency=concurrency,
        sip_trunk_id=sip_trunk_id or "",
        lead_rows=parsed["rows"],
        phone_column=parsed["phone_column"],
    )
    if autostart.lower() == "true":
        campaign_store.set_status(user.id, created["id"], "running")
        created["status"] = "running"
    return {**created, "phone_column": parsed["phone_column"],
            "dropped": parsed["dropped"], "mode": "sip"}


@router.get("/api/campaigns")
async def list_campaigns(user=Depends(auth.get_current_user)):
    return {"campaigns": campaign_store.list_campaigns(user.id)}


@router.get("/api/campaigns/{campaign_id}")
async def get_campaign(campaign_id: str, user=Depends(auth.get_current_user)):
    c = campaign_store.get(user.id, campaign_id)
    if not c:
        raise HTTPException(404, "Campaign not found")
    return c


@router.post("/api/campaigns/{campaign_id}/start")
async def start_campaign(campaign_id: str, user=Depends(auth.get_current_user)):
    c = campaign_store.get(user.id, campaign_id)
    if not c:
        raise HTTPException(404, "Campaign not found")
    wallet = await repo.get_wallet(user.id)
    if (wallet.get("balance") or 0) <= 0:
        raise HTTPException(402, "Wallet balance is ₹0. Recharge to run a campaign.")
    # Preflight the agent: a config that crashes the worker would fail EVERY
    # dial in this campaign and still bill the failed minutes.
    from .. import preflight as _pf
    agent_rec = await repo.get_agent(c["agent_id"], user.id)
    if agent_rec:
        err = await _pf.preflight_agent_config(agent_rec)
        if err:
            raise HTTPException(
                400,
                f"Campaign agent '{agent_rec.get('name')}' is not ready: {err}. Fix the agent config and retry.",
            )
    c = campaign_store.set_status(user.id, campaign_id, "running")
    return c


@router.post("/api/campaigns/{campaign_id}/pause")
async def pause_campaign(campaign_id: str, user=Depends(auth.get_current_user)):
    c = campaign_store.get(user.id, campaign_id)
    if not c:
        raise HTTPException(404, "Campaign not found")
    c = campaign_store.set_status(user.id, campaign_id, "paused")
    return c


@router.delete("/api/campaigns/{campaign_id}", status_code=204)
async def delete_campaign(campaign_id: str, user=Depends(auth.get_current_user)):
    if not campaign_store.get(user.id, campaign_id):
        raise HTTPException(404, "Campaign not found")
    # Pause first so the dispatcher stops touching it, then drop it.
    campaign_store.set_status(user.id, campaign_id, "paused")
    campaign_store.delete(user.id, campaign_id)


# ---------------------------------------------------------------------------