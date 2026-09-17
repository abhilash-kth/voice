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
from __future__ import annotations

import os
import re
import sys
import asyncio
import logging
import time
import json
import aiohttp
from typing import Optional

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

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

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

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("voice-agent-saas-worker")

# Latency fix globals: cache DB init and agent lookup per process
_DB_INIT_DONE = False
_AGENT_CACHE: dict = {}  # key -> {"rec": ..., "ts": float}
_AGENT_CACHE_TTL = 30.0

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
    # STT/TTS also get their own bound so a provider hiccup never stacks.
    _media_conn = APIConnectOptions(max_retry=1, retry_interval=0.5, timeout=6.0)
    return SessionConnectOptions(
        llm_conn_options=_conn,
        stt_conn_options=_media_conn,
        tts_conn_options=_media_conn,
    )


def _create_tts_timing_wrapper(tts_instance, timing_dict):
    """Wrap TTS instance to measure actual TTS pipeline timing.
    
    Measures REAL pipeline (not LLM completion):
    - tts_request: when text first sent to TTS (first chunk)
    - first_tts_audio: when first audio chunk returned from TTS (REAL)
    - first_audio: first audible audio (REAL, set by wrapper)
    - speech_end->first_audio: REAL total latency (target ~1-1.5s)
    - Works with any TTS provider (Google, ElevenLabs, OpenRouter) - no hardcoding
    - Verified preemptive_tts compatibility: wrapper preserves streaming interface
    """
    original_synthesize = getattr(tts_instance, 'synthesize', None)

    class TTSTimingWrapper:
        def __init__(self, inner, timing):
            self._inner = inner
            self._timing = timing
            try:
                self.capabilities = getattr(inner, 'capabilities', None)
                self._opts = getattr(inner, '_opts', None)
                self._label = getattr(inner, '_label', None)
            except Exception:
                pass

        def __getattr__(self, name):
            return getattr(self._inner, name)

        async def synthesize(self, text, **kwargs):
            now = time.time()
            if self._timing.get("first_token", 0) > 0 and self._timing.get("tts_request", 0) == 0:
                self._timing["tts_request"] = now
                first_token = self._timing.get("first_token", 0)
                if first_token > 0:
                    logger.info(f"⏱️ TIMING first_token->tts_request (text_chunk→TTS): {(now-first_token)*1000:.0f}ms (text: {text[:50]})")
                if self._timing.get("llm_start", 0) > 0:
                    logger.info(f"⏱️ TIMING llm_start->tts_request: {(now-self._timing['llm_start'])*1000:.0f}ms")
            first_chunk = True
            try:
                async for chunk in self._inner.synthesize(text, **kwargs):
                    if first_chunk:
                        now_audio = time.time()
                        if self._timing.get("first_tts_audio", 0) == 0:
                            self._timing["first_tts_audio"] = now_audio
                            if self._timing.get("tts_request", 0) > 0:
                                logger.info(f"⏱️ TIMING tts_request->first_tts_audio (TTS synthesis): {(now_audio-self._timing['tts_request'])*1000:.0f}ms")
                            if self._timing.get("first_token", 0) > 0:
                                logger.info(f"⏱️ TIMING first_token->first_tts_audio (REAL TTS): {(now_audio-self._timing['first_token'])*1000:.0f}ms")
                                if self._timing.get("first_audio", 0) == 0:
                                    self._timing["first_audio"] = now_audio
                                    logger.info(f"⏱️ TIMING first_token->first_audio (REAL TTS audio): {(now_audio-self._timing['first_token'])*1000:.0f}ms")
                                if self._timing.get("speech_end", 0) > 0:
                                    total = (now_audio-self._timing['speech_end'])*1000
                                    logger.info(f"⏱️ TIMING speech_end->first_audio (REAL total): {total:.0f}ms (target ~1-1.5s)")
                                    self._timing["last_speech_end_to_first_audio"] = total
                                    # Full breakdown with REAL TTS
                                    if self._timing.get("stt_final",0) and self._timing.get("turn_detected",0) and self._timing.get("llm_start",0) and self._timing.get("first_token",0):
                                        logger.info(
                                            f"📊 TURN BREAKDOWN (REAL): speech_end->STT_final {(self._timing['stt_final']-self._timing['speech_end'])*1000:.0f}ms | "
                                            f"STT_final->turn {(self._timing['turn_detected']-self._timing['stt_final'])*1000:.0f}ms | "
                                            f"turn->LLM {(self._timing['llm_start']-self._timing['turn_detected'])*1000:.0f}ms | "
                                            f"LLM->first_token {(self._timing['first_token']-self._timing['llm_start'])*1000:.0f}ms | "
                                            f"first_token->tts_request {(self._timing.get('tts_request',0)-self._timing['first_token'])*1000:.0f}ms | "
                                            f"tts_request->first_audio {(now_audio-self._timing.get('tts_request',now_audio))*1000:.0f}ms | "
                                            f"TOTAL {total:.0f}ms"
                                        )
                                    # Reset for next turn after REAL audio
                                    self._timing["speech_end"] = 0.0
                                    self._timing["stt_final"] = 0.0
                                    self._timing["turn_detected"] = 0.0
                                    self._timing["llm_start"] = 0.0
                                    self._timing["first_token"] = 0.0
                                    self._timing["tts_request"] = 0.0
                                    self._timing["first_tts_audio"] = 0.0
                                    self._timing["llm_complete"] = 0.0
                                    self._timing["first_audio"] = 0.0
                        first_chunk = False
                    yield chunk
            except Exception as e:
                logger.warning(f"TTS synthesize wrapper error: {e}")
                raise

        def stream(self, **kwargs):
            inner_stream = self._inner.stream(**kwargs)
            timing = self._timing

            class StreamWrapper:
                def __init__(self, inner_stream, timing):
                    self._inner_stream = inner_stream
                    self._timing = timing
                    self._first_chunk = True

                def __getattr__(self, name):
                    return getattr(self._inner_stream, name)

                async def __aenter__(self):
                    await self._inner_stream.__aenter__()
                    return self

                async def __aexit__(self, *args):
                    return await self._inner_stream.__aexit__(*args)

                def push_text(self, text):
                    now = time.time()
                    if timing.get("first_token", 0) > 0 and timing.get("tts_request", 0) == 0 and text and text.strip():
                        timing["tts_request"] = now
                        logger.info(f"⏱️ TIMING first_token->tts_request (stream push): {(now-timing['first_token'])*1000:.0f}ms (chunk: {text[:50]})")
                    return self._inner_stream.push_text(text)

                async def __aiter__(self):
                    async for chunk in self._inner_stream:
                        if self._first_chunk:
                            now_audio = time.time()
                            if timing.get("first_tts_audio", 0) == 0:
                                timing["first_tts_audio"] = now_audio
                                if timing.get("tts_request", 0) > 0:
                                    logger.info(f"⏱️ TIMING tts_request->first_tts_audio (stream): {(now_audio-timing['tts_request'])*1000:.0f}ms")
                                if timing.get("first_token", 0) > 0:
                                    logger.info(f"⏱️ TIMING first_token->first_tts_audio (REAL stream): {(now_audio-timing['first_token'])*1000:.0f}ms")
                                    if timing.get("first_audio", 0) == 0:
                                        timing["first_audio"] = now_audio
                                        logger.info(f"⏱️ TIMING first_token->first_audio (REAL stream audio): {(now_audio-timing['first_token'])*1000:.0f}ms")
                                    if timing.get("speech_end", 0) > 0:
                                        total = (now_audio-timing['speech_end'])*1000
                                        logger.info(f"⏱️ TIMING speech_end->first_audio (REAL stream total): {total:.0f}ms")
                                        timing["last_speech_end_to_first_audio"] = total
                                        if timing.get("stt_final",0) and timing.get("turn_detected",0) and timing.get("llm_start",0) and timing.get("first_token",0):
                                            logger.info(
                                                f"📊 TURN BREAKDOWN (REAL stream): speech_end->STT_final {(timing['stt_final']-timing['speech_end'])*1000:.0f}ms | "
                                                f"STT_final->turn {(timing['turn_detected']-timing['stt_final'])*1000:.0f}ms | "
                                                f"turn->LLM {(timing['llm_start']-timing['turn_detected'])*1000:.0f}ms | "
                                                f"LLM->first_token {(timing['first_token']-timing['llm_start'])*1000:.0f}ms | "
                                                f"first_token->tts_request {(timing.get('tts_request',0)-timing['first_token'])*1000:.0f}ms | "
                                                f"tts_request->first_audio {(now_audio-timing.get('tts_request',now_audio))*1000:.0f}ms | "
                                                f"TOTAL {total:.0f}ms"
                                            )
                                        timing["speech_end"] = 0.0
                                        timing["stt_final"] = 0.0
                                        timing["turn_detected"] = 0.0
                                        timing["llm_start"] = 0.0
                                        timing["first_token"] = 0.0
                                        timing["tts_request"] = 0.0
                                        timing["first_tts_audio"] = 0.0
                                        timing["llm_complete"] = 0.0
                                        timing["first_audio"] = 0.0
                            self._first_chunk = False
                        yield chunk

                async def aclose(self):
                    try:
                        return await self._inner_stream.aclose()
                    except Exception:
                        pass

                def close(self):
                    try:
                        return self._inner_stream.close()
                    except Exception:
                        pass

            return StreamWrapper(inner_stream, timing)

    return TTSTimingWrapper(tts_instance, timing_dict)



