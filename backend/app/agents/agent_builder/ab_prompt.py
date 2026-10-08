from __future__ import annotations

import logging
import os
import re
from typing import Any

from ...models import AgentConfig
from ...config import (
    GROQ_API_KEY,
)

logger = logging.getLogger("voice-agent-saas-agent-builder")


_RAG_PREFIX = "[RAG]"

# Deterministic closing speech — fixed line, never LLM-generated (bb393dd fix).
DETERMINISTIC_CLOSING = "Thank you for calling us. Aapse baat karke achha laga. Goodbye."
DETERMINISTIC_CLOSING_EN = "Thank you for calling us. It was nice talking to you. Goodbye."

def _get_closing_for_cfg(cfg: AgentConfig) -> str:
    lang = (getattr(cfg, "language", "hi") or "hi").lower()
    if lang.startswith("en"):
        return DETERMINISTIC_CLOSING_EN
    return DETERMINISTIC_CLOSING


def _truncate(text: str, budget: int) -> str:
    """Clip `text` to `budget` chars, preferring a sentence/line boundary."""
    text = (text or "").strip()
    if budget <= 0 or len(text) <= budget:
        return text
    cut = text[:budget]
    best = -1
    for m in re.finditer(r"[.!?\n]", cut):
        best = m.end()
    if best > budget * 0.5:
        cut = text[:best]
    return cut.rstrip() + " …"


def _rag_per_turn_enabled() -> bool:
    v = (os.getenv("VOICE_RAG_PER_TURN") or "").strip().lower()
    if v in ("0", "false", "off"):
        return False
    if v in ("1", "true", "on"):
        return True
    # FIXED: Always enable RAG per-turn for KB grounding, even when preemptive ON.
    # Previous: disabled RAG when VOICE_PREEMPTIVE=1 to preserve preemptive, but that
    # sacrificed correctness (\"Mere paas exact jaankari nahi hai\").
    # Now: RAG always ON for correctness. When preemptive ON, we explicitly log
    # that RAG will invalidate preemptive for this turn (correctness > latency),
    # but we still do RAG. This is explicit handling, not silent skip.
    # Preemptive still benefits non-KB turns (greetings, small talk).
    return True


