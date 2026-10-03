from __future__ import annotations

import os
import re
import sys
import asyncio
import logging
import time
import uuid
import json
import traceback
import hashlib as _hl
from typing import Any, Iterator, Optional

logger = logging.getLogger("voice-agent-saas-worker")


# cross-module imports (auto-generated)
from .w_gcp_creds import warm_google_credentials
from .w_imports import setup_logging, silero
from .w_runtime import _VAD_CACHE_LOCK

def prewarm(proc):
    setup_logging()
    # Job processes must keep ONLY livekit's IPC LogQueueHandler: our own
    # QueueListener prints directly to the console too, so without this purge
    # every job log line appears twice, all of it synchronously on the loop.
    try:
        from app.config import purge_sync_root_handlers
        purge_sync_root_handlers(job_proc=True)
    except Exception:
        pass

    # Production prewarm: VAD + Google auth + hyphenator + async_toolset off loop
    # Fixes: 406ms onnxruntime VAD, 176ms Google auth crypt, 256ms hyphenation re.split, 101ms async_toolset import
    # VAD 0.20/0.30/0.20/0.55 production-tuned for 300-400ms speech_end->STT_final + less CPU
    # VAD tuning comes from agent_builder._vad_tuning() (env-driven) so the
    # prewarmed model and the one build_vad() would create are identical — this
    # cache IS what build_vad() returns, so a hardcoded copy here would silently
    # override any VOICE_VAD_* / VOICE_ENDPOINTING_* tuning.
    global _VAD_CACHE
    try:
        from app.agents.agent_builder import _vad_tuning as _vad_params
        vad = silero.VAD.load(**_vad_params())
        with _VAD_CACHE_LOCK:
            _VAD_CACHE = vad
        # Also set agent_builder cache to avoid 406ms block in build_vad
        try:
            from app.agents import agent_builder as _ab
            with _ab._VAD_CACHE_LOCK_AGENT:
                _ab._VAD_CACHE_AGENT = vad
            logger.info("🔥 Prewarm: VAD hot cached in both worker and agent_builder (avoids 406ms onnxruntime block)")
        except Exception as _e:
            logger.info(f"🔥 Prewarm: VAD hot (production 0.20/0.30/0.20/0.55) - cached in worker, agent_builder cache set failed: {_e}")
    except Exception as e:
        logger.warning(f"VAD prewarm failed: {e}")
    
    # Prewarm Google auth crypt off loop to avoid 176ms and 198ms blocks
    try:
        import google.auth.crypt._cryptography_rsa as _crypt_rsa
        import google.auth._service_account_info as _sa_info
        import google.auth._default as _auth_default
        import google.oauth2.credentials as _oauth2_creds
        import google.oauth2.service_account as _oauth2_sa
        logger.info("🔥 Prewarm: Google auth crypt + oauth2.credentials imported (avoids 176ms and 198ms blocks during TTS)")
    except Exception as e:
        logger.debug(f"Google auth prewarm failed: {e}")
    
    # Prewarm hyphenator off loop to avoid 256ms/391ms block at re.split in _basic_hyphenator
    try:
        from livekit.agents.tokenize._basic_hyphenator import Hyphenator, PATTERNS, EXCEPTIONS
        Hyphenator(PATTERNS, EXCEPTIONS)
        logger.info("🔥 Prewarm: Hyphenator hot (avoids 256ms/391ms re.split block in transcription synchronizer)")
    except Exception as e:
        logger.debug(f"Hyphenator prewarm failed: {e}")
    
    # Prewarm async_toolset import off loop to avoid 101ms block
    try:
        import livekit.agents.llm.async_toolset as _async_toolset
        logger.info("🔥 Prewarm: async_toolset imported (avoids 101ms import block)")
    except Exception as e:
        logger.debug(f"async_toolset prewarm failed: {e}")

    # Prewarm (03:07–03:09 log): the remaining application-owned loop blocks
    # were module loads and first-execution costs, NOT audio math — the first
    # STT interim imported app.rag (+ pydantic validators for KnowledgeItem),
    # the first LLM completion imported app.llm_catalog inside the billing
    # block, hangup imports app.telephony/db. Job processes spawn fresh
    # (multiprocessing_context="spawn"), so warm per-job HERE; everything
    # below is import/constructor calls only — no state the live pipeline
    # reads, so a failure here changes nothing but the first-turn timing.
    try:
        from app import rag as _rag_pw
        _kb0 = _rag_pw.KnowledgeBase(text="prewarm warmup sample corpus tokens")
        # exercises build_index, _index_for, BM25 fast+fallback paths,
        # normalize_query, and the first KnowledgeItem validation (pydantic
        # model_rebuild imports inspect→tokenize — must never happen
        # mid-utterance either).
        _rag_pw.build_index(_kb0)
        _rag_pw.build_context_detailed(_kb0, "warmup query", top_k=1)
        _rag_pw.normalize_query(" Ok  warmup ")
        logger.info("🔥 Prewarm: RAG stack hot (rag import chain, index build, validators — 0ms module load on first interim)")
    except Exception as e:
        logger.debug(f"RAG prewarm failed: {e}")
    try:
        import app.llm_catalog  # noqa: F401  (billing cost calc: first LLM completion)
        import app.telephony  # noqa: F401   (end_active_room: hangup path)
        import app.db  # noqa: F401          (release_current_loop/get_prisma)
        logger.info("🔥 Prewarm: llm_catalog/telephony/db imported (billing + hangup paths load-free)")
    except Exception as e:
        logger.debug(f"billing/telephony prewarm failed: {e}")

    # Prewarm Pydantic ChatMessage and ChatContext validation schemas off the agent loop.
    # In Pydantic v2, ChatMessage.__init__ triggers model_rebuild() upon first invocation.
    # On Windows, this took 7259ms inside entrypoint. Prewarming here compiles it off-loop.
    try:
        from app.agents.agent_builder import warm_agent_builder_schemas
        warm_agent_builder_schemas()
    except Exception as e:
        logger.debug(f"ChatMessage prewarm failed: {e}")

    try:
        from livekit.agents.voice import Agent as _VoiceAgent, room_io as _room_io
        _ = _room_io.RoomOptions(close_on_disconnect=False, delete_room_on_close=False)
        logger.info("🔥 Prewarm: Voice Agent & RoomOptions imported")
    except Exception as e:
        logger.debug(f"Voice Agent prewarm failed: {e}")

    # Warm the Google TTS *credentials* before the first customer response so the
    # ~163-198ms JSON/RSA parse never lands on the agent event loop.
    #
    # This deliberately does NOT build a TextToSpeechAsyncClient any more. The old
    # version created a throwaway TTS and called _ensure_client() inside
    # asyncio.new_event_loop() + loop.close(); a grpc.aio channel remembers the
    # loop it was created on, so any client warmed that way is bound to a dead
    # loop and later synthesize() calls fail with
    # `RuntimeError: Event loop is closed`. The async client must be created on
    # the loop that uses it (the plugin does that lazily in _ensure_client()).
    # Everything that IS loop-independent — credential parsing and the grpc/google
    # module imports — is warmed here instead, in a thread so prewarm() itself
    # never blocks.
    try:
        import os as _os_tts
        from app.config import GOOGLE_APPLICATION_CREDENTIALS as _gac_default
        creds = _os_tts.getenv("GOOGLE_APPLICATION_CREDENTIALS") or _gac_default

        def _prewarm_google_tts():
            try:
                warmed = warm_google_credentials(creds)
                # Import the transport machinery so the on-loop client build is
                # just channel creation (module import cost paid off loop).
                try:
                    import grpc.aio  # noqa: F401
                    import google.api_core.grpc_helpers_async  # noqa: F401
                    from google.cloud import texttospeech  # noqa: F401
                except Exception:
                    pass
                if warmed:
                    logger.info(
                        "🔥 Prewarm: Google TTS credentials + grpc.aio/texttospeech imports warm "
                        "(async client is built on the agent loop — never off-loop)"
                    )
            except Exception as _e:
                logger.debug(f"Google TTS credential prewarm thread failed: {_e!r}")

        if creds and _os_tts.path.exists(creds):
            import threading as _thr
            t = _thr.Thread(target=_prewarm_google_tts, daemon=True)
            t.start()
            t.join(timeout=3)  # Wait up to 3s for prewarm
            logger.info("🔥 Prewarm: Google TTS credential prewarm attempted (off loop, thread)")
        else:
            logger.info("🔥 Prewarm: no Google credentials file found, skipping TTS credential prewarm")
    except Exception as e:
        logger.debug(f"Google TTS prewarm failed: {e!r}")
    
    # NOTE: DB prewarm removed - it used asyncio.run() which closes event loop, causing
    # "Event loop is closed" on next Prisma call -> 1.73s retry. DB is cached per process
    # via the _DB_INIT_DONE global and connected ON the agent loop in entrypoint() (the
    # 1359ms SSL block that pushed it off-loop is fixed by the cached SSL context patch).


def _worker_load(worker) -> float:
    """Calculate load based on actual active jobs rather than Windows event-loop jitter.

    Default CPU-sampling load_fnc in livekit-agents spikes to 1.0 on Windows due to
    asyncio IOCP polling (GetQueuedCompletionStatus) and synchronous console I/O,
    falsely marking the worker as 'at full capacity, marking as unavailable' and
    dropping incoming calls.
    """
    # Supervisor-side housekeeping, piggybacked on a tick that runs on the main
    # loop: livekit's CLI adds a synchronous JSON console handler to root AFTER
    # our async setup — every record would otherwise print twice and stall the
    # loop 150-350ms per burst on Windows console writes.
    try:
        from app.config import purge_sync_root_handlers
        purge_sync_root_handlers()
    except Exception:
        pass
    try:
        active = len(getattr(worker, "active_jobs", []) or [])
        max_jobs = int(os.getenv("MAX_CONCURRENT_CALLS", "10"))
        return min(float(active) / float(max_jobs), 1.0)
    except Exception:
        return 0.0


