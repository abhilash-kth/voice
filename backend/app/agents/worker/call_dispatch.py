"""Worker entrypoint: job-dispatch logging, 90s setup watchdog, failure
framing (end room + shutdown + re-raise) around `_entrypoint_body`.

Extracted verbatim from `w_entrypoint.py` (<=300-line rule). The body
function is imported lazily inside `entrypoint` to avoid a circular import
(w_entrypoint re-exports this entrypoint for __main__ / package __init__).
"""
from __future__ import annotations

import asyncio
import json
import logging
import traceback

logger = logging.getLogger("voice-agent-saas-worker")


async def entrypoint(ctx):
    """LiveKit job entrypoint — the worker's failure contract.

    Any exception during setup (agent load, provider build, session start) used
    to kill the job silently: the room stayed open with no agent, the UI waited
    on "Waiting for agent to connect..." forever, and the call row stayed
    "planned". Now every setup failure:

      1. logs CRITICAL with the full traceback,
      2. marks the call "failed" in the DB with the reason (the UI polls this
         and shows the caller the real error instead of an endless spinner),
      3. deletes the room (the caller's browser disconnects instead of hanging
         in a silent room),
      4. shuts the job down (frees the worker process for the next dispatch).

    A 90-second setup watchdog additionally force-fails jobs whose setup hangs
    (stuck provider build / DB init / dead loop) so one sick job can't clog
    dispatch — the classic "second call goes silent" symptom.
    """
    # FIRST observable link of the dispatch chain on the worker side. If the
    # API logs CALL_START -> ROOM_CREATED -> AGENT_DISPATCH_SENT but this line
    # never appears, LiveKit never offered the job to this worker (dispatch
    # dropped / worker not registered at dispatch time) — never a code issue.
    try:
        _md = getattr(getattr(ctx, "job", None), "metadata", "") or ""
        logger.info(
            "[JOB_RECEIVED] room=%s job_id=%s worker_agent=%s metadata=%s",
            getattr(getattr(ctx, "room", None), "name", ""),
            getattr(getattr(ctx, "job", None), "id", ""),
            WORKER_AGENT_NAME,
            _md[:200],
        )
        # P9 lifecycle marker: the job is now owned by THIS process (pid ties
        # every later log line to a concrete runner process — two "initializing
        # job runner" lines are two idle processes, not two worker instances).
        logger.info(
            "[JOB_ACCEPTED] job_id=%s room=%s pid=%s agent_name=%s",
            getattr(getattr(ctx, "job", None), "id", ""),
            getattr(getattr(ctx, "room", None), "name", ""),
            os.getpid(),
            WORKER_AGENT_NAME,
        )
    except Exception:
        pass
    setup_complete = {"done": False}

    async def _setup_watchdog():
        try:
            await asyncio.sleep(90.0)
        except asyncio.CancelledError:
            return
        if not setup_complete["done"]:
            logger.critical(
                "⛔ Setup exceeded 90s — force-shutting job to free the worker "
                "process (stuck provider build / DB init / event loop)"
            )
            try:
                ctx.shutdown()
            except Exception:
                pass

    watchdog_task = asyncio.create_task(_setup_watchdog())
    try:
        from .w_entrypoint import _entrypoint_body
        await _entrypoint_body(ctx, setup_complete)
    except Exception as e:
        # Avoid synchronous traceback.format_exc() on event loop (tokenize.open block)
        try:
            _tb_setup = await asyncio.to_thread(traceback.format_exc)
        except Exception:
            _tb_setup = f"{type(e).__name__}: {e}"
        logger.critical(
            "WORKER_JOB_SETUP_FAILED room=%s: %s: %s\n%s",
            getattr(ctx.room, "name", ""), type(e).__name__, e, _tb_setup,
        )
        try:
            meta = json.loads(ctx.job.metadata or "{}")
        except Exception:
            meta = {}
        await _mark_call_failed(
            meta.get("call_id", ""), meta.get("user_id", ""), f"{type(e).__name__}: {e}"
        )
        room_name = getattr(ctx.room, "name", None)
        if room_name:
            try:
                from app.telephony import end_active_room
                await end_active_room(room_name)
            except Exception:
                pass
        try:
            ctx.shutdown()
        except Exception:
            pass
        raise
    finally:
        if not watchdog_task.done():
            watchdog_task.cancel()
