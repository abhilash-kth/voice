"""Per-provider LLM model entries, combined into one list in definition order.

Note on ordering: the old single list interleaved providers by section; here
each provider keeps its own file. Order does not affect behaviour — every
lookup is indexed by (provider, model_id) or model_id alone.
"""
from __future__ import annotations

from typing import Any, Dict, List

from .openai import MODELS_OPENAI
from .groq import MODELS_GROQ
from .google import MODELS_GOOGLE
from .sarvam import MODELS_SARVAM
from .openrouter import MODELS_OPENROUTER

LLM_MODELS: List[Dict[str, Any]] = [
    *MODELS_OPENAI,
    *MODELS_GROQ,
    *MODELS_GOOGLE,
    *MODELS_SARVAM,
    *MODELS_OPENROUTER,
]

__all__ = ["LLM_MODELS"]
