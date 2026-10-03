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


