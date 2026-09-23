"""Preflight validation for an agent's runtime config.

The #1 production failure mode this module kills: a saved agent whose config no
longer builds (LLM provider/model removed from the catalog, missing API key,
unknown STT/TTS provider). The worker job then crashes *before joining the
room*, LiveKit gives up quietly, and the caller sits in a silent room forever
while the UI shows "Waiting for agent to connect..." with no error.

Instead of discovering that in the worker mid-call, ``preflight_agent_config``
runs the EXACT same code path the worker uses — ``AgentConfig(**rec)`` +
``build_stt/build_llm/build_tts`` — before the room is created. If it would
crash the worker, the API fails the call with the real reason, which the UI
surfaces immediately.

Safety notes:
  * Provider constructors are offline (they store args / build HTTP clients;
    no network round-trip happens at build time), so this is cheap and cannot
    burn tokens.
  * livekit plugins self-register AT IMPORT TIME and refuse to import off the
    main thread. The import therefore happens on the main thread (the lifespan
    warm or the first call), and only the lightweight *construction* runs in a
    worker thread.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

logger = logging.getLogger("voice-agent-saas-preflight")

# One-time guard so a slow first call doesn't double-run the import storm.
_warmed = False
_warm_lock = asyncio.Lock()


def _import_voice_runtime() -> None:
    """Import livekit agents + all plugins ON THE CALLING THREAD.

    Must be called from the main thread (plugin registration rule). Imports are
    idempotent — subsequent calls are near-free (sys.modules hit).
    """
    import livekit.agents  # noqa: F401
    from .agents import agent_builder  # noqa: F401  (exports the builders)
    import livekit.plugins.openai  # noqa: F401
    import livekit.plugins.deepgram  # noqa: F401
    import livekit.plugins.google  # noqa: F401
    import livekit.plugins.silero  # noqa: F401
    try:
        import livekit.plugins.sarvam  # noqa: F401
    except ImportError:
        pass  # optional plugin


async def warm_voice_runtime() -> None:
    """Import the voice runtime at API startup (main thread, off the request path).

    Running it during the first ``start_call`` would add a few seconds to that
    request; at startup it is invisible.
    """
    global _warmed
    async with _warm_lock:
        if _warmed:
            return
        try:
            _import_voice_runtime()
            _warmed = True
            logger.info("🔥 Voice runtime imported on main thread (call preflight ready)")
        except Exception as e:
            logger.warning(f"Voice runtime prewarm failed (preflight skips until livekit is importable): {e!r}")


def _build_sync(rec: dict) -> None:
    """The worker's exact config→runtime path. Raises the worker's real error."""
    from .models import AgentConfig
    from .agents import agent_builder

    cfg = AgentConfig(**rec)  # schema + LLM catalog validation (ValueError on bad combo)
    agent_builder.build_stt(cfg)   # lazy instances; raises on unknown provider / missing key
    agent_builder.build_llm(cfg)
    agent_builder.build_tts(cfg)


async def preflight_agent_config(rec: dict) -> Optional[str]:
    """Return a human-readable error if this config would crash the worker, else None.

    ``rec`` is the same agent dict ``repo.get_agent`` returns (and the same
    object the worker reads from its local cache), so validation parity is
    exact. Returns None (skip) only when the voice runtime is not installed in
    this process at all (API-only deployments).
    """
    global _warmed
    try:
        import livekit  # noqa: F401
    except ImportError:
        return None  # API-only process; the worker runs elsewhere.

    if not _warmed:
        # First call since startup: pay the import cost on the main thread
        # (this function is awaited from an endpoint on the main loop).
        try:
            _import_voice_runtime()
            _warmed = True
        except Exception as e:
            logger.warning(f"Preflight runtime import failed; skipping preflight: {e!r}")
            return None

    def _run():
        try:
            _build_sync(rec)
            return None
        except Exception as e:
            return f"{type(e).__name__}: {e}"

    try:
        err = await asyncio.wait_for(asyncio.to_thread(_run), timeout=20)
    except asyncio.TimeoutError:
        return "configuration check timed out (20s) — retry the call"
    except Exception as e:
        if "Plugins must be registered" in str(e):
            logger.warning(f"Preflight could not run off-main-thread imports; skipping: {e!r}")
            return None
        return f"{type(e).__name__}: {e}"

    if err:
        logger.error("PREFLIGHT FAILED agent=%s: %s", rec.get("id"), err)
    return err
