"""Tiny shared store for diagnostic-only HTTP timing (built 2026-09-24).

Why this exists: the three boundaries Task 2 asked for are produced by
different layers —

  HTTP_REQUEST_START      httpx request event hook  (agent_builder)
  HTTP_RESPONSE_HEADERS   httpx response event hook (agent_builder)
  FIRST_STREAM_CHUNK      first decoded SSE delta   (worker LLM stream wrapper)

— and the hooks can't reach the stream wrapper, so both sides rendezvous here.
Pure bookkeeping: dict writes + time.time(); no lock needed (single event
loop, no awaits inside). Nothing in this module can fail a request — every
caller wraps its use in try/except, and reads that find no record simply skip
the [HTTP_CHUNK] line rather than inventing numbers.

Naming discipline (explicit user requirement): send->headers is NOT called
"provider TTFB". For a streaming request, httpx headers arrival is the first
response headers; when exactly the provider flushes them relative to first
token generation is provider-implementation-defined. We report the measured
boundaries only: request_start->response_headers,
response_headers->first_stream_chunk, request_start->first_stream_chunk.
"""
from __future__ import annotations

import time

# rid -> record; model -> most recent rid on that client
_records: dict = {}
_model_last: dict = {}


def note_send(model: str, rid: str) -> None:
    """Called from the httpx request hook when the SDK hands the request to
    the transport. Bounded growth: a call has ~15 requests; prune stale."""
    now = time.time()
    _records[rid] = {"rid": rid, "model": model, "send_ts": now, "headers_ts": 0.0, "status": 0, "trace": None}
    _model_last[model] = rid
    if len(_records) > 256:
        for k in [k for k, v in _records.items() if now - v["send_ts"] > 120.0][:128]:
            _records.pop(k, None)


def set_trace(rid: str, events: dict) -> None:
    rec = _records.get(rid)
    if rec is not None:
        rec["trace"] = events


def trace_summary(rid: str) -> str:
    """Return phase durations emitted by httpcore for a single request."""
    rec = _records.get(rid)
    events = rec.get("trace") if rec else None
    if not events:
        return ""
    parts = []
    for phase, edges in events.items():
        start = edges.get("started")
        end = edges.get("complete") or edges.get("completed") or edges.get("failed")
        if start is not None and end is not None:
            parts.append(f"{phase}={max(0, (end - start) * 1000):.0f}ms")
    return ",".join(parts)


def note_headers(rid: str, status: int) -> float:
    """Called from the async httpx response hook (headers received, before
    the body is iterated). Returns send->headers ms, or -1.0 if unknown."""
    rec = _records.get(rid)
    if rec is None:
        return -1.0
    now = time.time()
    rec["headers_ts"] = now
    try:
        rec["status"] = int(status)
    except Exception:
        pass
    return (now - rec["send_ts"]) * 1000.0


def pop_for_model(model: str, max_age: float = 15.0):
    """Called from the worker stream wrapper on the FIRST chunk of a stream.
    Returns the record of the most recent completed hook pair for this model
    (headers seen, fresh), or None. Pops so one HTTP attempt feeds at most one
    [HTTP_CHUNK] line — no double attribution across turns."""
    rid = _model_last.pop(model, None)
    if rid is None:
        return None
    rec = _records.pop(rid, None)
    if not rec or rec["headers_ts"] <= 0.0:
        return None
    if time.time() - rec["send_ts"] > max_age:
        return None
    return rec
