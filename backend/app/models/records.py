"""Runtime records: calls, wallet, auth request/response bodies."""
from __future__ import annotations

from typing import Optional, List, Any, Dict
from pydantic import BaseModel, Field

from .providers import CallMode


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
    # Used by the PUBLIC /api/auth/register (always creates USER) and by the
    # key-protected one-time /api/setup/super-admin. Deliberately NO role
    # field: callers can never pick their own role.
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
