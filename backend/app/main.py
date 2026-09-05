"""
FastAPI management + call-dispatch server for the Voice Agent SaaS platform.

Storage is Prisma (Neon/Postgres, or SQLite for local). Run from backend/:

    python -m prisma db push --schema schema.prisma
    python -m prisma generate --schema schema.prisma
    uvicorn app.main:app --port 8000 --reload

Endpoints: auth, agents, knowledge, calls, wallet, billing.
The LiveKit worker (app.agents.worker) reports cost/usage/transcripts here.
"""
from __future__ import annotations

import os
import asyncio
import logging
from typing import Optional
from contextlib import asynccontextmanager

logger = logging.getLogger("voice-agent-saas-api")

from fastapi import FastAPI, HTTPException, Depends, Header, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware

from .models import (
    AgentCreate,
    AgentUpdate,
    Recharge,
    RegisterBody,
    LoginBody,
)
from . import auth
from . import repo
from .catalog import catalog_summary, get_provider
from . import telephony
from . import billing as billing_mod
from . import campaign as campaign_store
from . import campaign_runner
from . import leadfile
from .db import init, shutdown, get_prisma
from .config import WALLET_TOPUP_AMOUNT, LIVEKIT_URL, BILLING_INTERNAL_TOKEN, SERVER_COST_PER_MIN

@asynccontextmanager
async def lifespan(app):
    await init()

    # Safety net: any "in-progress" call that never got finalized (worker crashed,
    # room never closed, caller vanished) is auto-marked "failed". We use LiveKit's
    # live rooms as the source of truth so a genuinely long, active call is never
    # killed — only calls whose room has actually ended get cleaned up. Falls back
    # to age-based cleanup if LiveKit is unreachable.
    stale_minutes = int(os.getenv("STALE_CALL_MINUTES", "15"))
    stale_poll = int(os.getenv("STALE_CALL_POLL_SECONDS", "60"))

    async def _cleanup_loop():
        while True:
            try:
                live = await telephony.list_live_active_rooms()
                n = await repo.fail_stale_calls(stale_minutes, active_rooms=live)
                if n:
                    logger.warning(f"🧹 Marked {n} ended call(s) as failed.")
            except Exception as e:
                logger.warning(f"stale-call cleanup error: {e}")
            await asyncio.sleep(stale_poll)

    # Bulk-call campaign dispatcher: dials queued leads up to each campaign's
    # concurrency, reconciling finished calls each tick.
    campaign_tick = int(os.getenv("CAMPAIGN_TICK_SECONDS", "3"))

    async def _campaign_loop():
        while True:
            try:
                await campaign_runner.run_tick()
            except Exception as e:
                logger.warning(f"campaign dispatcher error: {e}")
            await asyncio.sleep(campaign_tick)

    cleanup_task = asyncio.create_task(_cleanup_loop())
    campaign_task = asyncio.create_task(_campaign_loop())
    try:
        yield
    finally:
        cleanup_task.cancel()
        campaign_task.cancel()
        await shutdown()


