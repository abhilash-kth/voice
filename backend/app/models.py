"""
Pydantic models for the Voice Agent SaaS platform - V2 Provider → Multiple Models.

Provider → Multiple Models architecture:
- Provider is selectable entity (openai, groq, openrouter)
- Model is selectable entity under provider (gpt-4.1, gpt-4.1-mini, etc.)
- Each model has rich metadata (pricing, context, capabilities, speed)
- No silent substitution, invalid provider/model returns clear config error
"""
from __future__ import annotations

from typing import Optional, List, Literal, Any, Dict
from pydantic import BaseModel, Field, model_validator


# ---------------------------------------------------------------------------
# Enums / literals
# ---------------------------------------------------------------------------
ProviderKind = Literal["llm", "stt", "tts", "telephony"]
CallMode = Literal["browser", "sip"]
AgentMode = Literal["assistant", "announcement"]


class ProviderPair(BaseModel):
    """A provider id + optional config override, chosen by customer.
    
    V2: Supports both old style (id = openai_gpt_4_1_mini) and new style
    (id = openai, config.model = gpt-4.1-mini).
    
    For LLM, prefer new style: id = provider, config.model = model_id
    Provider and model remain separate fields.
    """
    id: str
    # free-form overrides (api key, model, voice, speed, language...)
    config: Dict[str, Any] = Field(default_factory=dict)
    
    def resolve_llm_provider_model(self) -> tuple[str, str, str]:
        """
        Resolve to (provider, model_id, base_url) for LLM.
        Handles both old and new style ids.
        Returns provider, model_id, base_url.
        Does NOT silently substitute - returns exactly what user selected or legacy mapping.
        """
        # Old id mapping for backward compat
        old_mapping = {
            "openai_gpt_4o_mini": ("openai", "gpt-4o-mini", "https://api.openai.com/v1"),
            "openai_gpt_4o": ("openai", "gpt-4o", "https://api.openai.com/v1"),
            "openai_gpt_4_1_mini": ("openai", "gpt-4.1-mini", "https://api.openai.com/v1"),
            "openai_gpt_4_1": ("openai", "gpt-4.1", "https://api.openai.com/v1"),
            "openai_gpt_oss_120b": ("openai", "gpt-4o", "https://api.openai.com/v1"),  # Old invalid, now valid
            "groq_gpt_oss": ("groq", "openai/gpt-oss-120b", "https://api.groq.com/openai/v1"),
            "groq_gpt_oss_20b": ("groq", "openai/gpt-oss-20b", "https://api.groq.com/openai/v1"),
            "groq_llama_3_3_70b": ("groq", "llama-3.3-70b-versatile", "https://api.groq.com/openai/v1"),
            "groq_qwen_3_8_27b": ("groq", "qwen/qwen3-32b", "https://api.groq.com/openai/v1"),
            "openrouter_gemma": ("openrouter", "google/gemma-3-27b-it:free", "https://openrouter.ai/api/v1"),
            "openrouter_gemma_26b": ("openrouter", "google/gemma-3-12b-it:free", "https://openrouter.ai/api/v1"),
        }
        
        # If id is old style, use mapping but preserve exact model from config if present
        if self.id in old_mapping:
            prov, model, base_url = old_mapping[self.id]
            # If config has model override, use that (user explicitly set)
            model_override = self.config.get("model")
            if model_override:
                model = model_override
            base_override = self.config.get("base_url")
            if base_override:
                base_url = base_override
            return prov, model, base_url
        
        # New style: id is provider (openai, groq, openrouter)
        # Model comes from config.model or catalog default
        if self.id in ("openai", "groq", "openrouter"):
            provider = self.id
            model = self.config.get("model", "")
            base_url = self.config.get("base_url", "")
            # If no model in config, try to get default from catalog
            if not model:
                # Will be resolved in agent_builder from catalog
                model = ""
            if not base_url:
                if provider == "openai":
                    base_url = "https://api.openai.com/v1"
                elif provider == "groq":
                    base_url = "https://api.groq.com/openai/v1"
                elif provider == "openrouter":
                    base_url = "https://openrouter.ai/api/v1"
            return provider, model, base_url
        
        # Fallback: treat id as provider if it matches known providers, or as model_id
        # For backward compat with direct model_id usage
        if self.id in ("openai", "groq", "openrouter"):
            return self.id, self.config.get("model", ""), self.config.get("base_url", "")
        
        # If id looks like model_id (contains / or -), try to infer provider from config or mapping
        # This handles case where user selected model directly
        model_id = self.id
        # Check if config has provider
        prov_from_config = self.config.get("provider", "")
        if prov_from_config:
            return prov_from_config, model_id, self.config.get("base_url", "")
        
        # Infer provider from model_id pattern
        if "/" in model_id and model_id.startswith("openai/"):
            # Could be groq model openai/gpt-oss-120b
            if "gpt-oss" in model_id:
                return "groq", model_id, "https://api.groq.com/openai/v1"
        if model_id.startswith("gpt-") or model_id in ("o1", "o3-mini", "o4-mini"):
            return "openai", model_id, "https://api.openai.com/v1"
        if ":free" in model_id or "gemma" in model_id or "llama" in model_id.lower():
            return "openrouter", model_id, "https://openrouter.ai/api/v1"
        
        # Last resort: return id as provider, model from config
        return self.id, self.config.get("model", ""), self.config.get("base_url", "")

    def get_model_metadata(self) -> Optional[Dict[str, Any]]:
        """Get model metadata from catalog for this provider/model."""
        try:
            from .llm_catalog import get_llm_model, get_llm_model_by_id
            prov, model_id, _ = self.resolve_llm_provider_model()
            if prov and model_id:
                meta = get_llm_model(prov, model_id)
                if meta:
                    return meta
            # Try by model_id alone
            if model_id:
                return get_llm_model_by_id(model_id)
            # Try by id as model_id
            return get_llm_model_by_id(self.id)
        except Exception:
            return None


