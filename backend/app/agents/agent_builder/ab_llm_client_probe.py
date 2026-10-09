"""Instrumented AsyncOpenAI client build: httpx transport + send/headers/error
event hooks, per-request rid wiring, provider-bound cache fingerprint probes.
Extracted 1:1 from `agent_builder/ab_llm_pair.py` (<=300-line rule).
"""
from __future__ import annotations

import logging
import time

from openai import AsyncOpenAI

logger = logging.getLogger("voice-agent-saas-agent-builder")


def build_instrumented_http_client(api_key, base_url, provider, model_id, _native_google):
    import uuid as _uuid_mod
    import httpx as _httpx
    from .. import http_timing as _http_timing
    _http_inst = {"n": 0}

    async def _on_http_send(_request):
        try:
            _http_inst["n"] += 1
            _rid = _uuid_mod.uuid4().hex[:8]
            # extensions is httpx-internal metadata, never sent on the wire
            _request.extensions["voice_rid"] = _rid
            _http_timing.note_send(model_id, _rid)
            # httpx's request hook is before transport acquisition. httpcore's
            # trace extension separates connection-pool wait, DNS/TCP/TLS,
            # upload and response-header wait without touching the stream.
            _trace_events = {}
            async def _trace(_name, _info):
                try:
                    _phase, _edge = _name.rsplit(".", 1)
                    _trace_events.setdefault(_phase, {})[_edge] = time.perf_counter()
                except Exception:
                    pass
            _request.extensions["trace"] = _trace
            _http_timing.set_trace(_rid, _trace_events)
            # Critical-path: log REQUEST_START immediately without blocking work.
            # The old code did JSON decode + hashing synchronously on the event
            # loop (107ms block warning) — that adds directly to
            # request_start->response_headers and delays audio/turn handling.
            logger.info(
                "\U0001f310 [HTTP_REQUEST_START] monotonic_ns=%d rid=%s model=%s client_attempt#%d sdk_retry_count=%s path=%s — one send of one chat() attempt (see B/C distinction in builder comment; SDK retries are disabled by max_retries=0)",
                time.monotonic_ns(), _rid, model_id, _http_inst["n"],
                _request.headers.get("x-stainless-retry-count", "absent"),
                _request.url.path,
            )
            # --- Provider-bound fingerprint off critical path ---
            # Offload JSON parsing + hashing to a background task / thread so it
            # never blocks the agent event loop. Cache is FIXED and working
            # (1792 hit), so diagnostic can be async. No PII, only hashes/lens.
            try:
                _body_snapshot = _request.content  # bytes, safe to capture
                if _body_snapshot:
                    import asyncio as _aio2

                    def _parse_fp():
                        try:
                            import json as _js
                            import hashlib as _hl2

                            _j = _js.loads(
                                _body_snapshot.decode("utf-8", "ignore")
                                if isinstance(_body_snapshot, (bytes, bytearray))
                                else str(_body_snapshot)
                            )
                            _pck = _j.get("prompt_cache_key", "?")
                            _msgs = _j.get("messages", []) or []
                            _role_seq = ",".join([str(m.get("role", "?")) for m in _msgs])
                            _len_seq = ",".join([str(len(str(m.get("content", "")))) for m in _msgs])
                            _first_c = str(_msgs[0].get("content", "")) if _msgs else ""
                            _first_hash = (
                                _hl2.sha256(_first_c.encode("utf-8", "ignore")).hexdigest()[:12]
                                if _first_c
                                else "?"
                            )
                            _pref_c = "".join([str(m.get("content", "")) for m in _msgs[:2]])
                            _pref_hash = (
                                _hl2.sha256(_pref_c.encode("utf-8", "ignore")).hexdigest()[:12]
                                if _pref_c
                                else "?"
                            )
                            return (_pck, len(_msgs), _role_seq, _len_seq, _first_hash, _pref_hash)
                        except Exception:
                            return None

                    async def _log_fp():
                        try:
                            _res = await _aio2.to_thread(_parse_fp)
                            if _res is None:
                                return
                            _pck, _cnt, _role_seq, _len_seq, _first_hash, _pref_hash = _res
                            logger.info(
                                "\U0001f50d [HTTP_BODY_FINGERPRINT] rid=%s model=%s prompt_cache_key=%s prov_messages=%d role_seq=%s len_seq=%s first_hash=%s prefix_hash=%s",
                                _rid, model_id, _pck, _cnt, _role_seq, _len_seq, _first_hash, _pref_hash,
                            )
                        except Exception as _e:
                            logger.debug(f"[HTTP_BODY_FINGERPRINT] failed: {_e!r}")

                    _aio2.create_task(_log_fp())
            except Exception as _e:
                logger.debug(f"[HTTP_BODY_FINGERPRINT] schedule failed: {_e!r}")
        except Exception:
            pass

    async def _on_http_headers(_response):
        try:
            _rid = _response.request.extensions.get("voice_rid", "?")
            _el = _http_timing.note_headers(_rid, _response.status_code)
            _transport = _http_timing.trace_summary(_rid)
            logger.info(
                "\U0001f310 [HTTP_RESPONSE_HEADERS] monotonic_ns=%d rid=%s model=%s status=%d request_start->response_headers=%s transport=%s — headers boundary only; first streamed body bytes come later (see [HTTP_CHUNK])",
                time.monotonic_ns(), _rid, model_id, _response.status_code,
                ("%.0fms" % _el) if _el >= 0 else "?",
                _transport or "no_trace_events",
            )
        except Exception:
            pass

    async def _on_http_error(_request):
        try:
            _rid = _request.extensions.get("voice_rid", "?")
            logger.warning(
                "\U0001f310 [HTTP_ERROR] rid=%s model=%s — transport-level failure (connect/pool/read). The 02:31 TypeError regression came from sync hooks being awaited by httpx; hooks are async since that fix, so a line here now means a real network problem.",
                _rid, model_id,
            )
        except Exception:
            pass

    client = None if _native_google else AsyncOpenAI(
        api_key=api_key, base_url=base_url, max_retries=0,
        http_client=_httpx.AsyncClient(
            event_hooks={"request": [_on_http_send], "response": [_on_http_headers], "error": [_on_http_error]},
            follow_redirects=True,
            limits=_httpx.Limits(max_connections=50, max_keepalive_connections=50, keepalive_expiry=120.0),
            timeout=_httpx.Timeout(connect=15.0, read=5.0, write=5.0, pool=5.0),
        ),
    )
    return client
