"""Dynamic-catalog seed rows: providers that only exist in the DB catalog.

Extracted from the old monolithic catalog_service — behavior unchanged.
LLM providers requested by product: OpenAI, Qwen, Claude, Google Gemini
(OpenAI/Gemini/Groq/Sarvam come from the code catalog; Qwen + Claude are
added here). TTS additions: Fish Voice, MiniMax Voice, OpenAI TTS. These are
seeded DISABLED — the Super Admin turns them on explicitly and sets the API
key, so nothing new appears in the customer UI until the platform wants it.
"""
from __future__ import annotations

from typing import Any, Dict, List

# ---------------------------------------------------------------------------
# Seed data — providers that only exist in the dynamic catalog (not in code)
# ---------------------------------------------------------------------------
# LLM providers requested by product: OpenAI, Qwen, Claude, Google Gemini
# (OpenAI/Gemini/Groq/Sarvam come from the code catalog; Qwen + Claude are
# added here). TTS additions: Fish Voice, MiniMax Voice, OpenAI TTS. These are
# seeded DISABLED — the Super Admin turns them on explicitly and sets the API
# key, so nothing new appears in the customer UI until the platform wants it.
EXTRA_PROVIDER_SEEDS: List[Dict[str, Any]] = [
    {
        "kind": "llm", "slug": "qwen", "display_name": "Qwen (Alibaba DashScope)",
        "adapter": "openai", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "key_env": "QWEN_API_KEY", "tier": "paid", "enabled": False,
        "notes": "Alibaba Qwen models via the OpenAI-compatible DashScope endpoint.",
        "models": [
            {"model_id": "qwen3.6-27b", "display_name": "Qwen3.6 27B", "enabled": False,
             "meta": {"context_window": 131072, "max_output_tokens": 8192, "expected_speed": "fast"}},
            {"model_id": "qwen3.8-27b", "display_name": "Qwen3.8 27B", "enabled": False,
             "meta": {"context_window": 131072, "max_output_tokens": 8192, "expected_speed": "fast"}},
            {"model_id": "qwen3-max", "display_name": "Qwen3 Max", "enabled": False,
             "meta": {"context_window": 262144, "max_output_tokens": 16384, "expected_speed": "medium"}},
        ],
    },
    {
        "kind": "llm", "slug": "anthropic", "display_name": "Claude (Anthropic)",
        "adapter": "anthropic", "base_url": "",
        "key_env": "ANTHROPIC_API_KEY", "tier": "paid", "enabled": False,
        "notes": "Native Anthropic via livekit-plugins-anthropic.",
        "models": [
            {"model_id": "claude-sonnet-4-6", "display_name": "Claude Sonnet 4.6", "enabled": False,
             "meta": {"context_window": 200000, "max_output_tokens": 8192, "expected_speed": "medium"}},
            {"model_id": "claude-haiku-4-5-20251001", "display_name": "Claude Haiku 4.5", "enabled": False,
             "meta": {"context_window": 200000, "max_output_tokens": 8192, "expected_speed": "very_fast"}},
        ],
    },
    {
        "kind": "tts", "slug": "fish", "display_name": "Fish Voice (Fish Audio)",
        "adapter": "openai_compat_tts", "base_url": "https://api.fish.audio/v1",
        "key_env": "FISH_AUDIO_API_KEY", "tier": "paid", "enabled": False,
        "notes": "Fish Audio via its OpenAI-compatible TTS endpoint.",
        "models": [
            {"model_id": "s1", "display_name": "Fish Speech S1", "enabled": False,
             "meta": {"voices": [], "language": ["en", "hi", "multi"]}},
        ],
    },
    {
        "kind": "tts", "slug": "minimax", "display_name": "MiniMax Voice",
        "adapter": "openai_compat_tts", "base_url": "https://api.minimaxi.com/v1",
        "key_env": "MINIMAX_API_KEY", "tier": "paid", "enabled": False,
        "notes": "MiniMax speech via the OpenAI-compatible TTS endpoint.",
        "models": [
            {"model_id": "speech-2.6-hd", "display_name": "MiniMax Speech 2.6 HD", "enabled": False,
             "meta": {"voices": [], "language": ["en", "hi", "multi"]}},
        ],
    },
    {
        "kind": "tts", "slug": "openai", "display_name": "OpenAI TTS",
        "adapter": "openai_compat_tts", "base_url": "https://api.openai.com/v1",
        "key_env": "OPENAI_API_KEY", "tier": "paid", "enabled": False,
        "notes": "OpenAI audio speech (tts-1 / gpt-4o-mini-tts).",
        "models": [
            {"model_id": "gpt-4o-mini-tts", "display_name": "GPT-4o Mini TTS", "enabled": False,
             "meta": {"voices": ["alloy", "echo", "fable", "onyx", "nova", "shimmer"], "language": ["en", "multi"]}},
        ],
    },
]
