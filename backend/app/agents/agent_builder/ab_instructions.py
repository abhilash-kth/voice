from __future__ import annotations

import logging
import os

from ...models import AgentConfig, KnowledgeBase
from ...config import (
    GROQ_API_KEY
)

logger = logging.getLogger("voice-agent-saas-agent-builder")


# cross-module imports (auto-generated)
from .ab_budgets import _effective_budgets
from .ab_prompt import _rag_per_turn_enabled, _truncate

def _flatten_knowledge(kb: KnowledgeBase) -> list[str]:
    """Flatten every knowledge source into a list of bullet lines.

    Returns the WHOLE knowledge base; ``build_instructions`` then applies the
    context-size budgets to it (the capped static part), while the question-
    specific chunks are retrieved per-turn by ``rag.build_context`` inside
    ``on_user_turn_completed``.
    """
    blocks = []
    manual = (kb.text or "").strip()
    if manual:
        blocks.append(manual)
    for doc in kb.documents or []:
        name = doc.get("name", "document")
        content = doc.get("content") or doc.get("text") or ""
        if content.strip():
            blocks.append(f"[{name}]\n{content.strip()}")
    return blocks


def build_instructions(cfg: AgentConfig, query_context: str = "") -> str:
    """Build the permanent (stable-head) system prompt.

    Global prompt-budget policy (2026-09-24): the stable prompt carries ONLY
    behavioral rules. Company/KB/FAQ content is NOT part of it — the per-turn
    RAG hook retrieves exactly the relevant chunks for the caller's question
    and injects them as a [RAG] system message; when retrieval finds no
    relevant hit (relevance floor), nothing is injected. Escape hatches keep
    their old semantics: with VOICE_RAG_PER_TURN=0 the static KB/FAQ slices
    return (they are the only grounding in that mode), and the
    VOICE_KB_BUDGET_CHARS / VOICE_FAQ_BUDGET_CHARS /
    VOICE_OWNER_PROMPT_BUDGET_CHARS env overrides still apply. The output is
    deterministic per agent config, so the provider's prompt-cache prefix
    (head_sha) stays stable across every turn and every call.
    """
    persona = cfg.voice_personality or "friendly"
    lang = cfg.language or "hi"
    kb_budget, faq_budget, owner_budget = _effective_budgets(cfg)
    rag_on = _rag_per_turn_enabled()
    logger.info(
        "📚 [KNOWLEDGE_BASE_INIT] Agent '%s' knowledge loaded: manual_text=%d chars, documents=%d, faq=%d items | Static budgets: KB=%d chars, FAQ=%d chars, Owner=%d chars | stable-prompt policy: %s",
        cfg.name,
        len(getattr(cfg.knowledge, "text", "") or ""),
        len(getattr(cfg.knowledge, "documents", []) or []),
        len(getattr(cfg.knowledge, "faq", []) or []),
        kb_budget,
        faq_budget,
        owner_budget,
        "KB/FAQ included in stable prefix for caching + RAG per-turn injects relevant chunks" if rag_on else "KB/FAQ included — RAG disabled for this call",
    )

    lines = [
        f"You are {cfg.name}, a {persona} voice receptionist on a live phone call.",
        "Answer in the caller's language: English in -> English out; Hindi or Hinglish in -> Hindi in Devanagari script (देवनागरी) only — Roman-script Hindi sounds broken through TTS. Digits, phone numbers and emails stay as written. If the language is unclear, default to: " + lang + ".",
        "Speak like a warm, efficient receptionist: 1-2 short spoken sentences, under 25 words, start answering immediately, no markdown, lists, emojis or preambles; never read back the caller's question, never repeat yourself, never greet or introduce yourself again (the greeting already played), never pitch services unprompted and never reveal being an AI.",
    ]
    # Human rhythm + real latency win: a 1-3 word acknowledgment as its OWN
    # first sentence reaches TTS at the LLM's first tokens (~1s answer).
    # Env kill switch: VOICE_ACK_OPENERS=0.
    if os.getenv("VOICE_ACK_OPENERS", "1") == "1":
        lines.append(
            "Open every answer with a very short acknowledgment as its own complete sentence, in the caller's language ('जी.' / 'हाँ जी.' / 'Sure.'), 1-3 words, varied naturally, never the same one twice in a row; then give the full answer."
        )
    lines.append(
        "ACK/INCOMPLETE TURNS: pure acknowledgements and half-spoken fragments ('कि', 'और', 'एक minute') are answered deterministically before you are called; if one still reaches you, reply with at most one short warm line ('जी, बताइए।') — never facts, never guesses about what was meant. "
        "That line is ONLY for turn-less fragments: NEVER use it to dodge a question, even a garbled or unclear one — for any question, answer from the provided business facts, or say plainly you don't have that detail and offer a follow-up. And never repeat an answer you already gave in this call."
    )
    lines.append(
        "NEVER offer further help at the end of an answer: no 'Aur kuch poochna hai?', 'क्या मैं आपकी और मदद कर सकती हूँ?' or any variant — one answer, then stop and wait. Ask a follow-up only while actively collecting required enquiry details (name, phone, budget)."
    )

    extra = (cfg.knowledge.system_prompt or "").strip()
    if extra:
        if len(extra) > owner_budget:
            extra = _truncate(extra, owner_budget)
            logger.warning(
                "⚠️ Owner system prompt truncated to fit the LLM context budget "
                f"({len(cfg.knowledge.system_prompt)} -> {owner_budget} chars; "
                "raise VOICE_OWNER_PROMPT_BUDGET_CHARS to keep more)."
            )
        else:
            logger.info(f"✅ Owner system prompt kept full ({len(extra)} chars, budget {owner_budget})")
        lines.append("")
        lines.append("Instructions from the business owner:")
        lines.append(extra)

    # Cache fix v3: static KB/FAQ are genuinely stable for same agent and
    # increase the cacheable prefix to reliably >1024 real tokens. When RAG is
    # on, per-turn RAG still injects the *relevant* chunks (27-105ms), but the
    # static slices provide a large identical prefix for prompt caching.
    # This restores historical cache-hit size (~2350 tokens) without artificial
    # padding — natural business content only. RAG behavior unchanged.
    facts = _flatten_knowledge(cfg.knowledge)
    if facts:
        kept: list[str] = []
        used = 0
        truncated_any = False
        for f in facts:
            room = kb_budget - used
            if room <= 40:
                truncated_any = True
                break
            if len(f) > room:
                f = _truncate(f, room)
                truncated_any = True
            kept.append(f)
            used += len(f) + 2
        if truncated_any:
            logger.warning(
                "⚠️ Knowledge base truncated to fit the LLM context budget "
                f"({sum(len(f) for f in facts)} -> {used} chars; an oversized prompt "
                "is what causes rate-limit 429s → silent dropped "
                f"turns). Raise VOICE_KB_BUDGET_CHARS only if you've upgraded the "
                f"Groq tier or switched to a higher-limit provider (budget {kb_budget})."
            )
        else:
            logger.info(f"✅ Knowledge base kept ({used}/{kb_budget} chars)")
        if kept:
            lines.append("")
            lines.append("Business facts you know (use these when answering):")
            lines.extend(f"- {f}" for f in kept)

    if query_context:
        lines.append("")
        lines.append("Relevant business facts to use when answering:")
        lines.append(query_context)

    faq = getattr(cfg.knowledge, "faq", None) or []
    if faq:
        faq_lines: list[str] = []
        used = 0
        faq_truncated = False
        for item in faq:
            q = item.get("q", "")
            a = item.get("a", "")
            if not (q and a):
                continue
            block = f"- Q: {q}\n  A: {a}"
            room = faq_budget - used
            if room <= 40:
                faq_truncated = True
                break
            if len(block) > room:
                block = f"- Q: {q}\n  A: {_truncate(a, max(room - len(q) - 12, 40))}"
                faq_truncated = True
            faq_lines.append(block)
            used += len(block) + 2
        if faq_truncated:
            logger.warning(
                "⚠️ FAQ truncated to fit the LLM context budget "
                f"(VOICE_FAQ_BUDGET_CHARS={faq_budget})."
            )
        if faq_lines:
            lines.append("")
            lines.append(
                "Frequently asked questions. When the caller asks something that "
                "matches one of these, answer with its official answer VERBATIM "
                "(do not paraphrase or add extra info):"
            )
            lines.extend(faq_lines)

    lines.append("")
    lines.append(
        "FACTS & HONESTY: ground every substantive answer ONLY in the owner instructions and any per-turn [RAG] business facts; when a retrieved fact directly answers the question, follow it exactly — numbers, prices and timings verbatim, never paraphrased. If nothing covers it, say plainly that you do not have that detail and offer to have the team follow up — never invent prices, offices, transactions or history. Give contact numbers or emails ONLY exactly as written in the owner instructions; if none are listed there, offer a callback instead."
    )

    _stable_chars = sum(len(x) + 1 for x in lines)
    # ---- 📐 stable-prompt diagnostics: what the permanent head costs on
    # EVERY request, measured at build time (the per-request [PROMPT] line in
    # the worker shows the same numbers next to dynamic/RAG tokens).
    logger.info(
        "📐 [STABLE_PROMPT] chars=%d est_tokens=%d (4.0 chars/token) | sections: core+%sowner=%d kb_static=%s faq_static=%s | policy=%s",
        _stable_chars,
        int(_stable_chars / 4.0),
        "ack-rhythm " if os.getenv("VOICE_ACK_OPENERS", "1") == "1" else "",
        len(extra),
        "on" if facts else "off",
        "on" if faq else "off",
        "cache-optimized: KB/FAQ in stable for >1024 tokens + RAG per-turn" if rag_on else "RAG disabled: static slices re-included",
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# v1 Agent (subclass) — static knowledge + cross-call memory + greeting
# ---------------------------------------------------------------------------

