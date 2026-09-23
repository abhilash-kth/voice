"""
Knowledge base retrieval (lightweight RAG).

Chunks manual text + uploaded document text, indexes it, and retrieves the most
relevant chunks for a query using BM25 (rank_bm25) when available, otherwise a
simple token-overlap scorer. This keeps the platform dependency-light and works
offline for the demo.

Docs can be swapped for embeddings later without touching the API.
"""
from __future__ import annotations

import re
from typing import Any, List

from .models import KnowledgeBase, KnowledgeItem


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
    items = build_index(kb)
    if not items or not query:
        return items[:top_k]

    q_tokens = _tokens(query)
    if not q_tokens:
        return items[:top_k]

    doc_tokens = [_tokens(it.text) for it in items]
    try:
        from rank_bm25 import BM25Okapi  # optional fast path
        bm = BM25Okapi(doc_tokens)
        scores = bm.get_scores(q_tokens)
    except Exception:
        bm = _BM25(doc_tokens)
        scores = bm.score(q_tokens)

    ranked = sorted(zip(items, scores), key=lambda x: x[1], reverse=True)
    return [it for it, _s in ranked[:top_k]]


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
