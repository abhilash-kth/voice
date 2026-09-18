"""Small, provider-neutral runtime guards for the LiveKit voice worker.

The Google TTS plugin owns an asynchronous gRPC client.  That client is lazy,
so it must be created by the first TTS operation on the same event loop that
runs the LiveKit ``AgentSession``.  This module deliberately contains no Google
or LiveKit imports: it can be unit-tested without provider credentials and it
keeps prewarming limited to imports.
"""
from __future__ import annotations

import asyncio
import importlib
import inspect
import logging
import os
import time
from contextlib import suppress
from typing import Any, AsyncIterator, Optional

logger = logging.getLogger("voice-agent-saas-runtime")

# Google credential objects are synchronous data/signers, not async clients or
# gRPC channels.  They may safely be prepared during worker prewarm and passed
# into the Google TTS constructor; the async client itself remains loop-local.
_google_credentials_cache: dict[str, Any] = {}


def _credential_cache_key(credentials_file: str) -> str:
    return os.path.abspath(os.path.expanduser(credentials_file))


def get_google_credentials(credentials_file: Optional[str]) -> Any:
    if not credentials_file:
        return None
    return _google_credentials_cache.get(_credential_cache_key(credentials_file))


class TTSLoopOwnershipError(RuntimeError):
    """A TTS async client was found attached to a different event loop."""


_LOOP_ERROR_TEXT = (
    "event loop is closed",
    "attached to a different loop",
    "different event loop",
    "cannot schedule new futures",
)


def is_event_loop_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in _LOOP_ERROR_TEXT)


def _nested_provider_objects(root: Any) -> list[Any]:
    """Return the small set of plugin/client wrappers used by Google TTS.

    LiveKit plugin releases have used both ``tts._tts`` and a direct ``tts``
    client.  Do not walk arbitrary object graphs: doing so can touch lazy
    properties and accidentally construct a client during prewarm.
    """
    out: list[Any] = []
    seen: set[int] = set()
    pending = [root]
    while pending:
        obj = pending.pop(0)
        if obj is None or id(obj) in seen:
            continue
        seen.add(id(obj))
        out.append(obj)
        for name in ("_tts", "tts", "_provider"):
            with suppress(Exception):
                child = getattr(obj, name, None)
                if child is not None and child is not obj:
                    pending.append(child)
    return out


def _client_on(owner: Any) -> Any:
    """Get a cached async client without invoking a lazy property."""
    for name in ("_client", "_async_client", "client"):
        with suppress(Exception):
            if name in getattr(owner, "__dict__", {}):
                return getattr(owner, name)
    return None


def _client_owner(tts: Any) -> Any:
    for obj in _nested_provider_objects(tts):
        if callable(getattr(obj, "_ensure_client", None)) or _client_on(obj) is not None:
            return obj
    return tts


def _loop_value(value: Any) -> Optional[asyncio.AbstractEventLoop]:
    if isinstance(value, asyncio.AbstractEventLoop):
        return value
    return None


def _client_loop(client: Any) -> Optional[asyncio.AbstractEventLoop]:
    """Best-effort extraction of the loop held by grpc.aio's channel.

    This is intentionally read-only.  It supports the public-ish shapes used
    by grpc.aio and fake clients used by the event-loop ownership tests.
    """
    if client is None:
        return None
    objects = [client]
    for parent in list(objects):
        for name in ("transport", "_transport", "channel", "_channel", "_grpc_channel"):
            with suppress(Exception):
                child = getattr(parent, name, None)
                if child is not None:
                    objects.append(child)
    for obj in objects:
        for name in ("_loop", "loop"):
            with suppress(Exception):
                loop = _loop_value(getattr(obj, name, None))
                if loop is not None:
                    return loop
    return None


def _invalidate_cached_client(owner: Any) -> Any:
    """Drop a client without calling async ``close`` on its owning loop.

    Calling an async ``close`` method from this path is precisely how a second
    un-awaited coroutine warning can be created when the old loop is already
    closed.  The plugin will lazily build a replacement on the current loop.
    """
    old = _client_on(owner)
    if old is None:
        return None
    for name in ("_client", "_async_client", "client"):
        with suppress(Exception):
            if name in getattr(owner, "__dict__", {}):
                setattr(owner, name, None)
    with suppress(Exception):
        setattr(owner, "_voice_tts_loop", None)
    return old


