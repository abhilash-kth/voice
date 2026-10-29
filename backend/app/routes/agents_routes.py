"""Agent CRUD + knowledge-base routes (/api/agents*).
Extracted from the old monolithic main.py — behavior unchanged.
"""
from __future__ import annotations

import json

from ..services import config_store

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Form

from ..models import AgentCreate, AgentUpdate
from .. import auth
from .. import repo
from ..services.telephony_policy import (TelephonyError,
                                         validate_agent_phone_assignment)

logger = logging.getLogger("voice-agent-saas-api")

router = APIRouter(tags=["agents"])


def _cache_agent(rec: dict) -> None:
    try:
        from ..config import DATA_DIR
        cache_file = DATA_DIR / f"agent_{rec['id']}.json"
        cache_file.write_text(json.dumps(rec))
    except Exception:
        pass


async def _sync_agent_numbers(user_id: str, *phone_ids) -> str:
    """Best-effort inbound dispatch sync after assignment changes. Returns a
    warning (agent save still succeeds; the number shows the pending error)."""
    from ..services import telephony_provisioning
    warning = ""
    for phone_id in {p for p in phone_ids if p}:
        try:
            await telephony_provisioning.sync_inbound_dispatch(phone_id, user_id)
        except Exception as e:
            logger.warning("[AGENT_INBOUND_SYNC_WARN] phone=%s: %s", phone_id, e)
            warning = warning or f"Inbound routing sync pending: {e}"
    return warning


async def _enrich_phone(rec: dict, user_id: str) -> dict:
    if rec.get("phone_number_id"):
        phone = await repo.get_phone_number(rec["phone_number_id"], user_id)
        rec["phone_number"] = phone["number"] if phone else None
    else:
        rec["phone_number"] = None
    return rec


# ---------------------------------------------------------------------------
# Agents CRUD (per-user)
# ---------------------------------------------------------------------------
@router.get("/api/agents")
async def list_agents(user=Depends(auth.get_current_user)):
    agents = await repo.list_agents(user.id)
    try:
        phone_by_id = {p["id"]: p["number"]
                       for p in await repo.list_phone_numbers(user.id)}
    except Exception:
        phone_by_id = {}
    for a in agents:
        a["phone_number"] = phone_by_id.get(a.get("phone_number_id") or "")
        calls = await repo.list_calls(user.id, agent_id=a["id"])
        a["call_count"] = len([c for c in calls if c["status"] in ("completed", "in-progress")])
        a["total_billed"] = round(
            sum(float(c["cost"].get("client_price_inr", 0) or 0) for c in calls if c["status"] == "completed"), 2,
        )
        a["active_calls"] = await repo.count_active_calls(a["id"])
    return {"agents": agents}


@router.get("/api/agents/{agent_id}")
async def get_agent(agent_id: str, user=Depends(auth.get_current_user)):
    rec = await repo.get_agent(agent_id, user.id)
    if not rec:
        raise HTTPException(404, "Agent not found")
    return await _enrich_phone(rec, user.id)


@router.post("/api/agents", status_code=201)
async def create_agent(body: AgentCreate, user=Depends(auth.get_current_user)):
    from ..services import catalog_service

    await config_store.refresh_if_stale()

    def _v2_llm_validate(prov: str, model: str, label: str) -> None:
        ok_db, msg_db = catalog_service.validate_llm(prov, model) if prov else (False, "")
        if ok_db:
            return
        raise HTTPException(400, f"{label} LLM invalid: {msg_db}")

    # Validate LLM with new V2 catalog - no silent substitution, clear error
    try:
        if body.providers.llm_v2:
            _v2_llm_validate(body.providers.llm_v2.provider, body.providers.llm_v2.model_id, "Primary")
        else:
            # Old style: resolve provider/model and validate
            prov, model_id, _ = body.providers.llm.resolve_llm_provider_model()
            if prov and model_id:
                _v2_llm_validate(prov, model_id, "Primary")
            else:
                # Fallback to old get_provider check for backward compat
                if not config_store.get_provider("llm", body.providers.llm.id):
                    raise HTTPException(400, f"Unknown LLM provider {body.providers.llm.id}")

        if body.providers.llm_fallback_v2:
            _v2_llm_validate(body.providers.llm_fallback_v2.provider, body.providers.llm_fallback_v2.model_id, "Fallback")
        elif body.providers.llm_fallback:
            prov, model_id, _ = body.providers.llm_fallback.resolve_llm_provider_model()
            if prov and model_id:
                _v2_llm_validate(prov, model_id, "Fallback")

    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"LLM validation error: {e}")

    for kind, sel in (("stt", body.providers.stt),
                      ("tts", body.providers.tts), ("telephony", body.providers.telephony)):
        if not sel:
            continue
        prov = config_store.get_provider(kind, sel.id)
        if not prov:
            raise HTTPException(400, f"Unknown provider {sel.id} for {kind}")
        # Super-Admin-disabled providers can no longer be selected for NEW agents.
        # (Saved agents that already use one keep running — see voice pipeline.)
        if prov.get("enabled") is False:
            raise HTTPException(400, f"Provider {sel.id} is disabled by the administrator for {kind}")
    # Monthly-plan entitlements: active subscription + agent-slot headroom,
    # and the agent's max concurrency must fit the purchased lines.
    from ..services import subscription_service
    try:
        current = len(await repo.list_agents(user.id))
        await subscription_service.ensure_agent_creation_allowed(user.id, current)
        await subscription_service.ensure_concurrency_allowed(
            user.id, int(getattr(body, "max_concurrency", 1) or 1))
    except subscription_service.SubscriptionError as e:
        raise HTTPException(402, str(e)) from None
    # Purpose is required by the schema; an assigned number must be this
    # user's active DID, with at most one inbound-capable agent per DID.
    try:
        await validate_agent_phone_assignment(
            user.id, body.purpose, body.phone_number_id)
    except TelephonyError as e:
        raise HTTPException(e.status_code, str(e)) from None
    rec = await repo.create_agent(user.id, body.model_dump())
    _cache_agent(rec)
    warning = await _sync_agent_numbers(user.id, rec.get("phone_number_id"))
    rec = await _enrich_phone(rec, user.id)
    if warning:
        rec["telephony_warning"] = warning
    return rec


