from __future__ import annotations

import os
import re
import sys
import asyncio
import logging
import time
import traceback
from typing import Any
logger = logging.getLogger("voice-agent-saas-worker")


# cross-module imports (auto-generated)
from .gcp_credentials import install_credential_cache
from .dep_imports import AgentConfig, db_init, repo

async def _mark_call_failed(call_id: str, user_id: str, error: str) -> None:
    """Best-effort: record WHY a call failed so the UI can surface it.

    Called from the worker's failure path. The DB may not be initialized yet
    (the failure may have happened before DB init), so init on the agent loop
    with a short timeout and give up quietly if unavailable — the room is still
    cut and the job still shuts down by the caller. The reason lands in the
    call row's `usage` JSON (`{"error": ...}`), which the UI reads while the
    caller is still in the "waiting for agent" state.
    """
    if not call_id:
        return
    global _DB_INIT_DONE
    try:
        if not _DB_INIT_DONE:
            try:
                await asyncio.wait_for(db_init(), timeout=6)
                _DB_INIT_DONE = True
            except Exception as e:
                logger.warning(f"Could not init DB to mark call {call_id} failed: {e!r}")
                return
        await repo.update_call(call_id, {
            "status": "failed",
            "ended_at": time.strftime("%Y-%m-%d %H:%M"),
            "usage": {"error": (error or "unknown worker error")[:2000]},
        })
        logger.info(f"⛔ Call {call_id} marked failed with reason: {error[:300]}")
    except Exception as e:
        logger.warning(f"Could not mark call {call_id} failed in DB: {e!r}")


try:
    import google.auth.crypt._cryptography_rsa
    import google.auth._service_account_info
    import google.auth._default
    import google.oauth2.credentials
    import google.oauth2.service_account
    # Also prewarm google cloud texttospeech client to avoid TTS latency
    try:
        import google.cloud.texttospeech
        logger.info("🔧 Prewarmed google.cloud.texttospeech (reduces TTS 340-437ms)")
    except Exception:
        pass
    logger.info("🔧 Prewarmed Google auth crypt + oauth2.credentials + service_account + texttospeech (avoids 176ms and 198ms blocks, reduces TTS 340-437ms)")

    # Cache parsed credentials so the on-loop client build skips the 163ms RSA parse.
    install_credential_cache()
except Exception as e:
    logger.debug(f"Google auth prewarm failed: {e}")

# Prewarm async_toolset import
try:
    import livekit.agents.llm.async_toolset
    logger.info("🔧 Prewarmed async_toolset (avoids 101ms import block)")
except Exception as e:
    logger.debug(f"async_toolset prewarm failed: {e}")

# Prewarm tokenize and linecache to avoid 108ms tokenize.open during loop_monitor reporting
# FIX: previous code did linecache.clearcache() which *empties* the cache, forcing
# the loop monitor's report formatting (traceback.format_list -> linecache.getline
# -> updatecache -> tokenize.open) to do synchronous file I/O ON the agent event
# loop, triggering "event loop blocked for 176ms at tokenize.py:447 open".
# Proper prewarm populates cache OFF the event loop at import time, so later
# formatting hits cache and avoids tokenize.open entirely.
try:
    import linecache
    import tokenize
    import sys as _sys_lc
    # Populate cache for already-loaded modules so loop_monitor formatting
    # doesn't need to open files on the event loop
    _warmed = 0
    for _mod in list(_sys_lc.modules.values()):
        try:
            _fname = getattr(_mod, "__file__", None)
            if _fname and isinstance(_fname, str) and _fname.endswith(".py"):
                linecache.getlines(_fname)
                _warmed += 1
                if _warmed > 300:  # cap to avoid excessive startup work
                    break
        except Exception:
            continue
    # Also ensure tokenize and linecache themselves are cached
    try:
        linecache.getlines(tokenize.__file__)
        linecache.getlines(linecache.__file__)
        linecache.getlines(traceback.__file__)
    except Exception:
        pass
    logger.info(f"🔧 Prewarmed linecache/tokenize for {_warmed} files (reduces tokenize.open block during loop_monitor reporting)")