async def ensure_client_on_current_loop(tts: Any) -> Any:
    """Ensure a lazy Google TTS client belongs to the running LiveKit loop.

    This function is only called from an actual TTS operation.  It is never
    called by ``prewarm`` or by a worker/background thread.  If an older build
    left a cached client on another loop, the reference is discarded before the
    plugin can issue a grpc.aio request, preventing ``StreamStreamCall`` from
    attempting to schedule work on that loop.
    """
    current = asyncio.get_running_loop()
    owner = _client_owner(tts)
    client = _client_on(owner)
    owner_loop = getattr(owner, "_voice_tts_loop", None)
    bound_loop = _client_loop(client)

    if client is not None and (
        (bound_loop is not None and bound_loop is not current)
        or (owner_loop is not None and owner_loop is not current)
    ):
        _invalidate_cached_client(owner)
        client = None

    ensure = getattr(owner, "_ensure_client", None)
    if client is None and callable(ensure):
        # The await happens on the LiveKit agent loop.  No asyncio.run(),
        # new_event_loop(), or to_thread() is allowed in this path.
        result = ensure()
        if inspect.isawaitable(result):
            await result
        client = _client_on(owner)

    if client is not None:
        bound_loop = _client_loop(client)
        if bound_loop is not None and bound_loop is not current:
            _invalidate_cached_client(owner)
            raise TTSLoopOwnershipError(
                "Google TTS created an async client on a non-LiveKit event loop"
            )
        with suppress(Exception):
            setattr(owner, "_voice_tts_loop", current)
    return client


async def _close_stream_without_creating_warning(stream: Any) -> None:
    """Close a failed async iterator only when doing so is safe."""
    close = getattr(stream, "aclose", None)
    if not callable(close):
        return
    try:
        result = close()
        if inspect.isawaitable(result):
            await result
    except Exception:
        # Recovery must not mask the provider error or create another recovery
        # task.  In particular, never call an async close after this loop closes.
        pass


class GoogleTTSLoopGuard:
    """Lazy-loop guard around a LiveKit Google ``TTS`` instance.

    It preserves the provider's streaming surface while making client creation
    explicit at the only safe point: an active TTS operation on the agent loop.
    """

    _voice_google_loop_guard = True

    def __init__(self, inner: Any):
        self._inner = inner

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def _prepare(self) -> None:
        await ensure_client_on_current_loop(self._inner)

    def synthesize(self, text: str, **kwargs: Any) -> AsyncIterator[Any]:
        async def _run() -> AsyncIterator[Any]:
            await self._prepare()
            stream = self._inner.synthesize(text, **kwargs)
            if inspect.isawaitable(stream):
                stream = await stream
            try:
                async for chunk in stream:
                    yield chunk
            except Exception as exc:
                if is_event_loop_error(exc):
                    _invalidate_cached_client(_client_owner(self._inner))
                    logger.warning(
                        "Google TTS stream stopped on an event-loop error; "
                        "discarded the client without scheduling recovery"
                    )
                    raise TTSLoopOwnershipError(str(exc)) from exc
                raise
            finally:
                # Normal exhaustion does not need an explicit close.  On an
                # exception this prevents grpc recovery from leaving a coroutine
                # behind, without calling close on a foreign/closed loop.
                if "stream" in locals() and stream is not None:
                    await _close_stream_without_creating_warning(stream)

        return _run()

    def stream(self, **kwargs: Any) -> Any:
        inner_stream = self._inner.stream(**kwargs)
        guard = self

        class _GuardedStream:
            def __init__(self) -> None:
                self._entered = False

            def __getattr__(self, name: str) -> Any:
                return getattr(inner_stream, name)

            async def __aenter__(self) -> Any:
                await guard._prepare()
                self._entered = True
                enter = getattr(inner_stream, "__aenter__", None)
                if callable(enter):
                    result = enter()
                    if inspect.isawaitable(result):
                        await result
                return self

            async def __aexit__(self, *args: Any) -> Any:
                exit_fn = getattr(inner_stream, "__aexit__", None)
                if callable(exit_fn):
                    result = exit_fn(*args)
                    if inspect.isawaitable(result):
                        return await result
                return None

            def push_text(self, text: str) -> Any:
                return inner_stream.push_text(text)

            async def __aiter__(self) -> AsyncIterator[Any]:
                if not self._entered:
                    await guard._prepare()
                try:
                    async for chunk in inner_stream:
                        yield chunk
                except Exception as exc:
                    if is_event_loop_error(exc):
                        _invalidate_cached_client(_client_owner(guard._inner))
                        await _close_stream_without_creating_warning(inner_stream)
                        logger.warning(
                            "Google TTS stream recovery skipped after event-loop error"
                        )
                        raise TTSLoopOwnershipError(str(exc)) from exc
                    raise

        return _GuardedStream()


def guard_google_tts(tts: Any) -> Any:
    if getattr(tts, "_voice_google_loop_guard", False):
        return tts
    return GoogleTTSLoopGuard(tts)


