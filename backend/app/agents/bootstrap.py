"""Process-start bootstrap for synchronous network prerequisites.

This module is imported before Prisma/OpenAI/LiveKit create HTTP clients. It
must not create any provider async client or gRPC channel; it only prepares the
standard SSL contexts before the LiveKit event loop starts.
"""
from __future__ import annotations

import logging
import os
import ssl
import sys
from types import ModuleType
from typing import Any, Callable

logger = logging.getLogger("voice-agent-saas-bootstrap")


_cache: dict[tuple[str | None, str | None], ssl.SSLContext] = {}


def _key(cafile: str | None = None, capath: str | None = None) -> tuple[str | None, str | None]:
    return (cafile or os.getenv("SSL_CERT_FILE"), capath or os.getenv("SSL_CERT_DIR"))


def _get_ssl_context(cafile: str | None = None, capath: str | None = None) -> ssl.SSLContext:
    """Build a context during process bootstrap and retain it by trust-store key."""
    key = _key(cafile, capath)
    context = _cache.get(key)
    if context is None:
        context = ssl.create_default_context(cafile=key[0], capath=key[1])
        _cache[key] = context
    return context


def _prewarm_default_contexts() -> ssl.SSLContext:
    """Prepare the variants used by ssl, httpx, and LiveKit default paths."""
    # httpx passes (None, None) when trust_env=False, while LiveKit/httpx can
    # pass the values from the environment explicitly.  Prepare both before
    # any agent loop is started.  A platform's compiled-in CA path is included
    # because some LiveKit releases normalize the environment to that path.
    candidates = [
        (None, None),
        (os.getenv("SSL_CERT_FILE"), os.getenv("SSL_CERT_DIR")),
    ]
    try:
        paths = ssl.get_default_verify_paths()
        for cafile in (paths.cafile, paths.openssl_cafile):
            if cafile:
                candidates.append((cafile, None))
        for capath in (paths.capath, paths.openssl_capath):
            if capath:
                candidates.append((None, capath))
    except Exception:
        pass

    first: ssl.SSLContext | None = None
    for cafile, capath in candidates:
        try:
            context = _get_ssl_context(cafile, capath)
            first = first or context
        except Exception as exc:
            logger.debug("SSL context variant prewarm skipped (%r, %r): %s", cafile, capath, exc)
    if first is None:
        # Keep the original error and its useful traceback if every platform
        # variant failed; this is still process-start code, never loop code.
        first = _get_ssl_context()
    return first


def _cached_default_context(cafile: str | None, capath: str | None) -> ssl.SSLContext:
    """Return a prewarmed default without ever loading a trust store here."""
    context = _cache.get(_key(cafile, capath))
    if context is not None:
        return context
    # A LiveKit version may normalize a default path differently from the
    # value seen at import time.  The already loaded default context is safer
    # than invoking ssl.create_default_context on the agent loop.  Explicit
    # custom certificates are handled by the original httpx path below.
    return next(iter(_cache.values()))


def _replace_direct_references(module: ModuleType, original: Callable[..., Any], replacement: Callable[..., Any]) -> None:
    """Replace aliases imported with ``from httpx._config import ...``.

    httpx._client, httpx._transports.default, and generated Prisma modules have
    historically held direct references to create_ssl_context. Patching only
    httpx._config leaves those aliases pointing at the blocking implementation.
    Scan already-loaded modules by identity; modules imported later see the
    patched module attribute naturally.
    """
    for loaded in tuple(sys.modules.values()):
        if loaded is None or loaded is module:
            continue
        try:
            namespace = vars(loaded)
        except TypeError:
            continue
        for name, value in tuple(namespace.items()):
            if value is original:
                try:
                    setattr(loaded, name, replacement)
                except Exception:
                    pass


def install_ssl_context_cache() -> None:
    """Patch default LiveKit/httpx SSL construction before event-loop use."""
    try:
        default_context = _prewarm_default_contexts()

        from livekit.agents.utils import http_context

        original_livekit = http_context._create_ssl_context

        def cached_livekit(cafile=None, capath=None):
            # This wrapper must not call ssl.create_default_context.  In
            # particular, LiveKit may supply a normalized path that differs
            # from the environment key used during bootstrap.
            return _cached_default_context(cafile, capath) or default_context

        if getattr(http_context, "_voice_ssl_context_patched", False) is not True:
            http_context._create_ssl_context = cached_livekit
            http_context._voice_ssl_context_patched = True
        else:
            # Keep the context warm even when a test/reloader invokes setup
            # more than once; do not wrap an already-wrapped function.
            cached_livekit = http_context._create_ssl_context

        try:
            import httpx._config as httpx_config

            original_httpx = httpx_config.create_ssl_context

            def cached_httpx(verify=True, cert=None, trust_env=True, **kwargs: Any):
                if verify in (True, None) and cert is None:
                    key = (
                        os.getenv("SSL_CERT_FILE") if trust_env else None,
                        os.getenv("SSL_CERT_DIR") if trust_env else None,
                    )
                    return _cached_default_context(*key)
                return original_httpx(verify=verify, cert=cert, trust_env=trust_env, **kwargs)

            if getattr(httpx_config, "_voice_ssl_context_patched", False) is not True:
                httpx_config.create_ssl_context = cached_httpx
                httpx_config._voice_ssl_context_patched = True
                _replace_direct_references(httpx_config, original_httpx, cached_httpx)
        except Exception as exc:
            logger.debug("Could not patch httpx SSL context: %s", exc)

        # Warm only the pure tokenizer object; it has no provider/event-loop
        # ownership and otherwise initialized lazily on the first transcript.
        try:
            from livekit.agents.tokenize._basic_hyphenator import (
                EXCEPTIONS,
                PATTERNS,
                Hyphenator,
            )
            import livekit.agents.tokenize._basic_hyphenator as hyphenator_module

            hot_hyphenator = Hyphenator(PATTERNS, EXCEPTIONS)
            hyphenator_module._get_hyphenator = lambda: hot_hyphenator
        except Exception as exc:
            logger.debug("Hyphenator prewarm skipped: %s", exc)

        logger.info("SSL context and tokenizer prewarmed before the LiveKit agent loop")
    except Exception as exc:
        logger.debug("SSL context prewarm skipped: %s", exc)
