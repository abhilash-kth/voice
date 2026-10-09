"""Agent records (create/read/update/delete + knowledge base blobs)."""
from __future__ import annotations

from typing import Any, Optional

from ..db import get_prisma
from .common import _dump, _load_dict


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------
def _agent_dict(a: Any) -> dict:
    return {
        "id": a.id,
        "user_id": a.userId,
        "name": a.name,
        "description": a.description or "",
        "greeting": a.greeting or "",
        "language": a.language,
        "gender": getattr(a, "gender", "female") or "female",
        "voice_personality": a.voicePersonality,
        "client_rate_per_min": a.clientRatePerMin,
        "voice_speed": float(getattr(a, "voiceSpeed", 1.0) or 1.0),
        "memory_enabled": bool(a.memoryEnabled),
        "recording_enabled": bool(a.recordingEnabled),
        "max_concurrency": a.maxConcurrency,
        "enabled": bool(a.enabled),
        "agent_mode": a.agentMode or "assistant",
        "announce_text": a.announceText or "",
        "end_after_announcement": bool(getattr(a, "endAfterAnnouncement", False)) or bool(_load_dict(a.knowledge).get("end_after_announcement", False)),
        "fallback_response": getattr(a, "fallbackResponse", "") or "Sorry, there is a temporary technical problem. Please try again shortly.",
        "no_response_timeout_seconds": getattr(a, "noResponseTimeoutSeconds", 60) or 60,
        "no_response_message": getattr(a, "noResponseMessage", "") or "I did not hear a response, so I will end the call now. Thank you for calling.",
        "providers": _load_dict(a.providers),
        "knowledge": _load_dict(a.knowledge),
        "created_at": a.createdAt,
    }


async def list_agents(user_id: str) -> list[dict]:
    rows = await get_prisma().agent.find_many(
        where={"userId": user_id}, order={"createdAt": "desc"}
    )
    return [_agent_dict(a) for a in rows]


async def get_agent(agent_id: str, user_id: str) -> Optional[dict]:
    a = await get_prisma().agent.find_first(where={"id": agent_id, "userId": user_id})
    return _agent_dict(a) if a else None


async def create_agent(user_id: str, data: dict) -> dict:
    db = get_prisma()
    kn = data.get("knowledge") or {}
    if isinstance(kn, dict) and "end_after_announcement" not in kn:
        kn["end_after_announcement"] = bool(data.get("end_after_announcement", False))
    a = await db.agent.create(
        data={
            "userId": user_id,
            "name": data.get("name", "Agent"),
            "description": data.get("description", ""),
            "greeting": data.get("greeting", ""),
            "language": data.get("language", "hi"),
            "gender": data.get("gender", "female"),
            "voicePersonality": data.get("voice_personality", "friendly"),
            "clientRatePerMin": float(data.get("client_rate_per_min", 2.5)),
            "voiceSpeed": float(data.get("voice_speed", 1.0) or 1.0),
            "memoryEnabled": bool(data.get("memory_enabled", True)),
            "recordingEnabled": bool(data.get("recording_enabled", True)),
            "maxConcurrency": int(data.get("max_concurrency", 1)),
            "enabled": bool(data.get("enabled", True)),
            "agentMode": data.get("agent_mode", "assistant"),
            "announceText": data.get("announce_text", ""),
            "fallbackResponse": data.get("fallback_response", "Sorry, there is a temporary technical problem. Please try again shortly."),
            "noResponseTimeoutSeconds": max(15, int(data.get("no_response_timeout_seconds", 60))),
            "noResponseMessage": data.get("no_response_message", "I did not hear a response, so I will end the call now. Thank you for calling."),
            "providers": _dump(data.get("providers", {})),
            "knowledge": _dump(data.get("knowledge", {})),
        }
    )
    return _agent_dict(a)


async def update_agent(agent_id: str, user_id: str, patch: dict) -> Optional[dict]:
    data: dict = {}
    mapping = {
        "name": "name", "description": "description", "greeting": "greeting",
        "language": "language", "gender": "gender",
        "voice_personality": "voicePersonality",
        "client_rate_per_min": "clientRatePerMin", "voice_speed": "voiceSpeed",
        "memory_enabled": "memoryEnabled",
        "recording_enabled": "recordingEnabled", "max_concurrency": "maxConcurrency",
        "enabled": "enabled", "agent_mode": "agentMode", "announce_text": "announceText", "fallback_response": "fallbackResponse", "no_response_timeout_seconds": "noResponseTimeoutSeconds", "no_response_message": "noResponseMessage",
    }
    for k, v in patch.items():
        if k in mapping:
            data[mapping[k]] = v
    if "providers" in patch:
        data["providers"] = _dump(patch["providers"])
    if "knowledge" in patch:
        data["knowledge"] = _dump(patch["knowledge"])

    existing = await get_agent(agent_id, user_id)
    if not existing:
        return None
    if "end_after_announcement" in patch and "knowledge" not in data:
        kn = existing.get("knowledge", {})
        if isinstance(kn, dict):
            kn["end_after_announcement"] = bool(patch["end_after_announcement"])
            data["knowledge"] = _dump(kn)
    a = await get_prisma().agent.update(where={"id": agent_id}, data=data)
    return _agent_dict(a)


async def delete_agent(agent_id: str, user_id: str) -> bool:
    existing = await get_agent(agent_id, user_id)
    if not existing:
        return False
    await get_prisma().agent.delete(where={"id": agent_id})
    return True


async def set_agent_knowledge(agent_id: str, user_id: str, kb: dict) -> Optional[dict]:
    existing = await get_agent(agent_id, user_id)
    if not existing:
        return None
    current = dict(existing["knowledge"])
    if "text" in kb:
        current["text"] = kb.get("text") or ""
    if "system_prompt" in kb:
        current["system_prompt"] = kb.get("system_prompt") or ""
    if "faq" in kb:
        current["faq"] = kb.get("faq") or []
    if "documents" in kb:
        current["documents"] = kb.get("documents") or []
    # Keep the knowledge source unambiguous even for non-UI/API callers.
    if current.get("text", "").strip() and current.get("documents"):
        if "documents" in kb:
            current["text"] = ""
        else:
            current["documents"] = []
    a = await get_prisma().agent.update(where={"id": agent_id}, data={"knowledge": _dump(current)})
    return _agent_dict(a)


async def append_agent_document(agent_id: str, user_id: str, doc: dict) -> Optional[dict]:
    existing = await get_agent(agent_id, user_id)
    if not existing:
        return None
    current = dict(existing["knowledge"])
    docs = list(current.get("documents", []))
    docs.append(doc)
    current["documents"] = docs
    a = await get_prisma().agent.update(where={"id": agent_id}, data={"knowledge": _dump(current)})
    return _agent_dict(a)
