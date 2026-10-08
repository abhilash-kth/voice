"""Agent record fetch for a dispatched call: Prisma-binary prewarm, pooled
DB init (process-cached), cached-record short-circuit, 2-attempt lookup,
demo fallback, and the "agent not found → mark call failed → shutdown" path.

Extracted verbatim from `w_entrypoint.py` (<=300-line rule); only the
control-flow tail is adapted to return values (identical behaviour).
"""
from __future__ import annotations

import asyncio
import logging
import time

from .w_imports import AgentConfig, db_init, repo
from . import w_runtime as _wr

logger = logging.getLogger("voice-agent-saas-worker")


async def fetch_agent_record(ctx, agent_id, user_id, call_id, rec):
    """Returns (cfg, agent_id, aborted). aborted=True ⇒ the caller returns."""

    if rec is not None:
        # Warm DB connection in background so billing/cleanup at end of call is instant
        if not _wr._DB_INIT_DONE:
            async def _bg_db_init():
                try:
                    await asyncio.wait_for(db_init(), timeout=10)
                    _wr._DB_INIT_DONE = True
                    logger.info("⏱️ Background DB init completed ready for billing")
                except Exception as exc:
                    logger.warning("Background DB init failed: %r", exc)
            asyncio.create_task(_bg_db_init())
    else:
        db_t0 = time.time()
        db_just_initialized = False
        if not _wr._DB_INIT_DONE:
            try:
                try:
                    def _ensure_prisma_engine_binary() -> bool:
                        import importlib
                        for mod_base in ("prisma_client", "prisma"):
                            try:
                                paths = importlib.import_module(f"{mod_base}.binaries.paths")
                                utils = importlib.import_module(f"{mod_base}.engine.utils")
                                utils.ensure(paths.BINARY_PATHS.query_engine)
                                return True
                            except Exception:
                                continue
                        return False
                    if await asyncio.to_thread(_ensure_prisma_engine_binary):
                        logger.info("🔥 Prewarm: Prisma engine binary verified off-loop")
                except Exception:
                    pass
                await asyncio.wait_for(db_init(), timeout=8)
                _wr._DB_INIT_DONE = True
                db_just_initialized = True
                logger.info(f"⏱️ DB init {time.time()-db_t0:.2f}s on agent loop (first time, cached for next calls)")
            except Exception as exc:
                logger.error("database initialization unavailable (%.2fs); continuing voice call: %r", time.time()-db_t0, exc)
        else:
            try:
                await asyncio.wait_for(db_init(), timeout=5)
                logger.info("⏱️ DB init rechecked on this event loop")
            except Exception as exc:
                _wr._DB_INIT_DONE = False
                logger.warning("database re-init failed (%.2fs): %r", time.time() - db_t0, exc)

        if agent_id and user_id:
            lookup_t0 = time.time()
            timeouts = [6.0, 3.0] if db_just_initialized else [3.0, 3.0]
            for attempt in range(2):
                try:
                    rec = await asyncio.wait_for(repo.get_agent(agent_id, user_id), timeout=timeouts[attempt])
                    logger.info(f"⏱️ agent lookup ok attempt {attempt+1} in {time.time()-lookup_t0:.2f}s")
                    break
                except Exception as exc:
                    logger.warning(
                        "agent lookup attempt %s/2 failed (%.2fs, timeout=%.1fs): %r",
                        attempt + 1, time.time() - lookup_t0, timeouts[attempt], exc,
                    )
                    if attempt < 1:
                        await asyncio.sleep(0.15)

    if rec is None:
        if agent_id and agent_id != "demo":
            logger.error(
                "[CALL_ERROR] room=%s Agent '%s' not found for user %s. Refusing silent fallback.",
                getattr(ctx.room, "name", ""), agent_id, user_id,
            )
            if call_id and user_id:
                try:
                    await repo.update_call(call_id, {
                        "status": "failed",
                        "ended_at": time.strftime("%Y-%m-%d %H:%M"),
                    })
                except Exception:
                    pass
            try:
                ctx.shutdown()
            except Exception:
                pass
            return None, agent_id, True
        logger.info("[AGENT_SELECTED] room=%s Using default demo agent config", getattr(ctx.room, "name", ""))
        from app.sample import default_config
        cfg = default_config()
        agent_id = "demo"
    else:
        cfg = AgentConfig(**rec)
    return cfg, agent_id, False


def parse_job_metadata(ctx):
    """Parse the job metadata (agent_id, browser/SIP mode, phone, call/user ids,
    campaign lead data). Extracted verbatim from `_entrypoint_body`."""
    import json as _json
    try:
        meta = _json.loads(ctx.job.metadata or "{}")
    except Exception:
        meta = {}
    return (
        meta.get("agent_id"),
        meta.get("mode", "browser"),
        meta.get("phone"),
        meta.get("call_id", ""),
        meta.get("user_id", ""),
        meta.get("lead_data") or {},
        meta.get("agent_config"),
    )


def read_agent_cache(agent_id):
    """Fast-path local cache for the agent record (no DB delay). Verbatim."""
    rec = None
    if agent_id:
        try:
            from app.config import DATA_DIR
            import json as _json
            cache_file = DATA_DIR / f"agent_{agent_id}.json"
            if cache_file.exists():
                rec = _json.loads(cache_file.read_text(encoding="utf-8"))
                logger.info("⚡ Fast-path: Agent '%s' loaded from local cache in 0ms (no DB delay)", rec.get("name", agent_id))
        except Exception as exc:
            logger.warning("Could not read agent cache file: %r", exc)
    return rec


def mark_call_in_progress(ctx, call_id, user_id) -> None:
    """Fire-and-forget task that marks the call row in-progress (does not block
    audio setup). Extracted verbatim from `_entrypoint_body`."""
    async def _mark_call_in_progress():
        try:
            if not _wr._DB_INIT_DONE:
                await asyncio.wait_for(db_init(), timeout=10)
            if call_id and user_id:
                await repo.update_call(call_id, {"status": "in-progress", "room": getattr(ctx.room, "name", "")})
        except Exception as e:
            logger.warning("Could not mark call in-progress: %s", e)
    asyncio.create_task(_mark_call_in_progress())