def _create_llm_timing_wrapper(llm_instance, timing_dict, provider_info=None):
    """Fixed LLM timing wrapper that properly implements async context manager protocol.
    
    LiveKit's LLM.chat returns an async context manager (LLMStream), used as:
        async with llm.chat(chat_ctx=...) as stream:
            async for chunk in stream:
    
    Previous buggy version made chat async def returning StreamWrapper directly,
    causing TypeError: 'coroutine' object does not support async context manager.
    
    Fixed version: chat is sync def returning a custom async CM that wraps inner CM,
    and whose __aenter__ returns a TimingStreamWrapper that measures TTFT.
    """
    import asyncio as _asyncio
    import time as _time
    import logging as _logging
    _logger = _logging.getLogger("voice-agent-saas-worker")

    try:
        is_fallback = hasattr(llm_instance, '_llm_instances') or hasattr(llm_instance, 'llm_instances') or 'FallbackAdapter' in str(type(llm_instance))
        if is_fallback:
            inner_list = getattr(llm_instance, '_llm_instances', None) or getattr(llm_instance, 'llm_instances', None) or getattr(llm_instance, '_instances', None)
            if inner_list:
                _logger.info(f"LLM timing wrapper: FallbackAdapter with {len(inner_list)} providers - TTFT tracking enabled (fixed CM protocol)")
                for idx, inner_llm in enumerate(inner_list):
                    # Avoid infinite recursion: only wrap if not already wrapped
                    if 'LLMTimingWrapper' not in str(type(inner_llm)):
                        inner_list[idx] = _create_llm_timing_wrapper(inner_llm, timing_dict, provider_info)
                return llm_instance
    except Exception as e:
        _logger.debug(f"Could not wrap FallbackAdapter inner LLMs: {e}")

    original_chat = getattr(llm_instance, 'chat', None)
    if not original_chat:
        return llm_instance

    class TimingStreamWrapper:
        """Wraps LLMStream to measure first_token TTFT and generation_complete."""
        def __init__(self, inner_stream, timing, prov_info, req_start):
            self._inner_stream = inner_stream
            self._timing = timing
            self._prov_info = prov_info
            self._req_start = req_start
            self._first_token = True
            self._input_tokens = 0
            self._output_tokens = 0
            self._cached_tokens = 0

        def __getattr__(self, name):
            return getattr(self._inner_stream, name)

        async def __aiter__(self):
            try:
                async for chunk in self._inner_stream:
                    now = _time.time()
                    if self._first_token:
                        self._first_token = False
                        first_token = now
                        self._timing["first_token"] = first_token
                        ttft = (first_token - self._req_start) * 1000
                        self._timing["ttft_ms"] = ttft
                        prov = self._prov_info.get('provider', '') or self._timing.get('llm_provider', 'unknown')
                        model = self._prov_info.get('model_id', '') or self._timing.get('llm_model', 'unknown')
                        _logger.info(f"LLM TTFT provider={prov} model={model} TTFT={ttft:.0f}ms (first_token - request_start)")
                        if self._timing.get("llm_start", 0) > 0:
                            _logger.info(f"TIMING LLM_start->first_token: {(first_token-self._timing['llm_start'])*1000:.0f}ms (TTFT)")
                        if self._timing.get("speech_end", 0) > 0:
                            _logger.info(f"TIMING speech_end->first_token: {(first_token-self._timing['speech_end'])*1000:.0f}ms")
                    try:
                        usage = getattr(chunk, 'usage', None)
                        if usage:
                            self._input_tokens = getattr(usage, 'prompt_tokens', 0) or getattr(usage, 'input_tokens', 0) or self._input_tokens
                            self._output_tokens = getattr(usage, 'completion_tokens', 0) or getattr(usage, 'output_tokens', 0) or self._output_tokens
                            prompt_details = getattr(usage, 'prompt_tokens_details', None)
                            if prompt_details:
                                self._cached_tokens = getattr(prompt_details, 'cached_tokens', 0) or 0
                    except Exception:
                        pass
                    yield chunk
            finally:
                gen_complete = _time.time()
                self._timing["generation_complete"] = gen_complete
                self._timing["llm_complete"] = gen_complete
                gen_time = (gen_complete - self._req_start) * 1000
                self._timing["generation_time_ms"] = gen_time
                self._timing["input_tokens"] = self._input_tokens
                self._timing["output_tokens"] = self._output_tokens
                self._timing["cached_input_tokens"] = self._cached_tokens
                prov = self._prov_info.get('provider', '') or self._timing.get('llm_provider', 'unknown')
                model = self._prov_info.get('model_id', '') or self._timing.get('llm_model', 'unknown')
                _logger.info(f"LLM GENERATION COMPLETE provider={prov} model={model} generation_time={gen_time:.0f}ms input={self._input_tokens} cached={self._cached_tokens} output={self._output_tokens}")
                try:
                    from app.llm_catalog import get_llm_model, calculate_llm_cost
                    model_meta = get_llm_model(prov, model) if prov and model else None
                    if model_meta:
                        costs = calculate_llm_cost(model_meta, self._input_tokens, self._cached_tokens, self._output_tokens)
                        _logger.info(f"LLM COST provider={prov} model={model} input={self._input_tokens} cached={self._cached_tokens} output={self._output_tokens} input_cost=${costs['input_cost']:.6f} output_cost=${costs['output_cost']:.6f} total=${costs['total_llm_cost']:.6f} TTFT={self._timing.get('ttft_ms',0):.0f}ms gen_time={gen_time:.0f}ms")
                except Exception as e:
                    _logger.debug(f"Could not calculate LLM cost: {e}")

    class TimingChatCM:
        """Async context manager that wraps inner LLM chat CM and returns TimingStreamWrapper."""
        def __init__(self, inner_cm_or_coro, timing, prov_info, req_start):
            self._inner_orig = inner_cm_or_coro
            self._timing = timing
            self._prov_info = prov_info
            self._req_start = req_start
            self._inner_cm = None
            self._inner_stream = None

        async def __aenter__(self):
            # Resolve inner if it's a coroutine (some LLM impls have async chat)
            inner = self._inner_orig
            if _asyncio.iscoroutine(inner):
                inner = await inner
            self._inner_cm = inner
            # Enter inner CM
            if hasattr(inner, '__aenter__'):
                stream = await inner.__aenter__()
            else:
                stream = inner
            self._inner_stream = stream
            return TimingStreamWrapper(stream, self._timing, self._prov_info, self._req_start)

        async def __aexit__(self, exc_type, exc, tb):
            try:
                if self._inner_cm and hasattr(self._inner_cm, '__aexit__'):
                    return await self._inner_cm.__aexit__(exc_type, exc, tb)
            except Exception as e:
                _logger.debug(f"Error in inner CM __aexit__: {e}")
            return False

    class LLMTimingWrapper:
        def __init__(self, inner, timing, prov_info):
            self._inner = inner
            self._timing = timing
            self._prov_info = prov_info or {}
            try:
                self._model = getattr(inner, '_model', None) or getattr(inner, 'model', None) or prov_info.get('model_id', '') if prov_info else ''
                self._label = getattr(inner, '_label', None) or getattr(inner, 'label', None)
            except Exception:
                self._model = prov_info.get('model_id', '') if prov_info else ''
                self._label = None

        def __getattr__(self, name):
            # Delegate everything except chat
            if name == 'chat':
                return self.chat
            return getattr(self._inner, name)

        def chat(self, *args, **kwargs):
            # This is the critical fix: chat is SYNC, returns async CM, not coroutine
            # So `async with llm.chat(...) as stream` works
            request_start = _time.time()
            self._timing["request_start"] = request_start
            self._timing["llm_start"] = request_start
            prov = self._prov_info.get('provider', '') or self._timing.get('llm_provider', '') or 'unknown'
            model = self._prov_info.get('model_id', '') or self._timing.get('llm_model', '') or getattr(self._inner, 'model', 'unknown') or 'unknown'
            base_url = self._prov_info.get('base_url', '') or 'https://api.openai.com/v1'
            _logger.info(f"LLM REQUEST START provider={prov} model={model} base_url={base_url} request_start={request_start}")
            try:
                inner_result = self._inner.chat(*args, **kwargs)
                # inner_result may be coroutine or CM - handle both in TimingChatCM
                return TimingChatCM(inner_result, self._timing, self._prov_info, request_start)
            except Exception as e:
                error_time = _time.time()
                prov = self._prov_info.get('provider', '') or 'unknown'
                model = self._prov_info.get('model_id', '') or 'unknown'
                base_url = self._prov_info.get('base_url', '') or 'unknown'
                _logger.error(f"LLM API ERROR provider={prov} model={model} base_url={base_url} Error={e} Type={type(e).__name__} After {(error_time-request_start)*1000:.0f}ms")
                import traceback
                _logger.error(f"Full traceback: {traceback.format_exc()}")
                raise

    return LLMTimingWrapper(llm_instance, timing_dict, provider_info)


def _create_llm_failure_logging_wrapper(llm_instance, cfg):
    """Wrap LLM to log failures with provider/model/base_url for 404 debugging.
    
    Logs explicit provider/model/base_url when LLM fails, to debug 404 like:
    - openai_gpt_4_1_mini gpt-4.1-mini @ https://api.openai.com/v1 404
    - groq_gpt_oss openai/gpt-oss-120b @ https://api.groq.com/openai/v1 404
    """
    # For FallbackAdapter, wrap inner instances
    try:
        is_fallback = hasattr(llm_instance, '_llm_instances') or hasattr(llm_instance, 'llm_instances') or 'FallbackAdapter' in str(type(llm_instance))
        if is_fallback:
            inner_list = getattr(llm_instance, '_llm_instances', None) or getattr(llm_instance, 'llm_instances', None) or getattr(llm_instance, '_instances', None)
            if inner_list:
                # Log fallback chain
                import logging
                logger = logging.getLogger("voice-agent-saas-worker")
                logger.info(f"🔍 LLM FallbackAdapter with {len(inner_list)} providers - failure logging enabled")
                # We don't wrap inner here, rely on LiveKit's own logging which already logs "LLM failed, switching to next LLM"
                # But we add outer wrapper to log final failure
        # For single LLM, we could wrap chat method, but LiveKit's LLM is complex (streaming)
        # So we just return as-is and rely on enhanced logging in agent_builder
    except Exception as e:
        import logging
        logging.getLogger("voice-agent-saas-worker").debug(f"Could not create LLM failure wrapper: {e}")
    return llm_instance


