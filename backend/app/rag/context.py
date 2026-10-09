"""Context assembly for the LLM prompt: retrieval + graceful fallback.

Extracted from rag.py - behavior unchanged.
"""
from __future__ import annotations


import logging
from typing import Any, List
from ..models import KnowledgeBase, KnowledgeItem

_logger = logging.getLogger("voice-agent-saas")

from .cache import _index_for, _tokens
from .retrieval import retrieve


_FALLBACK_MAX_CHARS = 560

_GENERIC_QUERY_TOKENS = frozenset(
    "what how why when where who which whom this that these those have has had not and for you your "
    "mine tell give give me can could would should about with from they them here there work works "
    "doing does did done doing know thing things stuff detail details info information please company "
    "kya kaun kab kahan kaise karna karta karte karti karo karu mujhe mere mera tum tumha apna apni "
    "hai hain hoja bacha bas raha rahi bataye batao batana chahiye chhaiye liya liye sath saath liye".split()
    + ["क्या", "कब", "कहाँ", "कौन", "कैसे", "काम", "करता", "करती", "करने", "करो", "मुझे", "मेरा", "मेरी",
       "है", "हैं", "हूँ", "बताओ", "बताइए", "बताना", "चाहिए", "साथ", "लिये", "लिए", "वाला", "वाली",
       "कौनसा", "कौनसी", "क्याहै", "कुछ", "सब", "भारी", "हुआ", "हुई", "होता", "होती", "होते"]
)


def fallback_context(kb: KnowledgeBase, query: str) -> tuple:
    """(excerpt, n_source_chunks) — containment-based near-match lookup.

    Fires ONLY after main retrieval returned nothing; reuses the cached
    (items, doc_tokens) pair, so no re-chunking/re-tokenizing of the corpus
    happens here. Returns ("", 0) whenever no content word is found in any
    chunk, no KB exists, or any error occurs — never raises into the call.
    """
    try:
        items, doc_tokens, _bm = _index_for(kb)
    except Exception:
        return "", 0
    if not items or not query:
        return "", 0
    q_tokens = _tokens(query)
    q = []
    seen_q = set()
    for t in q_tokens:
        if len(t) >= 4 and t not in _GENERIC_QUERY_TOKENS and t not in seen_q:
            seen_q.add(t)
            q.append(t)
    if not q:
        return "", 0
    best = (-1.0, -1, "")
    for idx, it in enumerate(items[:400]):  # bounded scan; corpora are chunk-capped upstream
        if idx < len(doc_tokens):
            tokset = set(doc_tokens[idx])
            full = sum(1 for t in q if t in tokset)
            if full:
                score = 2.0 * full  # shouldn't happen after a 0-hit retrieve(); keep ordering sane
            else:
                hay = it.text.lower()
                part = sum(1 for t in q if t in hay)
                if not part:
                    continue
                score = float(part)
        else:
            hay = it.text.lower()
            part = sum(1 for t in q if t in hay)
            if not part:
                continue
            score = float(part)
        if score > best[0]:
            best = (score, idx, it.text)
    if best[0] <= 0:
        return "", 0
    _txt = best[2] or ""
    if len(_txt) > _FALLBACK_MAX_CHARS:
        _low = _txt.lower()
        _pos = -1
        for t in q:
            p = _low.find(t)
            if p != -1:
                _pos = p
                break
        if _pos < 0:
            _pos = 0
        _start = max(0, min(_pos - _FALLBACK_MAX_CHARS // 2, len(_txt) - _FALLBACK_MAX_CHARS))
        _txt = _txt[_start:_start + _FALLBACK_MAX_CHARS]
    return _txt.strip(), 1


def build_context_detailed(kb: KnowledgeBase, query: str, top_k: int = 3) -> dict:
    """Retrieve top facts and return detailed metadata on KB vs FAQ usage."""
    hits = retrieve(kb, query, top_k=top_k)
    if not hits:
        return {
            "text": "",
            "kb_used": False,
            "kb_chars": 0,
            "kb_hits": 0,
            "faq_used": False,
            "faq_chars": 0,
            "faq_hits": 0,
            "total_chars": 0,
            "sources": [],
        }

    kb_parts: List[str] = []
    faq_parts: List[str] = []
    sources: List[str] = []

    for it in hits:
        sources.append(it.source)
        if it.source == "faq":
            faq_parts.append(it.text)
        else:
            kb_parts.append(it.text)

    parts = [f"- {it.text}" for it in hits]
    full_text = "\n".join(parts)

    return {
        "text": full_text,
        "kb_used": len(kb_parts) > 0,
        "kb_chars": sum(len(p) for p in kb_parts),
        "kb_hits": len(kb_parts),
        "faq_used": len(faq_parts) > 0,
        "faq_chars": sum(len(p) for p in faq_parts),
        "faq_hits": len(faq_parts),
        "total_chars": len(full_text),
        "sources": sources,
    }


def build_context(kb: KnowledgeBase, query: str, top_k: int = 3) -> str:
    return build_context_detailed(kb, query, top_k=top_k)["text"]
