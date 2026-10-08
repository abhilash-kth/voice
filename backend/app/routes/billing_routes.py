"""Billing + wallet routes (/api/billing/*, /api/wallet/*, /api/cost-preview).

The worker posts usage/cost to /api/billing/log; the wallet endpoints are the
customer-facing recharge flow. Extracted from the old monolithic main.py —
behavior unchanged.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, Header

from ..models import Recharge
from .. import auth
from .. import repo
from .. import billing as billing_mod
from ..config import BILLING_INTERNAL_TOKEN

import logging
logger = logging.getLogger("voice-agent-saas-api")

router = APIRouter(tags=["billing"])


@router.post("/api/billing/log")
async def billing_log(payload: dict, x_internal_token: Optional[str] = Header(None)):
    if BILLING_INTERNAL_TOKEN and x_internal_token != BILLING_INTERNAL_TOKEN:
        raise HTTPException(401, "Invalid internal token")

    status = (payload.get("status") or "completed").lower()
    # Support both old (id) and new (callId, call_id) formats
    call_id = payload.get("callId") or payload.get("call_id") or payload.get("id")
    user_id_from_payload = payload.get("userId") or payload.get("user_id") or ""
    rec = None
    if call_id:
        rec = await get_call_for_billing(call_id, user_id_from_payload)
    if not rec:
        # Fix 404: worker may be using different DB or call not yet created in backend DB
        # Create call record from payload if not found, to allow billing to succeed
        # Trace exact call ID being sent
        logger.warning(f"Billing log: call record not found for id={call_id} user_id={user_id_from_payload} payload keys={list(payload.keys())} - attempting to create from payload (fixes 404)")
        try:
            # Extract user_id, agent_id from payload or use defaults
            create_user_id = user_id_from_payload or payload.get("userId") or payload.get("user_id") or "unknown"
            create_agent_id = payload.get("agentId") or payload.get("agent_id") or "unknown"
            # Try to create call record with same ID
            from ..db import get_prisma
            db = get_prisma()
            # Check if we can create with specific ID - Prisma allows specifying ID if not auto-generated? 
            # Use repo.create_call with data that will generate new ID, then update? Instead, create directly via prisma
            try:
                # Try direct prisma create with given ID
                created = await db.call.create(data={
                    "id": call_id,
                    "userId": create_user_id,
                    "agentId": create_agent_id,
                    "mode": payload.get("mode", "browser"),
                    "room": payload.get("room", ""),
                    "phone": payload.get("phone"),
                    "status": "planned",
                    "startedAt": payload.get("started_at", ""),
                    "transcripts": "[]",
                })
                from .. import repo as _repo
                rec = _repo._call_dict(created)
                logger.info(f"Billing log: created missing call record id={call_id} user_id={create_user_id} agent_id={create_agent_id} (fixes 404 for {call_id})")
            except Exception as e_create:
                # If create with ID fails (e.g., ID format), try repo.create_call and then update with our ID logic
                logger.warning(f"Billing log: direct create with ID failed {e_create}, trying fallback create")
                try:
                    fallback = await db.call.create(data={
                        "userId": create_user_id,
                        "agentId": create_agent_id,
                        "mode": payload.get("mode", "browser"),
                        "room": payload.get("room", ""),
                        "phone": payload.get("phone"),
                        "status": "planned",
                        "startedAt": payload.get("started_at", ""),
                        "transcripts": "[]",
                    })
                    from .. import repo as _repo
                    rec = _repo._call_dict(fallback)
                    # Use fallback ID for billing, but log original
                    logger.info(f"Billing log: created fallback call record id={rec['id']} original requested {call_id} (DB mismatch, using fallback)")
                    # Update call_id to fallback for rest of flow
                    call_id = rec["id"]
                except Exception as e_fallback:
                    logger.error(f"Billing log: failed to create call record for {call_id}: {e_fallback}")
                    raise HTTPException(404, f"Call record not found and could not create: {call_id}")
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Billing log: unexpected error creating call {call_id}: {e}")
            raise HTTPException(404, f"Call record not found: {call_id}")

    # Idempotency: if we already have a spend transaction for this call, don't double-charge.
    # But still ensure the call record is up-to-date.
    already_charged = False
    try:
        already_charged = await repo.has_spend_for_call(rec["user_id"], call_id)
    except Exception:
        already_charged = False

    if rec.get("status") == "completed" and already_charged:
        return {"ok": True, "call_id": call_id, "already_processed": True}

    # Parse new format (costs dict, usage dict) and old format (flat fields)
    costs = payload.get("costs") or {}
    usage = payload.get("usage") or {}
    # New format: usage contains sttSeconds, ttsChars, llmInputTokens etc, costs contains client_price_inr etc
    # Old format: flat fields costToUserNumber, providerCost, etc
    duration = payload.get("duration") or payload.get("durationSeconds") or rec.get("duration_seconds", 0)
    transcripts = payload.get("transcripts") or rec.get("transcripts", [])
    recording_url = payload.get("recordingUrl") or payload.get("recording_url") or rec.get("recording_url")

    # Build usage dict for storage
    if usage:
        # New format from worker.py _post_billing
        usage_to_store = {
            "stt_seconds": usage.get("sttSeconds", 0) or payload.get("sttSeconds", 0),
            "tts_chars": usage.get("ttsChars", 0) or payload.get("ttsChars", 0),
            "llm_input_tokens": usage.get("llmInputTokens", 0) or usage.get("llmInputTokensAuthoritative", 0) or usage.get("totalInputTokens", 0) or payload.get("llmInputTokens", 0),
            "llm_output_tokens": usage.get("llmOutputTokens", 0) or usage.get("llmOutputTokensAuthoritative", 0) or usage.get("totalOutputTokens", 0) or payload.get("llmOutputTokens", 0),
            "llm_cached_tokens": usage.get("llmCachedTokens", 0) or usage.get("totalCachedTokens", 0),
            "user_speech_seconds": usage.get("sttSeconds", 0) or payload.get("sttSeconds", 0),
            "successful_requests": usage.get("successfulRequests", 0),
            "failed_requests": usage.get("failedRequests", 0),
        }
    else:
        usage_to_store = {
            "stt_seconds": payload.get("sttSeconds", 0),
            "tts_chars": payload.get("ttsChars", 0),
            "llm_input_tokens": payload.get("llmInputTokens", 0),
            "llm_output_tokens": payload.get("llmOutputTokens", 0),
            "user_speech_seconds": payload.get("sttSeconds", 0),
        }

    # Build cost dict
    if costs:
        cost_to_store = costs
    else:
        cost_to_store = {
            "client_price_inr": payload.get("costToUserNumber", 0),
            "total_cost_inr": payload.get("providerCost", 0),
            "your_profit_inr": payload.get("profit", 0),
            "is_profit": payload.get("isProfit", True),
            "stt_cost_inr": payload.get("sttCost", 0),
            "llm_cost_inr": payload.get("llmCost", 0),
            "tts_cost_inr": payload.get("ttsCost", 0),
            "server_cost_inr": payload.get("serverCost", 0),
            "your_cost_per_min": payload.get("costPerMin", 0),
            "client_bill_per_min": payload.get("billPerMin", 0),
            "duration_mins": payload.get("durationMins", 0),
        }

    await repo.update_call(call_id, {
        "status": status,
        "room": payload.get("room", rec.get("room", "")),
        "ended_at": payload.get("date", "") or payload.get("ended_at", ""),
        "duration_seconds": duration,
        "transcripts": transcripts,
        "recording_url": recording_url,
        "usage": usage_to_store,
        "cost": cost_to_store,
    })

    # Settle the wallet for completed calls — deduct once per call, idempotent via repo.deduct.
    if status == "completed" and not already_charged:
        # New format: costs dict has client_price_inr, old: costToUserNumber
        charge = float(costs.get("client_price_inr", 0) or payload.get("costToUserNumber", 0) or 0)
        if charge > 0:
            try:
                await repo.deduct(rec["user_id"], charge, note=f"Call {call_id}")
                logger.info(f"💸 Deducted ₹{charge} for call {call_id} — remaining balance will update (billing_posted via backend)")
            except Exception as de:
                logger.warning(f"Could not deduct wallet for call {call_id}: {de}")

    return {"ok": True, "call_id": call_id, "billing_posted": True}


async def get_call_for_billing(call_id: str, user_id: str):
    # Find the call without user scoping (worker may pass user_id). Fall back to
    # unscoped lookup when user_id is empty.
    if user_id:
        rec = await repo.get_call(call_id, user_id)
        if rec:
            return rec
    return await get_call_unscoped(call_id)


async def get_call_unscoped(call_id: str):
    from ..db import get_prisma
    from .. import repo as _repo
    c = await get_prisma().call.find_unique(where={"id": call_id})
    return _repo._call_dict(c) if c else None


@router.get("/api/billing/usage")
async def billing_usage(agent_id: Optional[str] = None, user=Depends(auth.get_current_user)):
    return await repo.get_usage(user.id, agent_id=agent_id)


# ---------------------------------------------------------------------------
# Wallet
# ---------------------------------------------------------------------------
@router.get("/api/wallet")
async def get_wallet(user=Depends(auth.get_current_user)):
    return await repo.get_wallet(user.id)


@router.post("/api/wallet/recharge")
async def recharge(body: Recharge, user=Depends(auth.get_current_user)):
    if body.add_amount <= 0:
        raise HTTPException(400, "Recharge amount must be positive")
    out = await repo.recharge(user.id, body.add_amount)
    # A fresh top-up may be exactly what a past_due monthly plan was waiting
    # for — settle it immediately instead of on the hourly sweep.
    try:
        from ..services import subscription_service
        await subscription_service.retry_after_recharge(user.id)
    except Exception:
        pass
    return out


# ---------------------------------------------------------------------------
# Cost preview
# ---------------------------------------------------------------------------
@router.post("/api/cost-preview")
async def cost_preview(body: dict):
    agent_mode = str(body.get("agent_mode", "assistant"))
    # Preview must match the final bill exactly — include the Super-Admin
    # per-mode minimum billed duration.
    consts = billing_mod._billing_consts() if hasattr(billing_mod, "_billing_consts") else {}
    min_bill = int(consts.get(
        "announcement_min_bill_seconds" if agent_mode == "announcement"
        else "assistant_min_bill_seconds", 0) or 0)
    return billing_mod.calculate_call_cost(
        duration_seconds=int(body.get("duration_seconds", 60)),
        stt_seconds=float(body.get("stt_seconds", 30)),
        llm_input_tokens=int(body.get("llm_input_tokens", 500)),
        llm_output_tokens=int(body.get("llm_output_tokens", 800)),
        tts_chars=int(body.get("tts_chars", 800)),
        llm_provider_id=body.get("llm_provider_id", "groq_llama_3_3_70b"),
        stt_provider_id=body.get("stt_provider_id", "deepgram_nova2"),
        tts_provider_id=body.get("tts_provider_id", "google_wavenet_hi"),
        telephony_provider_id=body.get("telephony_provider_id", ""),
        client_rate_per_min=float(body.get("client_rate_per_min", 2.50)),
        agent_mode=agent_mode,
        max_concurrency=int(body.get("max_concurrency", 1) or 1),
        min_bill_seconds=min_bill,
    )