async def build_assistant_session(cfg: AgentConfig, turn_timing_ref=None):
    """Full conversational session: STT + VAD + LLM + TTS, production low-latency.

    Fixes:
    - Async parallel build to avoid blocking job executor (was 3.46s sync -> unresponsive 1.5s)
    - STT turn_detection with endpointing_ms 200ms + utterance_end_ms 1000ms (Deepgram correct params)
    - VAD tuned 0.20/0.30/0.20/0.55 for faster speech_end detection + less CPU
    - Endpointing 0.20/0.55 for target speech_end->LLM <=500ms
    - TTS timing wrapper to measure actual first TTS audio (not LLM completion)
    """
    from livekit.agents import AgentSession
    from app.agents.agent_builder import build_vad, build_stt, build_llm, build_tts

    vad_inst = build_vad()
    build_t0 = time.time()

    try:
        stt_inst, llm_inst, tts_inst = await asyncio.gather(
            asyncio.to_thread(build_stt, cfg),
            asyncio.to_thread(build_llm, cfg),
            asyncio.to_thread(build_tts, cfg),
        )
        logger.info(f"⏱️ provider build async parallel {time.time()-build_t0:.2f}s")
        # Log LLM provider details for 404 debugging and wrap with timing + failure logging
        try:
            llm_type = str(type(llm_inst))
            if "FallbackAdapter" in llm_type:
                logger.info(f"🤖 LLM FallbackAdapter built: {llm_type}")
                inner = getattr(llm_inst, '_llm_instances', None) or getattr(llm_inst, 'llm_instances', None) or getattr(llm_inst, '_instances', None)
                if inner:
                    logger.info(f"🤖 LLM fallback chain length: {len(inner)}")
            else:
                logger.info(f"🤖 LLM single provider built: {llm_type}")
            
            # Set provider/model in timing_dict for cost tracking and wrap with timing
            if turn_timing_ref is not None:
                try:
                    primary = cfg.providers.get_primary_llm() if hasattr(cfg.providers, 'get_primary_llm') else cfg.providers.llm
                    prov, model, base_url = primary.resolve_llm_provider_model()
                    turn_timing_ref["llm_provider"] = prov
                    turn_timing_ref["llm_model"] = model
                    provider_info = {"provider": prov, "model_id": model, "base_url": base_url or "https://api.openai.com/v1"}
                    llm_inst = _create_llm_timing_wrapper(llm_inst, turn_timing_ref, provider_info)
                    logger.info(f"🔧 LLM timing wrapper applied: provider={prov} model={model} base_url={base_url} (TTFT + cost tracking)")
                except Exception as e:
                    logger.warning(f"Could not apply LLM timing wrapper: {e}, using failure wrapper")
                    llm_inst = _create_llm_failure_logging_wrapper(llm_inst, cfg)
            else:
                llm_inst = _create_llm_failure_logging_wrapper(llm_inst, cfg)
        except Exception as e:
            logger.debug(f"Could not log LLM details: {e}")
    except Exception as e:
        logger.warning(f"Async parallel build failed ({e}), falling back to sync")
        stt_inst = build_stt(cfg)
        llm_inst = build_llm(cfg)
        tts_inst = build_tts(cfg)
        if turn_timing_ref is not None:
            try:
                primary = cfg.providers.get_primary_llm() if hasattr(cfg.providers, 'get_primary_llm') else cfg.providers.llm
                prov, model, base_url = primary.resolve_llm_provider_model()
                turn_timing_ref["llm_provider"] = prov
                turn_timing_ref["llm_model"] = model
                provider_info = {"provider": prov, "model_id": model, "base_url": base_url or "https://api.openai.com/v1"}
                llm_inst = _create_llm_timing_wrapper(llm_inst, turn_timing_ref, provider_info)
                logger.info(f"🔧 LLM timing wrapper applied (sync fallback): provider={prov} model={model}")
            except Exception as e:
                logger.warning(f"Could not apply LLM timing wrapper sync: {e}")
                llm_inst = _create_llm_failure_logging_wrapper(llm_inst, cfg)
        else:
            llm_inst = _create_llm_failure_logging_wrapper(llm_inst, cfg)
        logger.info(f"⏱️ provider build sync fallback {time.time()-build_t0:.2f}s")

    # Wrap TTS with timing instrumentation if timing ref provided - works with any provider
    if turn_timing_ref is not None:
        try:
            is_fallback = hasattr(tts_inst, '_tts_instances') or hasattr(tts_inst, 'tts_instances') or 'FallbackAdapter' in str(type(tts_inst))
            if is_fallback:
                try:
                    inner_list = getattr(tts_inst, '_tts_instances', None) or getattr(tts_inst, 'tts_instances', None) or getattr(tts_inst, '_instances', None)
                    if inner_list:
                        for idx, inner_tts in enumerate(inner_list):
                            inner_list[idx] = _create_tts_timing_wrapper(inner_tts, turn_timing_ref)
                        logger.info(f"🔧 TTS timing wrapper applied to FallbackAdapter ({len(inner_list)} providers)")
                    else:
                        tts_inst = _create_tts_timing_wrapper(tts_inst, turn_timing_ref)
                except Exception as e:
                    logger.warning(f"Could not wrap FallbackAdapter inner TTS: {e}, wrapping outer")
                    tts_inst = _create_tts_timing_wrapper(tts_inst, turn_timing_ref)
            else:
                tts_inst = _create_tts_timing_wrapper(tts_inst, turn_timing_ref)
                logger.info(f"🔧 TTS timing wrapper applied")
        except Exception as e:
            logger.warning(f"Could not apply TTS timing wrapper: {e}")

    min_delay = float(os.getenv("VOICE_ENDPOINTING_MIN", "0.20"))
    max_delay = float(os.getenv("VOICE_ENDPOINTING_MAX", "0.55"))
    turn_detection_mode = os.getenv("VOICE_TURN_DETECTION", "stt").strip().lower()
    if turn_detection_mode not in ("vad", "stt", "realtime_llm", "manual"):
        turn_detection_mode = "stt"

    # Preemptive TTS: check compatibility - all supported TTS (Google, ElevenLabs, OpenRouter) support streaming
    # So preemptive_tts is safe, but keep env-controlled to avoid unexpected behavior
    # Default 0 for compatibility, enable via VOICE_PREEMPTIVE_TTS=1 if needed
    # FIXED: Log preemptive_tts compatibility and verify wrapper works with it
    preemptive_tts_enabled = os.getenv("VOICE_PREEMPTIVE_TTS", "0") == "1"
    preemptive_enabled = os.getenv("VOICE_PREEMPTIVE", "1") == "1"
    logger.info(f"🔧 Session config: preemptive={preemptive_enabled}, preemptive_tts={preemptive_tts_enabled}, turn_detection={turn_detection_mode}, endpointing={min_delay}/{max_delay} (TTS wrapper compatible: yes, all providers support streaming)")

    return AgentSession(
        stt=stt_inst,
        vad=vad_inst,
        llm=llm_inst,
        tts=tts_inst,
        conn_options=_build_conn_options(),
        turn_handling={
            "turn_detection": turn_detection_mode,
            "endpointing": {"min_delay": min_delay, "max_delay": max_delay},
            "interruption": {"enabled": True, "mode": "vad", "min_duration": 0.25, "min_words": 1},
            "preemptive_generation": {
                "enabled": os.getenv("VOICE_PREEMPTIVE", "1") == "1",
                "preemptive_tts": preemptive_tts_enabled,
            },
        },
    )


def build_announcement_session(cfg: AgentConfig):
    """Fixed-script "reminder" session: TTS only. No STT, no VAD, no LLM."""
    from livekit.agents import AgentSession
    from app.agents.agent_builder import build_tts

    return AgentSession(
        stt=None,
        vad=None,
        llm=None,
        tts=build_tts(cfg),
        conn_options=_build_conn_options(),
        turn_handling={
            "endpointing": {"min_delay": 0.2, "max_delay": 0.5},
            "interruption": {"enabled": False},          # the script must not be cut off
            "preemptive_generation": {"enabled": False},
        },
    )


