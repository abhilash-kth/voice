from __future__ import annotations

import asyncio
import logging
from typing import Any

from ...models import AgentConfig
from ...config import (
    GROQ_API_KEY,
)

logger = logging.getLogger("voice-agent-saas-agent-builder")


async def wait_until_caller_can_hear(session, timeout: float = 12.0) -> None:
    """Wait until the caller is linked, then give the browser time to subscribe.

    Opening speech that starts before the browser attaches its audio element is
    generated and dropped. The call looks connected and stays silent.
    """
    room_io = getattr(session, "room_io", None)
    if room_io is not None and hasattr(room_io, "wait_for_ready"):
        try:
            await asyncio.wait_for(room_io.wait_for_ready(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning("Timed out waiting for the caller audio path — speaking anyway.")
        except Exception as e:
            logger.warning(f"wait_for_ready failed; speaking anyway: {e}")
    # RoomIO "ready" is earlier than the browser attaching <audio>.
    await asyncio.sleep(0.2)


async def speak_opening_line(
    session, text: str, *, timeout: float = 45.0, allow_interruptions: bool = False
) -> None:
    """Play one opening line and wait until playout finishes.

    Interruptions stay off for this line only. The browser mic opens at the
    same moment the agent starts, and that burst used to cancel the greeting
    before any audio reached the caller.
    """
    text = (text or "").strip()
    if not text:
        logger.warning("Opening line is empty — nothing to speak")
        return
    last_error: Exception | None = None
    for attempt in (1, 2):
        try:
            # allow_interruptions: the greeting used to be hard-protected
            # (False), which made EVERY interruption path skip it — library
            # barge-in checks _current_speech.allow_interruptions and
            # SpeechHandle.interrupt() raises while the handle is protected
            # (voice/speech_handle.py:221, agent_activity.py user-speech
            # gates). Result: talking over "Namaste…" changed nothing audible.
            # Assistant mode now passes True; announcement one-way playback
            # keeps False.
            handle = session.say(text, allow_interruptions=allow_interruptions)
            if handle is None:
                return
            waiter = getattr(handle, "wait_for_playout", None)
            if callable(waiter):
                await asyncio.wait_for(waiter(), timeout=timeout)
            else:
                await asyncio.wait_for(handle, timeout=timeout)
            return
        except Exception as e:
            last_error = e
            logger.warning(
                "opening line attempt %s failed: %s: %r",
                attempt, type(e).__name__, e,
            )
            if attempt == 1:
                await asyncio.sleep(0.4)
    if last_error is not None:
        raise last_error


def warm_agent_builder_schemas() -> None:
    """Pre-warm Pydantic ChatMessage and ChatContext validation schemas off the event loop.

    Pydantic v2 triggers a lazy model_rebuild() upon first ChatMessage instantiation.
    On Windows systems, model_rebuild() inspects caller namespaces and imports annotations,
    blocking the asyncio event loop for up to 7+ seconds if done inside an active call turn.
    Calling this in prewarm() compiles the validators ahead of time.
    """
    try:
        from livekit.agents.llm import chat_context
        chat_context.ChatMessage.model_rebuild()
        from livekit.agents import llm
        warm_ctx = llm.ChatContext()
        warm_ctx.add_message(role="system", content="warmup")
        warm_ctx.add_message(role="user", content="warmup")
        warm_ctx.add_message(role="assistant", content="warmup")
        logger.info("🔥 Prewarm: llm.ChatContext / ChatMessage models compiled (0ms model_rebuild during call)")
    except Exception as exc:
        logger.debug("ChatContext schema prewarm note: %r", exc)


