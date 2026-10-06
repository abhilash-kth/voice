"""Pydantic request/response schemas for the Super Admin API.

Conventions: request bodies use snake_case; money/price fields are validated
here (range-checked) BEFORE reaching the service layer; no secret ever appears
in a response model (credentials expose only ``masked_value``).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Literal

from pydantic import BaseModel, Field

Kind = Literal["llm", "stt", "tts", "telephony"]
Status = Literal["active", "deprecated"]
Role = Literal["USER", "SUPER_ADMIN"]
CredStatus = Literal["active", "disabled", "rotated"]


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
class Page(BaseModel):
    page: int = 1
    page_size: int = Field(50, ge=1, le=200)


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------
class RoleUpdateBody(BaseModel):
    role: Role


class DisabledBody(BaseModel):
    disabled: bool


class WalletAdjustBody(BaseModel):
    amount: float = Field(..., gt=0, le=10_000_000)
    note: str = ""


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------
class ProviderCreateBody(BaseModel):
    kind: Kind
    slug: str = Field(..., min_length=1, max_length=64)
    display_name: str = Field("", max_length=200)
    adapter: str = Field("", max_length=64)
    base_url: str = Field("", max_length=300)
    key_env: str = Field("", max_length=64)
    tier: str = "paid"
    requires_key: bool = True
    enabled: bool = False
    notes: str = ""
    sort_order: int = 0


class ProviderUpdateBody(BaseModel):
    display_name: Optional[str] = Field(None, max_length=200)
    adapter: Optional[str] = Field(None, max_length=64)
    base_url: Optional[str] = Field(None, max_length=300)
    key_env: Optional[str] = Field(None, max_length=64)
    tier: Optional[str] = None
    requires_key: Optional[bool] = None
    enabled: Optional[bool] = None
    status: Optional[Status] = None
    notes: Optional[str] = None
    sort_order: Optional[int] = None


# ---------------------------------------------------------------------------
# Catalog models
# ---------------------------------------------------------------------------
class ModelCreateBody(BaseModel):
    kind: Kind
    provider_id: str
    catalog_id: str = Field(..., min_length=1, max_length=128)
    model_id: str = Field("", max_length=200)
    display_name: str = Field("", max_length=200)
    enabled: bool = False
    tier: str = "paid"
    customer_price_per_min: float = Field(0, ge=0, le=100000)
    price_currency: str = "INR"
    input_price_per_1m: float = Field(0, ge=0, le=100000)
    cached_input_price_per_1m: float = Field(0, ge=0, le=100000)
    output_price_per_1m: float = Field(0, ge=0, le=100000)
    cost_per_min: float = Field(0, ge=0, le=100000)
    cost_per_1k_chars: float = Field(0, ge=0, le=100000)
    meta: Dict[str, Any] = Field(default_factory=dict)
    sort_order: int = 0


class ModelUpdateBody(BaseModel):
    display_name: Optional[str] = Field(None, max_length=200)
    enabled: Optional[bool] = None
    status: Optional[Status] = None
    tier: Optional[str] = None
    customer_price_per_min: Optional[float] = Field(None, ge=0, le=100000)
    price_currency: Optional[str] = None
    input_price_per_1m: Optional[float] = Field(None, ge=0, le=100000)
    cached_input_price_per_1m: Optional[float] = Field(None, ge=0, le=100000)
    output_price_per_1m: Optional[float] = Field(None, ge=0, le=100000)
    cost_per_min: Optional[float] = Field(None, ge=0, le=100000)
    cost_per_1k_chars: Optional[float] = Field(None, ge=0, le=100000)
    meta: Optional[Dict[str, Any]] = None
    sort_order: Optional[int] = None


# ---------------------------------------------------------------------------
# Credentials (secrets flow IN here; they never flow OUT)
# ---------------------------------------------------------------------------
class CredentialCreateBody(BaseModel):
    provider_id: str
    value: str = Field(..., min_length=1, max_length=4096)
    label: str = Field("", max_length=200)


class CredentialUpdateBody(BaseModel):
    value: Optional[str] = Field(None, min_length=1, max_length=4096)
    label: Optional[str] = Field(None, max_length=200)


class CredentialStatusBody(BaseModel):
    status: CredStatus


class CredentialRotateBody(BaseModel):
    new_value: str = Field(..., min_length=1, max_length=4096)
    label: str = Field("", max_length=200)


# ---------------------------------------------------------------------------
# Billing
# ---------------------------------------------------------------------------
class BillingUpdateBody(BaseModel):
    server_cost_per_min: Optional[float] = None
    min_client_price: Optional[float] = None
    profit_margin_percent: Optional[float] = None
    wallet_topup_amounts: Optional[List[float]] = None
    voice_speed_min: Optional[float] = None
    voice_speed_max: Optional[float] = None
    voice_speed_default: Optional[float] = None
    # Per-mode flat customer pricing + surcharges (see app/billing_rates.py)
    announcement_price_per_min: Optional[float] = None
    assistant_price_per_min: Optional[float] = None
    misc_fee_per_min: Optional[float] = None
    concurrency_addons: Optional[List[Dict[str, Any]]] = None
