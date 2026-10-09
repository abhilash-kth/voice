"""Google Gemini model definitions (seed data; DB CatalogModel takes precedence).

Extracted from the old monolithic models_data — identical entries, one file per provider.
LLM temperature is intentionally NOT part of any entry.
"""
from __future__ import annotations

from typing import Any, Dict, List

MODELS_GOOGLE: List[Dict[str, Any]] = [

    # -------------------- Google Gemini provider models --------------------
    {
        "provider": "google",
        "model_id": "gemini-2.5-flash-lite",
        "display_name": "Gemini 2.5 Flash-Lite",
        "base_url": "",
        "input_price_per_1m": 0.10,
        "cached_input_price_per_1m": 0.02,
        "output_price_per_1m": 0.40,
        "context_window": 1048576,
        "max_output_tokens": 65536,
        "reasoning_supported": True,
        "reasoning_default": "none",
        "streaming_supported": True,
        "tool_calling_supported": True,
        "structured_output_supported": True,
        "expected_speed": "very_fast",
        "status": "active",
        "capabilities": ["chat", "tools", "vision", "multilingual"],
        "notes": "⭐ Recommended for voice. Cheapest+fastest Gemini ($0.10/$0.40 per 1M), sub-second TTFT, thinking off by default. Strong Hinglish/Indian-English.",
        "tier": "paid", "voice_recommended": True,
        "reasoning_effort_options": ["none", "low", "high"],
    },
    {
        "provider": "google",
        "model_id": "gemini-2.5-flash",
        "display_name": "Gemini 2.5 Flash",
        "base_url": "",
        "input_price_per_1m": 0.30,
        "cached_input_price_per_1m": 0.075,
        "output_price_per_1m": 2.50,
        "context_window": 1048576,
        "max_output_tokens": 65536,
        "reasoning_supported": True,
        "reasoning_default": "low",
        "streaming_supported": True,
        "tool_calling_supported": True,
        "structured_output_supported": True,
        "expected_speed": "fast",
        "status": "active",
        "capabilities": ["chat", "reasoning", "tools", "vision", "multilingual"],
        "notes": "Higher-quality Gemini ($0.30/$2.50). Pick if Flash-Lite answers feel thin; keep thinking budget 0/low for voice.",
        "tier": "paid",
        "reasoning_effort_options": ["none", "low", "medium", "high"],
    },
]