app = FastAPI(title="Voice Agent SaaS", version="0.3.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@app.get("/api/health")
async def health():
    db = get_prisma()
    return {"ok": True, "service": "voice-agent-saas", "livekit_url": LIVEKIT_URL,
            "db_connected": db.is_connected()}


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
@app.post("/api/auth/register", status_code=201)
async def register(body: RegisterBody):
    if not body.email or not body.password:
        raise HTTPException(400, "Email and password required")
    if await repo.get_user_by_email(body.email):
        raise HTTPException(409, "Email already registered")
    user = await repo.create_user(body.email, body.name, auth.hash_password(body.password))
    token = auth.create_access_token(user["id"])
    return {"token": token, "user": user}


@app.post("/api/auth/login")
async def login(body: LoginBody):
    user = await repo.get_user_by_email(body.email)
    if not user:
        raise HTTPException(401, "Invalid credentials")
    if not auth.verify_password(body.password, user.passwordHash):
        raise HTTPException(401, "Invalid credentials")
    user_dict = repo._user_dict(user)
    token = auth.create_access_token(user.id)
    return {"token": token, "user": user_dict}


@app.get("/api/auth/me")
async def me(user=Depends(auth.get_current_user)):
    return repo._user_dict(user)


# ---------------------------------------------------------------------------
# Provider catalog (for the config UI)
# ---------------------------------------------------------------------------
@app.get("/api/catalog")
async def get_catalog():
    return {
        "catalog": catalog_summary(),
        "walletTopupAmounts": WALLET_TOPUP_AMOUNT,
        "server_cost_per_min": SERVER_COST_PER_MIN,
    }


# ---------------------------------------------------------------------------
# Agents CRUD (per-user)
# ---------------------------------------------------------------------------
@app.get("/api/agents")
async def list_agents(user=Depends(auth.get_current_user)):
    agents = await repo.list_agents(user.id)
    for a in agents:
        calls = await repo.list_calls(user.id, agent_id=a["id"])
        a["call_count"] = len([c for c in calls if c["status"] in ("completed", "in-progress")])
        a["total_billed"] = round(
            sum(float(c["cost"].get("client_price_inr", 0) or 0) for c in calls if c["status"] == "completed"), 2,
        )
        a["active_calls"] = await repo.count_active_calls(a["id"])
    return {"agents": agents}


@app.get("/api/agents/{agent_id}")
async def get_agent(agent_id: str, user=Depends(auth.get_current_user)):
    rec = await repo.get_agent(agent_id, user.id)
    if not rec:
        raise HTTPException(404, "Agent not found")
    return rec


@app.post("/api/agents", status_code=201)
async def create_agent(body: AgentCreate, user=Depends(auth.get_current_user)):
    for kind, sel in (("llm", body.providers.llm), ("stt", body.providers.stt),
                      ("tts", body.providers.tts), ("telephony", body.providers.telephony)):
        if sel and not get_provider(kind, sel.id):
            raise HTTPException(400, f"Unknown provider {sel.id} for {kind}")
    return await repo.create_agent(user.id, body.model_dump())


@app.put("/api/agents/{agent_id}")
async def update_agent(agent_id: str, body: AgentUpdate, user=Depends(auth.get_current_user)):
    patch = body.model_dump(exclude_none=True)
    rec = await repo.update_agent(agent_id, user.id, patch)
    if not rec:
        raise HTTPException(404, "Agent not found")
    return rec


@app.delete("/api/agents/{agent_id}", status_code=204)
async def delete_agent(agent_id: str, user=Depends(auth.get_current_user)):
    if not await repo.delete_agent(agent_id, user.id):
        raise HTTPException(404, "Agent not found")


# ---------------------------------------------------------------------------
# Knowledge base
# ---------------------------------------------------------------------------
@app.put("/api/agents/{agent_id}/knowledge")
async def set_knowledge(agent_id: str, body: dict, user=Depends(auth.get_current_user)):
    rec = await repo.set_agent_knowledge(agent_id, user.id, body)
    if not rec:
        raise HTTPException(404, "Agent not found")
    return rec


@app.post("/api/agents/{agent_id}/knowledge")
async def add_knowledge(
    agent_id: str,
    text: Optional[str] = Form(None),
    faq: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    user=Depends(auth.get_current_user),
):
    if not await repo.get_agent(agent_id, user.id):
        raise HTTPException(404, "Agent not found")

    if file is not None:
        doc_name = file.filename or "uploaded-doc"
        raw = await file.read()
        content = _parse_file(doc_name, raw)
        await repo.append_agent_document(agent_id, user.id, {"name": doc_name, "content": content})
        return {"ok": True, "appended": "document"}

    if text:
        await repo.set_agent_knowledge(agent_id, user.id, {"text": text})
        return {"ok": True, "appended": "text"}

    if faq:
        import json as _json
        try:
            items = _json.loads(faq)
        except Exception:
            raise HTTPException(400, "faq must be a JSON array of {q,a}")
        await repo.set_agent_knowledge(agent_id, user.id, {"faq": items})
        return {"ok": True, "appended": "faq", "count": len(items)}

    raise HTTPException(400, "Provide text, faq, or a file")


def _parse_file(name: str, raw: bytes) -> str:
    lower = name.lower()
    try:
        if lower.endswith(".txt") or lower.endswith(".md"):
            return raw.decode("utf-8", errors="ignore")
        if lower.endswith(".csv"):
            import io, csv
            lines = [" ".join(row) for row in csv.reader(io.StringIO(raw.decode("utf-8", errors="ignore")))]
            return "\n".join(lines)
        if lower.endswith(".pdf"):
            try:
                import io
                from pypdf import PdfReader
                reader = PdfReader(io.BytesIO(raw))
                return "\n".join((page.extract_text() or "") for page in reader.pages)
            except Exception as e:
                raise HTTPException(400, f"PDF parsing requires the 'pypdf' package: {e}")
        if lower.endswith(".json"):
            import json as _json
            return _json.dumps(_json.loads(raw.decode("utf-8", errors="ignore")), ensure_ascii=False)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, f"Could not parse {name}: {e}")
    raise HTTPException(400, "Unsupported file type. Use .txt, .md, .csv, .json or .pdf")


