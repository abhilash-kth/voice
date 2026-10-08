from __future__ import annotations

import logging
import os
from typing import Any

from ...models import AgentConfig
from ...config import (
    GROQ_API_KEY,
)

logger = logging.getLogger("voice-agent-saas-agent-builder")


_KB_BUDGET_CHARS_DEFAULT_GROQ = 2500
_FAQ_BUDGET_CHARS_DEFAULT_GROQ = 1200
_OWNER_PROMPT_BUDGET_CHARS_DEFAULT_GROQ = 3000

# FIXED for KB grounding: Previous 1000/600/1500 budgets were too small, causing
# "Mere paas company ki exact team size nahi hai" - KB truncated 45788->1001 chars.
# Groq 8k TPM is tight, but with 6-msg history trim we can afford larger budgets.
# New: Groq 2500/1200/3000, OpenAI 4000/2000/4000 to preserve KB grounding.
# Task: "Do not sacrifice correctness for latency" - so preserve KB.

# Voice latency optimization (20260917-230522): LLM TTFT 882-1203ms with 3500-3700 input tokens
# Root cause: static KB 4000 + FAQ 2000 + owner 4000 = 10000 chars ~2500 tokens + RAG 1091 + history 20*200 = 4000 => 3500-3700 tokens
# With RAG per-turn enabled (27-105ms), static KB is redundant. Reduce static when RAG enabled to lower TTFT.
# New for OpenAI voice latency: when RAG enabled, KB 1200 (was 4000), FAQ 800 (was 2000), owner 2500 (was 4000)
# Saves ~6000 chars ~1500 tokens, bringing 3500->~2000, TTFT should improve 200-400ms without hurting quality because RAG provides relevant facts.
# Env overrides still respected: VOICE_KB_BUDGET_CHARS etc.
_KB_BUDGET_CHARS_DEFAULT = 4000
_FAQ_BUDGET_CHARS_DEFAULT = 2000
_OWNER_PROMPT_BUDGET_CHARS_DEFAULT = 4000

# Voice latency optimized defaults when RAG enabled (reduces 3500-3700 -> ~2000 tokens)
# v2: Further reduction to hit ~1500 tokens for TTFT improvement, prior_memory also budgeted
# KB 800 (was 1200), FAQ 400 (was 800), owner 2000 (was 2500), prior_memory 800 (was unlimited 40 turns ~4000 tokens)
# Total static ~3200 chars ~800 tokens + RAG 500 + history 8*150=1200 = ~2500 tokens (was 3500-3700)
# Prior_memory 40 turns -> 800 chars preserves recent cross-call context without bloating
# v3 (2026-09-24 cache fix): 1126-token stable was borderline <1024 real tokens → cached=0 miss.
# Restore larger genuinely stable prefix: KB 2500 FAQ 1200 owner 3000 matches historical
# cache-hit size (~2350 tokens est) and is still bounded to avoid Groq 429s.
# This is natural business content, not artificial padding.
_KB_BUDGET_CHARS_VOICE_RAG = 2500
_FAQ_BUDGET_CHARS_VOICE_RAG = 1200
_OWNER_PROMPT_BUDGET_CHARS_VOICE_RAG = 3000
_PRIOR_MEMORY_BUDGET_CHARS_VOICE_RAG = 800

# Legacy module-level constants kept for backward compat / logging, but
# build_instructions now uses provider-aware effective budgets.
_KB_BUDGET_CHARS = int(os.getenv("VOICE_KB_BUDGET_CHARS", str(_KB_BUDGET_CHARS_DEFAULT)))
_FAQ_BUDGET_CHARS = int(os.getenv("VOICE_FAQ_BUDGET_CHARS", str(_FAQ_BUDGET_CHARS_DEFAULT)))
_OWNER_PROMPT_BUDGET_CHARS = int(os.getenv("VOICE_OWNER_PROMPT_BUDGET_CHARS", str(_OWNER_PROMPT_BUDGET_CHARS_DEFAULT)))


def _effective_budgets(cfg: AgentConfig) -> tuple[int, int, int]:
    """Return (kb_budget, faq_budget, owner_budget) based on LLM provider and RAG enabled for voice latency."""
    try:
        llm_id = (cfg.providers.llm.id or "").lower() if cfg.providers and cfg.providers.llm else ""
    except Exception:
        llm_id = ""
    is_groq = llm_id.startswith("groq")
    # Check if RAG enabled for voice latency optimization
    rag_enabled = True
    try:
        v = (os.getenv("VOICE_RAG_PER_TURN") or "").strip().lower()
        if v in ("0", "false", "off"):
            rag_enabled = False
    except Exception:
        rag_enabled = True

    if is_groq:
        kb = int(os.getenv("VOICE_KB_BUDGET_CHARS", str(_KB_BUDGET_CHARS_DEFAULT_GROQ)))
        faq = int(os.getenv("VOICE_FAQ_BUDGET_CHARS", str(_FAQ_BUDGET_CHARS_DEFAULT_GROQ)))
        owner = int(os.getenv("VOICE_OWNER_PROMPT_BUDGET_CHARS", str(_OWNER_PROMPT_BUDGET_CHARS_DEFAULT_GROQ)))
    else:
        # Voice latency optimization: when RAG enabled, use smaller static budgets to reduce 3500-3700 input tokens
        # RAG provides relevant facts per-turn (27-105ms), so static KB can be smaller without hurting quality
        # v2: 800/400/2000 + prior_memory 800 (was 1200/800/2500) saves additional ~1000 chars
        if rag_enabled:
            kb = int(os.getenv("VOICE_KB_BUDGET_CHARS", str(_KB_BUDGET_CHARS_VOICE_RAG)))
            faq = int(os.getenv("VOICE_FAQ_BUDGET_CHARS", str(_FAQ_BUDGET_CHARS_VOICE_RAG)))
            owner = int(os.getenv("VOICE_OWNER_PROMPT_BUDGET_CHARS", str(_OWNER_PROMPT_BUDGET_CHARS_VOICE_RAG)))
            logger.info(f"🔧 Voice latency budgets v2 (RAG enabled): KB {kb} (was 4000), FAQ {faq} (was 2000), owner {owner} (was 4000), prior_memory 800 - reduces 3500-3700 -> ~2000-2500, TTFT 1203/894/1189/882ms should improve")
        else:
            kb = int(os.getenv("VOICE_KB_BUDGET_CHARS", str(_KB_BUDGET_CHARS_DEFAULT)))
            faq = int(os.getenv("VOICE_FAQ_BUDGET_CHARS", str(_FAQ_BUDGET_CHARS_DEFAULT)))
            owner = int(os.getenv("VOICE_OWNER_PROMPT_BUDGET_CHARS", str(_OWNER_PROMPT_BUDGET_CHARS_DEFAULT)))
    return kb, faq, owner

# Marker for the per-turn RAG system message (used to prune the previous turn's).