class LLMProviderSelection(BaseModel):
    """New V2 LLM selection: provider + model_id separate, with rich metadata."""
    provider: str = Field(..., description="Provider id: openai, groq, openrouter")
    model_id: str = Field(..., description="Model id: gpt-4.1-mini, openai/gpt-oss-120b, etc.")
    base_url: Optional[str] = Field(None, description="Base URL override, optional")
    config: Dict[str, Any] = Field(default_factory=dict, description="Additional config: temperature, max_tokens, etc.")
    
    @model_validator(mode='after')
    def validate_provider_model(self):
        """Validate provider/model combination, no silent substitution."""
        try:
            from .llm_catalog import validate_provider_model
            is_valid, msg = validate_provider_model(self.provider, self.model_id)
            if not is_valid:
                raise ValueError(msg)
        except ImportError:
            pass
        return self
    
    def to_provider_pair(self) -> ProviderPair:
        """Convert to ProviderPair for backward compat runtime."""
        cfg = dict(self.config)
        cfg["model"] = self.model_id
        if self.base_url:
            cfg["base_url"] = self.base_url
        cfg["provider"] = self.provider
        return ProviderPair(id=self.provider, config=cfg)
    
    def get_metadata(self) -> Optional[Dict[str, Any]]:
        try:
            from .llm_catalog import get_llm_model
            return get_llm_model(self.provider, self.model_id)
        except Exception:
            return None


class ProviderSelection(BaseModel):
    llm: Optional[ProviderPair] = None
    stt: Optional[ProviderPair] = None
    tts: Optional[ProviderPair] = None
    telephony: Optional[ProviderPair] = None
    # Optional fallback providers — used when primary hits 429/rate-limit
    llm_fallback: Optional[ProviderPair] = None
    stt_fallback: Optional[ProviderPair] = None
    tts_fallback: Optional[ProviderPair] = None
    
    # New V2 fields for LLM with provider/model separate (optional, for new UI)
    llm_v2: Optional[LLMProviderSelection] = None
    llm_fallback_v2: Optional[LLMProviderSelection] = None
    
    @model_validator(mode='after')
    def validate_llm(self):
        """Validate LLM provider/model if v2 fields present."""
        if self.llm_v2:
            # Use v2 validation
            try:
                from .llm_catalog import validate_provider_model
                is_valid, msg = validate_provider_model(self.llm_v2.provider, self.llm_v2.model_id)
                if not is_valid:
                    raise ValueError(f"Primary LLM invalid: {msg}")
            except ImportError:
                pass
        if self.llm_fallback_v2:
            try:
                from .llm_catalog import validate_provider_model
                is_valid, msg = validate_provider_model(self.llm_fallback_v2.provider, self.llm_fallback_v2.model_id)
                if not is_valid:
                    raise ValueError(f"Fallback LLM invalid: {msg}")
            except ImportError:
                pass
        return self
    
    def get_primary_llm(self) -> Optional[ProviderPair]:
        """Get primary LLM as ProviderPair, preferring v2 if present."""
        if self.llm_v2:
            return self.llm_v2.to_provider_pair()
        return self.llm
    
    def get_fallback_llm(self) -> Optional[ProviderPair]:
        """Get fallback LLM as ProviderPair, preferring v2 if present."""
        if self.llm_fallback_v2:
            return self.llm_fallback_v2.to_provider_pair()
        return self.llm_fallback


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
    enabled: Optional[bool] = None
    agent_mode: Optional[str] = None
    announce_text: Optional[str] = None
    end_after_announcement: Optional[bool] = None
    fallback_response: Optional[str] = None
    no_response_timeout_seconds: Optional[int] = None
    no_response_message: Optional[str] = None


# ---------------------------------------------------------------------------
# Calls with LLM cost tracking
# ---------------------------------------------------------------------------
class CallRecord(BaseModel):
    id: str
    agent_id: str
    mode: CallMode
    room: str
    phone: Optional[str] = None
    status: str = "planned"
    started_at: str = ""
    ended_at: str = ""
    duration_seconds: int = 0
    transcripts: List[Dict[str, Any]] = Field(default_factory=list)
    recording_url: Optional[str] = None
    cost: Dict[str, Any] = Field(default_factory=dict)
    usage: Dict[str, Any] = Field(default_factory=dict)
    # New: LLM detailed tracking
    llm_provider: Optional[str] = None
    llm_model: Optional[str] = None
    llm_usage: Optional[Dict[str, Any]] = None  # input_tokens, cached_input_tokens, output_tokens, costs, TTFT, generation_time


# ---------------------------------------------------------------------------
# Wallet / recharge
# ---------------------------------------------------------------------------
class Recharge(BaseModel):
    add_amount: float


class Wallet(BaseModel):
    balance: float = 0.0
    currency: str = "INR"
    transactions: List[Dict[str, Any]] = Field(default_factory=list)


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
