"""Text chunking and KB -> item indexing. Extracted from rag.py.
"""
from __future__ import annotations


import re
from collections import OrderedDict
from typing import Any, List
from ..models import KnowledgeBase, KnowledgeItem


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
