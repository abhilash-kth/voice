"""
Pydantic models for the Voice Agent SaaS platform.

These are intentionally decoupled from LiveKit so the FastAPI layer can import
them without pulling the heavy AI/agent dependencies.
"""
from __future__ import annotations

from typing import Optional, List, Literal, Any
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums / literals
# ---------------------------------------------------------------------------
ProviderKind = Literal["llm", "stt", "tts", "telephony"]
CallMode = Literal["browser", "sip"]
# agent_mode:
#   "assistant"   -> full conversation (STT + LLM + TTS)
#   "announcement"-> fixed-script reminder: TTS only plays the script, then hangs up.
#                    No STT, no LLM.
AgentMode = Literal["assistant", "announcement"]


class ProviderPair(BaseModel):
    """A provider id + optional config override, chosen by the customer."""
    id: str
    # free-form overrides (api key, model, voice, speed, language...)
    config: dict[str, Any] = Field(default_factory=dict)


class ProviderSelection(BaseModel):
    llm: ProviderPair
    stt: ProviderPair
    tts: ProviderPair
    telephony: Optional[ProviderPair] = None


# ---------------------------------------------------------------------------
# Knowledge base
# ---------------------------------------------------------------------------
class KnowledgeItem(BaseModel):
    chunk_id: str
    text: str
    source: str  # "manual-text" | filename


class KnowledgeBase(BaseModel):
    text: str = ""
    documents: List[dict[str, Any]] = Field(default_factory=list)  # {name, chunks}
    system_prompt: str = ""
    # Structured FAQ: [{q, a}]
    faq: List[dict[str, Any]] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Agent configuration
# ---------------------------------------------------------------------------
class AgentConfig(BaseModel):
    id: str
    name: str
    description: str = ""
    greeting: str = ""
    providers: ProviderSelection
    knowledge: KnowledgeBase = Field(default_factory=KnowledgeBase)
    language: str = "hi"
    voice_personality: str = "friendly"
    client_rate_per_min: float = 2.50
    memory_enabled: bool = True
    recording_enabled: bool = True
    max_concurrency: int = 1
    created_at: str = ""
    enabled: bool = True
    # "assistant" (STT+LLM+TTS) or "announcement" (fixed-script only, no STT/LLM).
    agent_mode: str = "assistant"
    # The fixed script spoken in "announcement" mode; falls back to `greeting`.
    announce_text: str = ""


class AgentCreate(BaseModel):
    name: str
    description: str = ""
    greeting: str = ""
    providers: ProviderSelection
    knowledge: KnowledgeBase = Field(default_factory=KnowledgeBase)
    language: str = "hi"
    voice_personality: str = "friendly"
    client_rate_per_min: float = 2.50
    memory_enabled: bool = True
    recording_enabled: bool = True
    max_concurrency: int = 1
    enabled: bool = True
    agent_mode: str = "assistant"
    announce_text: str = ""


class AgentUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    greeting: Optional[str] = None
    providers: Optional[ProviderSelection] = None
    knowledge: Optional[KnowledgeBase] = None
    language: Optional[str] = None
    voice_personality: Optional[str] = None
    client_rate_per_min: Optional[float] = None
    memory_enabled: Optional[bool] = None
    recording_enabled: Optional[bool] = None
    max_concurrency: Optional[int] = None
    enabled: Optional[bool] = None
    agent_mode: Optional[str] = None
    announce_text: Optional[str] = None


# ---------------------------------------------------------------------------
# Calls
# ---------------------------------------------------------------------------
class CallRecord(BaseModel):
    id: str
    agent_id: str
    mode: CallMode
    room: str
    phone: Optional[str] = None
    status: str = "planned"           # planned | in-progress | completed | failed
    started_at: str = ""
    ended_at: str = ""
    duration_seconds: int = 0
    transcripts: List[dict[str, Any]] = Field(default_factory=list)
    recording_url: Optional[str] = None
    # cost breakdown (see billing.py)
    cost: dict[str, Any] = Field(default_factory=dict)
    usage: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Wallet / recharge
# ---------------------------------------------------------------------------
class Recharge(BaseModel):
    add_amount: float


class Wallet(BaseModel):
    balance: float = 0.0
    currency: str = "INR"
    transactions: List[dict[str, Any]] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
class RegisterBody(BaseModel):
    email: str
    password: str
    name: str = ""


class LoginBody(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    id: str
    email: str
    name: str
    wallet_balance: float
    created_at: str
