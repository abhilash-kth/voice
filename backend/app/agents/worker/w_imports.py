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


"""
LiveKit worker — the runtime that turns a customer-saved AgentConfig into a
live phone/browser call for a logged-in user.

It:
  * reads the dispatched room metadata to find user_id + agent_id + call_id,
  * loads the agent + call record from the DB (SQLite or Neon via DATABASE_URL),
  * builds a LiveKit **v1** ``AgentSession``+``Agent`` for that config,
  * respects per-agent toggles: conversation memory on/off, recording on/off,
  * runs RAG (text + documents + FAQ) against the customer's knowledge base,
  * records transcripts + usage, and
  * POSTs the per-component cost breakdown + recording URL back to FastAPI.

Run with:
    python -m app.agents.worker
"""

import os
import re
import sys
import asyncio
import logging
import time
import uuid
import json
import traceback
import aiohttp
# Hoisted (03:08:14 log: a first-time module import tokenized for 273ms INSIDE
# the event loop): hashlib used to be lazily imported on the first LLM request
# of every call, right inside [PROMPT]. Import once at startup instead.
import hashlib as _hl

# Same lesson, applied to the modules whose first real import landed during an
# active call (see the prewarm() blocks): the first STT interim used to import
# app.rag ON THE LOOP (rag → models/pydantic chain → rank_bm25), which is the
# tokenize/parse stall the monitor blamed on "tokenize.py"/numpy frames while
# the import lock starved everything else. Import at process start; the
# function-local "from app import rag" lines then cost ~200ns dict lookups.
# Guarded so a bare `python worker.py` without the app package on sys.path
# still starts.
try:
    from app import rag as _rag_preload  # noqa: F401
except Exception:
    pass
from typing import Any, Iterator, Optional

# ---------------------------------------------------------------------------
# Thread limits. Cap the BLAS/math libs to 1 thread (avoids per-thread pool
# thrashing), but leave ONNX runtime UNTHROTTLED so the local silero VAD can use
# all cores — throttling it to 1 thread is what made "inference is slower than
# realtime" worse on a multi-core machine. Set VOICE_THREAD_LIMITS=0 to disable.
# MUST run before numpy/onnx/livekit are imported so the runtimes pick them up.
# ---------------------------------------------------------------------------
if os.getenv("VOICE_THREAD_LIMITS", "1") == "1":
    for _v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS",
               "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS"):
        os.environ.setdefault(_v, "1")
    # Let onnxruntime auto-size its intra-op threads (silero VAD) instead of 1.
    os.environ.setdefault("ONNXRUNTIME_NUM_THREADS", "0")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from app.config import (  # noqa: E402
    LIVEKIT_URL,
    LIVEKIT_API_KEY,
    LIVEKIT_API_SECRET,
    EGRESS_ENABLED,
    EGRESS_S3_BUCKET,
    EGRESS_S3_ENDPOINT,
    EGRESS_S3_REGION,
    EGRESS_PUBLIC_BASE_URL,
    BILLING_INTERNAL_TOKEN,
)
from app.db import init as db_init  # noqa: E402
from app import repo  # noqa: E402
from app.models import AgentConfig  # noqa: E402
from app.billing import calculate_call_cost  # noqa: E402
from app import memory  # noqa: E402
from app import leadfile  # noqa: E402

# ---------------------------------------------------------------------------
# Register LiveKit plugins on the MAIN THREAD.
#
# livekit.plugins.* call `Plugin.register_plugin(...)` at import time, and that
# refuses to run off the main thread (`RuntimeError: Plugins must be registered
# on the main thread`). The worker runs each job in a background thread on
# Windows (job_proc_lazy_main.thread_main), so a lazy import inside
# prewarm()/entrypoint()/agent_builder would crash the job before the agent can
# join the room. Importing them here (module top-level = main thread, when you
# run `python -m app.agents.worker`) registers them once, safely.
from livekit.plugins import silero    # noqa: E402,F401  (VAD)
from livekit.plugins import google    # noqa: E402,F401  (STT/TTS)
from livekit.plugins import deepgram  # noqa: E402,F401  (STT)
from livekit.plugins import openai    # noqa: E402,F401  (LLM)
# Sarvam (LLM/STT/TTS) self-registers AT IMPORT TIME, and LiveKit only allows
# registration on the MAIN thread. Importing it here — the top level of the
# worker module, which every job child process re-imports on its main thread
# (Windows spawn) — means agent_builder's lazy
#   "from livekit.plugins.sarvam import TTS/STT/LLM"
# just binds the already-registered module from sys.modules. Without this, the
# first Sarvam-using call ran the import on a to_thread worker and died with
# "RuntimeError: Plugins must be registered on the main thread".
try:  # noqa: E402
    from livekit.plugins import sarvam as _sarvam_plugin  # noqa: F401
except ImportError:  # package is optional (pip install livekit-plugins-sarvam)
    _sarvam_plugin = None
# Same for Cartesia TTS: agent_builder's lazy
#   "from livekit.plugins.cartesia import TTS"
# would otherwise be the FIRST import of the module, running inside the job
# thread and dying with "RuntimeError: Plugins must be registered on the main
# thread" before the agent joins the room.
try:  # noqa: E402
    from livekit.plugins import cartesia as _cartesia_plugin  # noqa: F401
except ImportError:  # package is optional (pip install livekit-plugins-cartesia)
    _cartesia_plugin = None

from app.config import setup_logging
setup_logging()
logger = logging.getLogger("voice-agent-saas-worker")

# FIX: 314ms synchronous SSL initialization block on LiveKit agent event loop
# LiveKit worker startup does: aiohttp.TCPConnector(ssl=http_context._create_ssl_context())
# which calls ssl.create_default_context() synchronously on event loop, blocking 314ms
# Fix: Prewarm SSL context at import time in background thread and cache, patch http_context to use cached
import ssl as _ssl_prewarm
import threading as _threading_prewarm
