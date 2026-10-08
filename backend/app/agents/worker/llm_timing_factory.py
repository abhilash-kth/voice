from __future__ import annotations

import logging
from typing import Any
logger = logging.getLogger("voice-agent-saas-worker")


def _create_llm_timing_wrapper(llm_instance, timing_dict, provider_info=None, inst_label=None):
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
    import re as _re_own
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
                        _lbl = "primary/0-of-%d" % len(inner_list) if idx == 0 else "fallback/%d-of-%d" % (idx, len(inner_list))
                        # 12:28 attribution fix: the builder stamps every LLM
                        # instance with ITS OWN _prov_meta (agent_builder
                        # _pm_attach). Passing the chain HEAD's provider_info to
                        # every inner wrapper is what labelled OpenAI fallback
                        # usage as provider=groq model=qwen3.8 — cached tokens
                        # included, and priced it at the wrong model's rates.
                        _info_i = getattr(inner_llm, "_prov_meta", None) or provider_info
                        inner_list[idx] = _create_llm_timing_wrapper(inner_llm, timing_dict, _info_i, inst_label=_lbl)
                return llm_instance
    except Exception as e:
        _logger.debug(f"Could not wrap FallbackAdapter inner LLMs: {e}")

    original_chat = getattr(llm_instance, 'chat', None)
    if not original_chat:
        return llm_instance

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
            from .llm_chat_metrics import timed_chat_outer
            return timed_chat_outer(self, *args, **kwargs)

    _w = LLMTimingWrapper(llm_instance, timing_dict, provider_info)
    try:
        _w._inst_label = inst_label or "single/1"
    except Exception:
        pass
    return _w