# ---------------------------------------------------------------------------
# Timing instrumentation.  It observes the pipeline; it does not alter
# endpointing, VAD, provider selection, prompt caching, or billing.
# ---------------------------------------------------------------------------
_TIMING_KEYS = (
    "speech_end", "stt_final", "turn_detected", "llm_start", "request_start",
    "first_token", "tts_request", "first_tts_audio", "first_audio",
)


def new_turn_timing() -> dict[str, Any]:
    return {
        **{key: 0.0 for key in _TIMING_KEYS},
        "turn_id": 0,
        "tts_request_source": "",
        "tts_request_delay_ms": 0.0,
        "last_speech_end_to_first_audio": 0.0,
    }


def reset_turn_timing(timing: dict[str, Any], *, preserve_speech_end: float = 0.0,
                      preserve_stt_final: float = 0.0) -> None:
    timing["turn_id"] = int(timing.get("turn_id", 0)) + 1
    for key in _TIMING_KEYS:
        timing[key] = 0.0
    timing["speech_end"] = preserve_speech_end
    timing["stt_final"] = preserve_stt_final
    timing["tts_request_source"] = ""
    timing["tts_request_delay_ms"] = 0.0


def record_speech_end(timing: dict[str, Any], when: Optional[float] = None) -> None:
    """Record only a real user speech-state transition; never synthesize one."""
    timing["speech_end"] = when if when is not None else time.time()


def _mark_tts_request(timing: dict[str, Any], source: str, turn_id: int) -> None:
    if turn_id != timing.get("turn_id") or timing.get("tts_request", 0):
        return
    now = time.time()
    timing["tts_request"] = now
    timing["tts_request_source"] = source
    first_token = timing.get("first_token", 0)
    if first_token:
        timing["tts_request_delay_ms"] = (now - first_token) * 1000.0
        logger.info(
            "TIMING first_token->tts_request source=%s: %.0fms",
            source, timing["tts_request_delay_ms"],
        )


def _record_first_audio(timing: dict[str, Any], turn_id: int, source: str) -> None:
    if turn_id != timing.get("turn_id") or timing.get("first_tts_audio", 0):
        return
    now = time.time()
    timing["first_tts_audio"] = now
    timing["first_audio"] = now
    speech_end = timing.get("speech_end", 0)
    if speech_end:
        total = (now - speech_end) * 1000.0
        timing["last_speech_end_to_first_audio"] = total
        logger.info("TIMING speech_end->first_audio source=%s REAL stream: %.0fms", source, total)


class TTSTimingWrapper:
    """Observe TTS request and first returned audio without changing audio."""

    _voice_timing_wrapper = True

    def __init__(self, inner: Any, timing: dict[str, Any]):
        self._inner = inner
        self._timing = timing

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def synthesize(self, text: str, **kwargs: Any) -> AsyncIterator[Any]:
        # Capture the turn when LiveKit actually asks for synthesis, not when
        # the wrapper was constructed during session setup.
        turn_id = int(self._timing.get("turn_id", 0))
        inner_stream = self._inner.synthesize(text, **kwargs)

        async def _run() -> AsyncIterator[Any]:
            _mark_tts_request(self._timing, "synthesize", turn_id)
            if inspect.isawaitable(inner_stream):
                stream = await inner_stream
            else:
                stream = inner_stream
            try:
                async for chunk in stream:
                    _record_first_audio(self._timing, turn_id, "synthesize")
                    yield chunk
            finally:
                await _close_stream_without_creating_warning(stream)

        return _run()

    def stream(self, **kwargs: Any) -> Any:
        inner_stream = self._inner.stream(**kwargs)
        timing = self._timing
        # Capture the turn when a stream is requested, after the current user
        # turn has been reset.
        turn_id = int(timing.get("turn_id", 0))

        class _StreamWrapper:
            def __init__(self) -> None:
                self._first = True

            def __getattr__(self, name: str) -> Any:
                return getattr(inner_stream, name)

            async def __aenter__(self) -> Any:
                enter = getattr(inner_stream, "__aenter__", None)
                if callable(enter):
                    result = enter()
                    if inspect.isawaitable(result):
                        await result
                return self

            async def __aexit__(self, *args: Any) -> Any:
                exit_fn = getattr(inner_stream, "__aexit__", None)
                if callable(exit_fn):
                    result = exit_fn(*args)
                    if inspect.isawaitable(result):
                        return await result
                return None

            def push_text(self, text: str) -> Any:
                if text and text.strip():
                    _mark_tts_request(timing, "stream.push_text", turn_id)
                return inner_stream.push_text(text)

            async def __aiter__(self) -> AsyncIterator[Any]:
                async for chunk in inner_stream:
                    if self._first:
                        self._first = False
                        _record_first_audio(timing, turn_id, "stream")
                    yield chunk

            async def aclose(self) -> None:
                await _close_stream_without_creating_warning(inner_stream)

            def close(self) -> Any:
                close = getattr(inner_stream, "close", None)
                return close() if callable(close) else None

        return _StreamWrapper()


