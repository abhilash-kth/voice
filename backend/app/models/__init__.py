"""Pydantic models for the Voice Agent SaaS platform (split into domain modules).

Provider → Multiple Models architecture:
- Provider is selectable entity (openai, groq, qwen, anthropic, google, sarvam)
- Model is selectable entity under provider (gpt-4.1-mini, gemini-2.5-flash, …)
- No silent substitution — an invalid provider/model returns a clear config
  error. LLM temperature is intentionally NOT part of the tuning config.

This package is a pure re-export façade over the per-domain modules; the
import surface is IDENTICAL to the old single-file ``app/models.py``.
"""
from .providers import (
    ProviderKind,
    CallMode,
    AgentMode,
    ProviderPair,
    LLMProviderSelection,
    ProviderSelection,
)
from .agent_models import (
    KnowledgeItem,
    KnowledgeBase,
    AgentConfig,
    AgentCreate,
    AgentUpdate,
)
from .records import (
    CallRecord,
    Recharge,
    Wallet,
    RegisterBody,
    LoginBody,
    UserOut,
)

__all__ = [
    "ProviderKind", "CallMode", "AgentMode",
    "ProviderPair", "LLMProviderSelection", "ProviderSelection",
    "KnowledgeItem", "KnowledgeBase",
    "AgentConfig", "AgentCreate", "AgentUpdate",
    "CallRecord", "Recharge", "Wallet",
    "RegisterBody", "LoginBody", "UserOut",
]
