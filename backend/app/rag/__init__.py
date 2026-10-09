"""
Knowledge base retrieval (lightweight RAG).

Chunks manual text + uploaded document text, indexes it, and retrieves the most
relevant chunks for a query using BM25 (rank_bm25) when available, otherwise a
simple token-overlap scorer. This keeps the platform dependency-light and works
offline for the demo.

Docs can be swapped for embeddings later without touching the API.
"""
from __future__ import annotations

# Facade: keeps the full import surface of the old app/rag.py module.
from ..models import KnowledgeBase, KnowledgeItem

from .chunking import _chunk_text, build_index
from .cache import (
    _BM25Okapi,
    _INDEX_CACHE,
    _INDEX_CACHE_MAX,
    _WORD_RE,
    _index_for,
    _kb_fingerprint,
    _tokens,
    normalize_query,
)
from .retrieval import _BM25, retrieve
from .context import (
    _FALLBACK_MAX_CHARS,
    _GENERIC_QUERY_TOKENS,
    build_context,
    build_context_detailed,
    fallback_context,
)

from ..turn_rules import ack_reply, is_acknowledgement, is_incomplete_turn  # noqa: F401