@router.put("/api/agents/{agent_id}")
async def update_agent(agent_id: str, body: AgentUpdate, user=Depends(auth.get_current_user)):
    existing = await repo.get_agent(agent_id, user.id)
    if not existing:
        raise HTTPException(404, "Agent not found")
    patch = body.model_dump(exclude_none=True)
    # exclude_none would drop an explicit null; present-but-null is how the
    # form clears the assigned number.
    if "phone_number_id" in body.model_fields_set:
        patch["phone_number_id"] = body.phone_number_id or None
    effective_purpose = patch.get("purpose", existing.get("purpose") or "outbound")
    effective_phone = (patch["phone_number_id"] if "phone_number_id" in patch
                       else existing.get("phone_number_id"))
    try:
        await validate_agent_phone_assignment(
            user.id, effective_purpose, effective_phone,
            current_agent_id=agent_id)
    except TelephonyError as e:
        raise HTTPException(e.status_code, str(e)) from None
    if patch.get("max_concurrency") is not None:
        from ..services import subscription_service
        try:
            await subscription_service.ensure_concurrency_allowed(
                user.id, int(patch["max_concurrency"] or 1))
        except subscription_service.SubscriptionError as e:
            raise HTTPException(402, str(e)) from None
    rec = await repo.update_agent(agent_id, user.id, patch)
    if not rec:
        raise HTTPException(404, "Agent not found")
    _cache_agent(rec)
    warning = await _sync_agent_numbers(
        user.id, existing.get("phone_number_id"), rec.get("phone_number_id"))
    rec = await _enrich_phone(rec, user.id)
    if warning:
        rec["telephony_warning"] = warning
    return rec


@router.delete("/api/agents/{agent_id}", status_code=204)
async def delete_agent(agent_id: str, user=Depends(auth.get_current_user)):
    existing = await repo.get_agent(agent_id, user.id)
    if not await repo.delete_agent(agent_id, user.id):
        raise HTTPException(404, "Agent not found")
    if existing and existing.get("phone_number_id"):
        await _sync_agent_numbers(user.id, existing["phone_number_id"])


# ---------------------------------------------------------------------------
# Knowledge base
# ---------------------------------------------------------------------------
@router.put("/api/agents/{agent_id}/knowledge")
async def set_knowledge(agent_id: str, body: dict, user=Depends(auth.get_current_user)):
    rec = await repo.set_agent_knowledge(agent_id, user.id, body)
    if not rec:
        raise HTTPException(404, "Agent not found")
    return rec


@router.post("/api/agents/{agent_id}/knowledge")
async def add_knowledge(
    agent_id: str,
    text: Optional[str] = Form(None),
    faq: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    user=Depends(auth.get_current_user),
):
    agent_rec = await repo.get_agent(agent_id, user.id)
    if not agent_rec:
        raise HTTPException(404, "Agent not found")

    # Entitlement limits (free base + purchased KB packs), enforced per agent.
    from ..services import subscription_service
    lim = await subscription_service.kb_limits(user.id)

    def _kb_over(total_chars: int = 0, faq_count: int = 0) -> None:
        if total_chars > lim["kb_char_limit"]:
            raise HTTPException(402, (
                f"Knowledge base limit exceeded ({total_chars}/{lim['kb_char_limit']} chars). "
                "Buy a KB pack on the Billing page for a bigger allowance."))
        if faq_count > lim["kb_faq_limit"]:
            raise HTTPException(402, (
                f"FAQ limit exceeded ({faq_count}/{lim['kb_faq_limit']}). "
                "Buy a KB pack on the Billing page for more FAQs."))

    if file is not None and text and text.strip():
        raise HTTPException(400, "Choose either a knowledge file or pasted text, not both")

    if file is not None:
        doc_name = file.filename or "uploaded-doc"
        raw = await file.read()
        if len(raw) > 10 * 1024 * 1024:
            raise HTTPException(413, "Knowledge file must be 10 MB or smaller")
        content = _parse_file(doc_name, raw)
        if len(content) > 2_000_000:
            raise HTTPException(413, "Extracted knowledge content is too large")
        # File upload REPLACES the document source — the new total is just it.
        _kb_over(total_chars=len(content))
        await repo.set_agent_knowledge(agent_id, user.id, {"text": "", "documents": [{"name": doc_name, "content": content}]})
        return {"ok": True, "replaced": "document", "kb_char_limit": lim["kb_char_limit"]}

    if text:
        # Pasted text replaces the whole knowledge source (repo clears
        # documents when text is set), so the new total is just the text.
        _kb_over(total_chars=len(text))
        await repo.set_agent_knowledge(agent_id, user.id, {"text": text})
        return {"ok": True, "appended": "text", "kb_char_limit": lim["kb_char_limit"]}

    if faq:
        import json as _json
        try:
            items = _json.loads(faq)
        except Exception:
            raise HTTPException(400, "faq must be a JSON array of {q,a}")
        _kb_over(faq_count=len(items))
        await repo.set_agent_knowledge(agent_id, user.id, {"faq": items})
        return {"ok": True, "appended": "faq", "count": len(items), "kb_faq_limit": lim["kb_faq_limit"]}

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