def _chat_msg_text(item) -> str:
    """Best-effort text of a v1 ChatMessage (or a plain string)."""
    if item is None:
        return ""
    if isinstance(item, str):
        return item
    if hasattr(item, "text_content") and item.text_content:
        return str(item.text_content)
    content = getattr(item, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(str(c) for c in content if isinstance(c, str))
    return ""


# ---------------------------------------------------------------------------
# Incomplete-turn fragment state machine — the 03:07 call fix.
#
# Production evidence (03:07:39→03:08:44): a held fragment "Ok और" was
# merged into EVERY following turn — the buffer had no consume step, so it
# accumulated duplicates ("merged 3 fragment(s): 'Ok और Ok और और इसका
# office...'") and contaminated RAG queries for the rest of the call. Two
# additional first-answer failures were visible in the same log: the real
# K-exam question DID retrieve (2 hits), but its LLM request was clobbered
# 104ms in by the caller's own next FINAL ("वह क्या है?" — one continuous
# speech burst split by VAD), and that bare pronoun follow-up then went to
# RAG alone → 0 hits → "मेरे पास जानकारी नहीं है". Repeats worked only
# because the contaminated buffer accidentally carried the question text.
#
# Rules implemented here (per spec, no keyword special-casing):
#   - fragments are TIMESTAMPED and CONSUMED (buffer cleared) when merged;
#   - ACK turns and drops also clear — a new independent turn starts clean;
#   - fragments older than _FRAGMENT_TTL_S never merge (stale evidence);
#   - a turn whose request was superseded BEFORE producing any output is
#     strong evidence the caller is still in the same utterance (worker tags
#     it via turn_timing["overwritten_turn"] with its generation token); the
#     just-killed question merges forward with the immediate continuation,
#     so the FIRST valid question gets its retrieved context — with the same
#     clean query the repeat had to fight for. The gen tag makes a late
#     teardown unable to contaminate a turn two generations later.
# ---------------------------------------------------------------------------
_FRAGMENT_TTL_S = 12.0
_SUPERSEDED_MERGE_MAX_AGE_S = 6.0


def _frag_norm(p, now_ts):
    if isinstance(p, (tuple, list)) and len(p) == 2:
        try:
            return str(p[0]), float(p[1] or 0.0)
        except Exception:
            return str(p[0]), now_ts
    return str(p), now_ts


def _frag_append_fresh(tt, texts, now_ts):
    """Append texts to the fragment buffer after dropping TTL-stale entries."""
    pend = []
    for q in (tt.get("pending_fragments") or []):
        t, ts = _frag_norm(q, now_ts)
        if t and now_ts - ts <= _FRAGMENT_TTL_S:
            pend.append((t, ts))
    for t in texts:
        if t:
            pend.append((str(t), now_ts))
    pend = pend[-4:]
    if pend:
        tt["pending_fragments"] = pend
    else:
        tt.pop("pending_fragments", None)
    return pend


def _frag_consume(tt, now_ts):
    """TAKE the whole buffer and CLEAR it (the missing consume step).
    Returns (fresh_texts, dropped_stale_count)."""
    raw = list(tt.get("pending_fragments") or [])
    if raw:
        tt.pop("pending_fragments", None)
    fresh, dropped = [], 0
    for q in raw:
        t, ts = _frag_norm(q, now_ts)
        if t and now_ts - ts <= _FRAGMENT_TTL_S:
            fresh.append(t)
        else:
            dropped += 1
    return fresh, dropped


def _strip_trailing_ack_turns(target: Any) -> int:
    """Drop trailing pure-ack assistant messages from THIS TURN's ctx copy.

    11:41 log defect #2: the previous turn's deterministic acknowledgement
    ('जी, बताइए।') sat as the last assistant message right above the model's
    answer slot, and the model pattern-completed instead of answering the
    real question — even on RAG-hit turns, and it kept re-seeding the echo
    each turn. `target` is the per-turn temp_mutable_chat_ctx (the library
    discards it after generation; ChatContext.copy() owns a fresh items
    list), so removal changes THIS request only — session history,
    transcripts and billing stay intact. Detection reuses
    rag.is_acknowledgement (the same turn_rules classifier that produces
    deterministic acks) — no new string matching.
    """
    if target is None:
        return 0
    n = 0
    try:
        items = getattr(target, "items", None)
        if not isinstance(items, list):
            return 0
        from ... import rag as _ack_rules
        _outs = _ack_reply_texts(_ack_rules)
        for k in range(len(items) - 1, -1, -1):
            m = items[k]
            if getattr(m, "type", "message") != "message" or getattr(m, "role", "") != "assistant":
                break
            txt = _chat_msg_text(m).strip()
            if not txt or len(txt) > 40:
                break
            if not (_ack_rules.is_acknowledgement(txt) or txt in _outs):
                break
            del items[k]
            n += 1
            if n >= 3:
                break
    except Exception:
        return n
    return n


_ACK_REPLY_OUTPUTS: set = set()


def _ack_reply_texts(rules) -> frozenset:
    """The exact strings turn_rules.ack_reply() can emit — probed at runtime
    from the module's OWN function (its classifier seeds), never a copy of
    its wording hardcoded here: if the deterministic reply ever changes, the
    strip follows automatically. Assistant messages equal to a generated ack
    reply (or classifying as a bare acknowledgement) are the echo template;
    nothing else ever matches."""
    global _ACK_REPLY_OUTPUTS
    if not _ACK_REPLY_OUTPUTS:
        try:
            _ACK_REPLY_OUTPUTS = frozenset(
                rules.ack_reply(w) for w in ("haan", "हाँ", "हां", "han", "जी", "ji", "ok", "yes", "thanks")
            ) - {""}
        except Exception:
            return frozenset()
    return _ACK_REPLY_OUTPUTS


def _find_chat_ctx(obj) -> Any:
    """Return the mutable ChatContext from a v1 turn context (defensively)."""
    candidates = [obj]
    for attr in ("chat_ctx", "llm_ctx", "context"):
        v = getattr(obj, attr, None)
        if v is not None:
            candidates.append(v)
    for c in candidates:
        if c is not None and hasattr(c, "add_message"):
            return c
    return None


# ---------------------------------------------------------------------------
# System prompt builder (persona + business facts + FAQ)
# ---------------------------------------------------------------------------
