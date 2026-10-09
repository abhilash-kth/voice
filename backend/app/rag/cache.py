"""Tokeniser + per-KB in-memory index cache with content fingerprints.

Extracted from rag.py. rank_bm25 is imported at module import time (not
lazily mid-call); see the note below for why.
"""
from __future__ import annotations


import logging
import re
from collections import OrderedDict
from typing import List

from ..models import KnowledgeBase


_logger = logging.getLogger("voice-agent-saas")

from .chunking import build_index


# rank_bm25 used to be imported lazily INSIDE retrieve() ("optional fast
# path"). retrieve() first runs on the worker's STT-interim prefetch — mid
# call — so the very first partial transcript paid the whole module load
# (rank_bm25 + numpy chain, source parsing via tokenize) while holding the
# import lock; the 03:07–03:09 log shows exactly that as the 119ms
# "numpy/_core/fromnumeric.py" and 175ms "tokenize.py" event-loop blocks
# (the loop starves on the import lock and samples frames it never chose).
# Importing here costs startup microseconds and can no longer land inside a
# live call. Behavior is unchanged: availability still decided by try/
# except, same fast path, same _BM25 fallback on construction failure.
try:
    from rank_bm25 import BM25Okapi as _BM25Okapi
except Exception:  # not installed / broken wheel -> pure-python fallback
    _BM25Okapi = None


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------
_WORD_RE = re.compile(r"[A-Za-z0-9\u0900-\u097F]+")


def _tokens(text: str) -> List[str]:
    return [t.lower() for t in _WORD_RE.findall(text)]


# ---------------------------------------------------------------------------
# Corpus-side memoization (event-loop blocking fix, 03:07–03:09 log).
#
# retrieve() re-chunked, re-tokenized and rebuilt the BM25 index on EVERY
# call — including every STT-interim prefetch. That whole-corpus work is
# pure Python: even inside asyncio.to_thread it holds the GIL for 100ms+
# bursts, starving the audio loop (the monitor sampled numpy/_core/
# fromnumeric.py 119ms and asyncio/windows_events.py 109ms — frames the loop
# never chose, just where it was parked while our thread hogged the lock).
# The corpus side is now built once per KB snapshot and reused; query-side
# work (tokenize query + score) still runs per call, so RETRIEVAL RESULTS
# ARE BIT-IDENTICAL — same items, same index, same scores, same floor.
# ---------------------------------------------------------------------------
_INDEX_CACHE: "OrderedDict[tuple, tuple]" = OrderedDict()
_INDEX_CACHE_MAX = 4


def _kb_fingerprint(kb: KnowledgeBase) -> tuple:
    """Cheap content fingerprint of the KB snapshot. Reading lengths is
    O(documents), not O(corpus); mutating any text changes the hash or a
    doc length, and worst case (in-place edit with identical length) just
    keeps the current per-call staleness window of the prefetch cache."""
    try:
        th = hash(kb.text or "")
    except Exception:
        th = -1
    try:
        docs = tuple(
            (str(d.get("name", "")),
             hash(str(d.get("content", "") or d.get("text", ""))))
            for d in (kb.documents or [])
        )
    except Exception:
        docs = None
    try:
        faq = tuple(
            (hash(str(x.get("q", "") or x.get("question", ""))),
             hash(str(x.get("a", "") or x.get("answer", ""))))
            for x in (getattr(kb, "faq", None) or [])
        )
    except Exception:
        faq = None
    return (id(kb), th, docs, faq)


def _index_for(kb: KnowledgeBase):
    """(items, doc_tokens, bm_fast) for a KB snapshot — corpus work once."""
    key = _kb_fingerprint(kb)
    hit = _INDEX_CACHE.get(key)
    if hit is not None:
        _INDEX_CACHE.move_to_end(key)
        return hit
    items = build_index(kb)
    doc_tokens = [_tokens(it.text) for it in items]
    bm = None
    if _BM25Okapi is not None and doc_tokens:
        try:
            bm = _BM25Okapi(doc_tokens)
        except Exception:
            bm = None  # per-query construction errors still fall back below
    _INDEX_CACHE[key] = (items, doc_tokens, bm)
    while len(_INDEX_CACHE) > _INDEX_CACHE_MAX:
        _INDEX_CACHE.popitem(last=False)
    return items, doc_tokens, bm


# Acknowledgement / incomplete-turn classification lives in turn_rules.py
# (shared with worker + builder hook without importing retrieval deps).
# Re-exported here for existing call sites.
def normalize_query(text: str) -> str:
    """Lowercase, punctuation-free, whitespace-collapsed form of a query.

    Used as the key for RAG prefetch results: the worker runs retrieval on STT
    *interim* text and the turn hook looks it up with the *final* text — both
    sides must normalise identically for the cache to hit. Strips everything
    the tokeniser would drop (punctuation, digits-are-kept), Latin + Devanagari
    word characters only, so "Kya, aapka rate?" and "kya aapka rate" collide.
    """
    return " ".join(_WORD_RE.findall((text or "").lower()))


# ---------------------------------------------------------------------------
# Scorer (BM25 or fallback)
# ---------------------------------------------------------------------------
