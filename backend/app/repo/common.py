"""Shared helpers for the repo package: timestamps + JSON (de)serialization.

Prisma stores the JSON blobs (providers, knowledge, transcripts, usage, cost)
as plain strings so SQLite and Postgres/Neon behave identically.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional


def _ts() -> str:
    return datetime.utcnow().isoformat(timespec="seconds")


def _dump(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False) if v is not None else "{}"


def _load_dict(s: Optional[str]) -> dict:
    if not s:
        return {}
    try:
        return json.loads(s)
    except Exception:
        return {}


def _load_list(s: Optional[str]) -> list:
    if not s:
        return []
    try:
        return json.loads(s)
    except Exception:
        return []
