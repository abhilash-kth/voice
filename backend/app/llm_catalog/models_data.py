"""LLM model catalog (static seed data — merged with the DB CatalogModel rows
by services/config_store; only Super-Admin-enabled entries surface to users).

Each model has: provider, model_id, display_name, base_url (optional override),
input_price_per_1m, cached_input_price_per_1m, output_price_per_1m,
context_window, max_output_tokens, reasoning_supported, reasoning_default,
streaming_supported, tool_calling_supported, structured_output_supported,
expected_speed, status, capabilities, notes.

No silent model substitution. Invalid provider/model returns clear config error.
LLM temperature is intentionally NOT part of the model metadata.

The entries themselves live in ``app/llm_catalog/models/<provider>.py`` —
one file per provider, to keep every source file small and reviewable.
"""
from __future__ import annotations

from typing import Any, Dict

from .models import LLM_MODELS

__all__ = ["LLM_MODELS"]
