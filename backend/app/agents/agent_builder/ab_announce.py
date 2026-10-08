from __future__ import annotations

import asyncio
import logging
from typing import Any

from ...models import AgentConfig
from ...config import (
    GROQ_API_KEY,
)

logger = logging.getLogger("voice-agent-saas-agent-builder")


# cross-module imports (auto-generated)
from .ab_opening import speak_opening_line, wait_until_caller_can_hear

def build_announce_agent(
    cfg: AgentConfig,
    *,
    announce_text: str = "",
) -> "Any":
    """Return a LiveKit v1 ``Agent`` that only plays a fixed script and hangs up.

    Used for "reminder"/"inform-only" calls: the agent answers, reads the script
    aloud via TTS, then ends the call. It never listens (no STT) and never
    generates a reply (no LLM). The customer is not billed for STT/LLM.
    """
    from livekit.agents import Agent
    from livekit.agents import llm

    text = (announce_text or getattr(cfg, "announce_text", "") or cfg.greeting or f"Hello, this is {cfg.name} with an announcement.").strip()
    end_after_announcement = bool(getattr(cfg, "end_after_announcement", False))

    class _AnnounceAgent(Agent):
        def __init__(self):
            self.cfg = cfg
            self._opening_started = False
            self._opening_done = False
            super().__init__(
                # No LLM: a still/empty instruction set. Everything is hardcoded.
                instructions="You are a one-way announcement. Do not use tools.",
                chat_ctx=llm.ChatContext(),
                turn_handling={
                    "endpointing": {"min_delay": 0.2, "max_delay": 0.5},
                    "interruption": {"enabled": False},  # script should not be cut off
                    "preemptive_generation": {"enabled": False},
                },
            )

        async def on_enter(self) -> None:
            self._opening_started = True
            try:
                logger.info("[ANNOUNCEMENT_STARTED] Announcement connected — waiting for caller audio path")
                await wait_until_caller_can_hear(self.session)
                logger.info("[ANNOUNCEMENT_STARTED] Reading announcement script: %s", text[:60])
                await speak_opening_line(self.session, text, timeout=120)
                logger.info("[ANNOUNCEMENT_FINISHED] Announcement script playback completed")
            except Exception as e:
                logger.warning(f"Announcement playback failed: {type(e).__name__}: {e!r}")
            finally:
                self._opening_done = True

            if end_after_announcement:
                logger.info("[CALL_END_REQUESTED] source=announcement reason=announcement_completed")
                try:
                    await asyncio.sleep(2.5)  # flush audio playout buffer to caller
                    from livekit.agents import get_job_context
                    ctx = get_job_context(required=False)
                    try:
                        self.session.shutdown(drain=True)
                    except Exception:
                        pass
                    if ctx is not None:
                        room = getattr(ctx.room, "name", None)
                        if room:
                            try:
                                from ...telephony import end_active_room
                                await end_active_room(room)
                            except Exception as e:
                                logger.warning(f"announcement: could not delete room {room}: {e}")
                        ctx.shutdown()
                    logger.info("[CALL_ENDED] reason=announcement_completed")
                except Exception as e:
                    logger.warning(f"could not close announcement session: {e}")
            else:
                logger.info("📢 Announcement finished — keeping call connected (end_after_announcement=False)")

    return _AnnounceAgent()

