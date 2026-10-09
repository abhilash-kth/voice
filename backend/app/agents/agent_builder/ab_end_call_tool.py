"""end_call LLM tool: speaks the deterministic closing and deletes the room.

Extracted verbatim from agent_builder/ab_agent.py (<=300-line rule).
"""
from __future__ import annotations

import asyncio
import logging

from .ab_prompt import _get_closing_for_cfg

logger = logging.getLogger("voice-agent-saas-worker")


def build_end_call_tool(cfg, lead_data, llm, agent_ref, closing_state,
                        prior_memory, _in_call_memory_lines):
    from livekit.agents import get_job_context  # lazy, as in the original builder
    """Returns the tool callable for Agent(tools=[...]). `explicit_goodbye`
    became the shared cell closing_state["explicit_goodbye"] (same semantics)."""

    async def _end_call() -> str:
        """End this call and hang up. Call it ONLY when user says goodbye, bye, thank you, etc.
        Do NOT call for 'sahi baat hai', 'ok', 'achhi lagti', 'product hai', number, email, etc.
        Deterministic closing: worker speaks fixed closing line, tool only deletes room.
        """
        if not closing_state["explicit_goodbye"]:
            logger.warning("end_call rejected: caller did not give an explicit final goodbye - keeping call open")
            # Return instruction for LLM to continue naturally, not silence
            return "DO NOT END CALL. User did NOT say goodbye. Phrases like 'sahi baat hai', 'ok', 'achhi lagti', 'product hai', phone numbers, emails are NOT goodbye. Continue conversation warmly, ask how you can help."
        ctx = get_job_context(required=False)
        if ctx is None:
            return "No job context; call not ended."
        logger.info("[CALL_END_REQUESTED] source=agent reason=completed")
        # Avoid duplicate TTS: worker.py already spoke deterministic closing.
        # Only speak here as fallback if worker hasn't (check last closing timestamp).
        import time as _time
        now = _time.time()
        last_ts = agent_ref.get("last_closing_ts", 0)
        agent_inst = agent_ref.get("instance")
        if agent_inst is not None:
            # Check timestamp set by worker.py _do_deterministic_closing
            ts1 = getattr(agent_inst, '_last_deterministic_closing_ts', 0)
            ts2 = getattr(getattr(agent_inst, 'cfg', None), '_last_closing_ts', 0) if hasattr(agent_inst, 'cfg') else 0
            last_ts = max(last_ts, ts1, ts2)
        # If worker spoke within last 4s, skip TTS here.
        if now - last_ts > 4:
            # Fallback deterministic closing if worker missed it
            closing_line = _get_closing_for_cfg(cfg)
            agent_inst = agent_ref.get("instance")
            if agent_inst is not None:
                try:
                    sess = getattr(agent_inst, "session", None)
                    if sess is not None:
                        logger.info(f"👋 Fallback deterministic closing via end_call tool: {closing_line}")
                        await sess.say(closing_line, allow_interruptions=False)
                        await asyncio.sleep(0.6)
                except Exception as e:
                    logger.warning(f"Fallback closing via tool failed: {e}")
        else:
            await asyncio.sleep(0.4)
        # Physically cut the call: delete the LiveKit room so the caller/SIP
        # participant is disconnected (not left in a silent, open call).
        agent_inst = agent_ref.get("instance")
        if agent_inst is not None:
            sess = getattr(agent_inst, "session", None)
            if sess is not None:
                try:
                    sess.shutdown(drain=False)
                except Exception:
                    pass
        room = getattr(ctx.room, "name", None)
        if room:
            try:
                from ...telephony import end_active_room
                await end_active_room(room)
            except Exception as e:
                logger.warning(f"end_call: could not delete room {room}: {e}")
        ctx.shutdown()
        logger.info("[CALL_ENDED] reason=completed")
        return "Call ended."

    # `name="end_call"` keeps the LLM-visible tool name in sync with the prompt
    # (otherwise it would default to "_end_call" and the model might not call it).
    end_call_tool = llm.function_tool(
        _end_call,
        name="end_call",
        description="End the call and hang up. Call this once the conversation is finished.",
    )

    # Cross-call memory becomes part of the initial conversation history, so it
    # influences every turn without being re-inserted.
    chat_ctx = llm.ChatContext()
    if lead_data:
        # For bulk-call campaigns, give the agent the lead's details (from the
        # uploaded file) so it can address them by name / reference their data.
        lead_blurb = ", ".join(f"{k}: {v}" for k, v in (lead_data or {}).items() if v)
        chat_ctx.add_message(
            role="system",
            content=(
                "You are now speaking with a specific caller from a contact list.\n"
                f"This caller's details: {lead_blurb or '(none)'}.\n"
                "Use the caller's name naturally when it is known, and reference their "
                "details when relevant."
            ),
        )
    if prior_memory:
        # Voice latency: truncate prior_memory to 800 chars when RAG enabled (was unlimited 40 turns ~4000 tokens)
        # Preserves recent cross-call memory (name, preferences) without bloating input tokens 3500-3700
        try:
            import os as _os_pm
            _rag_pm = (_os_pm.getenv("VOICE_RAG_PER_TURN") or "").strip().lower() not in ("0", "false", "off")
            _pm_budget = int(_os_pm.getenv("VOICE_PRIOR_MEMORY_BUDGET_CHARS", "800")) if _rag_pm else 2000
        except Exception:
            _pm_budget = 800
        _pm_truncated = prior_memory
        if len(prior_memory) > _pm_budget:
            # Keep last _pm_budget chars (most recent)
            _pm_truncated = prior_memory[-_pm_budget:]
            # Try to cut at line boundary
            _nl = _pm_truncated.find("\n")
            if _nl != -1 and _nl < _pm_budget * 0.3:
                _pm_truncated = _pm_truncated[_nl+1:]
        chat_ctx.add_message(
            role="system",
            content="Prior conversation with this customer:\n" + _pm_truncated,
        )
        if len(prior_memory) != len(_pm_truncated):
            logger.info(f"🔧 Prior memory truncated {len(prior_memory)} -> {len(_pm_truncated)} chars (budget {_pm_budget}) to reduce 3500-3700 tokens")

    return end_call_tool, chat_ctx
