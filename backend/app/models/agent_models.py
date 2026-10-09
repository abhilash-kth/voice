"""Agent configuration + knowledge base models."""
from __future__ import annotations

from typing import Optional, List, Any, Dict
from pydantic import BaseModel, Field

from .providers import ProviderSelection


# ---------------------------------------------------------------------------
# Knowledge base
# ---------------------------------------------------------------------------
class KnowledgeItem(BaseModel):
    chunk_id: str
    text: str
    source: str  # "manual-text" | filename


class KnowledgeBase(BaseModel):
    text: str = ""
    documents: List[Dict[str, Any]] = Field(default_factory=list)  # {name, chunks}
    system_prompt: str = ""
    # Structured FAQ: [{q, a}]
    faq: List[Dict[str, Any]] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Agent configuration
# ---------------------------------------------------------------------------
class AgentConfig(BaseModel):
    id: str
    name: str
    description: str = ""
    greeting: str = ""
    providers: ProviderSelection = Field(default_factory=ProviderSelection)
    knowledge: KnowledgeBase = Field(default_factory=KnowledgeBase)
    language: str = "hi"
    # Voice gender: drives the TTS voice (Google Chirp3 speaker / Sarvam Bulbul speaker)
    # and helps STT pick the right acoustic expectations.
    gender: str = "female"
    voice_personality: str = "friendly"
    client_rate_per_min: float = 2.50
    memory_enabled: bool = True
    recording_enabled: bool = True
    max_concurrency: int = 1
    # Normalized user-side voice speed (min/max default from Super Admin's
    # BillingConfig). Mapped per-TTS-provider only for adapters with a native
    # speed knob; never sent for providers that do not support it.
    voice_speed: float = 1.0
    created_at: str = ""
    enabled: bool = True
    agent_mode: str = "assistant"
    announce_text: str = ""
    end_after_announcement: bool = False
    fallback_response: str = "Sorry, there is a temporary technical problem. Please try again shortly."
    no_response_timeout_seconds: int = 30
    no_response_message: str = "I did not hear a response, so I will end the call now. Thank you for calling."


class AgentCreate(BaseModel):
    name: str
    description: str = ""
    greeting: str = ""
    providers: ProviderSelection
    knowledge: KnowledgeBase = Field(default_factory=KnowledgeBase)
    language: str = "hi"
    # Voice gender: drives the TTS voice (Google Chirp3 speaker / Sarvam Bulbul speaker)
    # and helps STT pick the right acoustic expectations.
    gender: str = "female"
    voice_personality: str = "friendly"
    client_rate_per_min: float = 2.50
    memory_enabled: bool = True
    recording_enabled: bool = True
    max_concurrency: int = 1
    voice_speed: float = 1.0
    enabled: bool = True
    agent_mode: str = "assistant"
    announce_text: str = ""
    end_after_announcement: bool = False
    fallback_response: str = "Sorry, there is a temporary technical problem. Please try again shortly."
    no_response_timeout_seconds: int = 30
    no_response_message: str = "I did not hear a response, so I will end the call now. Thank you for calling."


class AgentUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    greeting: Optional[str] = None
    providers: Optional[ProviderSelection] = None
    knowledge: Optional[KnowledgeBase] = None
    language: Optional[str] = None
    gender: Optional[str] = None
    voice_personality: Optional[str] = None
    client_rate_per_min: Optional[float] = None
    memory_enabled: Optional[bool] = None
    recording_enabled: Optional[bool] = None
    max_concurrency: Optional[int] = None
    voice_speed: Optional[float] = None
    enabled: Optional[bool] = None
    agent_mode: Optional[str] = None
    announce_text: Optional[str] = None
    end_after_announcement: Optional[bool] = None
    fallback_response: Optional[str] = None
    no_response_timeout_seconds: Optional[int] = None
    no_response_message: Optional[str] = None