# ---------------------------------------------------------------------------
# Start a call (browser or SIP)
# ---------------------------------------------------------------------------
@app.post("/api/calls")
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

    # Concurrency = calls that are ACTUALLY live right now (LiveKit rooms with real
    # participants), NOT rows stuck in "in-progress". Falls back to the DB count if
    # LiveKit is unreachable. Stuck calls are cleared automatically by the sweeper.
    live_rooms = await telephony.list_live_active_rooms()
    active = await repo.count_live_calls(agent_id, active_rooms=live_rooms)
    if active >= rec["max_concurrency"]:
        raise HTTPException(
            409,
            f"This agent is already on {active} live call(s) (limit {rec['max_concurrency']}). "
            "Wait a few seconds for a call to end, or raise the 'Max concurrent calls' limit.",
        )

    wallet = await repo.get_wallet(user.id)
    if wallet["balance"] <= 0:
        raise HTTPException(402, "Wallet balance is ₹0. Recharge to place a call.")

    if mode == "sip" and not phone:
        raise HTTPException(400, "SIP mode requires a phone number")

    call = await repo.create_call({
        "user_id": user.id,
        "agent_id": agent_id,
        "mode": mode,
        "phone": phone or None,
        "status": "planned",
    })

    try:
        if mode == "sip":
            result = await telephony.create_sip_call(agent_id, phone, sip_trunk_id, call["id"], user.id)
        else:
            result = telephony.create_browser_room(agent_id, phone, call["id"], user.id)
    except ModuleNotFoundError:
        raise HTTPException(503, "livekit not installed on the backend. Run `pip install -r requirements.txt` to enable calls.")
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(400, f"Call setup failed: {e}")

    await repo.update_call(call["id"], {"room": result["room"]})
    result["call_id"] = call["id"]
    return result


@app.get("/api/calls")
async def list_calls(agent_id: Optional[str] = None, user=Depends(auth.get_current_user)):
    return {"calls": await repo.list_calls(user.id, agent_id=agent_id)}


@app.get("/api/calls/{call_id}")
async def get_call(call_id: str, user=Depends(auth.get_current_user)):
    rec = await repo.get_call(call_id, user.id)
    if not rec:
        raise HTTPException(404, "Call not found")
    return rec


# ---------------------------------------------------------------------------
# Bulk-call campaigns (upload leads -> dial up to concurrency)
# ---------------------------------------------------------------------------
@app.post("/api/campaigns", status_code=201)
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


@app.get("/api/campaigns")
async def list_campaigns(user=Depends(auth.get_current_user)):
    return {"campaigns": campaign_store.list_campaigns(user.id)}


@app.get("/api/campaigns/{campaign_id}")
async def get_campaign(campaign_id: str, user=Depends(auth.get_current_user)):
    c = campaign_store.get(user.id, campaign_id)
    if not c:
        raise HTTPException(404, "Campaign not found")
    return c


@app.post("/api/campaigns/{campaign_id}/start")
async def start_campaign(campaign_id: str, user=Depends(auth.get_current_user)):
    c = campaign_store.get(user.id, campaign_id)
    if not c:
        raise HTTPException(404, "Campaign not found")
    wallet = await repo.get_wallet(user.id)
    if (wallet.get("balance") or 0) <= 0:
        raise HTTPException(402, "Wallet balance is ₹0. Recharge to run a campaign.")
    c = campaign_store.set_status(user.id, campaign_id, "running")
    return c


@app.post("/api/campaigns/{campaign_id}/pause")
async def pause_campaign(campaign_id: str, user=Depends(auth.get_current_user)):
    c = campaign_store.get(user.id, campaign_id)
    if not c:
        raise HTTPException(404, "Campaign not found")
    c = campaign_store.set_status(user.id, campaign_id, "paused")
    return c


