"""Scoring + per-turn retrieval: BM25 fast path with pure-python fallback.

Extracted from rag.py - behavior unchanged.
"""
from __future__ import annotations


import logging
import os
import re
from collections import OrderedDict
from typing import Any, List

from ..models import KnowledgeBase, KnowledgeItem


_logger = logging.getLogger("voice-agent-saas")

from .cache import _index_for, _tokens


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


# ---------------------------------------------------------------------------
# 0-hit near-match fallback (RAG_MISS handling, 05:37 log).
#
# When a caller's question contains an STT-mangled brand/product word —
# e.g. "Kriscent" transcribed as "sent" / "किसent" — BM25 finds zero token
# overlap, the relevance floor (correctly) returns no hits, and the LLM gets
# no context and stalls. This fallback does NOT re-rank, re-chunk, or touch
# BM25/ASR: it only re-uses the memoized corpus from _index_for and asks a
# weaker question — does any CONTENT word of the query occur INSIDE a chunk's
# text (substring), where exact-token matching found none? That catches word
# fragments like "sent" inside "kriscent". One best chunk, hard-capped at
# _FALLBACK_MAX_CHARS; nothing found -> "" (the turn proceeds ungrounded,
# which is the honest outcome). The generic stoplist below is function-word
# filtering only — no company/product keyword lives here.
# ---------------------------------------------------------------------------
