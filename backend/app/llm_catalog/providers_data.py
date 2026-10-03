"""LLM provider definitions (static seed data — the DB copy in the Provider
table is the live source; this code copy is the fallback when the DB snapshot
is unavailable).

Each provider has: provider id, display_name, base_url, key_env, tier,
provider_type. Merged with DB rows by services/config_store.
"""
from __future__ import annotations

from typing import Any, Dict

LLM_PROVIDERS: Dict[str, Dict[str, Any]] = {
    "openai": {
        "id": "openai",
        "display_name": "OpenAI",
        "provider_type": "openai",  # backend plugin type
        "base_url": "https://api.openai.com/v1",
        "key_env": "OPENAI_API_KEY",
        "tier": "paid",
        "requires_key": True,
        "notes": "Direct OpenAI API. Supports gpt-4.1, gpt-5 families.",
    },
    "groq": {
        "id": "groq",
        "display_name": "Groq (free tier)",
        "provider_type": "openai",  # Groq uses OpenAI-compatible API
        "base_url": "https://api.groq.com/openai/v1",
        "key_env": "GROQ_API_KEY",
        "tier": "free",
        "requires_key": True,
        "notes": "Groq's OpenAI-compatible endpoint on LPU hardware. Only current, non-deprecated free models are listed (llama-3.1-8b, llama-3.3-70b, qwen3-32b, llama-4-scout were retired by Groq in Jul-Aug 2026).",
    },
    "google": {
        "id": "google",
        "display_name": "Google Gemini",
        "provider_type": "google",
        "base_url": "",  # native plugin; no REST base_url needed
        "key_env": "GEMINI_API_KEY",
        "tier": "paid",
        "requires_key": True,
        "notes": "Native Gemini via livekit-plugins-google. Flash-Lite = cheapest/fastest (best for voice), Flash = higher quality.",
    },
    "sarvam": {
        "id": "sarvam",
        "display_name": "Sarvam AI (Indic)",
        "provider_type": "sarvam",  # OpenAI-compatible base_url
        "base_url": "https://api.sarvam.ai",
        "key_env": "SARVAM_API_KEY",
        "tier": "paid",
        "requires_key": True,
        "notes": "Bengaluru-built full Indic stack. sarvam-30b is the low-latency pick; 105b for higher quality. Priced in INR, matched by Bulbul TTS + Saaras STT.",
    },
    "openrouter": {
        "id": "openrouter",
        "display_name": "OpenRouter (removed)",
        "provider_type": "openrouter",
        "base_url": "https://openrouter.ai/api/v1",
        "key_env": "OPENROUTER_API_KEY",
        "tier": "free",
        "requires_key": True,
        "status": "deprecated",
        "notes": "Removed from the picker — extra proxy hop adds latency and :free models rate-limit mid-call. Kept in the catalog so existing saved agents keep working.",
    },
}

# ---------------------------------------------------------------------------
# Model catalog - Provider → Multiple Models
# Based on currently supported API models (2025-2026)
# Pricing from OpenAI and Groq official pricing
# ---------------------------------------------------------------------------