except Exception as e:
    logger.debug(f"linecache prewarm failed: {e}")

# Also patch aiohttp TCPConnector creation if needed - but http_context patch should be enough


# Task 5 (2026-09-24): make the OpenAI SDK's own retry/error telemetry visible —
# openai._base_client logs "Retrying request to /v1/chat/completions" (429/5xx
# backoff) at INFO. TTFT spikes of ~2-3.5s match 1-2 backoff retries exactly;
# without these lines we cannot distinguish provider retry from network.
try:
    import logging as _logging_oai
    _logging_oai.getLogger("openai").setLevel(_logging_oai.INFO)
    _logging_oai.getLogger("httpx").setLevel(_logging_oai.WARNING)
except Exception:
    pass

# Latency fix globals: cache DB init and agent lookup per process
_DB_INIT_DONE = False
# Preemptive gate state of the current call (set by build_assistant_session;
# read by finalize_billing's [PREEMPTIVE] summary — worker process == one call).
_PREEMPTIVE_ENABLED_FOR_LOG = False
_AGENT_CACHE: dict = {}  # key -> {"rec": ..., "ts": float}
_AGENT_CACHE_TTL = 30.0
_VAD_CACHE = None
_VAD_CACHE_LOCK = __import__('threading').Lock()

FALLBACK_REPLY = "Sorry, mujhe yeh samajh nahi aaya. Aap dobara bata sakte hain?"
# Spoken when a user turn gets NO LLM reply at all (provider 429 after the
# fail-fast retries, or a failed/empty generation) so the caller is never left
# in dead air — that silence is what made callers hang up.
DEFAULT_FALLBACK_RESPONSE = "Sorry, there is a temporary technical problem. Please try again shortly."
# Deterministic closing speech — always the same line, never LLM-generated.
# This is the fix for non-deterministic goodbyes: the closing TTS is fixed so
# every call ends with the same polite sentence in the caller's language.
DETERMINISTIC_CLOSING_MESSAGE = "Thank you for calling us. Aapse baat karke achha laga. Goodbye."
DETERMINISTIC_CLOSING_MESSAGE_EN = "Thank you for calling us. It was nice talking to you. Goodbye."

def _get_deterministic_closing(cfg: AgentConfig) -> str:
    lang = (getattr(cfg, "language", "hi") or "hi").lower()
    if lang.startswith("en"):
        return DETERMINISTIC_CLOSING_MESSAGE_EN
    return DETERMINISTIC_CLOSING_MESSAGE

# How long to wait for the LLM to answer a user turn before speaking
# FALLBACK_SILENCE. Groq's 429 backoff can be 7-45s, so 12s is a good balance:
# a normal fast turn never gets here, but a rate-limited one does.
LLM_FALLBACK_DELAY = float(os.getenv("VOICE_LLM_FALLBACK_DELAY", "8"))

BILLING_BACKEND_URL = os.getenv("BILLING_BACKEND_URL", "http://127.0.0.1:8000")
WORKER_AGENT_NAME = "voice-agent-saas"

# A call is only a real conversation if it ran for more than this many seconds
# OR the customer actually said something. Otherwise we mark it "failed".
_FAIL_THRESHOLD_SECONDS = 3


