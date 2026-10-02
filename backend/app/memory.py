"""
Cross-call customer conversation memory.

Per customer (keyed by phone number), we keep the most recent exchanges so the
agent can reference earlier context ("continue where we left off"). Stored in
JSON under backend/data/memory.json — keyed to feel like a customer 360 view.

Swap the backing store for Neon when ready; the interface stays the same.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import DATA_DIR

_FILE = DATA_DIR / "memory.json"
_LOCK = threading.Lock()

_MAX_TURNS = 40  # keep the most recent ~20 exchanges


def _read() -> dict[str, Any]:
    if not _FILE.exists():
        return {}
    try:
        return json.loads(_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write(data: dict[str, Any]) -> None:
    with _LOCK:
        _FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def format_memory(transcripts: list[dict[str, Any]]) -> str:
    """Turn a list of {role, text} into a readable prior-conversation blurb."""
    lines = []
    for t in transcripts[-_MAX_TURNS:]:
        who = "Customer" if t.get("role") == "user" else "Agent"
        lines.append(f"{who}: {t.get('text','')}")
    return "\n".join(lines)


def load(key: str) -> str:
    """Return the prior-conversation text for a customer key (phone/room)."""
    data = _read()
    item = data.get(key, {})
    return format_memory(item.get("transcripts", []))


def save(key: str, transcripts: list[dict[str, Any]]) -> None:
    data = _read()
    # keep the last N turns and add a timestamp
    data[key] = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "transcripts": transcripts[-_MAX_TURNS:],
    }
    _write(data)


def clear(key: str) -> None:
    data = _read()
    data.pop(key, None)
    _write(data)
