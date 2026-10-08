"""Per-turn RAG injection: retrieval enrichment of the turn context,
prefetch-cache reuse, contextual follow-up queries, and anchored system
message insertion strictly before the user question.

Extracted verbatim from agent_builder/ab_agent.py (<=300-line rule). RAG
only *enriches* context: a retrieval failure never gates the LLM reply.
"""
from __future__ import annotations

import asyncio
import logging
import time as _time

from .ab_prompt import (
    _RAG_PREFIX, _chat_msg_text, _find_chat_ctx, _rag_per_turn_enabled,
    _strip_trailing_ack_turns,
)

logger = logging.getLogger("voice-agent-saas-worker")


async def apply_per_turn_rag(self, turn_ctx, new_message, cfg, rag_prefetch,
                             user_text, preemptive_on, _rag_t0):

    # RAG handling - ALWAYS enabled for KB grounding (correctness > latency)
    # When preemptive ON, RAG will invalidate preemptive for this turn, but we explicitly log it
    # This is the fix for "Mere paas exact jaankari nahi hai" - KB grounding preserved
    if not _rag_per_turn_enabled():
        logger.info(f"⏱️ TIMING on_user_turn_completed (RAG disabled by env): {(_time.time()-_rag_t0)*1000:.0f}ms")
        return
    try:
        user_text = _chat_msg_text(new_message).strip()
        if not user_text:
            logger.info(f"⏱️ TIMING on_user_turn_completed (empty text): {(_time.time()-_rag_t0)*1000:.0f}ms")
            return
        from ... import rag  # local import: keep this module light
        from ...turn_rules import is_contextual_followup
        # If this turn completed a split thought, retrieve for the MERGED
        # question (fragments + this final) instead of the bare tail —
        # [COMPLETE_TURN] logged above shows the merge.
        _cq = (self._turn_timing_ref or {}).get("combined_query")
        if _cq:
            user_text = str(_cq)

        # --- Conversational context for RAG (fix for pronoun follow-ups) ---
        # Preserve actual user message for LLM (new_message unchanged).
        # Only the INTERNAL retrieval query gets enriched with recent context.
        from .ab_rag_context import build_contextual_retrieval
        original_user_query = user_text
        retrieval_query, context_used = build_contextual_retrieval(turn_ctx, original_user_query)
        logger.info(
            "🔎 [RAG_STARTED] query='%s' retrieval_query='%s' context_used=%s",
            original_user_query[:60],
            retrieval_query[:60],
            "yes" if context_used else "no",
        )
        # --- Fast path: the worker precomputes RAG from STT interim
        # text (in parallel with endpointing), so by the time the turn
        # completes the retrieval result for this exact text is usually
        # already cached. This hook is AWAITED by the session before the
        # LLM starts, so a cache hit removes ~30-100ms from EVERY turn.
        hits = ""
        _rag_src = "normal"
        # P3 ROOT-CAUSE FIX: initialize EVERY retrieval-result field
        # before either branch. Previously kb_used/faq_used & friends
        # were assigned ONLY on the cache-MISS path; the shared log
        # line after injection then raised UnboundLocalError on each
        # prefetch-HIT turn (surfacing as the misleading
        # "per-turn RAG injection skipped" warning — the context was in
        # fact injected). Both branches now produce the same structure.
        kb_used = False
        kb_chars = 0
        kb_hits = 0
        faq_used = False
        faq_chars = 0
        faq_hits = 0
        total_chars = 0
        _prefetch_entry = None
        if rag_prefetch is not None:
            try:
                # Prefetch cache is keyed by original normalized query (worker stores contextual result under original key)
                _prefetch_entry = rag_prefetch.get(rag.normalize_query(original_user_query))
                # Fallback: try retrieval_query key as well (in case worker stored under contextual key)
                if _prefetch_entry is None and retrieval_query != original_user_query:
                    _prefetch_entry = rag_prefetch.get(rag.normalize_query(retrieval_query))
            except Exception:
                _prefetch_entry = None
        # The worker caches the full detailed result; tolerate the old
        # bare-string shape too so a worker/builder version skew cannot
        # turn a hit into a crash.
        if isinstance(_prefetch_entry, dict):
            hits = (_prefetch_entry.get("text") or "").strip()
        elif isinstance(_prefetch_entry, str):
            hits = _prefetch_entry.strip()
        else:
            hits = ""
        if hits:
            _rag_src = "prefetch"
            if isinstance(_prefetch_entry, dict):
                kb_used = bool(_prefetch_entry.get("kb_used", False))
                kb_chars = int(_prefetch_entry.get("kb_chars", 0) or 0)
                kb_hits = int(_prefetch_entry.get("kb_hits", 0) or 0)
                faq_used = bool(_prefetch_entry.get("faq_used", False))
                faq_chars = int(_prefetch_entry.get("faq_chars", 0) or 0)
                faq_hits = int(_prefetch_entry.get("faq_hits", 0) or 0)
                total_chars = int(_prefetch_entry.get("total_chars", len(hits)) or len(hits))
            else:  # bare text (older worker): source flags unknown
                kb_used = True
                kb_chars = total_chars = len(hits)
            _rag_elapsed = (_time.time() - _rag_t0) * 1000
            logger.info(
                "📚 [KNOWLEDGE_RETRIEVAL] query='%s' | latency=%.0fms | kb_used=%s (%d chars, %d hits) | faq_used=%s (%d chars, %d hits) | total=%d chars | prefetch=true",
                retrieval_query[:60], _rag_elapsed, kb_used, kb_chars, kb_hits,
                faq_used, faq_chars, faq_hits, total_chars,
            )
            logger.info(
                "⚡ RAG PREFETCH HIT '%s' (%d chars) — computed during the STT interim, "
                "critical-path cost %.0fms",
                retrieval_query[:60], len(hits), _rag_elapsed,
            )
        else:
            # Cache miss (final text diverged from every interim, or the
            # interim compute lost the race): compute now using contextual retrieval_query.
            # Actual LLM user message (new_message) remains unchanged.
            try:
                rag_res = await asyncio.to_thread(rag.build_context_detailed, cfg.knowledge, retrieval_query, 3)
            except Exception:
                # Fallback sync if to_thread fails
                rag_res = rag.build_context_detailed(cfg.knowledge, retrieval_query, top_k=3)
            _rag_elapsed = (_time.time() - _rag_t0) * 1000
            hits = (rag_res.get("text") or "").strip()
            kb_used = rag_res.get("kb_used", False)
            kb_chars = rag_res.get("kb_chars", 0)
            kb_hits = rag_res.get("kb_hits", 0)
            faq_used = rag_res.get("faq_used", False)
            faq_chars = rag_res.get("faq_chars", 0)
            faq_hits = rag_res.get("faq_hits", 0)
            total_chars = rag_res.get("total_chars", 0)

            # Authoritative user-facing retrieval log detailing KB and FAQ usage
            logger.info(
                "📚 [KNOWLEDGE_RETRIEVAL] query='%s' | latency=%.0fms | kb_used=%s (%d chars, %d hits) | faq_used=%s (%d chars, %d hits) | total=%d chars",
                retrieval_query[:60],
                _rag_elapsed,
                kb_used,
                kb_chars,
                kb_hits,
                faq_used,
                faq_chars,
                faq_hits,
                total_chars,
            )

            if _rag_elapsed > 200:
                logger.warning(f"🐢 Slow RAG: {_rag_elapsed:.0f}ms exceeds 100ms target")

        logger.info(
            "🔎 [RAG_QUERY] query='%s' source=%s result_count=%d relevant_context_found=%s",
            retrieval_query[:70], _rag_src, int(kb_hits) + int(faq_hits), "yes" if hits else "no",
        )
        # NOTE: deliberately NO "same as last turn" dedupe here. This hook
        # edits the per-turn copy of the chat context (temp_mutable_chat_ctx);
        # the library discards it after generation, so the previous turn's
        # injected facts are NOT in this turn's prompt. Skipping injection on
        # "no new hits" (the old behavior) silently left repeat-question turns
        # ungrounded (23:19 log: identical kb result -> "RAG no new hits" ->
        # model answered from generic priors). Same text = same injection cost
        # (~600 tokens); correctness wins.
        _rag_kind = "retrieved"
        target = _find_chat_ctx(turn_ctx)
        _nstripped = _strip_trailing_ack_turns(target)
        if _nstripped:
            logger.info("🧹 [ACK_STRIPPED] removed %d trailing acknowledgement assistant message(s) from this turn's generation context (per-turn copy only — session history untouched)", _nstripped)
        if not hits:
            # ---- 0-hit turn: ONE cheap containment fallback over the
            # cached corpus (rag.fallback_context — BM25/ranking
            # untouched, runs in a thread so the loop stays free).
            # STT-mangled keywords ("Kriscent" heard as "sent") share
            # no exact token with any chunk, so main retrieval is
            # legitimately empty; containment still finds the chunk
            # containing the fragment, capped at ~560 chars. If the
            # fallback also finds nothing, the request proceeds
            # ungrounded — the prompt tells the model to say so
            # honestly instead of guessing.
            _fb_text = ""
            _fb_hits = 0
            try:
                _fb_text, _fb_hits = await asyncio.to_thread(
                    rag.fallback_context, cfg.knowledge, retrieval_query
                )
            except Exception as _fb_exc:
                logger.debug("RAG fallback failed: %r", _fb_exc)
            if _fb_text:
                hits = _fb_text
                _rag_kind = "near-match"
                logger.info(
                    "🕳️ [RAG_MISS] query='%s' fallback_attempted=yes fallback_hits=%d fallback_context_chars=%d",
                    retrieval_query[:70], _fb_hits, len(_fb_text),
                )
            else:
                logger.info(
                    "🕳️ [RAG_MISS] query='%s' fallback_attempted=yes fallback_hits=0 fallback_context_chars=0",
                    retrieval_query[:70],
                )
                logger.info("🧠 [LLM_CONTEXT] user_query='%s' rag_context_present=no", retrieval_query[:70])
                logger.info(f"⏱️ TIMING on_user_turn_completed (no RAG hits): {(_time.time()-_rag_t0)*1000:.0f}ms")
                return  # nothing to inject, main retrieval AND fallback came up empty
        if target is None:
            logger.warning("⚠️ RAG: no chat_ctx found, skipping injection")
            return
        
        # FIX ROOT CAUSE: When KB/FAQ RAG enabled, preemptive must be disabled BEFORE turn begins
        rag_enabled = True
        try:
            import os as _os_rag_check
            v = (_os_rag_check.getenv("VOICE_RAG_PER_TURN") or "").strip().lower()
            if v in ("0", "false", "off"):
                rag_enabled = False
        except Exception:
            rag_enabled = True
        
        if preemptive_on and rag_enabled:
            logger.info(f"🔧 RAG+preemptive: KB grounding needed ({len(hits)} chars) but preemptive already disabled at session level (rag_enabled={rag_enabled}, env preemptive={preemptive_on}) - no invalidation, exactly one REQUEST START per turn (query: {retrieval_query[:60]})")
        elif preemptive_on:
            logger.info(f"🔍 RAG+preemptive conflict: KB grounding needed ({len(hits)} chars) will invalidate preemptive for this turn — preserving correctness over latency (query: {retrieval_query[:60]})")
        
        if _rag_kind == "near-match":
            _header = (
                f"{_RAG_PREFIX} NEAR-MATCH business context (the exact question "
                "keywords were not found in the knowledge base; use ONLY statements "
                "this excerpt makes verbatim, do not stretch it to fit the question):"
            )
        else:
            _header = (
                f"{_RAG_PREFIX} Relevant business facts for THIS specific question:"
            )
        # 11:41 log defect #1 (ORDER, not presence — final_user=0c
        # explained): agent_activity creates user_message BEFORE this
        # hook, then inserts it into the generation ctx by
        # created_at (_pipeline_reply_task_impl: chat_ctx.insert()).
        # A plain add_message() stamps created_at=NOW — newer than the
        # question — so [RAG] landed AFTER it: [..., USER question,
        # [RAG] system]. The question was never the last message and
        # the trailing system line read like new instructions. Anchor
        # the block 1ms before the question instead: the library then
        # slots the question right behind it — [..., [RAG] facts,
        # USER question] — facts precede the question it grounds, and
        # the question is last (stable prefix → dynamic RAG → user
        # content, per the cache-prefix contract).
        _inj_at = float(getattr(new_message, "created_at", 0.0) or 0.0) - 0.001
        if _inj_at <= 0:
            _inj_at = _time.time() - 0.001
        target.add_message(
            role="system",
            content=f"{_header}\n{hits}",
            created_at=_inj_at,
        )
        logger.info(f"✅ [RAG_DONE] RAG injected {len(hits)} chars for query: {retrieval_query[:80]} (kb_used={kb_used}, faq_used={faq_used}) original='{original_user_query[:60]}'")
        logger.info("🧠 [LLM_CONTEXT] user_query='%s' rag_context_present=yes (chars=%d, kind=%s)", retrieval_query[:70], len(hits), _rag_kind)
    except Exception as e:
        # RAG only *enriches* the turn context: a retrieval failure must
        # never gate or delay the LLM reply (brief P4). Log loudly with
        # the real exception, then fall through so LiveKit generates.
        logger.warning(f"⚠️ per-turn RAG handling raised {type(e).__name__}: {e!r} — LLM reply still proceeds ungrounded for this turn")
        logger.info(f"⏱️ TIMING on_user_turn_completed (RAG error, fallback): {(_time.time()-_rag_t0)*1000:.0f}ms")
