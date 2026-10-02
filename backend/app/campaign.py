"""
Bulk-call campaigns: upload a lead file, then dial the numbers up to a concurrency
limit, substituting each lead's columns into the agent's dynamic script.

Stored as JSON under backend/data/campaigns.json (swap for Neon later; the
interface stays the same). Kept intentionally DB-agnostic so it works on a fresh
setup without a schema migration.
"""
from __future__ import annotations

import uuid
import threading
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from .config import DATA_DIR

_FILE = DATA_DIR / "campaigns.json"
_LOCK = threading.Lock()

VALID_STATUS = ("queued", "calling", "done", "failed")


def _read() -> dict[str, dict]:
    if not _FILE.exists():
        return {}
    try:
        return json.loads(_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write(data: dict[str, dict]) -> None:
    with _LOCK:
        _FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _new_id() -> str:
    return "cmp-" + uuid.uuid4().hex[:10]


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def create(*, user_id: str, agent_id: str, name: str, concurrency: int,
           sip_trunk_id: str = "", lead_rows: list[dict], phone_column: str) -> dict:
    """Create a campaign with pre-parsed leads. Status starts as 'paused' (caller
    starts it explicitly, or the API can auto-start)."""
    cid = _new_id()
    leads = []
    for i, row in enumerate(lead_rows):
        leads.append({
            "index": i,
            "data": row,
            "status": "queued",
            "call_id": "",
            "error": "",
            "updated_at": _now(),
        })
    campaign = {
        "id": cid,
        "user_id": user_id,
        "agent_id": agent_id,
        "name": name,
        "concurrency": max(1, int(concurrency)),
        "sip_trunk_id": sip_trunk_id,
        "phone_column": phone_column,
        "created_at": _now(),
        "status": "paused",          # paused | running | done
        "leads": leads,
    }
    campaign["summary"] = _recalc_summary(campaign)
    data = _read()
    data[cid] = campaign
    _write(data)
    return campaign


def _recalc_summary(c: dict) -> dict:
    counts = {"queued": 0, "calling": 0, "done": 0, "failed": 0, "total": len(c.get("leads", []))}
    for lead in c.get("leads", []):
        st = lead.get("status", "queued")
        if st in counts:
            counts[st] += 1
    return counts


def get(user_id: str, campaign_id: str) -> Optional[dict]:
    c = _read().get(campaign_id)
    if not c or c.get("user_id") != user_id:
        return None
    c["summary"] = _recalc_summary(c)
    return c


def list_campaigns(user_id: str) -> list[dict]:
    data = _read()
    items = [c for c in data.values() if c.get("user_id") == user_id]
    items.sort(key=lambda c: c.get("created_at", ""), reverse=True)
    for c in items:
        c["summary"] = _recalc_summary(c)
    return items


def list_running() -> list[dict]:
    data = _read()
    return [c for c in data.values() if c.get("status") == "running"]


def set_status(user_id: str, campaign_id: str, status: str) -> Optional[dict]:
    data = _read()
    c = data.get(campaign_id)
    if not c or c.get("user_id") != user_id:
        return None
    c["status"] = status
    c["summary"] = _recalc_summary(c)
    _write(data)
    return c


def delete(user_id: str, campaign_id: str) -> bool:
    data = _read()
    c = data.get(campaign_id)
    if not c or c.get("user_id") != user_id:
        return False
    del data[campaign_id]
    _write(data)
    return True


def update_lead(campaign_id: str, lead_index: int, patch: dict) -> None:
    data = _read()
    c = data.get(campaign_id)
    if not c:
        return
    for lead in c.get("leads", []):
        if lead.get("index") == lead_index:
            lead.update(patch)
            lead["updated_at"] = _now()
            break
    c["summary"] = _recalc_summary(c)
    _write(data)


def get_lead(campaign_id: str, lead_index: int) -> Optional[dict]:
    c = _read().get(campaign_id)
    if not c:
        return None
    for lead in c.get("leads", []):
        if lead.get("index") == lead_index:
            return lead
    return None


def running_campaigns_with_free_slots() -> list[dict]:
    """All running campaigns, annotated with how many more calls they can place."""
    out = []
    for c in list_running():
        summary = _recalc_summary(c)
        free = max(0, c.get("concurrency", 1) - summary["calling"] - summary["queued"])
        # Actually we dispatch queued up to the limit; free slots = concurrency - calling.
        free = max(0, c.get("concurrency", 1) - summary["calling"])
        out.append({**c, "free_slots": free, "summary": summary})
    return out