@app.delete("/api/campaigns/{campaign_id}", status_code=204)
async def delete_campaign(campaign_id: str, user=Depends(auth.get_current_user)):
    if not campaign_store.get(user.id, campaign_id):
        raise HTTPException(404, "Campaign not found")
    # Pause first so the dispatcher stops touching it, then drop it.
    campaign_store.set_status(user.id, campaign_id, "paused")
    campaign_store.delete(user.id, campaign_id)


# ---------------------------------------------------------------------------
# Billing (posted by the worker)
# ---------------------------------------------------------------------------
@app.post("/api/billing/log")
async def billing_log(payload: dict, x_internal_token: Optional[str] = Header(None)):
    if BILLING_INTERNAL_TOKEN and x_internal_token != BILLING_INTERNAL_TOKEN:
        raise HTTPException(401, "Invalid internal token")

    status = (payload.get("status") or "completed").lower()
    call_id = payload.get("id")
    rec = None
    if call_id:
        rec = await get_call_for_billing(call_id, payload.get("user_id", ""))
    if not rec:
        raise HTTPException(404, "Call record not found")

    await repo.update_call(call_id, {
        "status": status,
        "room": payload.get("room", rec.get("room", "")),
        "ended_at": payload.get("date", ""),
        "duration_seconds": payload.get("durationSeconds", rec.get("duration_seconds", 0)),
        "transcripts": payload.get("transcripts", rec.get("transcripts", [])),
        "recording_url": payload.get("recording_url", rec.get("recording_url")),
        "usage": {
            "stt_seconds": payload.get("sttSeconds", 0),
            "tts_chars": payload.get("ttsChars", 0),
            "llm_input_tokens": payload.get("llmInputTokens", 0),
            "llm_output_tokens": payload.get("llmOutputTokens", 0),
            "user_speech_seconds": payload.get("sttSeconds", 0),
        },
        "cost": {
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
        },
    })

    # Settle the wallet for completed calls (deduct the customer's price once).
    if status == "completed" and rec.get("status") != "completed":
        charge = float(payload.get("costToUserNumber", 0) or 0)
        if charge > 0:
            try:
                await repo.deduct(rec["user_id"], charge, note=f"Call {call_id}")
            except Exception as de:
                logger.warning(f"Could not deduct wallet for call {call_id}: {de}")

    return {"ok": True, "call_id": call_id}


async def get_call_for_billing(call_id: str, user_id: str):
    # Find the call without user scoping (worker may pass user_id). Fall back to
    # unscoped lookup when user_id is empty.
    if user_id:
        rec = await repo.get_call(call_id, user_id)
        if rec:
            return rec
    return await get_call_unscoped(call_id)


async def get_call_unscoped(call_id: str):
    from .db import get_prisma
    from . import repo as _repo
    c = await get_prisma().call.find_unique(where={"id": call_id})
    return _repo._call_dict(c) if c else None


@app.get("/api/billing/usage")
async def billing_usage(agent_id: Optional[str] = None, user=Depends(auth.get_current_user)):
    return await repo.get_usage(user.id, agent_id=agent_id)


# ---------------------------------------------------------------------------
# Wallet
# ---------------------------------------------------------------------------
@app.get("/api/wallet")
async def get_wallet(user=Depends(auth.get_current_user)):
    return await repo.get_wallet(user.id)


@app.post("/api/wallet/recharge")
async def recharge(body: Recharge, user=Depends(auth.get_current_user)):
    if body.add_amount <= 0:
        raise HTTPException(400, "Recharge amount must be positive")
    return await repo.recharge(user.id, body.add_amount)


# ---------------------------------------------------------------------------
# Cost preview
# ---------------------------------------------------------------------------
@app.post("/api/cost-preview")
async def cost_preview(body: dict):
    return billing_mod.calculate_call_cost(
        duration_seconds=int(body.get("duration_seconds", 60)),
        stt_seconds=float(body.get("stt_seconds", 30)),
        llm_input_tokens=int(body.get("llm_input_tokens", 500)),
        llm_output_tokens=int(body.get("llm_output_tokens", 800)),
        tts_chars=int(body.get("tts_chars", 800)),
        llm_provider_id=body.get("llm_provider_id", "groq_llama_3_3_70b"),
        stt_provider_id=body.get("stt_provider_id", "deepgram_nova2"),
        tts_provider_id=body.get("tts_provider_id", "google_wavenet_hi"),
        client_rate_per_min=float(body.get("client_rate_per_min", 2.50)),
    )


def run():
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")), reload=False)


if __name__ == "__main__":
    run()