def clean_reply_text(raw: str) -> str:
    if not raw:
        return FALLBACK_REPLY
    text = raw

    # 1. Drop reasoning blocks. Qwen3/Gemini-style models wrap their chain of
    #    thought in <think>...</think> (and it is sometimes unclosed). Keep only
    #    the content AFTER the last closing tag; if there is no closing tag,
    #    strip the tags themselves.
    for tag in ("</think>", "</reasoning>"):
        if tag in text:
            text = text.split(tag)[-1]
    text = re.sub(r"</?(?:think|reasoning)>", "", text, flags=re.IGNORECASE)

    # 2. Prefer an explicitly-labelled final answer if the model emitted one.
    m = re.search(
        r"(?:Final\s+Output|Spoken\s+(?:sentence|reply|answer)|Final\s+answer|Response|Reply|Answer)"
        r"\s*:\s*[\"']?([^\n\"']+)",
        text, flags=re.IGNORECASE,
    )
    if m:
        text = m.group(1)

    # 3. Keep only lines that look like spoken content; drop reasoning/format lines.
    drop_re = re.compile(
        r"^(Here'?s a thinking|Analyze|Identify|Formulate|Draft|Check Constraints|"
        r"Key\s+(points|Details|Constraints)|Language:|Questions:|Role:|Output:|"
        r"NO\s|DO\s+NOT\s|The\s+user|I\s+should|I\s+need|I\s+will|Mental|Refine|"
        r"Self-Correction|Final\s+Polish|Wait,|Or\s+simpler|Let's\s+|Proceed|"
        r"(?:Reasoning|Thought|Step)\s*\d*\s*[:.]|^\d+\.|^[-*#•])",
        re.I,
    )
    lines = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if drop_re.match(s):
            continue
        lines.append(s)
    text = " ".join(lines).strip()
    text = re.sub(r"[*#_`~]", "", text).strip(" \n\t-\"'")
    text = re.sub(r"\s+", " ", text).strip()

    # 4. If the model is pointing back at its own reasoning, bail.
    if re.search(r"\b(thinking process|analyze user|chain of thought)\b", text, re.I):
        return FALLBACK_REPLY

    # 5. Empty or implausibly short => fallback. A bare name/entity such as
    #    "Kapil Gautam" or "2014" is a legitimate short spoken answer, so only
    #    reject text that is essentially empty (< 4 chars).
    if not text or len(text) < 4:
        return FALLBACK_REPLY
    return text


def _item_is_tool_related(item) -> bool:
    """True if this conversation item is a tool call / tool result / function
    message — i.e. NOT a spoken reply.

    These items have no speakable text; without this guard they fall through as
    "empty assistant replies" (bogus ``🗣️ TTS: Sorry...`` lines and, worse, a
    fallback line spoken right before ``end_call`` hangs up)."""
    # Depending on the LiveKit version, a tool invocation is exposed as
    # ``tool_calls`` (ChatMessage), ``function_call`` or ``tool_call``.  In
    # particular, an assistant item can have *no text* and still be a perfectly
    # valid tool-call item.  Treat all of these as non-spoken items before the
    # empty-text handling below.
    for attr in ("function_call", "function_call_output", "tool_call", "tool_calls"):
        value = getattr(item, attr, None)
        if value:
            return True
    if getattr(item, "role", None) == "tool":
        return True
    # Some SDK releases put the calls in ``content`` as typed objects, while
    # others use a dict. Neither form is speakable.
    if isinstance(getattr(item, "content", None), dict):
        return True
    content = getattr(item, "content", None)
    # A text message's content is strings; a function message carries objects.
    if isinstance(content, list) and any(not isinstance(c, str) for c in content):
        return True
    return False


def _msg_text(item) -> str:
    """Extract display text from a v1 ``ChatMessage`` (or any object with
    ``text_content``), falling back to plain strings."""
    if item is None:
        return ""
    if hasattr(item, "text_content"):
        txt = item.text_content
        if txt:
            return str(txt)
        txt = item.raw_text_content
        if txt:
            return str(txt)
        content = getattr(item, "content", None)
        if isinstance(content, list):
            return " ".join(str(c) for c in content if isinstance(c, str))
        return ""
    if isinstance(item, str):
        return item
    return str(item)


# ---------------------------------------------------------------------------
# Session builders (assistant vs announcement "fixed-script" mode)
# ---------------------------------------------------------------------------
