"""
Knowledge base retrieval (lightweight RAG).

Chunks manual text + uploaded document text, indexes it, and retrieves the most
relevant chunks for a query using BM25 (rank_bm25) when available, otherwise a
simple token-overlap scorer. This keeps the platform dependency-light and works
offline for the demo.

Docs can be swapped for embeddings later without touching the API.
"""
from __future__ import annotations

import logging
import os
import re
from collections import OrderedDict
from typing import Any, List

from .models import KnowledgeBase, KnowledgeItem

_logger = logging.getLogger("voice-agent-saas")

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
def _chunk_text(text: str, chunk_size: int = 700, overlap: int = 100) -> List[str]:
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text] if text else []
    chunks: List[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + chunk_size, n)
        # try to break at a sentence / whitespace boundary near the end
        window = text[start:end]
        candidates = [m.start() for m in re.finditer(r"[.!?。\n]", window)]
        if candidates:
            cut = candidates[-1] + 1
            if cut > chunk_size * 0.5:  # keep chunks reasonably sized
                end = start + cut
        chunks.append(text[start:end].strip())
        if end >= n:
            break
        start = max(end - overlap, start + 1)
    return [c for c in chunks if c]


# ---------------------------------------------------------------------------
# Index builder
# ---------------------------------------------------------------------------
def build_index(kb: KnowledgeBase) -> List[KnowledgeItem]:
    items: List[KnowledgeItem] = []
    if kb.text and kb.text.strip():
        for i, chunk in enumerate(_chunk_text(kb.text)):
            items.append(KnowledgeItem(chunk_id=f"manual:{i}", text=chunk, source="knowledge_base"))
    for doc in kb.documents:  # [{name, content}, ...]
        name = doc.get("name", "document")
        content = doc.get("content", "") or doc.get("text", "")
        for i, chunk in enumerate(_chunk_text(content)):
            items.append(KnowledgeItem(chunk_id=f"{name}:{i}", text=chunk, source=f"doc:{name}"))
    for i, item in enumerate(getattr(kb, "faq", []) or []):
        if not isinstance(item, dict):
            continue
        q = (item.get("q") or item.get("question") or "").strip()
        a = (item.get("a") or item.get("answer") or "").strip()
        if q or a:
            faq_text = f"Q: {q}\nA: {a}" if q and a else (q or a)
            items.append(KnowledgeItem(chunk_id=f"faq:{i}", text=faq_text, source="faq"))
    return items


# ---------------------------------------------------------------------------
# Tokeniser
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
from .turn_rules import ack_reply, is_acknowledgement, is_incomplete_turn  # noqa: F401


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
class _BM25:
    def __init__(self, docs: List[List[str]]):
        self.docs = docs
        self.doc_freq: dict[str, int] = {}
        self.tf: List[dict[str, int]] = []
        self.N = len(docs)
        k1, b = 1.5, 0.75
        self.k1, self.b = k1, b
        self.avgdl = 0.0
        for d in docs:
            tfd: dict[str, int] = {}
            for t in d:
                tfd[t] = tfd.get(t, 0) + 1
            self.tf.append(tfd)
            for t in set(d):
                self.doc_freq[t] = self.doc_freq.get(t, 0) + 1
            self.avgdl += len(d)
        self.avgdl = (self.avgdl / self.N) if self.N else 0.0

    def _idf(self, t: str) -> float:
        import math
        n = self.doc_freq.get(t, 0)
        return math.log(1 + (self.N - n + 0.5) / (n + 0.5))

    def score(self, query: List[str]) -> List[float]:
        scores = [0.0] * self.N
        for q in query:
            idf = self._idf(q)
            for i in range(self.N):
                tfd = self.tf[i]
                if q in tfd:
                    tf = tfd[q]
                    dl = len(self.docs[i])
                    denom = tf + self.k1 * (1 - self.b + self.b * dl / (self.avgdl or 1))
                    scores[i] += idf * (tf * (self.k1 + 1) / denom)
        return scores


def retrieve(kb: KnowledgeBase, query: str, top_k: int = 5) -> List[KnowledgeItem]:
    # Corpus side (chunking/tokenizing/index building) is memoized per KB
    # fingerprint; only query-scale work runs here now.
    items, doc_tokens, _bm_fast = _index_for(kb)
    if not items or not query:
        return items[:top_k]

    q_tokens = _tokens(query)
    if not q_tokens:
        return items[:top_k]

    try:
        if _bm_fast is None:
            raise RuntimeError("rank_bm25 unavailable")
        scores = _bm_fast.get_scores(q_tokens)
    except Exception:
        # Identical to the previous per-call fallback: rebuild _BM25 for THIS
        # query on the rare error path (empty vocab, broken fast index, …).
        bm = _BM25(doc_tokens)
        scores = bm.score(q_tokens)

    ranked = sorted(zip(items, scores), key=lambda x: x[1], reverse=True)
    # Relevance floor (2026-09-24 latency review): retrieve() used to return
    # top_k hits even at BM25 score 0 — every off-topic turn ("Number लिखो
    # मेरा 9538", "Ok bye.") was shipped a constant 1942-char / 3-hit block of
    # irrelevant business text: ~500 wasted input tokens per turn AND junk
    # grounding the model then tried to answer from. This is NOT a KB shrink:
    # full corpus and retrieval are intact; we only drop what is demonstrably
    # unrelated to THIS question. best<=0 -> no lexical overlap -> no
    # injection (the static instructions slice still grounds the basics).
    if not ranked:
        _logger.info("🔎 [RAG_HITS] query='%.48s' kept=0/0 top=[] relevant_context_found=no", query)
        return []
    _best = float(ranked[0][1] or 0.0)
    if _best <= 0.0:
        _logger.info("🔎 [RAG_HITS] query='%.48s' kept=0/%d top=[] relevant_context_found=no", query, len(ranked))
        return []
    try:
        _rel = float(os.getenv("VOICE_RAG_MIN_RELATIVE", "0.25"))
    except Exception:
        _rel = 0.25
    _rel = min(max(_rel, 0.0), 1.0)
    out = []
    _dbg = []
    for _it, _sc in ranked[:top_k]:
        if out and float(_sc) < _rel * _best:
            break
        out.append(_it)
        _dbg.append("%s:%.2f" % (getattr(_it, "chunk_id", "?"), float(_sc or 0.0)))
    # [RAG_HITS] (03:07 spec): retrieved chunk ids + BM25 scores per query.
    # INFO because the task demands observable retrieval forensics and the
    # production log level filters DEBUG out entirely.
    _logger.info("🔎 [RAG_HITS] query='%.48s' kept=%d top=[%s] relevant_context_found=%s", query, len(out), ",".join(_dbg), "yes" if out else "no")
    return out


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