def wrap_tts_for_timing(tts: Any, timing: Optional[dict[str, Any]]) -> Any:
    if timing is None or getattr(tts, "_voice_timing_wrapper", False):
        return tts
    return TTSTimingWrapper(tts, timing)


class _LLMStreamTimingWrapper:
    def __init__(self, inner: Any, timing: dict[str, Any], turn_id: int):
        self._inner = inner
        self._timing = timing
        self._turn_id = turn_id
        self._first = True

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def __aiter__(self) -> AsyncIterator[Any]:
        async for chunk in self._inner:
            if self._first and self._turn_id == self._timing.get("turn_id"):
                self._first = False
                self._timing["first_token"] = time.time()
                logger.info(
                    "TIMING LLM_start->first_token: %.0fms",
                    (self._timing["first_token"] - self._timing.get("llm_start", self._timing["first_token"])) * 1000,
                )
            yield chunk


class _LLMChatTimingContext:
    def __init__(self, original: Any, timing: dict[str, Any]):
        self._original = original
        self._timing = timing
        self._inner_cm: Any = None
        self._turn_id = int(timing.get("turn_id", 0))

    async def __aenter__(self) -> Any:
        now = time.time()
        if self._turn_id == self._timing.get("turn_id"):
            self._timing["llm_start"] = now
            self._timing["request_start"] = now
        inner = self._original
        if inspect.isawaitable(inner):
            inner = await inner
        self._inner_cm = inner
        if hasattr(inner, "__aenter__"):
            stream = await inner.__aenter__()
        else:
            stream = inner
        return _LLMStreamTimingWrapper(stream, self._timing, self._turn_id)

    async def __aexit__(self, *args: Any) -> Any:
        if self._inner_cm is not None and hasattr(self._inner_cm, "__aexit__"):
            return await self._inner_cm.__aexit__(*args)
        return None


class LLMTimingWrapper:
    """Observe actual ``LLM.chat`` scheduling and first streamed token."""

    _voice_llm_timing_wrapper = True

    def __init__(self, inner: Any, timing: dict[str, Any]):
        self._inner = inner
        self._timing = timing

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def chat(self, *args: Any, **kwargs: Any) -> Any:
        # This timestamp is intentionally taken at the actual chat call, not at
        # the state transition.  The difference is the real turn->LLM scheduling
        # delay and makes a ~986ms outlier attributable to loop scheduling or
        # upstream queuing rather than hiding it as endpointing latency.
        if self._timing.get("turn_detected", 0):
            self._timing["llm_start"] = time.time()
            self._timing["request_start"] = self._timing["llm_start"]
            logger.info(
                "TIMING turn->LLM_start: %.0fms",
                (self._timing["llm_start"] - self._timing["turn_detected"]) * 1000,
            )
        return _LLMChatTimingContext(self._inner.chat(*args, **kwargs), self._timing)


def wrap_llm_for_timing(llm: Any, timing: Optional[dict[str, Any]]) -> Any:
    if timing is None or getattr(llm, "_voice_llm_timing_wrapper", False):
        return llm
    return LLMTimingWrapper(llm, timing)


def prewarm_google_imports(credentials_file: Optional[str] = None) -> None:
    """Prewarm imports and sync credentials, never an async client/channel."""
    modules = (
        "google.auth.crypt._cryptography_rsa",
        "google.auth._service_account_info",
        "google.auth._default",
        "google.oauth2.credentials",
        "google.oauth2.service_account",
        "google.cloud.texttospeech",
    )
    imported = 0
    for name in modules:
        try:
            importlib.import_module(name)
            imported += 1
        except Exception as exc:
            logger.debug("Google import prewarm skipped %s: %s", name, exc)

    if credentials_file:
        try:
            import google.auth

            path = _credential_cache_key(credentials_file)
            if path not in _google_credentials_cache:
                credentials, _ = google.auth.load_credentials_from_file(
                    path,
                    scopes=["https://www.googleapis.com/auth/cloud-platform"],
                )
                _google_credentials_cache[path] = credentials
                logger.info(
                    "Prewarmed Google credentials/RSA only; async TTS client remains loop-local"
                )
        except Exception as exc:
            logger.debug("Google credential prewarm skipped: %s", exc)

    if imported and not credentials_file:
        logger.info("Prewarmed Google auth/TTS imports only; async client remains loop-local")