# ---------------------------------------------------------------------------
# Recording (LiveKit Egress) — best-effort, only if enabled
# ---------------------------------------------------------------------------
async def start_egress(room: str) -> Optional[str]:
    """Start a room-composite egress for `room`, return a public recording URL
    (or None if egress isn't configured). Requires the livekit-egress service."""
    if not EGRESS_ENABLED:
        return None
    if not (EGRESS_S3_BUCKET and EGRESS_PUBLIC_BASE_URL):
        logger.info("🎙️ Recording enabled but Egress storage not configured — skipping.")
        return None
    try:
        from livekit import api

        client = api.LiveKitAPI(LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
        try:
            req = api.RoomCompositeEgressRequest(
                room_name=room,
                layout="speaker",
                audio_only=True,
                file_outputs=[api.EncodedFileOutput(
                    file_type=api.EncodedFileType.MP4,
                    filepath=f"recordings/{room}-{int(time.time())}.mp4",
                    s3=api.S3Upload(
                        access_key=os.getenv("EGRESS_S3_ACCESS_KEY", ""),
                        secret=os.getenv("EGRESS_S3_SECRET", ""),
                        bucket=EGRESS_S3_BUCKET,
                        endpoint=EGRESS_S3_ENDPOINT or None,
                        region=EGRESS_S3_REGION,
                    ),
                )],
            )
            res = await client.egress.start_room_composite_egress(req)
            egress_id = getattr(res, "egress_id", "")
            file_results = list(getattr(res, "file_results", []) or [])
            filename = file_results[0].filename if file_results else f"recordings/{room}.mp4"
            logger.info(f"🎙️ Egress started: {egress_id} (status={res.status}) → {filename}")
            return f"{EGRESS_PUBLIC_BASE_URL.rstrip('/')}/{filename}"
        finally:
            await client.aclose()
    except Exception as e:
        logger.warning(f"⚠️ Could not start egress: {e}")
        return None


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
async def entrypoint(ctx):
    from livekit.agents import AgentSession
    from app.agents.agent_builder import (
        build_vad,
        build_stt,
        build_llm,
        build_tts,
        build_voice_agent,
        build_announce_agent,
    )

    call_start = time.time()

    # --- Latency fix: DB init was 2.33s per job + 1.13s lookup + 8.62s None->listening
    # Previous log: job request 10.184 -> DB init 2.33s (12.845) -> lookup 1.13s (13.978) -> provider build 4.37s (18.350) -> listening 8.62s (23.648)
    # Total 13.5s before user hears greeting. Fix: cache DB init per process, parallel provider build.
    global _DB_INIT_DONE, _AGENT_CACHE
    db_t0 = time.time()
    if not _DB_INIT_DONE:
        try:
            await asyncio.wait_for(db_init(), timeout=5)
            _DB_INIT_DONE = True
            logger.info(f"⏱️ DB init {time.time()-db_t0:.2f}s (first time, cached for next calls)")
        except Exception as exc:
            logger.error("database initialization unavailable (%.2fs); continuing voice call: %s", time.time()-db_t0, exc)
    else:
        logger.info(f"⏱️ DB init 0.00s (cached)")

    # Agent lookup cache (in-memory, 30s TTL) to avoid 1.13s DB hit per call

    try:
        meta = json.loads(ctx.job.metadata or "{}")
    except Exception:
        meta = {}
    agent_id = meta.get("agent_id")
    mode = meta.get("mode", "browser")
    phone = meta.get("phone")
    call_id = meta.get("call_id", "")
    user_id = meta.get("user_id", "")
    # Per-lead data for dynamic scripts (bulk-call campaigns). Every lead's columns
    # can be referenced in the greeting/announcement text as {column_name}.
    lead_data = meta.get("lead_data") or {}

    rec = None
    cache_key = f"{agent_id}:{user_id}"
    cache_entry = _AGENT_CACHE.get(cache_key) if agent_id and user_id else None
    if cache_entry and (time.time() - cache_entry["ts"]) < _AGENT_CACHE_TTL:
        rec = cache_entry["rec"]
        logger.info(f"⏱️ agent lookup 0.00s (cached, age {time.time()-cache_entry['ts']:.1f}s)")
    elif agent_id and user_id:
        lookup_t0 = time.time()
        for attempt in range(2):  # Reduced from 3 to 2 attempts for faster fail
            try:
                rec = await asyncio.wait_for(repo.get_agent(agent_id, user_id), timeout=3)  # 3s instead of 4s
                logger.info(f"⏱️ agent lookup ok attempt {attempt+1} in {time.time()-lookup_t0:.2f}s")
                _AGENT_CACHE[cache_key] = {"rec": rec, "ts": time.time()}
                break
            except Exception as exc:
                logger.warning("agent lookup attempt %s/2 failed (%.2fs): %s", attempt + 1, time.time()-lookup_t0, exc)
                if attempt < 1:
                    await asyncio.sleep(0.15)

    if rec is None:
        # fall back to the default demo agent so the worker never crashes
        from app.sample import default_config
        cfg = default_config()
        agent_id = agent_id or "demo"
    else:
        cfg = AgentConfig(**rec)

    logger.info(f"📞 agent={cfg.name} mode={mode} phone={phone} call={call_id}")

    # Ensure the call record exists / is in-progress.
    call_record = None
    if call_id and user_id:
        call_record = await repo.get_call(call_id, user_id)
    if call_record is None:
        call_record = await repo.create_call({
            "user_id": user_id or "demo",
            "agent_id": agent_id or "demo",
            "mode": mode,
            "phone": phone or None,
            "room": ctx.room.name,
            "status": "in-progress",
            "started_at": time.strftime("%Y-%m-%d %H:%M"),
        })
    else:
        await repo.update_call(call_record["id"], {"status": "in-progress", "room": ctx.room.name})

    usage = {"tts_chars": 0, "llm_input_tokens": 0, "llm_output_tokens": 0,
             "user_speech_seconds": 0.0, "transcripts": []}

    # Dedupe identical user transcripts (STT can emit the same phrase twice) and
    # track how long the agent stays in each state so we can flag slow turns.
    last_user_transcript = {"text": "", "ts": 0.0}
    state_tracker = {"state": None, "since": time.time()}

    # Cross-call memory (ONLY if the agent enabled it).
    # Cross-call memory key. SIP calls are keyed by the phone number (the person's
    # real identity). Browser calls have no phone, so key them by the logged-in
    # user + agent — otherwise a brand-new randomised room name per call means the
    # agent NEVER remembers a browser caller between calls.
    if phone:
        customer_key = phone
    elif user_id:
        customer_key = f"user:{user_id}:{agent_id}"
    else:
        customer_key = ctx.room.name
    memory_enabled = bool(getattr(cfg, "memory_enabled", True))
    prior_memory = memory.load(customer_key) if memory_enabled else ""

    greeting = cfg.greeting or f"Namaste! Main {cfg.name} hoon. Aap kaise madad kar sakta hoon?"
    # Dynamic script: substitute {column} placeholders with this lead's values
    # (used by bulk-call campaigns so every call is personalized).
    greeting = leadfile.render_template(greeting, lead_data)

    # --- Production timing instrumentation for latency tracing - V2 with TTFT and generation time ---
    # Track complete path: user stops speaking -> STT final -> turn detection -> LLM request
    # These timestamps are per-turn, reset on each user turn
    # V2: Added request_start, first_token, generation_complete for TTFT and generation_time
    # Also logs provider, model, input_tokens, cached_input_tokens, output_tokens, costs
    turn_timing = {
        "speech_end": 0.0,
        "stt_final": 0.0,
        "turn_detected": 0.0,
        "llm_start": 0.0,
        "request_start": 0.0,
        "first_token": 0.0,
        "tts_request": 0.0,
        "first_tts_audio": 0.0,
        "llm_complete": 0.0,
        "generation_complete": 0.0,
        "first_audio": 0.0,
        "last_speech_end_to_first_audio": 0.0,
        "llm_provider": "",
        "llm_model": "",
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "output_tokens": 0,
        "ttft_ms": 0.0,
        "generation_time_ms": 0.0,
    }

    # ------------------------------------------------------------------
    # Mode: assistant (STT+LLM+TTS) vs announcement (fixed script only).
    # ------------------------------------------------------------------
    agent_mode = getattr(cfg, "agent_mode", "assistant") or "assistant"
    if agent_mode == "announcement":
        session = build_announcement_session(cfg)
    else:
        # Async build to avoid blocking job executor (was 3.46s sync -> unresponsive)
        # Pass turn_timing_ref to enable TTS timing wrapper (measures real TTS audio)
        session = await build_assistant_session(cfg, turn_timing_ref=turn_timing)

    # ------------------------------------------------------------------
    # Silence watchdog + No-response watchdog.
    #
    # 1) LLM silence: When the LLM 429s (Groq free-tier TPM limit) the fail-fast
    #    retry budget gives up in <1s and LiveKit logs the error but speaks
    #    NOTHING — caller left in dead air. So arm timer on every user turn,
    #    if no assistant reply within LLM_FALLBACK_DELAY, speak fallback.
    # 2) User silence: If user says nothing for no_response_timeout_seconds
    #    (configurable per agent, e.g. 30 sec), speak the agent's
    #    no_response_message and hang up. Requested by user.
    # ------------------------------------------------------------------
    call_closed = {"done": False}
    closing_requested = {"done": False}
    closing_in_progress = {"done": False}
    closing_task_ref = {"task": None}
    agent_holder = {"agent": None}
    reply_tracker = {
        "last_user_ts": 0.0,
        "last_assistant_ts": 0.0,
        "empty_spoken": False,
        "pending": None,
        "fallback_say": None,
    }
    # No-response tracking: last time user spoke or agent spoke
    no_response_state = {
        "last_activity": time.time(),
        "task": None,
        "triggered": False,
    }

    async def _do_deterministic_closing():
        # Prevent duplicate closings, but allow if already closing to ensure completion
        if closing_in_progress["done"]:
            logger.info("Deterministic closing already in progress — skipping duplicate")
            return
        closing_in_progress["done"] = True
        call_closed["done"] = True
        closing_requested["done"] = True
        _cancel_pending()
        _cancel_no_response()
        fb = reply_tracker.get("fallback_say")
        if fb is not None and not fb.done():
            fb.cancel()
        reply_tracker["fallback_say"] = None
        closing_msg = _get_deterministic_closing(cfg)
        try:
            usage["tts_chars"] += len(closing_msg)
            usage["transcripts"].append({"role": "agent", "text": closing_msg})
            logger.info(f"👋 Deterministic closing: {closing_msg} — will play fully then auto-cut")
            # Mark timestamp so end_call tool knows closing was already spoken
            try:
                ag = agent_holder.get("agent")
                if ag is not None:
                    setattr(ag, '_last_deterministic_closing_ts', time.time())
                    if hasattr(ag, 'cfg'):
                        setattr(ag.cfg, '_last_closing_ts', time.time())
                    # Also store on global ref for agent_builder
                    setattr(ag, '_closing_msg', closing_msg)
            except Exception:
                pass
            # Interrupt any ongoing LLM/TTS generation to prioritize goodbye
            try:
                session.interrupt()
                await asyncio.sleep(0.15)
            except Exception:
                pass
            # Speak deterministic closing — MUST complete before shutdown
            try:
                await asyncio.wait_for(session.say(closing_msg, allow_interruptions=False), timeout=20)
                logger.info(f"✅ Deterministic closing TTS completed: {closing_msg}")
            except asyncio.TimeoutError:
                logger.warning(f"⏱️ Deterministic closing TTS timed out after 20s: {closing_msg}")
            except Exception as e:
                # Transport closed is expected if frontend already left, but try to still log
                if "transport is closed" in str(e).lower() or "no stream" in str(e).lower():
                    logger.warning(f"⚠️ Transport closed during closing TTS (frontend may have left early), but message was: {closing_msg} — will still shutdown after delay: {e}")
                else:
                    logger.warning(f"Deterministic closing say failed: {e}")
            # Critical: wait for audio to flush to frontend before cutting
            # 2.5s ensures TTS audio packet fully delivered even on slow network
            await asyncio.sleep(2.5)
        except asyncio.CancelledError:
            logger.info("Deterministic closing cancelled")
            return
        except Exception as e:
            logger.warning(f"Deterministic closing outer failed: {e}")
            await asyncio.sleep(1.0)
        # Now auto-cut the call
        logger.info("✂️ Auto-cutting call after deterministic closing TTS")
        try:
            session.shutdown(drain=False)
        except Exception:
            pass
        try:
            ctx.shutdown()
        except Exception:
            pass

    def _schedule_deterministic_closing():
        if closing_in_progress["done"]:
            return
        if closing_task_ref["task"] is not None and not closing_task_ref["task"].done():
            return
        try:
            closing_task_ref["task"] = asyncio.ensure_future(_do_deterministic_closing())
        except Exception as e:
            logger.warning(f"Could not schedule deterministic closing: {e}")

    def _cancel_pending():
        t = reply_tracker["pending"]
        if t is not None:
            t.cancel()
            reply_tracker["pending"] = None

    def _mark_reply(ts: float):
        reply_tracker["last_assistant_ts"] = ts
        _cancel_pending()
        fallback_task = reply_tracker.get("fallback_say")
        if fallback_task is not None and not fallback_task.done():
            fallback_task.cancel()
        reply_tracker["fallback_say"] = None

    def _spawn_say(text_to_say: str):
        async def _say():
            try:
                await asyncio.wait_for(session.say(text_to_say, allow_interruptions=True), timeout=15)
            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.warning(f"🛟 fallback say failed: {e}")
        try:
            old = reply_tracker.get("fallback_say")
            if old is not None and not old.done():
                old.cancel()
            reply_tracker["fallback_say"] = asyncio.ensure_future(_say())
        except Exception as e:
            logger.warning(f"🛟 could not schedule fallback reply: {e}")

    async def _silence_fallback(turn_ts: float):
        try:
            await asyncio.sleep(LLM_FALLBACK_DELAY)
        except asyncio.CancelledError:
            return
        finally:
            if reply_tracker["pending"] is asyncio.current_task():
                reply_tracker["pending"] = None
        if reply_tracker["last_assistant_ts"] >= turn_ts or closing_requested["done"]:
            return  # closing turns must never receive a delayed fallback
        logger.warning(
            f"🛟 No LLM reply within {LLM_FALLBACK_DELAY:.0f}s of the user's turn "
            "(rate-limited 429 or failed generation) — speaking a fallback line "
            "so the call is not silent."
        )
        _spawn_say(getattr(cfg, "fallback_response", "").strip() or DEFAULT_FALLBACK_RESPONSE)

    def _schedule_silence_fallback(turn_ts: float):
        _cancel_pending()
        try:
            reply_tracker["pending"] = asyncio.ensure_future(_silence_fallback(turn_ts))
        except Exception as e:
            reply_tracker["pending"] = None
            logger.warning(f"🛟 could not arm silence watchdog: {e}")

    # ---------- No-response handling — robust scheduled timer ----------
    def _cancel_no_response():
        t = no_response_state.get("task")
        if t is not None and not t.done():
            t.cancel()
        no_response_state["task"] = None

    async def _no_response_timeout_handler():
        idle_timeout = max(15, int(getattr(cfg, "no_response_timeout_seconds", 30) or 30))
        no_response_msg = (getattr(cfg, "no_response_message", "") or
                           "I did not hear a response, so I will end the call now. Thank you for calling.").strip()
        try:
            await asyncio.sleep(idle_timeout)
        except asyncio.CancelledError:
            return
        if call_closed["done"] or closing_in_progress["done"] or closing_requested["done"] or no_response_state.get("triggered"):
            return
        elapsed = time.time() - no_response_state.get("last_activity", 0)
        # If user spoke during sleep, task would have been cancelled; double-check
        if elapsed < idle_timeout - 0.5:
            logger.info(f"⏱️ No-response timer fired but user spoke {elapsed:.1f}s ago (timeout {idle_timeout}s) — skipping")
            return
        # Only trigger when waiting for user
        cur_state = state_tracker.get("state")
        if cur_state not in ("listening", None):
            logger.info(f"⏱️ No-response timer fired but state is {cur_state} (not listening) — rescheduling")
            _schedule_no_response()
            return
        no_response_state["triggered"] = True
        # Mark call as closing to prevent re-arming watchdog on listening transition
        call_closed["done"] = True
        closing_in_progress["done"] = True
        logger.info(f"⏱️ No user response for {elapsed:.0f}s (timeout {idle_timeout}s) — speaking no-response message and ending call")
        try:
            _cancel_pending()
            fb = reply_tracker.get("fallback_say")
            if fb is not None and not fb.done():
                fb.cancel()
            reply_tracker["fallback_say"] = None
            try:
                session.interrupt()
                await asyncio.sleep(0.15)
            except Exception:
                pass
            usage["tts_chars"] += len(no_response_msg)
            usage["transcripts"].append({"role": "agent", "text": no_response_msg})
            logger.info(f"⏱️ No-response closing TTS: {no_response_msg} — will play fully then auto-cut")
            try:
                await asyncio.wait_for(session.say(no_response_msg, allow_interruptions=False), timeout=20)
                logger.info(f"✅ No-response TTS completed: {no_response_msg}")
            except asyncio.TimeoutError:
                logger.warning(f"⏱️ No-response TTS timed out after 20s: {no_response_msg}")
            except Exception as e:
                if "transport is closed" in str(e).lower() or "no stream" in str(e).lower():
                    logger.warning(f"⚠️ Transport closed during no-response TTS (frontend left early), but message was: {no_response_msg}: {e}")
                else:
                    logger.warning(f"No-response say failed: {e}")
            await asyncio.sleep(2.5)
        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.warning(f"No-response outer failed: {e}")
            await asyncio.sleep(1.0)
        logger.info("✂️ Auto-cutting call after no-response TTS")
        try:
            session.shutdown(drain=False)
        except Exception:
            pass
        try:
            ctx.shutdown()
        except Exception:
            pass

    def _schedule_no_response():
        if no_response_state.get("triggered") or call_closed["done"] or closing_in_progress["done"] or closing_requested["done"]:
            logger.info("⏱️ Not arming no-response — call already closing/triggered")
            return
        _cancel_no_response()
        idle_timeout = max(15, int(getattr(cfg, "no_response_timeout_seconds", 30) or 30))
        no_response_msg = (getattr(cfg, "no_response_message", "") or
                           "I did not hear a response, so I will end the call now. Thank you for calling.").strip()
        no_response_state["last_activity"] = time.time()
        try:
            no_response_state["task"] = asyncio.ensure_future(_no_response_timeout_handler())
            logger.info(f"⏱️ No-response watchdog armed: {idle_timeout}s -> '{no_response_msg[:60]}' (scheduled)")
        except Exception as e:
            logger.warning(f"Could not arm no-response watchdog: {e}")

    # Fallback loop monitor (kept for safety, primary is scheduled timer)
    async def _no_response_monitor():
        idle_timeout = max(15, int(getattr(cfg, "no_response_timeout_seconds", 30) or 30))
        no_response_msg = (getattr(cfg, "no_response_message", "") or
                           "I did not hear a response, so I will end the call now. Thank you for calling.").strip()
        logger.info(f"⏱️ No-response loop watchdog armed: {idle_timeout}s -> '{no_response_msg[:60]}'")
        await asyncio.sleep(2)
        while not call_closed["done"] and not closing_in_progress["done"] and not no_response_state.get("triggered"):
            try:
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                return
            if closing_requested["done"] or closing_in_progress["done"] or call_closed["done"]:
                continue
            elapsed = time.time() - no_response_state.get("last_activity", 0)
            cur_state = state_tracker.get("state")
            if cur_state not in ("listening", None):
                if cur_state in ("speaking", "thinking"):
                    no_response_state["last_activity"] = time.time()
                continue
            if elapsed >= idle_timeout and not no_response_state.get("triggered"):
                if no_response_state.get("task") is None or no_response_state["task"].done():
                    logger.info(f"⏱️ Loop detected no response {elapsed:.0f}s — triggering")
                    await _no_response_timeout_handler()
                return

    def on_item_added(ev):
        # Allow system closing/no-response messages even after call_closed is set
        # to ensure transcript logging works; otherwise early return hides TTS log
        try:
            _item_role = getattr(getattr(ev, "item", None), "role", None)
        except Exception:
            _item_role = None
        if call_closed["done"] and _item_role != "assistant" and not no_response_state.get("triggered"):
            return
        if call_closed["done"] and _item_role == "assistant":
            # Still process if it's system closing (triggered flag) — otherwise skip LLM chatter after close
            if not (no_response_state.get("triggered") or closing_in_progress["done"]):
                return
        item = getattr(ev, "item", None)
        role = getattr(item, "role", None)
        text = _msg_text(item)
        if role == "user":
            if not text:
                return
            now = time.time()
            # Production debounce fix: 2.5s was too long for short "haan/ok/yes" causing missed turns
            # For short utterances (<3 words), debounce 0.8s, for longer 1.5s (was 2.5s)
            # Prevents duplicate STT events (interim->final same text) from delaying turn, but allows quick repeats
            words_in_text = len(text.split())
            debounce_threshold = 0.8 if words_in_text <= 2 else 1.5
            if text == last_user_transcript["text"] and (now - last_user_transcript["ts"]) < debounce_threshold:
                logger.info(f"⏭️ Dedupe STT duplicate (same text within {debounce_threshold}s): {text[:60]}")
                return
            last_user_transcript["text"] = text
            last_user_transcript["ts"] = now
            # --- Production timing: STT final received ---
            # FIX: Always start fresh timing for each user turn (unconditional reset)
            # Previous bug: conditional reset only if stale>5s caused first_token from previous turn
            # to leak into next turn's tts_request (2099ms artifact) and speech_end 16.8s old artifact
            # Now: unconditional fresh reset per turn, then set speech_end and stt_final fresh
            prev_speech_end = turn_timing.get("speech_end", 0)
            if prev_speech_end != 0:
                stale_age = now - prev_speech_end
                if stale_age > 2.0:
                    logger.info(f"🔄 Resetting turn_timing: prev speech_end {stale_age:.1f}s old (empty turn or long pause) for fresh turn")
            # Fresh timing for this turn - reset ALL keys unconditionally (V2 with TTFT)
            turn_timing["turn_detected"] = 0.0
            turn_timing["llm_start"] = 0.0
            turn_timing["request_start"] = 0.0
            turn_timing["first_token"] = 0.0
            turn_timing["tts_request"] = 0.0
            turn_timing["first_tts_audio"] = 0.0
            turn_timing["llm_complete"] = 0.0
            turn_timing["generation_complete"] = 0.0
            turn_timing["first_audio"] = 0.0
            turn_timing["ttft_ms"] = 0.0
            turn_timing["generation_time_ms"] = 0.0
            turn_timing["input_tokens"] = 0
            turn_timing["cached_input_tokens"] = 0
            turn_timing["output_tokens"] = 0
            # Fresh speech_end and stt_final for this turn
            turn_timing["speech_end"] = now - 0.25  # approximate speech end 250ms before final
            turn_timing["stt_final"] = now
            # Calculate speech_end->STT_final
            if turn_timing["speech_end"] > 0:
                speech_to_stt = (now - turn_timing["speech_end"]) * 1000
                logger.info(f"⏱️ TIMING speech_end->STT_final: {speech_to_stt:.0f}ms (text: {text[:50]}, words: {words_in_text})")
                # Flag if exceeds 400ms target
                if speech_to_stt > 600:
                    logger.warning(f"🐢 Slow STT final: speech_end->STT_final {speech_to_stt:.0f}ms exceeds 400ms target (possible Deepgram delay)")
            # Reset speech_end for next turn after logging
            # Keep it for total calculation until first_audio
            # User spoke — cancel any pending no-response timer (user is active)
            _cancel_no_response()
            no_response_state["last_activity"] = now
            words = max(len(text.split()), 1)
            usage["llm_input_tokens"] += int(words * 1.3)
            usage["user_speech_seconds"] += (words / 150.0) * 60.0
            usage["transcripts"].append({"role": "user", "text": text})
            logger.info(f"👂 User: {text}")
            normalized_user = " ".join(text.lower().replace(".", " ").replace(",", " ").split())
            # Expanded closing detection for low-latency deterministic goodbye.
            # Covers: bye variants, ok good bye, thank you, mixed Hindi/English,
            # and natural no-help phrases like "नहीं और कोई मदद नहीं चाहिए"
            # and transliterated "mujhe kuch nahi puchna hai".
            closing_exact = {
                "bye", "bye bye", "goodbye", "good bye", "ok bye", "okay bye",
                "ok good bye", "okay good bye", "ok goodbye", "okay goodbye",
                "good bye bye", "thank you", "thanks", "thankyou",
                "और तो मुझे कुछ नहीं जानना", "अब मुझे कुछ नहीं जानना",
                "मुझे और कुछ नहीं जानना", "बस इतना ही", "बस इतना ही पूछना था",
                "no more questions", "no more help", "that's all", "that is all",
                "नहीं और कोई मदद नहीं चाहिए", "और कोई मदद नहीं चाहिए",
                "कोई मदद नहीं चाहिए", "और कुछ नहीं चाहिए", "बस हो गया",
                "नहीं और कोई सवाल नहीं है", "और कोई सवाल नहीं है",
                "कोई सवाल नहीं है", "मुझे कुछ नहीं पूछना है", "मुझे कुछ नहीं पूछना",
                "कुछ नहीं पूछना है", "कुछ नहीं पूछना",
                "mujhe kuch nahi puchna hai", "mujhe kuch nahi puchna",
                "kuch nahi puchna hai", "kuch nahi puchna",
                "koi sawaal nahi hai", "koi sawal nahi hai",
                "aur koi sawaal nahi hai", "aur koi sawal nahi hai",
                "nahi aur koi madad nahi chahiye", "aur koi madad nahi chahiye",
                "nahi aur koi sawaal nahi hai",
            }
            closing_substrings = (
                "cut the call", "hang up", "disconnect", "end the call", "call cut",
                "कॉल कट", "call काट", "कॉल काट", "call cut कर दीजिए", "call काट दीजिए",
                "कॉल बंद कर दीजिए", "फोन काट दीजिए", "फोन काट दो",
                "और तो मुझे कुछ नहीं जानना", "अब मुझे कुछ नहीं जानना",
                "मुझे और कुछ नहीं जानना", "बस इतना ही", "बस इतना ही पूछना था",
                "no more questions", "no more help", "that's all", "that is all",
                "नहीं और कोई मदद नहीं चाहिए", "और कोई मदद नहीं चाहिए",
                "कोई मदद नहीं चाहिए", "और कुछ नहीं चाहिए",
                "नहीं और कोई सवाल नहीं है", "और कोई सवाल नहीं है",
                "मुझे कुछ नहीं पूछना है", "कुछ नहीं पूछना है",
                "mujhe kuch nahi puchna", "kuch nahi puchna",
                "koi sawaal nahi", "koi sawal nahi",
            )
            # Robust bye detection: any occurrence of goodbye/good bye, or standalone bye
            has_goodbye = "goodbye" in normalized_user or "good bye" in normalized_user
            # bye as separate token or at end, avoid false positive from "by" substring
            tokens = normalized_user.split()
            has_bye_token = "bye" in tokens or normalized_user.endswith(" bye") or normalized_user.startswith("bye ")
            # Enhanced thank detection: "thank you very much", "thank kota" (mis-heard), "accha laga thank" etc
            # Previous logic required <=12 tokens and exact thank you — too strict, caused
            # "Ok, चलिए ठीक है आपसे बात करके अच्छा लगा thank Kota." to NOT close.
            # Now: thank/thanks/dhanyavaad + positive sentiment or accha laga/khushi = closing
            has_thank = "thank" in normalized_user or "thanks" in normalized_user or "धन्यवाद" in text or "dhanyavaad" in normalized_user
            has_positive_close = any(w in normalized_user for w in ("accha laga", "achha laga", "khushi", "bahut accha", "very much", "bahut"))
            has_contact_info = any(c in normalized_user for c in ("nine", "five", "double", "triple", "zero", "at the rate", "gmail", "dot com", "number", "email")) or (any(ch.isdigit() for ch in text) and len(tokens) >= 4 and len(tokens) <= 20)
            if has_contact_info:
                closing_requested["done"] = False
            else:
                closing_requested["done"] = (
                    normalized_user in closing_exact
                    or has_goodbye
                    or (has_bye_token and len(tokens) <= 8)
                    or (has_thank and "?" not in text and (len(tokens) <= 18 or has_positive_close or "accha laga" in normalized_user or "achha laga" in normalized_user))
                    or any(phrase in normalized_user for phrase in closing_substrings)
                )
            if closing_requested["done"]:
                # Never let the generic provider-timeout fallback speak after a
                # caller has already asked to leave. Speak deterministic closing
                # and hang up (bb393dd fix).
                _cancel_pending()
                old_fallback = reply_tracker.get("fallback_say")
                if old_fallback is not None and not old_fallback.done():
                    old_fallback.cancel()
                reply_tracker["fallback_say"] = None
                _schedule_deterministic_closing()
                return
            # A fresh turn supersedes any fallback still speaking from the
            # previous failed turn; never let it bleed into this reply.
            old_fallback = reply_tracker.get("fallback_say")
            if old_fallback is not None and not old_fallback.done():
                old_fallback.cancel()
            reply_tracker["fallback_say"] = None
            # A fresh turn starts: arm the silence watchdog so a 429'd or empty
            # LLM turn never leaves the caller in dead air.
            reply_tracker["last_user_ts"] = now
            reply_tracker["empty_spoken"] = False
            _schedule_silence_fallback(now)
        elif role == "assistant":
            # Log raw assistant item for debugging empty turns
            raw_text = _msg_text(item)
            is_tool = _item_is_tool_related(item)
            if is_tool:
                logger.info(f"🔧 Assistant item is tool-related, skipping TTS (role={role}, text_len={len(raw_text)}, attrs={[a for a in ('function_call','tool_call','tool_calls') if getattr(item,a,None)]})")
                return
            now = time.time()
            if not text.strip():
                # Detailed logging for empty LLM turn root cause
                logger.warning(f"🧮 LLM produced an empty assistant item (raw_len={len(raw_text)}, role={role}, text_content={getattr(item,'text_content',None)}, content={getattr(item,'content',None)}); waiting for speakable reply. Possible 404/429 or filtered.")
                # Also log timing for empty turn diagnostics
                if turn_timing.get("llm_start",0) > 0:
                    logger.warning(f"⏱️ Empty turn timing: llm_start->now {(now-turn_timing['llm_start'])*1000:.0f}ms, speech_end->now {(now-turn_timing.get('speech_end',now))*1000:.0f}ms")
                return
            _mark_reply(now)
            # Reset no-response timer when agent speaks - timeout starts after agent finishes
            no_response_state["last_activity"] = now
            cleaned = clean_reply_text(text)
            # Never let the LLM close a call on its own. Models sometimes emit
            # a farewell after ambiguous STT fragments such as "company go".
            # Only transcript-level explicit intent may produce a closing TTS.
            # EXEMPT system-initiated messages: no-response and deterministic closing
            # must never be suppressed (they contain "thank you for calling").
            is_system_closing = False
            try:
                sys_closing_msgs = [
                    DETERMINISTIC_CLOSING_MESSAGE,
                    DETERMINISTIC_CLOSING_MESSAGE_EN,
                    (getattr(cfg, "no_response_message", "") or "").strip(),
                ]
                # also check configured message truncated log comparison
                if any(cleaned == m or text.strip() == m for m in sys_closing_msgs if m):
                    is_system_closing = True
                if no_response_state.get("triggered") or closing_in_progress["done"] or closing_requested["done"]:
                    # If we are already in closing/no-response flow, allow any farewell
                    is_system_closing = True
            except Exception:
                pass
            latest_user = last_user_transcript["text"].lower()
            explicit_end = any(term in latest_user for term in (
                "goodbye", "good bye", "bye", "hang up", "cut the call",
                "disconnect", "end the call", "thank you", "thankyou", "bye bye",
                "ok bye", "okay bye", "कॉल कट", "call काट", "कॉल काट",
                "call cut कर दीजिए", "call काट दीजिए", "कॉल बंद कर दीजिए",
                "फोन काट दीजिए"
            ))
            if not is_system_closing and not explicit_end and any(term in cleaned.lower() for term in ("goodbye", "good bye", "thank you for calling")):
                logger.warning("🛡️ Suppressed model farewell without explicit caller goodbye")
                cleaned = "Ji, batayiye, aapko kis tarah ki madad chahiye?"
            if cleaned == FALLBACK_REPLY and text.strip() != FALLBACK_REPLY:
                # The model returned something but we flagged it as a fallback —
                # surface the raw text so we can see WHY.
                logger.warning(f"🧮 LLM reply flagged as fallback. RAW: {text!r}")
            usage["tts_chars"] += len(cleaned)
            # Only count LLM output in assistant mode; announcement plays a fixed
            # script with no LLM, so it must not be billed for LLM tokens.
            if agent_mode != "announcement":
                words = max(len(cleaned.split()), 1)
                usage["llm_output_tokens"] += int(words * 1.3)
            usage["transcripts"].append({"role": "agent", "text": cleaned})
            # --- Production timing: LLM complete (NOT audio yet) ---
            # conversation_item_added = LLM finished, not TTS audio
            # Real TTS audio timing is measured by TTS wrapper (first_tts_audio, first_audio)
            now_llm_complete = time.time()
            if turn_timing.get("llm_complete", 0) == 0:
                turn_timing["llm_complete"] = now_llm_complete
                if turn_timing["first_token"] > 0:
                    logger.info(f"⏱️ TIMING first_token->llm_complete (LLM full response): {(now_llm_complete-turn_timing['first_token'])*1000:.0f}ms")
                if turn_timing["llm_start"] > 0:
                    logger.info(f"⏱️ TIMING llm_start->llm_complete: {(now_llm_complete-turn_timing['llm_start'])*1000:.0f}ms")
                if turn_timing["speech_end"] > 0:
                    logger.info(f"⏱️ TIMING speech_end->llm_complete: {(now_llm_complete-turn_timing['speech_end'])*1000:.0f}ms (NOTE: NOT audio, real audio via TTS wrapper)")
            # Fallback for say() calls without TTS wrapper
            if turn_timing.get("first_tts_audio", 0) == 0 and turn_timing.get("first_audio", 0) == 0:
                if turn_timing["first_token"] > 0:
                    token_to_audio = (now_llm_complete - turn_timing["first_token"]) * 1000
                    logger.info(f"⏱️ TIMING first_token->first_audio (fallback no wrapper): {token_to_audio:.0f}ms")
                if turn_timing["speech_end"] > 0:
                    speech_to_audio = (now_llm_complete - turn_timing["speech_end"]) * 1000
                    logger.info(f"⏱️ TIMING speech_end->first_audio (fallback): {speech_to_audio:.0f}ms")
                    turn_timing["last_speech_end_to_first_audio"] = speech_to_audio
                    if turn_timing["stt_final"] > 0 and turn_timing["turn_detected"] > 0 and turn_timing["llm_start"] > 0 and turn_timing["first_token"] > 0:
                        logger.info(
                            f"📊 TURN BREAKDOWN (fallback): speech_end->STT_final {(turn_timing['stt_final']-turn_timing['speech_end'])*1000:.0f}ms | "
                            f"STT_final->turn {(turn_timing['turn_detected']-turn_timing['stt_final'])*1000:.0f}ms | "
                            f"turn->LLM {(turn_timing['llm_start']-turn_timing['turn_detected'])*1000:.0f}ms | "
                            f"LLM->first_token {(turn_timing['first_token']-turn_timing['llm_start'])*1000:.0f}ms | "
                            f"first_token->audio {(now_llm_complete-turn_timing['first_token'])*1000:.0f}ms | "
                            f"TOTAL {speech_to_audio:.0f}ms"
                        )
                    if turn_timing.get("tts_request", 0) == 0:
                        turn_timing["speech_end"] = 0.0
                        turn_timing["stt_final"] = 0.0
                        turn_timing["turn_detected"] = 0.0
                        turn_timing["llm_start"] = 0.0
                        turn_timing["request_start"] = 0.0
                        turn_timing["first_token"] = 0.0
                        turn_timing["tts_request"] = 0.0
                        turn_timing["first_tts_audio"] = 0.0
                        turn_timing["llm_complete"] = 0.0
                        turn_timing["generation_complete"] = 0.0
                        turn_timing["first_audio"] = 0.0
                        turn_timing["ttft_ms"] = 0.0
                        turn_timing["generation_time_ms"] = 0.0
            logger.info(f"🗣️ TTS (LLM complete): {cleaned}")

    session.on("conversation_item_added", on_item_added)

    def _on_state(ev):
        now = time.time()
        prev = state_tracker["state"]
        elapsed = now - state_tracker["since"]
        if prev == "thinking" and elapsed > 2.5:
            logger.warning(f"🐢 Slow turn: agent was in 'thinking' for {elapsed:.2f}s")
        logger.info(f"🔄 state {prev} -> {ev.new_state} ({elapsed:.2f}s)")

        # --- Production timing instrumentation ---
        if prev == "listening" and ev.new_state == "thinking":
            # Turn detected: listening -> thinking = endpointing triggered
            # This is speech_end + VAD + endpointing + STT final -> LLM request path
            turn_timing["turn_detected"] = now
            if turn_timing["stt_final"] > 0:
                stt_to_turn = (now - turn_timing["stt_final"]) * 1000
                logger.info(f"⏱️ TIMING STT_final->turn_detected (endpointing): {stt_to_turn:.0f}ms")
                if stt_to_turn > 150:
                    logger.warning(f"🐢 Slow endpointing: STT_final->turn {stt_to_turn:.0f}ms exceeds 100ms target")
            if turn_timing["speech_end"] > 0:
                speech_to_turn = (now - turn_timing["speech_end"]) * 1000
                logger.info(f"⏱️ TIMING speech_end->turn_detected (VAD+STT+endpointing): {speech_to_turn:.0f}ms")
                if speech_to_turn > 700:
                    logger.warning(f"🐢 Slow turn detection: speech_end->turn {speech_to_turn:.0f}ms exceeds 500ms target (outlier!)")
            # Also log as LLM start (turn completed -> LLM request)
            turn_timing["llm_start"] = now
            if turn_timing["stt_final"] > 0:
                stt_to_llm = (now - turn_timing["stt_final"]) * 1000
                logger.info(f"⏱️ TIMING STT_final->LLM_start: {stt_to_llm:.0f}ms (target ≤100ms)")

        elif prev == "thinking" and ev.new_state == "speaking":
            # First token -> first audio: LLM first token arrived, TTS starting
            turn_timing["first_token"] = now
            if turn_timing["llm_start"] > 0:
                llm_to_token = (now - turn_timing["llm_start"]) * 1000
                logger.info(f"⏱️ TIMING LLM_start->first_token: {llm_to_token:.0f}ms (target ≤500ms)")
            if turn_timing["speech_end"] > 0:
                speech_to_token = (now - turn_timing["speech_end"]) * 1000
                logger.info(f"⏱️ TIMING speech_end->first_token: {speech_to_token:.0f}ms")

        elif prev == "thinking" and ev.new_state == "listening":
            # Empty turn: thinking->listening without speaking (LLM returned empty/no TTS)
            # Root causes observed: 404 LLM failure, 429 rate-limit, empty LLM response, tool filtering
            # FIX: Reset timing so next turn doesn't use stale speech_end (caused 4712ms artifact)
            # Also log detailed diagnostics for empty turn
            logger.warning(f"⚠️ Empty LLM turn detected (thinking {elapsed:.2f}s → listening without speaking). Possible causes: LLM 404/429, empty response, or tool filtering. speech_end age: {(now-turn_timing.get('speech_end',0)) if turn_timing.get('speech_end') else 'N/A'}")
            if turn_timing["speech_end"] != 0 and turn_timing["first_audio"] == 0:
                logger.info(f"🔄 Resetting turn_timing after empty turn to avoid next-turn outlier")
                turn_timing["speech_end"] = 0.0
                turn_timing["stt_final"] = 0.0
                turn_timing["turn_detected"] = 0.0
                turn_timing["llm_start"] = 0.0
                turn_timing["request_start"] = 0.0
                turn_timing["first_token"] = 0.0
                turn_timing["first_audio"] = 0.0
                if "tts_request" in turn_timing:
                    turn_timing["tts_request"] = 0.0
                if "first_tts_audio" in turn_timing:
                    turn_timing["first_tts_audio"] = 0.0
                if "audio_published" in turn_timing:
                    turn_timing["audio_published"] = 0.0
                if "llm_complete" in turn_timing:
                    turn_timing["llm_complete"] = 0.0
                if "generation_complete" in turn_timing:
                    turn_timing["generation_complete"] = 0.0
                if "request_start" in turn_timing:
                    turn_timing["request_start"] = 0.0
                if "ttft_ms" in turn_timing:
                    turn_timing["ttft_ms"] = 0.0
                if "generation_time_ms" in turn_timing:
                    turn_timing["generation_time_ms"] = 0.0

        elif ev.new_state == "listening" and prev == "speaking":
            # Agent finished speaking, now listening: estimate speech_end for next turn
            # Reset timing for next turn, but keep last turn's metrics for final calc
            # Actually speech_end will be set when user starts speaking? We need VAD hook.
            # For now, reset stt_final and turn_detected for next turn
            # Keep speech_end as 0 until next VAD end (we approximate via last_user_transcript timing)
            pass

        # Track VAD speech end approximation: when listening starts, user hasn't spoken yet
        # When user stops speaking, STT final arrives, then turn detected.
        # For barge-in detection: listening->thinking is turn, but we also need speech_end.
        # We approximate speech_end as stt_final - 200ms (Deepgram endpointing) or use VAD if available.
        # Better: set speech_end when we get interim STT that then becomes final after silence.
        # For now, we set speech_end when state goes listening->thinking minus endpointing delay
        # to measure outlier.

        if ev.new_state == "speaking":
            _cancel_pending()
            # Don't cancel if we are in no-response closing flow — keep triggered flag
            if not no_response_state.get("triggered"):
                _cancel_no_response()
            no_response_state["last_activity"] = now
            # First audio timing will be logged in TTS handler
        elif ev.new_state == "listening":
            # If no-response already triggered or call closing, do NOT re-arm
            if no_response_state.get("triggered") or call_closed["done"] or closing_in_progress["done"] or closing_requested["done"]:
                logger.info(f"⏱️ Listening but no-response/closing already triggered — not re-arming")
            else:
                no_response_state["last_activity"] = now
                _schedule_no_response()
            # Reset for next turn's speech_end detection
            # We will set speech_end when VAD would have detected end, approx now + user speech
            # Actually we need to track when user starts speaking vs stops.
            # For outlier detection, we log listening duration: if >3s, flag
            if elapsed > 3.0 and prev in ("listening", None):
                logger.warning(f"🐢 Listening outlier: {prev}->{ev.new_state} took {elapsed:.2f}s (possible 3-7s outlier, check VAD/STT)")
        elif ev.new_state == "thinking":
            if not no_response_state.get("triggered"):
                _cancel_no_response()
            no_response_state["last_activity"] = now
        state_tracker["state"] = ev.new_state
        state_tracker["since"] = now

    session.on("agent_state_changed", _on_state)

    # Start recording if the agent has it on — but DO NOT block the call from
    # connecting. A missing/unavailable Egress service used to add ~21s before
    # session.start(), delaying every call. Now it runs in the background and the
    # recording URL is filled in before billing finalizes (or skipped if Egress
    # isn't reachable).
    recording_url = None
    egress_task = None
    if getattr(cfg, "recording_enabled", True):
        async def _start_egress_later():
            nonlocal recording_url
            try:
                recording_url = await asyncio.wait_for(start_egress(ctx.room.name), timeout=10)
            except asyncio.TimeoutError:
                logger.warning("⏱️ Egress timed out after 10s — recording disabled for this call.")
            except Exception as e:
                logger.warning(f"⚠️ Egress unavailable; continuing without recording: {e}")
        egress_task = asyncio.create_task(_start_egress_later())

    if agent_mode == "announcement":
        script = getattr(cfg, "announce_text", "") or greeting
        script = leadfile.render_template(script, lead_data)
        agent = build_announce_agent(cfg, announce_text=script)
        logger.info("📢 mode=announcement (fixed-script only, no STT/LLM)")
    else:
        agent = build_voice_agent(cfg, greeting=greeting, prior_memory=prior_memory, lead_data=lead_data)
        logger.info("💬 mode=assistant (STT+LLM+TTS)")
    agent_holder["agent"] = agent

    # Server-side noise cancellation. Two tiers:
    #   * NOISE_CANCELLATION=krisp -> server-side Krisp (BVC) filter. Only works on
    #     LiveKit Cloud WITH the `livekit-krisp-noise-cancellation` package installed
    #     (it's a closed-source binary; it does NOT run on a plain self-hosted SFU).
    #   * default (browser calls) -> the browser already applies WebRTC
    #     noiseSuppression/echoCancellation/autoGainControl (see CallPanel.tsx),
    #     and Deepgram STT uses its built-in VAD (`vad_events=True`), which rejects
    #     non-speech/noise frames before they reach the LLM.
    room_options = None
    nc_mode = os.getenv("NOISE_CANCELLATION", "").strip().lower()
    if nc_mode == "krisp":
        try:
            from livekit import rtc
            from livekit.agents.voice import room_io
            room_options = room_io.RoomOptions(
                close_on_disconnect=False,
                input_options=room_io.RoomInputOptions(
                    noise_cancellation=rtc.NoiseCancellationOptions(provider="krisp"),
                )
            )
            logger.info("🎤 Krisp noise cancellation enabled (close_on_disconnect=False).")
        except Exception as e:
            logger.warning(
                "Krisp noise cancellation unavailable (%s). To enable it on LiveKit "
                "Cloud: pip install livekit-krisp-noise-cancellation and set "
                "NOISE_CANCELLATION=krisp. For a self-hosted demo, leave it unset — "
                "browser calls get WebRTC noise suppression and Deepgram VAD filters "
                "non-speech.", e,
            )
            # Fallback: still ensure close_on_disconnect=False even if Krisp fails
            try:
                from livekit.agents.voice import room_io as _rio
                room_options = _rio.RoomOptions(close_on_disconnect=False)
                logger.info("🎤 RoomOptions(close_on_disconnect=False) armed as fallback after Krisp failure.")
            except Exception:
                pass
    else:
        try:
            from livekit.agents.voice import room_io as _rio
            room_options = _rio.RoomOptions(close_on_disconnect=False)
            logger.info("🎤 RoomOptions(close_on_disconnect=False) armed (TTS goodbye protected).")
        except Exception as e:
            logger.warning(f"Could not set RoomOptions close_on_disconnect=False: {e}")
        if nc_mode:
            logger.warning(f"Unknown NOISE_CANCELLATION='{nc_mode}' (expected 'krisp'); skipping.")

    # ------------------------------------------------------------------
    # Finalization (idempotent) + call-end watchdog.
    #
    # LiveKit's built-in `close_on_disconnect` only ends a session when the
    # disconnect reason is CLIENT_INITIATED / ROOM_DELETED / USER_REJECTED.
    # Closing the browser tab or a network drop uses a different reason, so the
    # session never closes and the call stays "in-progress" forever. We fix that
    # with a watchdog that ends the job (which runs `finalize_billing`) as soon
    # as the caller leaves for ANY reason.
    # ------------------------------------------------------------------
    _finalized = {"done": False}

    async def finalize_billing(reason=None):
        if _finalized["done"]:
            return
        _finalized["done"] = True
        try:
            duration = int(time.time() - call_start)
            # V2: Use actual LLM provider/model and cached tokens + TTFT for cost tracking
            try:
                llm_provider = turn_timing.get("llm_provider") or cfg.providers.get_primary_llm().resolve_llm_provider_model()[0] if hasattr(cfg.providers, 'get_primary_llm') else cfg.providers.llm.id
                llm_model = turn_timing.get("llm_model") or cfg.providers.get_primary_llm().resolve_llm_provider_model()[1] if hasattr(cfg.providers, 'get_primary_llm') else (cfg.providers.llm.config or {}).get("model", "")
                llm_input = turn_timing.get("input_tokens", 0) or usage["llm_input_tokens"]
                llm_cached = turn_timing.get("cached_input_tokens", 0)
                llm_output = turn_timing.get("output_tokens", 0) or usage["llm_output_tokens"]
                ttft = turn_timing.get("ttft_ms", 0)
                gen_time = turn_timing.get("generation_time_ms", 0)
                logger.info(f"💰 FINAL BILLING LLM provider={llm_provider} model={llm_model} input={llm_input} cached={llm_cached} output={llm_output} TTFT={ttft:.0f}ms gen_time={gen_time:.0f}ms")
            except Exception as e:
                logger.debug(f"Could not get V2 billing info: {e}")
                llm_provider = cfg.providers.llm.id
                llm_model = (cfg.providers.llm.config or {}).get("model", "")
                llm_input = usage["llm_input_tokens"]
                llm_cached = 0
                llm_output = usage["llm_output_tokens"]
                ttft = turn_timing.get("ttft_ms", 0)
                gen_time = turn_timing.get("generation_time_ms", 0)

            costs = calculate_call_cost(
                duration_seconds=duration,
                stt_seconds=usage["user_speech_seconds"],
                llm_input_tokens=llm_input,
                llm_output_tokens=llm_output,
                tts_chars=usage["tts_chars"],
                llm_provider_id=llm_provider,
                llm_provider=llm_provider,
                llm_model_id=llm_model,
                llm_cached_input_tokens=llm_cached,
                llm_ttft_ms=ttft,
                llm_generation_time_ms=gen_time,
                stt_provider_id=cfg.providers.stt.id,
                tts_provider_id=cfg.providers.tts.id,
                client_rate_per_min=cfg.client_rate_per_min,
            )
            if memory_enabled:
                memory.save(customer_key, usage["transcripts"])

            # Only treat it as a real call if something was said or it ran long
            # enough. Otherwise mark it failed so it isn't billed.
            real_call = (duration >= _FAIL_THRESHOLD_SECONDS) or (usage["user_speech_seconds"] > 0)
            status = "completed" if real_call else "failed"

            print(_billing_report(costs, usage, duration))

            # IMPORTANT: Post billing to backend FIRST so wallet deduction happens
            # atomically in main.py (which also updates the call record). This
            # prevents the race where worker marks completed before backend can deduct.
            billing_posted = False
            if real_call:
                try:
                    billing_posted = await _post_billing(call_record["id"], user_id, agent_id, mode, phone,
                                        duration, costs, usage, recording_url, status)
                except Exception as e:
                    logger.warning(f"Billing POST exception, will fallback to direct DB: {e!r}", exc_info=True)
                    billing_posted = False

            # Fallback local update (ensures call is marked completed even if backend unreachable)
            try:
                await repo.update_call(call_record["id"], {
                    "status": status,
                    "ended_at": time.strftime("%Y-%m-%d %H:%M"),
                    "duration_seconds": duration,
                    "transcripts": usage["transcripts"][-60:],
                    "usage": usage,
                    "cost": costs if real_call else {},
                    "recording_url": recording_url,
                })
            except Exception as e:
                logger.warning(f"Local call update failed: {e}")

            # Safety net: ALWAYS check wallet deduction — if backend failed or returned non-200,
            # deduct directly via DB (idempotent, checks existing spend transaction)
            if real_call:
                try:
                    has_spend = False
                    try:
                        has_spend = await repo.has_spend_for_call(call_record.get("user_id", user_id), call_record["id"])
                    except Exception as he:
                        logger.warning(f"has_spend check failed: {he}")
                        has_spend = False
                    if not has_spend:
                        charge = float(costs.get("client_price_inr", 0) or 0)
                        if charge > 0:
                            wallet = await repo.deduct(call_record.get("user_id", user_id), charge, note=f"Call {call_record['id']}")
                            logger.info(f"💸 Wallet auto-deducted ₹{charge} for call {call_record['id']} — remaining balance ₹{wallet.get('balance', 0)} (billing_posted={billing_posted})")
                        else:
                            logger.info(f"Call {call_record['id']} has zero charge, no deduction needed")
                    else:
                        logger.info(f"💰 Wallet already deducted for call {call_record['id']} (billing_posted={billing_posted}) — skipping direct deduct")
                except Exception as de:
                    logger.warning(f"Direct wallet deduct failed for call {call_record['id']}: {de!r}", exc_info=True)

        except Exception as e:
            logger.exception(f"finalize_billing error: {e}")

    # Register the shutdown callback BEFORE the session starts, so finalization is
    # always wired even if setup/session errors out or the room closes instantly.
    try:
        ctx.add_shutdown_callback(finalize_billing)
    except Exception:
        pass

    # Watchdog: end the call when the caller leaves for any reason (closing the
    # tab, network drop, or clicking "Leave"). Closing the session unblocks
    # session.start(), which lets the job shut down and run finalize_billing.
    async def watch_call_end():
        room = ctx.room
        caller_joined = asyncio.Event()
        caller_left = asyncio.Event()

        def _on_connected(participant):
            if participant != room.local_participant:
                caller_joined.set()

        def _on_disconnected(participant):
            # If we are already in deterministic closing, don't trigger hangup watchdog
            # — let closing TTS finish fully before cutting
            if closing_in_progress["done"]:
                logger.info("👋 Caller disconnected during deterministic closing — letting goodbye TTS finish before cut")
                if not room.remote_participants:
                    caller_left.set()
                return
            call_closed["done"] = True
            # Cancel pending fallback speech immediately when the caller leaves.
            # Otherwise the watchdog can try to speak into a closed AgentSession.
            _cancel_pending()
            fallback_task = reply_tracker.get("fallback_say")
            if fallback_task is not None and not fallback_task.done():
                fallback_task.cancel()
            reply_tracker["fallback_say"] = None
            # "remote participants" = the caller(s). When there are none left and
            # we previously saw at least one caller, the call is over.
            if not room.remote_participants:
                caller_left.set()

        room.on("participant_connected", _on_connected)
        room.on("participant_disconnected", _on_disconnected)
        try:
            # The caller may already be in the room before this watcher attaches.
            if room.remote_participants:
                caller_joined.set()
            await caller_joined.wait()
            idle_timeout = max(15, int(getattr(cfg, "no_response_timeout_seconds", 30) or 30))
            try:
                await asyncio.wait_for(caller_left.wait(), timeout=idle_timeout)
            except asyncio.TimeoutError:
                # Keep this deterministic and customer-configurable. Do not run
                # the LLM for an idle caller; speak the saved line once, then hang up.
                message = (getattr(cfg, "no_response_message", "") or
                           "I did not hear a response, so I will end the call now. Thank you for calling.").strip()
                _cancel_pending()
                _cancel_no_response()
                no_response_state["triggered"] = True
                call_closed["done"] = True
                closing_in_progress["done"] = True
                fallback_task = reply_tracker.get("fallback_say")
                if fallback_task is not None and not fallback_task.done():
                    fallback_task.cancel()
                try:
                    await session.say(message, allow_interruptions=False)
                except Exception as exc:
                    logger.info("Idle timeout message could not be played because the session closed: %s", exc)
                logger.info("⏱️ Caller inactive for %ss — ending call.", idle_timeout)
                try:
                    session.shutdown(drain=False)
                except Exception:
                    pass
                try:
                    ctx.shutdown()
                except Exception:
                    pass
                return
            logger.info("👋 Caller hang up — ending call.")
        finally:
            room.off("participant_connected", _on_connected)
            room.off("participant_disconnected", _on_disconnected)
        # Close the agent session so the job can wind down and finalize.
        try:
            session.shutdown(drain=False)
        except Exception as e:
            logger.warning(f"session.shutdown failed: {e}")
        try:
            ctx.shutdown()
        except Exception as e:
            logger.warning(f"could not trigger job shutdown: {e}")

    watchdog = asyncio.create_task(watch_call_end())
    # Primary: scheduled timer (resets on activity), fallback: loop monitor
    loop_monitor_task = asyncio.create_task(_no_response_monitor())

    start_kwargs: dict = {"agent": agent, "room": ctx.room}
    if room_options is not None:
        start_kwargs["room_options"] = room_options
    try:
        await session.start(**start_kwargs)
    finally:
        watchdog.cancel()
        loop_monitor_task.cancel()
        _cancel_no_response()
        if egress_task is not None:
            egress_task.cancel()


def _billing_report(costs, usage, duration) -> str:
    return (
        "\n" + "=" * 64 + "\n"
        f"📊 BILLING  duration={duration}s ({costs['duration_mins']} min)\n"
        f"👂 STT {round(usage['user_speech_seconds'],1)}s -> ₹{costs['stt_cost_inr']}\n"
        f"🧠 LLM {usage['llm_input_tokens']}in/{usage['llm_output_tokens']}out -> ₹{costs['llm_cost_inr']}\n"
        f"🗣️ TTS {usage['tts_chars']} chars -> ₹{costs['tts_cost_inr']}\n"
        f"🖥️ Server -> ₹{costs['server_cost_inr']}\n"
        f"💸 YOUR COST ₹{costs['total_cost_inr']} (₹{costs['your_cost_per_min']}/min)\n"
        f"💳 CUSTOMER BILL ₹{costs['client_price_inr']} (₹{costs['client_bill_per_min']}/min)\n"
        f"🤑 PROFIT ₹{costs['your_profit_inr']} [{'PROFIT ✅' if costs['is_profit'] else 'LOSS ⚠️'}]\n"
        + "=" * 64
    )


async def _post_billing(call_id, user_id, agent_id, mode, phone, duration, costs, usage,
                       recording_url, status="completed") -> bool:
    headers = {"Content-Type": "application/json"}
    if BILLING_INTERNAL_TOKEN:
        headers["X-Internal-Token"] = BILLING_INTERNAL_TOKEN
    payload = {
        "id": call_id,
        "user_id": user_id,
        "agent_id": agent_id,
        "mode": mode,
        "phone": phone,
        "room": "",
        "date": time.strftime("%Y-%m-%d %H:%M"),
        "recording_url": recording_url,
        "durationSeconds": duration,
        "durationMins": costs["duration_mins"],
        "sttSeconds": round(usage["user_speech_seconds"], 1),
        "ttsChars": usage["tts_chars"],
        "llmInputTokens": usage["llm_input_tokens"],
        "llmOutputTokens": usage["llm_output_tokens"],
        "costToUser": f"₹{costs['client_price_inr']}",
        "costToUserNumber": costs["client_price_inr"],
        "clientRatePerMin": costs["client_rate_per_min"],
        "providerCost": costs["total_cost_inr"],
        "costPerMin": costs["your_cost_per_min"],
        "billPerMin": costs["client_bill_per_min"],
        "profit": costs["your_profit_inr"],
        "isProfit": costs["is_profit"],
        "sttCost": costs["stt_cost_inr"],
        "llmCost": costs["llm_cost_inr"],
        "ttsCost": costs["tts_cost_inr"],
        "serverCost": costs["server_cost_inr"],
        "status": status.title(),
        "transcripts": usage["transcripts"][-30:],
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{BILLING_BACKEND_URL}/api/billing/log",
                                    json=payload, headers=headers, timeout=8) as resp:
                body = await resp.text()
                logger.info(f"✅ Billing posted HTTP {resp.status} for call {call_id} — billed ₹{costs['client_price_inr']} — backend will deduct wallet")
                if resp.status >= 400:
                    logger.warning(f"⚠️ Billing POST returned {resp.status}: {body[:500]}")
                    return False
                return True
    except Exception as e:
        logger.warning(f"⚠️ Billing POST failed for call {call_id} to {BILLING_BACKEND_URL}: {e!r} — will fallback to direct DB deduct", exc_info=True)
        return False


def prewarm(proc):
    # Production prewarm: ONLY VAD, NOT DB (DB prewarm caused "Event loop is closed" -> 1.73s lookup retry)
    # VAD 0.20/0.30/0.20/0.55 production-tuned for 300-400ms speech_end->STT_final + less CPU (no more 0.4s slower-than-realtime)
    # Endpointing now STT-based 0.20/0.55, so VAD only for barge-in, not turn detection
    silero.VAD.load(
        min_speech_duration=0.20,
        min_silence_duration=0.30,
        prefix_padding_duration=0.20,
        activation_threshold=0.55,
    )
    logger.info("🔥 Prewarm: VAD hot (production 0.20/0.30/0.20/0.55, STT turn_detection, endpointing 0.20/0.55)")
    # NOTE: DB prewarm removed - it used asyncio.run() which closes event loop, causing
    # "Event loop is closed" on next Prisma call -> 1.73s retry. DB now cached per process
    # via _DB_INIT_DONE global, first job pays 2.33s, subsequent 0.00s, no loop closure.


if __name__ == "__main__":
    from livekit.agents import WorkerOptions, cli

    # livekit-agents v1 ships a Typer CLI that requires a subcommand
    # (start / dev / console). Default to `start` so that
    # `python -m app.agents.worker` boots a production worker out of the box.
    if len(sys.argv) == 1:
        sys.argv.append("start")

    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            prewarm_fnc=prewarm,
            # Pre-warm one idle worker process so the first call connects fast
            # instead of paying the plugin-import + VAD-load cost on every call.
            # Bump this for more concurrent calls; set 0 to never pre-warm.
            num_idle_processes=int(os.getenv("NUM_IDLE_PROCESSES", "1")),
            agent_name=WORKER_AGENT_NAME,
            # Windows doesn't support the default "forkserver" context; "spawn"
            # is portable and works on Windows/macOS/Linux alike.
            multiprocessing_context="spawn",
        )
    )
