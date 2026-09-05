"""
Provider catalog for the Voice Agent SaaS platform.

Each provider exposes:
  - kind          : llm | stt | tts
  - display_name  : shown in the UI
  - provider      : the backend plugin type (openai, deepgram, google, ...)
  - tier          : "free" | "paid"  -> decides wallet requirement / badge
  - requires_key  : True if the customer must supply their own API key
  - cost          : per-unit cost used for the "your cost" billing line.
                   Units are normalised below.
  - options       : selectable sub-options (models / voices / languages).

We deliberately include a FREE-ONLY set (Groq LLM, Deepgram STT, Google TTS)
so the demo runs with essentially zero cost, plus paid options to show the
"different quality, different price" pitch. Prices are illustrative and live
entirely in this file + config JSON so they can be edited without code changes.
"""
from __future__ import annotations

from typing import Any

# Cost units (normalised):
#   llm  : per 1K tokens (in        -> cost_per_1k_in;  out -> cost_per_1k_out)
#   stt  : per minute of audio     -> cost_per_min
#   tts  : per 1K characters       -> cost_per_1k_chars
# Server cost is handled separately in config.SERVER_COST_PER_MIN.

CATALOG: dict[str, Any] = {
    # ----------------------------------------------------------------------
    # LLMs
    # ----------------------------------------------------------------------
    "llm": {
        "groq_gpt_oss": {
            "kind": "llm",
            "display_name": "Groq GPT-OSS 120B (recommended, free-tier)",
            "provider": "openai",             # Groq exposes an OpenAI-compatible API
            "base_url": "https://api.groq.com/openai/v1",
            "model": "openai/gpt-oss-120b",
            "tier": "free",
            "requires_key": True,
            "key_env": "GROQ_API_KEY",
            "cost": {"per_1k_in": 0.03, "per_1k_out": 0.06},
            # Groq DEPRECATED llama-3.3-70b-versatile / llama-3.1-8b-instant (shutdown
            # 08/16/26); their replacement is the openai/gpt-oss family.
            "notes": "Groq's current default. Reasoning model — keep 'reasoning_effort' = low for fast voice replies.",
            "options": {
                "model": ["openai/gpt-oss-120b", "openai/gpt-oss-20b"],
                "reasoning_effort": ["low", "medium", "high"],
                "temperature": [0.0, 0.1, 0.3, 0.7],
            },
        },
        "groq_llama_3_3_70b": {
            "kind": "llm",
            "display_name": "Groq Llama 3.3 70B (⚠️ deprecated by Groq)",
            "provider": "openai",             # Groq exposes an OpenAI-compatible API
            "base_url": "https://api.groq.com/openai/v1",
            "model": "llama-3.3-70b-versatile",
            "tier": "free",
            "requires_key": True,
            "key_env": "GROQ_API_KEY",
            "cost": {"per_1k_in": 0.03, "per_1k_out": 0.06},
            "notes": "Deprecated by Groq (shutdown 08/16/26). Use Groq GPT-OSS 120B / 20B instead.",
            "options": {
                "model": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"],
                "temperature": [0.0, 0.1, 0.3, 0.7],
            },
        },
        "groq_qwen": {
            "kind": "llm",
            "display_name": "Groq Qwen3 (⚠️ reasoning, burns free-tier quota)",
            "provider": "openai",
            "base_url": "https://api.groq.com/openai/v1",
            "model": "qwen/qwen3.6-27b",
            "tier": "free",
            "requires_key": True,
            "key_env": "GROQ_API_KEY",
            "cost": {"per_1k_in": 0.03, "per_1k_out": 0.06},
            # LiveKit retries a rate-limit 3x with backoff -> 15-20s "thinking" stalls.
            "notes": "Reasoning model: hits Groq's 200k tokens/day quota in a few calls, then 429s. Prefer Groq GPT-OSS for voice.",
            "options": {"model": ["qwen/qwen3.6-27b", "qwen/qwen3-32b"]},
        },
        "openrouter_gemma": {
            "kind": "llm",
            "display_name": "OpenRouter Gemma 4 31B (free, tool-calling)",
            "provider": "openrouter",
            "base_url": "https://openrouter.ai/api/v1",
            "model": "google/gemma-4-31b-it:free",
            "tier": "free",
            "requires_key": True,
            "key_env": "OPENROUTER_API_KEY",
            "cost": {"per_1k_in": 0.00, "per_1k_out": 0.00},
            "notes": "Needs OPENROUTER_API_KEY. Free :free models are rate-limited (low req/day) — good for a demo. All options support tool calling (end_call).",
            "options": {
                "model": [
                    "google/gemma-4-31b-it:free",
                    "google/gemma-4-26b-a4b-it:free",
                    "nvidia/nemotron-3-super-120b-a12b:free",
                    "z-ai/glm-5.2:free",
                    "openrouter/free",
                ],
                "temperature": [0.0, 0.1, 0.3, 0.7],
            },
        },
        "openrouter_gemma_26b": {
            "kind": "llm",
            "display_name": "OpenRouter Gemma 4 26B (free, lighter)",
            "provider": "openrouter",
            "base_url": "https://openrouter.ai/api/v1",
            "model": "google/gemma-4-26b-a4b-it:free",
            "tier": "free",
            "requires_key": True,
            "key_env": "OPENROUTER_API_KEY",
            "cost": {"per_1k_in": 0.00, "per_1k_out": 0.00},
            "notes": "Smaller/faster sibling of Gemma 31B. Free tier rate-limited.",
            "options": {
                "model": ["google/gemma-4-26b-a4b-it:free", "google/gemma-4-31b-it:free"],
                "temperature": [0.0, 0.1, 0.3, 0.7],
            },
        },
        "openai_gpt_4o_mini": {
            "kind": "llm",
            "display_name": "OpenAI GPT-4o mini (paid, better quality)",
            "provider": "openai",
            "base_url": None,
            "model": "gpt-4o-mini",
            "tier": "paid",
            "requires_key": True,
            "key_env": "OPENAI_API_KEY",
            "cost": {"per_1k_in": 0.15, "per_1k_out": 0.60},
        },
        "openai_gpt_oss_120b": {
            "kind": "llm",
            "display_name": "OpenAI GPT-OSS-120B (reasoning, paid)",
            "provider": "openai",
            "base_url": None,
            "model": "gpt-oss-120b",
            "tier": "paid",
            "requires_key": True,
            "key_env": "OPENAI_API_KEY",
            "cost": {"per_1k_in": 0.20, "per_1k_out": 0.80},
            # A reasoning model can be slow on a voice call. Keep reasoning_effort
            # low (build_llm's default for gpt-oss) for human latency.
            "notes": "Uses OPENAI_API_KEY (not Groq). Keep 'reasoning_effort' = low for fast voice replies.",
            "options": {
                "model": ["gpt-oss-120b", "gpt-oss-20b"],
                "reasoning_effort": ["low", "medium", "high"],
            },
        },
    },
    # ----------------------------------------------------------------------
    # STT (speech-to-text)
    # ----------------------------------------------------------------------
    "stt": {
        "deepgram_nova2": {
            "kind": "stt",
            "display_name": "Deepgram Nova-2 (free-tier, multilingual)",
            "provider": "deepgram",
            "model": "nova-2",
            "tier": "free",
            "requires_key": False,            # key comes from backend env
            "key_env": "DEEPGRAM_API_KEY",
            "cost": {"per_min": 0.22},
            "options": {"language": ["hi", "en", "hi-Latn", "multi"]},
        },
        "deepgram_nova3": {
            "kind": "stt",
            "display_name": "Deepgram Nova-3 (paid, best Hindi)",
            "provider": "deepgram",
            "model": "nova-3",
            "tier": "paid",
            "requires_key": False,
            "key_env": "DEEPGRAM_API_KEY",
            "cost": {"per_min": 0.43},
            "options": {"language": ["hi", "en", "hi-Latn", "multi"]},
        },
        "google_stt": {
            "kind": "stt",
            "display_name": "Google Cloud STT (paid)",
            "provider": "google",
            "model": "latest",
            "tier": "paid",
            "requires_key": False,
            "key_env": "GOOGLE_APPLICATION_CREDENTIALS",
            "cost": {"per_min": 0.24},
            "options": {"language": ["hi-IN", "en-IN"]},
        },
    },
    # ----------------------------------------------------------------------
    # TTS (text-to-speech)
    # ----------------------------------------------------------------------
    "tts": {
        "google_wavenet_hi": {
            "kind": "tts",
            "display_name": "Google Chirp 3 HD Hindi (natural, streaming)",
            "provider": "google",
            "voice": "hi-IN-Chirp3-HD-Leda",
            "language": "hi-IN",
            "tier": "free",
            "requires_key": False,
            "key_env": "GOOGLE_APPLICATION_CREDENTIALS",
            "cost": {"per_1k_chars": 1.33},
            # NOTE: Google's streaming TTS endpoint only supports Chirp 3: HD
            # voices (Wavenet/Standard/Neural2 are rejected with 400).
            "options": {"voice": ["hi-IN-Chirp3-HD-Leda", "hi-IN-Chirp3-HD-Kore", "hi-IN-Chirp3-HD-Charon", "hi-IN-Chirp3-HD-Fenrir"]},
        },
        "google_neural2_hi": {
            "kind": "tts",
            "display_name": "Google Chirp 3 HD Hindi (paid, Studio quality)",
            "provider": "google",
            "voice": "hi-IN-Chirp3-HD-Kore",
            "language": "hi-IN",
            "tier": "paid",
            "requires_key": False,
            "key_env": "GOOGLE_APPLICATION_CREDENTIALS",
            "cost": {"per_1k_chars": 8.00},
            "options": {"voice": ["hi-IN-Chirp3-HD-Kore", "hi-IN-Chirp3-HD-Zephyr"]},
        },
        "elevenlabs_hi": {
            "kind": "tts",
            "display_name": "ElevenLabs Multilingual v2 (paid)",
            "provider": "elevenlabs",
            "voice": "pNInz6obpgDQGcFmaJgB",
            "language": "hi",
            "tier": "paid",
            "requires_key": True,
            "key_env": "ELEVENLABS_API_KEY",
            "cost": {"per_1k_chars": 30.00},
            "options": {"voice": ["pNInz6obpgDQGcFmaJgB", "onwK4e9ZLuTAKqWW03F9"]},
        },
        "openrouter_flux_tts": {
            "kind": "tts",
            "display_name": "OpenRouter Deepgram Flux TTS (FREE, English only)",
            "provider": "openrouter",
            "model": "deepgram/flux-tts:free",
            "voice": "flux-bree-en",
            "language": "en",
            "tier": "free",
            "requires_key": True,
            "key_env": "OPENROUTER_API_KEY",
            "cost": {"per_1k_chars": 0.00},
            # Flux voices are all English (`*-en`). It is the easiest FREE OpenRouter
            # TTS to test (has documented voices + streams). Not for Hindi.
            "notes": "FREE but ENGLISH-only. Needs OPENROUTER_API_KEY. Use for English test calls; use Google Chirp 3 HD for Hindi.",
            "options": {"voice": ["flux-bree-en", "flux-alexis-en", "flux-priya-en", "flux-maeve-en"]},
        },
        "openrouter_kokoro_tts": {
            "kind": "tts",
            "display_name": "OpenRouter Kokoro 82M (multilingual, paid)",
            "provider": "openrouter",
            "model": "hexgrad/kokoro-82m",
            "voice": "af_bella",
            "language": "en",
            "tier": "paid",
            "requires_key": True,
            "key_env": "OPENROUTER_API_KEY",
            "cost": {"per_1k_chars": 0.20},
            # Kokoro is multilingual (incl. Hindi via the `hf_*` voices) but is
            # NOT free on OpenRouter.
            "notes": "Multilingual (Hindi voices hf_alpha/hf_beta). PAID on OpenRouter. Needs OPENROUTER_API_KEY.",
            "options": {"voice": ["af_bella", "af_heart", "am_michael", "hf_alpha", "hf_beta"]},
        },
        # NOTE: fish-audio/s2.1-pro-free:free is NOT listed here because it is
        # voice-cloning only (no preset voice) — it cannot synthesize from a plain
        # voice string, so it is not a self-service drop-in. If a saved agent still
        # references it, build_tts falls back to the free Flux voice instead of
        # failing the call.
    },
    # ----------------------------------------------------------------------
    # Telephony providers (outbound)
    # ----------------------------------------------------------------------
    "telephony": {
        "telnyx": {
            "kind": "telephony",
            "display_name": "Telnyx (SIP trunk)",
            "provider": "telnyx",
            "tier": "paid",
            "requires_key": True,
            "key_env": "TELNYX_API_KEY",
            "cost": {"per_min": 0.013},
        },
        "twilio": {
            "kind": "telephony",
            "display_name": "Twilio (SIP trunk)",
            "provider": "twilio",
            "tier": "paid",
            "requires_key": True,
            "key_env": "TWILIO_API_KEY",
            "cost": {"per_min": 0.013},
        },
        "browser": {
            "kind": "telephony",
            "display_name": "Browser test call (no carrier, free)",
            "provider": "browser",
            "tier": "free",
            "requires_key": False,
            "key_env": "",
            "cost": {"per_min": 0.0},
        },
    },
}


def providers_of(kind: str) -> list[dict[str, Any]]:
    """Return the provider list, each with its own id embedded."""
    out = []
    for pid, spec in CATALOG.get(kind, {}).items():
        item = dict(spec)
        item["id"] = pid
        out.append(item)
    return out


def get_provider(kind: str, provider_id: str) -> dict[str, Any] | None:
    return CATALOG.get(kind, {}).get(provider_id)


def catalog_summary() -> dict[str, Any]:
    """Return the catalogue organised for the frontend config UI."""
    out: dict[str, Any] = {}
    for kind in ("llm", "stt", "tts", "telephony"):
        out[kind] = providers_of(kind)
    return out
