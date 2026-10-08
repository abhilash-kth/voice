"""Contextual retrieval-query construction for per-turn RAG: recent-turn
harvest, follow-up query building, context-diagnostics log. Extracted 1:1
from `agent_builder/ab_turn_rag.py` (<=300-line rule).
"""
from __future__ import annotations

import logging

from .ab_prompt import _chat_msg_text, _find_chat_ctx

from ...turn_rules import build_contextual_retrieval_query, is_contextual_followup

logger = logging.getLogger("voice-agent-saas-worker")


def build_contextual_retrieval(turn_ctx, original_user_query):
    """Harvest recent conversational context and build the internal
    retrieval query (the caller-facing user message stays unchanged)."""
    original_user_query = user_text
    retrieval_query = original_user_query
    recent_user_ctx = ""
    recent_assistant_ctx = ""
    context_used = False
    try:
        _ctx_for_recent = _find_chat_ctx(turn_ctx)
        if _ctx_for_recent is not None:
            _items = getattr(_ctx_for_recent, "items", []) or []
            # Find last user before current (not ack/incomplete, not same text)
            for m in reversed(_items):
                if getattr(m, "role", "") == "user":
                    _txt = _chat_msg_text(m).strip()
                    if not _txt or _txt == original_user_query or len(_txt) < 4:
                        continue
                    try:
                        from ...turn_rules import is_acknowledgement as _is_ack_r, is_incomplete_turn as _is_inc_r
                        if _is_ack_r(_txt) or _is_inc_r(_txt):
                            continue
                    except Exception:
                        pass
                    recent_user_ctx = _txt
                    break
            if not recent_user_ctx:
                for m in reversed(_items):
                    if getattr(m, "role", "") == "assistant":
                        _txt = _chat_msg_text(m).strip()
                        if _txt and len(_txt) > 10:
                            recent_assistant_ctx = _txt[:200]
                            break
    except Exception:
        recent_user_ctx = ""
        recent_assistant_ctx = ""

    try:
        if is_contextual_followup(original_user_query):
            _ctx_candidate = recent_user_ctx or recent_assistant_ctx
            if _ctx_candidate:
                _built = build_contextual_retrieval_query(
                    original_user_query, recent_user_ctx, recent_assistant_ctx
                )
                if _built and _built != original_user_query:
                    retrieval_query = _built
                    context_used = True
    except Exception:
        retrieval_query = original_user_query
        context_used = False

    try:
        logger.info(
            "🔎 [RAG_CONTEXT_QUERY] user_query='%s' retrieval_query='%s' context_used=%s recent_len=%d",
            original_user_query[:80],
            retrieval_query[:120],
            "yes" if context_used else "no",
            len(recent_user_ctx or recent_assistant_ctx),
        )
    except Exception:
        pass

    return retrieval_query, context_used
