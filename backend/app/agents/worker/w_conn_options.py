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


def _build_conn_options():
    """Capped connect/retry budgets for LLM/STT/TTS.

    LiveKit's default is ``APIConnectOptions(max_retry=3, retry_interval=2.0,
    timeout=10.0)`` — 3 retries with backoff. On a Groq 429 (rate-limit, ~20 min),
    a transient ``getaddrinfo`` DNS blip, or a Deepgram ``1006`` disconnect, those
    3 retries are what produced the 16–19s "thinking"/silent stalls.

    We cut retries to 1 with a short 0.5s interval so a brief blip recovers but a
    persistent rate-limit fails in well under a second instead of freezing the caller.
    """
    from livekit.agents.llm.llm import APIConnectOptions
    from livekit.agents.voice.agent_session import SessionConnectOptions

    _conn = APIConnectOptions(max_retry=0, retry_interval=0.5, timeout=8.0)
    # Keep STT on the short media timeout. Google streaming TTS can emit audio
    # before the RPC finishes; a six-second deadline was aborting normal closing
    # streams mid-utterance. TTS gets LiveKit's normal 10s request budget while
    # retaining the same single retry policy for failures before audio starts.
    _media_conn = APIConnectOptions(max_retry=1, retry_interval=0.5, timeout=6.0)
    _tts_conn = APIConnectOptions(max_retry=1, retry_interval=0.5, timeout=10.0)
    return SessionConnectOptions(
        llm_conn_options=_conn,
        stt_conn_options=_media_conn,
        tts_conn_options=_tts_conn,
    )


