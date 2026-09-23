"""
LLM Provider → Multiple Models architecture.

Each provider has:
- provider id (openai, groq, openrouter)
- display_name, base_url, key_env, tier, provider_type

Each model has:
- provider, model_id, display_name, base_url (optional override), 
- input_price_per_1m, cached_input_price_per_1m, output_price_per_1m,
- context_window, max_output_tokens,
- reasoning_supported, reasoning_default,
- streaming_supported, tool_calling_supported, structured_output_supported,
- expected_speed (very_fast, fast, medium, slow),
- status (active, deprecated),
- capabilities, notes

No silent model substitution. Invalid provider/model returns clear config error.
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Provider definitions
# ---------------------------------------------------------------------------
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
LLM_MODELS: List[Dict[str, Any]] = [
    # -------------------- OpenAI provider models --------------------
    {
        "provider": "openai",
        "model_id": "gpt-4.1",
        "display_name": "GPT-4.1",
        "base_url": "https://api.openai.com/v1",
        "input_price_per_1m": 2.00,
        "cached_input_price_per_1m": 0.50,
        "output_price_per_1m": 8.00,
        "context_window": 1048576,
        "max_output_tokens": 32768,
        "reasoning_supported": False,
        "reasoning_default": None,
        "streaming_supported": True,
        "tool_calling_supported": True,
        "structured_output_supported": True,
        "expected_speed": "medium",
        "status": "deprecated",
        "capabilities": ["chat", "vision", "tools", "structured_output"],
        "notes": "1M context, strong instruction following, long-doc RAG.",
    },
    {
        "provider": "openai",
        "model_id": "gpt-4.1-mini",
        "display_name": "GPT-4.1 Mini",
        "base_url": "https://api.openai.com/v1",
        "input_price_per_1m": 0.40,
        "cached_input_price_per_1m": 0.10,
        "output_price_per_1m": 1.60,
        "context_window": 1048576,
        "max_output_tokens": 32768,
        "reasoning_supported": False,
        "reasoning_default": None,
        "streaming_supported": True,
        "tool_calling_supported": True,
        "structured_output_supported": True,
        "expected_speed": "fast",
        "status": "active",
        "capabilities": ["chat", "tools", "structured_output"],
        "notes": "Budget long-context, fast voice responses. Recommended for voice.",
    },
    {
        "provider": "openai",
        "model_id": "gpt-4.1-nano",
        "display_name": "GPT-4.1 Nano",
        "base_url": "https://api.openai.com/v1",
        "input_price_per_1m": 0.0,
        "cached_input_price_per_1m": 0.025,
        "output_price_per_1m": 0.40,
        "context_window": 1048576,
        "max_output_tokens": 32768,
        "reasoning_supported": False,
        "reasoning_default": None,
        "streaming_supported": True,
        "tool_calling_supported": True,
        "structured_output_supported": True,
        "expected_speed": "very_fast",
        "status": "active",
        "capabilities": ["chat", "tools", "structured_output"],
        "notes": "Cheapest long-context, very fast.",
    },
    {
        "provider": "openai",
        "model_id": "gpt-4o",
        "display_name": "GPT-4o",
        "base_url": "https://api.openai.com/v1",
        "input_price_per_1m": 2.50,
        "cached_input_price_per_1m": 1.25,
        "output_price_per_1m": 10.00,
        "context_window": 128000,
        "max_output_tokens": 16384,
        "reasoning_supported": False,
        "reasoning_default": None,
        "streaming_supported": True,
        "tool_calling_supported": True,
        "structured_output_supported": True,
        "expected_speed": "medium",
        "status": "deprecated",
        "capabilities": ["chat", "vision", "tools", "structured_output", "audio"],
        "notes": "Multimodal, legacy but still supported.",
    },
    {
        "provider": "openai",
        "model_id": "gpt-4o-mini",
        "display_name": "GPT-4o Mini",
        "base_url": "https://api.openai.com/v1",
        "input_price_per_1m": 0.0,
        "cached_input_price_per_1m": 0.075,
        "output_price_per_1m": 0.60,
        "context_window": 128000,
        "max_output_tokens": 16384,
        "reasoning_supported": False,
        "reasoning_default": None,
        "streaming_supported": True,
        "tool_calling_supported": True,
        "structured_output_supported": True,
        "expected_speed": "fast",
        "status": "active",
        "capabilities": ["chat", "vision", "tools", "structured_output"],
        "notes": "Cheap general chat.",
    },
    {
        "provider": "openai",
        "model_id": "gpt-5",
        "display_name": "GPT-5",
        "base_url": "https://api.openai.com/v1",
        "input_price_per_1m": 2.50,
        "cached_input_price_per_1m": 0.25,
        "output_price_per_1m": 15.00,
        "context_window": 400000,
        "max_output_tokens": 128000,
        "reasoning_supported": True,
        "reasoning_default": "medium",
        "streaming_supported": True,
        "tool_calling_supported": True,
        "structured_output_supported": True,
        "expected_speed": "medium",
        "status": "deprecated",
        "capabilities": ["chat", "reasoning", "tools", "structured_output"],
        "notes": "Flagship, unified knowledge + reasoning. Uses Responses API.",
    },
    {
        "provider": "openai",
        "model_id": "gpt-5-mini",
        "display_name": "GPT-5 Mini",
        "base_url": "https://api.openai.com/v1",
        "input_price_per_1m": 0.25,
        "cached_input_price_per_1m": 0.025,
        "output_price_per_1m": 2.00,
        "context_window": 400000,
        "max_output_tokens": 128000,
        "reasoning_supported": True,
        "reasoning_default": "medium",
        "streaming_supported": True,
        "tool_calling_supported": True,
        "structured_output_supported": True,
        "expected_speed": "fast",
        "status": "active",
        "capabilities": ["chat", "reasoning", "tools", "structured_output"],
        "notes": "GPT-5 budget, faster.",
    },
    {
        "provider": "openai",
        "model_id": "gpt-5-nano",
        "display_name": "GPT-5 Nano",
        "base_url": "https://api.openai.com/v1",
        "input_price_per_1m": 0.05,
        "cached_input_price_per_1m": 0.005,
        "output_price_per_1m": 0.40,
        "context_window": 400000,
        "max_output_tokens": 128000,
        "reasoning_supported": True,
        "reasoning_default": "low",
        "streaming_supported": True,
        "tool_calling_supported": True,
        "structured_output_supported": True,
        "expected_speed": "very_fast",
        "status": "active",
        "capabilities": ["chat", "reasoning", "tools", "structured_output"],
        "notes": "Cheapest GPT-5, ultra fast.",
    },
    {
        "provider": "openai",
        "model_id": "gpt-5.4",
        "display_name": "GPT-5.4",
        "base_url": "https://api.openai.com/v1",
        "input_price_per_1m": 2.50,
        "cached_input_price_per_1m": 0.25,
        "output_price_per_1m": 15.00,
        "context_window": 400000,
        "max_output_tokens": 128000,
        "reasoning_supported": True,
        "reasoning_default": "medium",
        "streaming_supported": True,
        "tool_calling_supported": True,
        "structured_output_supported": True,
        "expected_speed": "medium",
        "status": "deprecated",
        "capabilities": ["chat", "reasoning", "tools", "structured_output"],
        "notes": "Current flagship, balanced.",
    },
    {
        "provider": "openai",
        "model_id": "gpt-5.4-mini",
        "display_name": "GPT-5.4 Mini",
        "base_url": "https://api.openai.com/v1",
        "input_price_per_1m": 0.25,
        "cached_input_price_per_1m": 0.025,
        "output_price_per_1m": 1.00,
        "context_window": 400000,
        "max_output_tokens": 128000,
        "reasoning_supported": True,
        "reasoning_default": "medium",
        "streaming_supported": True,
        "tool_calling_supported": True,
        "structured_output_supported": True,
        "expected_speed": "fast",
        "status": "active",
        "capabilities": ["chat", "reasoning", "tools", "structured_output"],
        "notes": "Current budget, fast + cheap, good for voice.",
    },
    {
        "provider": "openai",
        "model_id": "gpt-5.4-nano",
        "display_name": "GPT-5.4 Nano",
        "base_url": "https://api.openai.com/v1",
        "input_price_per_1m": 0.05,
        "cached_input_price_per_1m": 0.005,
        "output_price_per_1m": 0.40,
        "context_window": 400000,
        "max_output_tokens": 128000,
        "reasoning_supported": True,
        "reasoning_default": "low",
        "streaming_supported": True,
        "tool_calling_supported": True,
        "structured_output_supported": True,
        "expected_speed": "very_fast",
        "status": "active",
        "capabilities": ["chat", "reasoning", "tools", "structured_output"],
        "notes": "Ultra budget, fastest.",
    },
    {
        "provider": "openai",
        "model_id": "o1",
        "display_name": "o1",
        "base_url": "https://api.openai.com/v1",
        "input_price_per_1m": 15.00,
        "cached_input_price_per_1m": 7.50,
        "output_price_per_1m": 60.00,
        "context_window": 200000,
        "max_output_tokens": 100000,
        "reasoning_supported": True,
        "reasoning_default": "high",
        "streaming_supported": True,
        "tool_calling_supported": False,
        "structured_output_supported": False,
        "expected_speed": "slow",
        "status": "deprecated",
        "capabilities": ["reasoning"],
        "notes": "Think-before-answering, slow, expensive.",
    },
    {
        "provider": "openai",
        "model_id": "o3-mini",
        "display_name": "o3 Mini",
        "base_url": "https://api.openai.com/v1",
        "input_price_per_1m": 1.10,
        "cached_input_price_per_1m": 0.55,
        "output_price_per_1m": 4.40,
        "context_window": 200000,
        "max_output_tokens": 100000,
        "reasoning_supported": True,
        "reasoning_default": "medium",
        "streaming_supported": True,
        "tool_calling_supported": True,
        "structured_output_supported": True,
        "expected_speed": "medium",
        "status": "deprecated",
        "capabilities": ["reasoning", "tools"],
        "notes": "Fast reasoning.",
    },
    {
        "provider": "openai",
        "model_id": "o4-mini",
        "display_name": "o4 Mini",
        "base_url": "https://api.openai.com/v1",
        "input_price_per_1m": 1.10,
        "cached_input_price_per_1m": 0.275,
        "output_price_per_1m": 4.40,
        "context_window": 200000,
        "max_output_tokens": 100000,
        "reasoning_supported": True,
        "reasoning_default": "medium",
        "streaming_supported": True,
        "tool_calling_supported": True,
        "structured_output_supported": True,
        "expected_speed": "fast",
        "status": "deprecated",
        "capabilities": ["reasoning", "tools", "vision"],
        "notes": "Fast, cost-efficient reasoning.",
    },
    # -------------------- Groq provider models --------------------
    {
        "provider": "groq",
        "model_id": "openai/gpt-oss-120b",
        "display_name": "GPT-OSS 120B",
        "base_url": "https://api.groq.com/openai/v1",
        "input_price_per_1m": 0.15,
        "cached_input_price_per_1m": 0.0,
        "output_price_per_1m": 0.60,
        "context_window": 131072,
        "max_output_tokens": 32768,
        "reasoning_supported": True,
        "reasoning_default": "low",
        "streaming_supported": True,
        "tool_calling_supported": True,
        "structured_output_supported": True,
        "expected_speed": "fast",
        "status": "active", "free_tier": True,
        "capabilities": ["chat", "reasoning", "tools"],
        "notes": "Groq recommended, 120B reasoning, tool use.",
    },
    {
        "provider": "groq",
        "model_id": "openai/gpt-oss-20b",
        "display_name": "GPT-OSS 20B",
        "base_url": "https://api.groq.com/openai/v1",
        "input_price_per_1m": 0.075,
        "cached_input_price_per_1m": 0.0,
        "output_price_per_1m": 0.30,
        "context_window": 131072,
        "max_output_tokens": 32768,
        "reasoning_supported": True,
        "reasoning_default": "low",
        "streaming_supported": True,
        "tool_calling_supported": True,
        "structured_output_supported": True,
        "expected_speed": "very_fast",
        "status": "active", "free_tier": True,
        "capabilities": ["chat", "reasoning", "tools"],
        "notes": "Groq fast, 20B, lower TPM cost, good for voice.",
    },
    {
        "provider": "groq",
        "model_id": "openai/gpt-oss-safeguard-20b",
        "display_name": "GPT-OSS Safeguard 20B (free)",
        "base_url": "https://api.groq.com/openai/v1",
        "input_price_per_1m": 0.075,
        "cached_input_price_per_1m": 0.0,
        "output_price_per_1m": 0.3,
        "context_window": 131072,
        "max_output_tokens": 32768,
        "reasoning_supported": True,
        "reasoning_default": "low",
        "streaming_supported": True,
        "tool_calling_supported": True,
        "structured_output_supported": True,
        "expected_speed": "very_fast",
        "status": "active", "free_tier": True,
        "capabilities": ["chat", "safety"],
        "notes": "SAFETY-CLASSIFIER, not a chat model: fine-tuned for content moderation, replies are erratic as a receptionist and it tried to end_call on 'Ok.'. Use openai/gpt-oss-20b instead (same speed/price). Retired from pickers 2026-09-19.",
        "tier": "free",
        "status": "deprecated",
    },
    # -------------------- Groq provider models (current, post-Jun-2026 deprecations) --------------------
    # llama-3.1-8b-instant + llama-3.3-70b-versatile retired 2026-08-16
    # qwen/qwen3-32b + llama-4-scout retired 2026-07-17
    # -> replacements per Groq: openai/gpt-oss-20b, openai/gpt-oss-120b, qwen/qwen3.6-27b
    # Qwen3.6 27B -> Qwen3.8 27B swap 2026-09-24 (user request; Groq lists 3.8 as the
    # current Qwen: console.groq.com/docs/model/qwen/qwen3.8-27b). 3.6 stays callable
    # for agents that saved it explicitly, but is hidden from pickers as deprecated.
    {
        "provider": "groq",
        "model_id": "qwen/qwen3.8-27b",
        "display_name": "Qwen3.8 27B",
        "base_url": "https://api.groq.com/openai/v1",
        "input_price_per_1m": 0.8,
        "cached_input_price_per_1m": 0.0,
        "output_price_per_1m": 4.0,
        "context_window": 131072,
        "max_output_tokens": 16384,
        "reasoning_supported": True,
        "reasoning_default": "none",
        "streaming_supported": True,
        "tool_calling_supported": True,
        "structured_output_supported": True,
        "expected_speed": "very_fast",
        "status": "active", "free_tier": True,
        "capabilities": ["chat", "reasoning", "tools", "vision"],
        "notes": "Free tier (rate-limited). Qwen3.6's successor on Groq: 27B dense, thinking/instruct dual mode (reasoning_effort none=default-for-voice; low/medium/high supported), vision (2048 tokens per image), ~450+ tps. Pricing $0.80/$4.00 per 1M — no prompt-cache discount, and Groq still rejects prompt_cache_key, so caching stays OpenAI-only.",
        "tier": "free",
    },
    {
        "provider": "groq",
        "model_id": "qwen/qwen3.6-27b",
        "display_name": "Qwen3.6 27B",
        "base_url": "https://api.groq.com/openai/v1",
        "input_price_per_1m": 0.6,
        "cached_input_price_per_1m": 0.0,
        "output_price_per_1m": 3.0,
        "context_window": 131072,
        "max_output_tokens": 32768,
        "reasoning_supported": True,
        "reasoning_default": "none",
        "streaming_supported": True,
        "tool_calling_supported": True,
        "structured_output_supported": True,
        "expected_speed": "very_fast",
        "status": "deprecated", "free_tier": True,
        "capabilities": ["chat", "reasoning", "tools", "vision"],
        "notes": "Superseded by qwen/qwen3.8-27b (2026-09-24): hidden from pickers, still valid for agents that saved it explicitly. Free. Groq's former recommended Llama/Qwen3 replacement (27B dense, thinking mode); strong Hindi.",
        "tier": "free",
    },
    {
        "provider": "groq",
        "model_id": "meta-llama/llama-4-maverick-17b-128e-instruct",
        "display_name": "Llama 4 Maverick 17Bx128E",
        "base_url": "https://api.groq.com/openai/v1",
        "input_price_per_1m": 0.2,
        "cached_input_price_per_1m": 0.0,
        "output_price_per_1m": 0.6,
        "context_window": 131072,
        "max_output_tokens": 8192,
        "reasoning_supported": False,
        "reasoning_default": None,
        "streaming_supported": True,
        "tool_calling_supported": True,
        "structured_output_supported": True,
        "expected_speed": "fast",
        "status": "active", "free_tier": True,
        "capabilities": ["chat", "tools", "vision"],
        "notes": "Free. Current Llama generation on Groq (llama-4-scout retired 2026-07-17). MoE, ~15 RPM free tier.",
        "tier": "free",
    },
    {
        "provider": "groq",
        "model_id": "moonshotai/kimi-k2-instruct",
        "display_name": "Kimi K2 Instruct",
        "base_url": "https://api.groq.com/openai/v1",
        "input_price_per_1m": 1.0,
        "cached_input_price_per_1m": 0.5,
        "output_price_per_1m": 3.0,
        "context_window": 262144,
        "max_output_tokens": 16384,
        "reasoning_supported": False,
        "reasoning_default": None,
        "streaming_supported": True,
        "tool_calling_supported": True,
        "structured_output_supported": True,
        "expected_speed": "fast",
        "status": "active", "free_tier": True,
        "capabilities": ["chat", "tools"],
        "notes": "Free (60 RPM / 1k RPD on Groq). Strong reasoning & Hindi; 262k context swallows a full knowledge base.",
        "tier": "free",
    },
    {
        "provider": "groq",
        "model_id": "minimaxai/minimax-m2.7",
        "display_name": "MiniMax M2.7",
        "base_url": "https://api.groq.com/openai/v1",
        "input_price_per_1m": 0.6,
        "cached_input_price_per_1m": 0.3,
        "output_price_per_1m": 1.8,
        "context_window": 196608,
        "max_output_tokens": 16384,
        "reasoning_supported": False,
        "reasoning_default": None,
        "streaming_supported": True,
        "tool_calling_supported": True,
        "structured_output_supported": True,
        "expected_speed": "fast",
        "status": "active", "free_tier": True,
        "capabilities": ["chat", "tools"],
        "notes": "Free. 196k context; good multilingual instruction following.",
        "tier": "free",
    },
    {
        "provider": "groq",
        "model_id": "qwen/qwen3-32b",
        "display_name": "Qwen3 32B",
        "base_url": "https://api.groq.com/openai/v1",
        "input_price_per_1m": 0.10,
        "cached_input_price_per_1m": 0.0,
        "output_price_per_1m": 0.40,
        "context_window": 131072,
        "max_output_tokens": 32768,
        "reasoning_supported": True,
        "reasoning_default": "none",
        "streaming_supported": True,
        "tool_calling_supported": True,
        "structured_output_supported": True,
        "expected_speed": "fast",
        "status": "deprecated",
        "capabilities": ["chat", "reasoning", "vision"],
        "notes": "Multimodal reasoning.",
    },
    {
        "provider": "groq",
        "model_id": "llama-3.3-70b-versatile",
        "display_name": "Llama 3.3 70B Versatile (deprecated)",
        "base_url": "https://api.groq.com/openai/v1",
        "input_price_per_1m": 0.59,
        "cached_input_price_per_1m": 0.0,
        "output_price_per_1m": 0.79,
        "context_window": 131072,
        "max_output_tokens": 32768,
        "reasoning_supported": False,
        "reasoning_default": None,
        "streaming_supported": True,
        "tool_calling_supported": True,
        "structured_output_supported": True,
        "expected_speed": "medium",
        "status": "deprecated",
        "capabilities": ["chat", "tools"],
        "notes": "Deprecated by Groq 08/16/26, use gpt-oss models.",
    },
    {
        "provider": "groq",
        "model_id": "llama-3.1-8b-instant",
        "display_name": "Llama 3.1 8B Instant (deprecated)",
        "base_url": "https://api.groq.com/openai/v1",
        "input_price_per_1m": 0.05,
        "cached_input_price_per_1m": 0.0,
        "output_price_per_1m": 0.08,
        "context_window": 131072,
        "max_output_tokens": 8192,
        "reasoning_supported": False,
        "reasoning_default": None,
        "streaming_supported": True,
        "tool_calling_supported": True,
        "structured_output_supported": True,
        "expected_speed": "very_fast",
        "status": "deprecated",
        "capabilities": ["chat", "tools"],
        "notes": "Deprecated by Groq 08/16/26.",
    },
    # -------------------- OpenRouter provider models --------------------
    {
        "provider": "openrouter",
        "model_id": "google/gemma-3-27b-it:free",
        "display_name": "Gemma 3 27B IT Free",
        "base_url": "https://openrouter.ai/api/v1",
        "input_price_per_1m": 0.0,
        "cached_input_price_per_1m": 0.0,
        "output_price_per_1m": 0.0,
        "context_window": 131072,
        "max_output_tokens": 8192,
        "reasoning_supported": False,
        "reasoning_default": None,
        "streaming_supported": True,
        "tool_calling_supported": True,
        "structured_output_supported": True,
        "expected_speed": "medium",
        "status": "deprecated",
        "capabilities": ["chat", "tools"],
        "notes": "Free tier rate-limited.",
    },
    {
        "provider": "openrouter",
        "model_id": "google/gemma-3-12b-it:free",
        "display_name": "Gemma 3 12B IT Free",
        "base_url": "https://openrouter.ai/api/v1",
        "input_price_per_1m": 0.0,
        "cached_input_price_per_1m": 0.0,
        "output_price_per_1m": 0.0,
        "context_window": 32768,
        "max_output_tokens": 8192,
        "reasoning_supported": False,
        "reasoning_default": None,
        "streaming_supported": True,
        "tool_calling_supported": True,
        "structured_output_supported": True,
        "expected_speed": "fast",
        "status": "deprecated",
        "capabilities": ["chat", "tools"],
        "notes": "Free, lighter.",
    },
    {
        "provider": "openrouter",
        "model_id": "meta-llama/llama-3.3-70b-instruct:free",
        "display_name": "Llama 3.3 70B Instruct Free",
        "base_url": "https://openrouter.ai/api/v1",
        "input_price_per_1m": 0.0,
        "cached_input_price_per_1m": 0.0,
        "output_price_per_1m": 0.0,
        "context_window": 131072,
        "max_output_tokens": 8192,
        "reasoning_supported": False,
        "reasoning_default": None,
        "streaming_supported": True,
        "tool_calling_supported": True,
        "structured_output_supported": True,
        "expected_speed": "medium",
        "status": "deprecated",
        "capabilities": ["chat", "tools"],
        "notes": "Free tier.",
    },
    {
        "provider": "openrouter",
        "model_id": "qwen/qwen3-32b:free",
        "display_name": "Qwen3 32B Free",
        "base_url": "https://openrouter.ai/api/v1",
        "input_price_per_1m": 0.0,
        "cached_input_price_per_1m": 0.0,
        "output_price_per_1m": 0.0,
        "context_window": 131072,
        "max_output_tokens": 8192,
        "reasoning_supported": True,
        "reasoning_default": "none",
        "streaming_supported": True,
        "tool_calling_supported": True,
        "structured_output_supported": True,
        "expected_speed": "fast",
        "status": "deprecated",
        "capabilities": ["chat", "reasoning", "tools"],
        "notes": "Free reasoning.",
    },

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
        "supports_temperature": True, "default_temperature": 0.6,
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
        "supports_temperature": True, "default_temperature": 0.6,
        "reasoning_effort_options": ["none", "low", "medium", "high"],
    },
    # -------------------- Sarvam AI provider models --------------------
    {
        "provider": "sarvam",
        "model_id": "sarvam-30b",
        "display_name": "Sarvam 30B",
        "base_url": "https://api.sarvam.ai",
        "input_price_per_1m": 0.03012,
        "cached_input_price_per_1m": 0.01807,
        "output_price_per_1m": 0.12048,
        "context_window": 32768,
        "max_output_tokens": 8192,
        "reasoning_supported": False,
        "reasoning_default": None,
        "streaming_supported": True,
        "tool_calling_supported": True,
        "structured_output_supported": False,
        "expected_speed": "very_fast",
        "status": "active",
        "capabilities": ["chat", "tools", "multilingual"],
        "notes": "⭐ Best pick when Bulbul TTS is also in use — purpose-built for Hindi/Hinglish. Prices are INR per 1M tokens (₹2.5 in / ₹1.5 cached / ₹10 out); set SARVAM_API_KEY.",
        "price_currency": "INR", "price_inr_per_1m": {"input": 2.5, "cached_input": 1.5, "output": 10.0}, "tier": "paid", "currency": "INR", "voice_recommended": True,
        "supports_temperature": True, "default_temperature": 0.5,
        "reasoning_effort_options": [],
    },
    {
        "provider": "sarvam",
        "model_id": "sarvam-30b-16k",
        "display_name": "Sarvam 30B 16k",
        "base_url": "https://api.sarvam.ai",
        "input_price_per_1m": 0.03012,
        "cached_input_price_per_1m": 0.01807,
        "output_price_per_1m": 0.12048,
        "context_window": 16384,
        "max_output_tokens": 8192,
        "reasoning_supported": False,
        "reasoning_default": None,
        "streaming_supported": True,
        "tool_calling_supported": True,
        "structured_output_supported": False,
        "expected_speed": "very_fast",
        "status": "active",
        "capabilities": ["chat", "tools", "multilingual"],
        "notes": "Same rate as sarvam-30b with a 16k window. ₹2.5/₹1.5/₹10 per 1M.",
        "price_currency": "INR", "price_inr_per_1m": {"input": 2.5, "cached_input": 1.5, "output": 10.0}, "tier": "paid", "currency": "INR",
        "supports_temperature": True, "default_temperature": 0.5,
        "reasoning_effort_options": [],
    },
    {
        "provider": "sarvam",
        "model_id": "sarvam-105b",
        "display_name": "Sarvam 105B",
        "base_url": "https://api.sarvam.ai",
        "input_price_per_1m": 0.04819,
        "cached_input_price_per_1m": 0.03012,
        "output_price_per_1m": 0.19277,
        "context_window": 32768,
        "max_output_tokens": 8192,
        "reasoning_supported": False,
        "reasoning_default": None,
        "streaming_supported": True,
        "tool_calling_supported": True,
        "structured_output_supported": False,
        "expected_speed": "fast",
        "status": "active",
        "capabilities": ["chat", "tools", "multilingual"],
        "notes": "Highest-quality Indic (₹4/₹2.5/₹16). Use only if 30B quality feels thin — slower than 30B for voice turns.",
        "price_currency": "INR", "price_inr_per_1m": {"input": 4.0, "cached_input": 2.5, "output": 16.0}, "tier": "paid", "currency": "INR",
        "supports_temperature": True, "default_temperature": 0.5,
        "reasoning_effort_options": [],
    },
    {
        "provider": "sarvam",
        "model_id": "sarvam-105b-32k",
        "display_name": "Sarvam 105B 32k",
        "base_url": "https://api.sarvam.ai",
        "input_price_per_1m": 0.04819,
        "cached_input_price_per_1m": 0.03012,
        "output_price_per_1m": 0.19277,
        "context_window": 32768,
        "max_output_tokens": 8192,
        "reasoning_supported": False,
        "reasoning_default": None,
        "streaming_supported": True,
        "tool_calling_supported": True,
        "structured_output_supported": False,
        "expected_speed": "fast",
        "status": "active",
        "capabilities": ["chat", "tools", "multilingual"],
        "notes": "32k-window variant of Sarvam 105B.",
        "price_currency": "INR", "price_inr_per_1m": {"input": 4.0, "cached_input": 2.5, "output": 16.0}, "tier": "paid", "currency": "INR",
        "supports_temperature": True, "default_temperature": 0.5,
        "reasoning_effort_options": [],
    },
]

# Index for fast lookup
_MODEL_INDEX: Dict[str, Dict[str, Any]] = {}
for m in LLM_MODELS:
    key = f"{m['provider']}:{m['model_id']}"
    _MODEL_INDEX[key] = m
    # Also index by model_id alone for backward compat (last wins, but provider-specific preferred)
    _MODEL_INDEX[m['model_id']] = m

def get_llm_provider(provider_id: str) -> Optional[Dict[str, Any]]:
    return LLM_PROVIDERS.get(provider_id)

def get_llm_model(provider: str, model_id: str) -> Optional[Dict[str, Any]]:
    """Get model by provider and model_id. Returns None if not found."""
    key = f"{provider}:{model_id}"
    if key in _MODEL_INDEX:
        return _MODEL_INDEX[key]
    # Fallback: search list for exact provider+model_id
    for m in LLM_MODELS:
        if m["provider"] == provider and m["model_id"] == model_id:
            return m
    return None

def get_llm_model_by_id(model_id: str) -> Optional[Dict[str, Any]]:
    """Get model by model_id alone (any provider). Returns first match."""
    for m in LLM_MODELS:
        if m["model_id"] == model_id:
            return m
    return _MODEL_INDEX.get(model_id)

def list_providers(include_deprecated: bool = False) -> List[Dict[str, Any]]:
    """Providers offered in the UI. Deprecated ones (openrouter) are hidden from
    new selections but keep validating existing agents (see validate_provider_model)."""
    return [p for p in LLM_PROVIDERS.values()
            if include_deprecated or p.get("status") != "deprecated"]


def list_all_providers() -> List[Dict[str, Any]]:
    """Every provider including deprecated — for validation/legacy display only."""
    return list(LLM_PROVIDERS.values())

def list_models_for_provider(provider: str) -> List[Dict[str, Any]]:
    return [m for m in LLM_MODELS if m["provider"] == provider and m["status"] == "active"]

def list_all_models() -> List[Dict[str, Any]]:
    return LLM_MODELS

def validate_provider_model(provider: str, model_id: str) -> tuple[bool, str]:
    """
    Validate provider/model combination.
    Returns (is_valid, error_message). If invalid, error_message explains why.
    Does NOT silently replace.
    """
    prov = get_llm_provider(provider)
    if not prov:
        return False, f"Unknown LLM provider '{provider}'. Valid providers: {list(LLM_PROVIDERS.keys())}"
    
    model = get_llm_model(provider, model_id)
    if not model:
        # Check if model exists under different provider
        existing = get_llm_model_by_id(model_id)
        if existing:
            return False, f"Invalid model '{model_id}' for provider '{provider}'. Model '{model_id}' belongs to provider '{existing['provider']}' (base_url {existing['base_url']}). Use provider='{existing['provider']}' with model='{model_id}'. Do not treat Groq's 120B as OpenAI model. Provider and model must remain separate."
        else:
            # List valid models for this provider
            valid_models = [m["model_id"] for m in list_models_for_provider(provider)]
            return False, f"Unknown model '{model_id}' for provider '{provider}'. Valid models for {provider}: {valid_models}. If model is from another provider, use that provider."
    
    if model["status"] == "deprecated":
        # Still valid but warn
        return True, f"Warning: model '{model_id}' for provider '{provider}' is deprecated: {model.get('notes','')}"
    
    return True, ""

def calculate_llm_cost(model_meta: Dict[str, Any], input_tokens: int, cached_input_tokens: int, output_tokens: int) -> Dict[str, float]:
    """
    Calculate LLM cost per request using selected model's pricing metadata.
    """
    input_price = model_meta.get("input_price_per_1m", 0) / 1_000_000
    cached_price = model_meta.get("cached_input_price_per_1m", 0) / 1_000_000
    output_price = model_meta.get("output_price_per_1m", 0) / 1_000_000
    
    # If cached tokens not separately tracked, treat all input as regular
    # But if cached provided, subtract from input? Actually input_tokens includes cached? We assume separate.
    # For OpenAI, cached_input_tokens are part of input_tokens that were cached.
    # So we calculate: (input - cached) * input_price + cached * cached_price + output * output_price
    # If input_tokens already excludes cached, then use as is.
    # We will assume input_tokens is total input, and cached is subset that was cached.
    # To be safe, if cached > input, cap.
    if cached_input_tokens > input_tokens:
        cached_input_tokens = input_tokens
    
    non_cached_input = input_tokens - cached_input_tokens
    input_cost = non_cached_input * input_price + cached_input_tokens * cached_price
    output_cost = output_tokens * output_price
    total = input_cost + output_cost
    
    return {
        "input_cost": input_cost,
        "cached_input_cost": cached_input_tokens * cached_price,
        "output_cost": output_cost,
        "total_llm_cost": total,
        "input_price_per_1m": model_meta.get("input_price_per_1m", 0),
        "cached_input_price_per_1m": model_meta.get("cached_input_price_per_1m", 0),
        "output_price_per_1m": model_meta.get("output_price_per_1m", 0),
    }

def catalog_summary_v2() -> Dict[str, Any]:
    """Return new catalog organized for frontend: providers with models.

    Deprecated providers (openrouter) are excluded from the picker; their saved
    agents keep working via the legacy-id mapping + validate_provider_model().
    Deprecated *models* stay visible under their provider (marked) so users see
    when a saved model was retired and can pick the replacement.
    """
    active_providers = {p["id"]: p for p in list_providers()}
    return {
        "providers": active_providers,
        "models": LLM_MODELS,
        "by_provider": {pid: list_models_for_provider(pid) for pid in active_providers},
    }
