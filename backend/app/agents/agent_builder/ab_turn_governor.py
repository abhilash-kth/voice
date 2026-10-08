"""Turn governor + conversation-history trimming.

The governor (2026-09-24 spec) runs BEFORE any LLM scheduling and decides
ack / incomplete / complete; trimming keeps the rolling conversation bounded
against provider TPM while preserving system facts and memory.
Extracted verbatim from agent_builder/ab_agent.py (<=300-line rule).
"""
from __future__ import annotations

import logging
import time as _time

import os

from .ab_prompt import (_FRAGMENT_TTL_S, _SUPERSEDED_MERGE_MAX_AGE_S,
                        _chat_msg_text, _find_chat_ctx, _frag_append_fresh, _frag_consume)

logger = logging.getLogger("voice-agent-saas-worker")


async def govern_and_trim(self, turn_ctx, new_message, user_text, _rag_t0,
                          explicit_goodbye, cfg, _in_call_memory_lines):
    """Runs the turn governor and trims chat history. `explicit_goodbye` is
    the value of closing_state["explicit_goodbye"] at this point (read-only
    in this phase, exactly as before)."""

    # --- Turn governor (2026-09-24 spec) — runs BEFORE any LLM
    # scheduling and decides three outcomes:
    #   ack        -> llm_node answers with a canned line; NO LLM request,
    #                 NO tokens, NO billing (00:31 log: 'Ok.' still cost a
    #                 2865-token request whose 3-char answer was then
    #                 mis-flagged into an apology).
    #   incomplete -> llm_node produces NOTHING; the fragment is kept in
    #                 pending_fragments and merged into the next complete
    #                 turn (00:31 log: one thought split into 4 finals
    #                 produced 3 invalidated 0/0 requests + 1 answered).
    #   complete   -> normal trim+RAG+LLM path; if fragments are pending,
    #                 RAG runs on the MERGED query.
    # Closing intent always wins (explicit_goodbye computed above), so
    # "thanks"/"बस इतना ही..." keep the existing deterministic closing.
    try:
        _gtext = user_text
    except NameError:
        _gtext = ""
    _tt = self._turn_timing_ref
    if _tt is not None:
        # per-turn flags: drop anything left from a cancelled turn so a
        # stale 'ack'/'suppress' can never hijack the next real question
        _tt.pop("gov_turn_state", None)
        _tt.pop("ack_reply", None)
        _tt.pop("combined_query", None)
        if _gtext and not explicit_goodbye:
            try:
                from ... import rag as _rag_rules
                _is_ack = _rag_rules.is_acknowledgement(_gtext)
                _is_inc = (not _is_ack) and _rag_rules.is_incomplete_turn(_gtext)
            except Exception:
                _is_ack = _is_inc = False
            _now_f = _time.time()
            _fb_before = len(list(_tt.get("pending_fragments") or []))
            if _is_ack:
                _tt["gov_turn_state"] = "ack"
                _tt["ack_reply"] = {"text": _gtext, "reply": _rag_rules.ack_reply(_gtext)}
                # an ACK means the caller moved past whatever they were
                # composing — held fragments can never "continue" into
                # this turn; clear so the NEXT turn starts clean.
                _freshA, _dropA = _frag_consume(_tt, _now_f)
                if _freshA or _dropA:
                    logger.info("🧹 fragments cleared on ACK turn (kept=%d dropped_stale=%d) — deterministic answer owns the floor", len(_freshA), _dropA)
                logger.info("⏭️ [RAG_SKIPPED] acknowledgement turn: '%s' → deterministic reply, no LLM", _gtext[:40])
                logger.info("📥 [TURN_INPUT] raw_stt='%s' cleaned_turn='' fragment_buffer_before=%d fragment_buffer_after=0 merged=no path=ack", _gtext[:70], _fb_before)
                return {"stop": True}
            if _is_inc:
                _pend = _frag_append_fresh(_tt, [_gtext], _now_f)
                _tt["gov_turn_state"] = "suppress"
                logger.info("⏸️ [INCOMPLETE_TURN] text='%s' waiting_for_continuation=true fragments=%d (TTL=%.0fs)", _gtext[:60], len(_pend), _FRAGMENT_TTL_S)
                logger.info("📥 [TURN_INPUT] raw_stt='%s' cleaned_turn='' fragment_buffer_before=%d fragment_buffer_after=%d merged=no path=hold", _gtext[:70], _fb_before, len(_pend))
                return {"stop": True}
            # complete turn — strong-evidence continuation merge: a
            # previous question whose request was killed BEFORE any
            # output (worker-set overwritten_turn, generation-tagged)
            # joins the buffer as a fresh-in-time fragment.
            _ov = _tt.pop("overwritten_turn", None)
            _ov_used = False
            if isinstance(_ov, dict):
                _ovt = str(_ov.get("text") or "").strip()
                _ov_age = _now_f - float(_ov.get("ts") or 0.0)
                _ov_gen_ok = int(_ov.get("gen") or -1) == int(_tt.get("gen", 0) or 0)
                if _ovt and _ov_gen_ok and _ov_age <= _SUPERSEDED_MERGE_MAX_AGE_S and _ovt[:120] != _gtext[:120]:
                    _old_p = list(_tt.get("pending_fragments") or [])
                    _tt["pending_fragments"] = ([(_ovt, float(_ov.get("ts") or _now_f))] + _old_p)[-5:]
                    _ov_used = True
                    logger.info("🔗 [CONTINUATION_MERGE] caller's previous question was superseded %.1fs ago with zero output — treating '%s…' + '%s…' as ONE utterance", _ov_age, _ovt[:40], _gtext[:40])
            _kept, _dropped = _frag_consume(_tt, _now_f)
            if _dropped:
                logger.info("🧹 dropped %d stale fragment(s) (>%.0fs) — independent turn gets a clean query", _dropped, _FRAGMENT_TTL_S)
            if _kept:
                _combined = " ".join(_kept + [_gtext])
                _tt["gov_turn_state"] = "complete"
                _tt["combined_query"] = _combined
                logger.info("🧩 [COMPLETE_TURN] merged %d fragment(s)%s: '%s'", len(_kept) + 1, " (incl. superseded continuation)" if _ov_used else "", _combined[:90])
                logger.info("📥 [TURN_INPUT] raw_stt='%s' cleaned_turn='%s' fragment_buffer_before=%d fragment_buffer_after=0 merged=%s", _gtext[:70], _combined[:70], _fb_before, "yes+continuation" if _ov_used else "yes")
            else:
                logger.info("📥 [TURN_INPUT] raw_stt='%s' cleaned_turn='%s' fragment_buffer_before=%d fragment_buffer_after=0 merged=no", _gtext[:70], _gtext[:70], _fb_before)
    # Keep the rolling conversation bounded. Groq accounts the entire
    # prompt against TPM; an unbounded voice call eventually turns every
    # request into a 429 even with the 20b model. Preserve system facts
    # and only the latest few conversational messages.
    # CRITICAL FIX: Do NOT trim when preemptive generation is enabled.
    # Trimming mutates chat_ctx (len changes) → is_equivalent False → 
    # preemptive generation invalidated after on_user_turn_completed
    # → full LLM restart adds 1-2s latency (observed 1826-2364ms)
    # When preemptive ON, skip trimming to preserve preemptive.
    # When preemptive OFF, trim to avoid 429.
    preemptive_on = os.getenv("VOICE_PREEMPTIVE", "0") == "1"
    # FIX 4: Conversation memory - name unavailable but mobile remembered
    # Root cause: trimming to 6 dialogue messages max drops early name if many turns
    # Evidence: user asked name after previously giving it, agent said unavailable, but mobile 9538450441 remembered (later in conversation)
    # Fix: increase trim limit from 6 to 20 dialogue messages to preserve name, and preserve memory when memory_enabled
    # Also check if KB present - when KB present we already disable preemptive in worker.py, so trimming will happen
    # We should preserve more history for memory retention, not aggressively trim
    if not preemptive_on:
        try:
            target_ctx = _find_chat_ctx(turn_ctx) or turn_ctx
            items = getattr(target_ctx, "items", None)
            # Voice latency optimization v2: keep 8 dialogue max for OpenAI when RAG enabled (was 12) to reduce 3500-3700 tokens further
            # Billing shows avg 4 turns per call, 8 covers full call. prior_memory 800 chars handles cross-call memory.
            # Saves additional ~4*150=600 tokens vs 12. Groq still 16 for TPM safety (reduced from 20), OpenAI 8 for latency.
            # Determine history limit based on provider
            try:
                _llm_id_hist = (cfg.providers.llm.id or "").lower() if cfg.providers and cfg.providers.llm else ""
                _is_groq_hist = _llm_id_hist.startswith("groq")
                _history_limit = 16 if _is_groq_hist else 8
                _trim_threshold = 20 if _is_groq_hist else 12
            except Exception:
                _history_limit = 8
                _trim_threshold = 12
            if isinstance(items, list):
                # Cache fix (applies ALWAYS, not just when trimming): keep ONLY the stable
                # behavioral instructions at the very beginning (id=lk.agent_task.instructions)
                # as the cacheable prefix. All other system messages (prior_memory, lead_data,
                # prior RAG if ever left) are dynamic per customer/lead/turn and must be AFTER
                # history so the stable prefix remains byte-identical across turns and across
                # customers (cross-customer cache sharing). This guarantees the provider-bound
                # prompt starts with the identical stable head.
                _stable_sys = []
                _other_sys = []
                for m in items:
                    if getattr(m, "role", "") == "system":
                        if getattr(m, "id", "") == "lk.agent_task.instructions":
                            _stable_sys.append(m)
                        else:
                            _other_sys.append(m)
                # If no explicit instructions id found (older contexts), treat first system as stable
                if not _stable_sys:
                    _all_sys = [m for m in items if getattr(m, "role", "") == "system"]
                    if _all_sys:
                        _stable_sys = [_all_sys[0]]
                        _other_sys = _all_sys[1:]
                dialogue_items = [m for m in items if getattr(m, "role", "") != "system"]
                if len(items) > _trim_threshold:
                    kept_dialogue = dialogue_items[-_history_limit:]
                else:
                    kept_dialogue = dialogue_items
                trimmed_count = len(dialogue_items) - len(kept_dialogue)
                if trimmed_count > 0:
                    # Keep a bounded, verbatim window of this call's older
                    # dialogue in the existing system-memory path. This
                    # prevents context trimming from erasing caller facts
                    # without RAG or entity-specific extraction.
                    for _old_item in dialogue_items[:-_history_limit]:
                        _old_role = getattr(_old_item, "role", "")
                        _old_text = _chat_msg_text(_old_item).strip()
                        if _old_role in ("user", "assistant") and _old_text:
                            _speaker = "Customer" if _old_role == "user" else "Agent"
                            _in_call_memory_lines.append(f"{_speaker}: {_old_text}")
                    try:
                        _memory_budget = int(os.getenv("VOICE_PRIOR_MEMORY_BUDGET_CHARS", "800"))
                    except (TypeError, ValueError):
                        _memory_budget = 800
                    _memory_budget = max(1, _memory_budget)
                    _memory_text = "\n".join(_in_call_memory_lines)[-_memory_budget:]
                    _line_boundary = _memory_text.find("\n")
                    if _line_boundary != -1 and _line_boundary < _memory_budget * 0.3:
                        _memory_text = _memory_text[_line_boundary + 1:]
                    _in_call_memory_lines[:] = [_memory_text] if _memory_text else []
                    _memory_id = "voice.in_call_memory"
                    _memory_message = next(
                        (m for m in _other_sys if getattr(m, "id", "") == _memory_id),
                        None,
                    )
                    _memory_content = (
                        "Earlier turns from this call (verbatim context):\n" + _memory_text
                    )
                    if _memory_message is None:
                        _memory_message = target_ctx.add_message(
                            role="system", content=_memory_content, id=_memory_id,
                        )
                        _other_sys.append(_memory_message)
                    else:
                        _memory_message.content = [_memory_content]
                    logger.info(
                        "🧠 [IN_CALL_MEMORY] archived_dialogue_items=%d retained_chars=%d",
                        trimmed_count, len(_memory_text),
                    )
                # Order: stable behavioral → history (dynamic) → other dynamic system (prior_memory, lead_data)
                # RAG for THIS turn is injected later with created_at just before final user, so it lands after history as well.
                # For cache: stable at beginning, identical across turns/customers; dynamic after.
                if len(items) > _trim_threshold or _other_sys:
                    target_ctx.items = _stable_sys + kept_dialogue + _other_sys
                # else: no reordering needed (only stable present)
                logger.info("🧹 Trimmed conversation context to %s messages (dialogue max=%s, older turns retained in bounded in-call memory)", len(target_ctx.items), _history_limit)
                if trimmed_count > 0:
                    logger.info(f"📝 Trimmed {trimmed_count} old dialogue items, kept last {_history_limit} for memory retention (reduces input tokens)")
        except Exception as exc:
            logger.debug("conversation context trim skipped: %s", exc)
    else:
        # Preemptive ON: DO NOT mutate chat_ctx at all — any mutation invalidates preemptive
        # Previous lenient trim (10 msgs when >12) still changed chat_ctx → is_equivalent False → invalidation
        # So when preemptive ON, skip trimming entirely to preserve preemptive generation
        # This eliminates "preemptive generation invalidated after on_user_turn_completed" warning
        # FIX: Also for memory, when preemptive ON and KB present, we already disabled preemptive in worker.py
        # So this path is for non-KB calls where preemptive ON is safe and we want speed
        logger.debug("Preemptive ON: skipping chat_ctx trim to preserve preemptive generation and memory")
    # Log timing for STT_final->LLM_start path
    try:
        _elapsed_goodbye = (_time.time() - _rag_t0) * 1000
        if _elapsed_goodbye > 50:
            logger.warning(f"🐢 Slow goodbye detection: {_elapsed_goodbye:.0f}ms (should be <10ms)")
        else:
            logger.info(f"⏱️ TIMING on_user_turn_completed (goodbye check): {_elapsed_goodbye:.0f}ms")
    except Exception:
        pass

    # Normal (complete-turn) path: continue to the per-turn RAG phase.
    return {"stop": False, "preemptive_on": preemptive_on}
