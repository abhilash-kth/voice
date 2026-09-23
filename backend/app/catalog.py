"""
Provider catalog for the Voice Agent SaaS platform - V2 architecture.

Provider → Multiple Models architecture.

Each provider has multiple models with rich metadata:
- provider, model_id, display_name, base_url
- input_price_per_1m, cached_input_price_per_1m, output_price_per_1m
- context_window, max_output_tokens
- reasoning_supported, reasoning_default
- streaming_supported, tool_calling_supported, structured_output_supported
- expected_speed (very_fast, fast, medium, slow)
- status (active/deprecated), capabilities, notes

No silent model substitution. Invalid provider/model returns clear config error.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
import os

# Import new LLM catalog with Provider → Multiple Models
from .llm_catalog import (
    LLM_PROVIDERS,
    LLM_MODELS,
    get_llm_provider as _get_llm_provider_v2,
    get_llm_model as _get_llm_model_v2,
    get_llm_model_by_id as _get_llm_model_by_id_v2,
    list_providers as _list_llm_providers_v2,
    list_models_for_provider as _list_llm_models_for_provider_v2,
    validate_provider_model as _validate_llm_provider_model,
    calculate_llm_cost as _calculate_llm_cost_v2,
    catalog_summary_v2 as _llm_catalog_summary_v2,
)

# ---------------------------------------------------------------------------
# Legacy STT/TTS/Telephony catalog (unchanged, but kept for backward compat)
# ---------------------------------------------------------------------------
CATALOG: Dict[str, Any] = {
    "llm": {},  # Will be populated from new LLM catalog with backward compat
    "stt": {
        "deepgram_nova2": {
            "kind": "stt",
            "display_name": "Deepgram Nova-2 (free-tier, multilingual)",
            "provider": "deepgram",
            "model": "nova-2",
            "tier": "free",
            "requires_key": False,
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
        "sarvam_saaras_3": {
            "kind": "stt",
            "display_name": "Sarvam Saaras 3 (best Indic code-mix, paid)",
            "provider": "sarvam",
            "model": "saaras_3",
            "tier": "paid",
            "requires_key": True,
            "key_env": "SARVAM_API_KEY",
            "cost": {"per_min": 0.00833},
            "options": {
                "language": ["hi-IN", "en-IN", "mr-IN", "ta-IN", "te-IN", "kn-IN", "ml-IN", "gu-IN", "bn-IN", "pa-IN", "auto"],
                "genders": ["female", "male", "neutral"],
            },
        },
    },
    "tts": {
        "sarvam_bulbul_v3": {
            "kind": "tts",
            "display_name": "Sarvam Bulbul v3 (Indic, streaming, low-latency)",
            "provider": "sarvam",
            "model": "bulbul:v3",
            "tier": "paid",
            "requires_key": True,
            "key_env": "SARVAM_API_KEY",
            "cost": {"per_1k_chars": 3.0},
            "currency": "INR",
            "options": {
                # LiveKit plugin speakers for bulbul:v3 (docs.livekit.io TTS guide, Sep 2026)
                # Female: amelia, ishita, kavitha, kavya, neha, pooja, priya, ritu, roopa, rupali, shruti, shreya, simran, sophia, suhani, tanya
                # Male: aayan, aditya, advait, amit, ashutosh, dev, kabir, manan, rahul, ratan, rohan, shubh, sumit, varun
                "voices_female": ["priya", "ishita", "pooja", "kavya", "neha", "ritu", "roopa", "suhani", "tanya", "simran", "kavitha", "rupali", "shruti", "shreya", "amelia", "sophia"],
                "voices_male": ["shubh", "ratan", "rahul", "amit", "rohan", "aditya", "dev", "kabir", "manan", "sumit", "varun", "aayan", "advait", "ashutosh"],
                "language": ["hi-IN", "en-IN", "mr-IN", "ta-IN", "te-IN", "kn-IN", "ml-IN", "gu-IN", "bn-IN", "od-IN", "pa-IN"],
                "genders": ["female", "male", "neutral"],
            },
            "notes": "₹3/1k chars (₹30/10k). Streaming via livekit-plugins-sarvam. Gender picks the speaker (female→priya/ishita, male→shubh/ratan); language follows the agent language.",
        },
        "sarvam_bulbul_v2": {
            "kind": "tts",
            "display_name": "Sarvam Bulbul v2 (RETIRED by Sarvam — auto-upgraded to v3)",
            "provider": "sarvam",
            "model": "bulbul:v2",
            "tier": "paid",
            "requires_key": True,
            "key_env": "SARVAM_API_KEY",
            "cost": {"per_1k_chars": 1.5},
            "currency": "INR",
            "deprecated": True,  # Sarvam returns 400 'deprecated'; runtime upgrades to bulbul:v3
            "options": {
                "voices_female": ["anushka", "vidya", "manisha"],
                "voices_male": ["abhilash", "hitesh", "karun", "arya"],
                "language": ["hi-IN", "en-IN", "mr-IN", "ta-IN", "te-IN", "kn-IN", "ml-IN", "gu-IN", "bn-IN", "pa-IN"],
                "genders": ["female", "male", "neutral"],
            },
            "notes": "RETIRED by Sarvam (every request now returns 400). Saved configs auto-upgrade to bulbul:v3 at call time; pick Bulbul v3 instead.",
        },
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
            "kind": "tts", "deprecated": True,
            "display_name": "OpenRouter Deepgram Flux TTS (FREE, English only)",
            "provider": "openrouter",
            "model": "deepgram/flux-tts:free",
            "voice": "flux-bree-en",
            "language": "en",
            "tier": "free",
            "requires_key": True,
            "key_env": "OPENROUTER_API_KEY",
            "cost": {"per_1k_chars": 0.00},
            "notes": "FREE but ENGLISH-only.",
            "options": {"voice": ["flux-bree-en", "flux-alexis-en", "flux-priya-en", "flux-maeve-en"]},
        },
        "openrouter_kokoro_tts": {
            "kind": "tts", "deprecated": True,
            "display_name": "OpenRouter Kokoro 82M (multilingual, paid)",
            "provider": "openrouter",
            "model": "hexgrad/kokoro-82m",
            "voice": "af_bella",
            "language": "en",
            "tier": "paid",
            "requires_key": True,
            "key_env": "OPENROUTER_API_KEY",
            "cost": {"per_1k_chars": 0.20},
            "notes": "Multilingual.",
            "options": {"voice": ["af_bella", "af_heart", "am_michael", "hf_alpha", "hf_beta"]},
        },
    },
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

# ---------------------------------------------------------------------------
# Build LLM catalog from new V2 architecture with backward compat
# ---------------------------------------------------------------------------
def _build_llm_catalog_v2_with_compat():
    """Populate CATALOG['llm'] from new LLM_PROVIDERS and LLM_MODELS with backward compat."""
    llm_catalog = {}
    
    # New provider → models structure: each provider id has multiple models
    # For backward compat, also create old-style ids like openai_gpt_4_1_mini
    # that map to provider=openai, model=gpt-4.1-mini
    
    # First, add new-style entries: provider id itself (e.g., "openai") with models list
    # But old code expects CATALOG["llm"] to be dict of provider_id -> spec with model field
    # We will create both:
    # - New style: "openai" provider with models catalog
    # - Old style: "openai_gpt_4_1_mini" etc for backward compat, marked deprecated
    
    # Map old ids to new provider/model for backward compat
    old_id_mapping = {
        "openai_gpt_4o_mini": ("openai", "gpt-4o-mini"),
        "openai_gpt_4o": ("openai", "gpt-4o"),
        "openai_gpt_4_1_mini": ("openai", "gpt-4.1-mini"),
        "openai_gpt_4_1": ("openai", "gpt-4.1"),
        "openai_gpt_oss_120b": ("openai", "gpt-4o"),  # Old invalid mapping, now points to valid gpt-4o
        "groq_gpt_oss": ("groq", "openai/gpt-oss-120b"),
        "groq_gpt_oss_20b": ("groq", "openai/gpt-oss-20b"),
        "groq_llama_3_3_70b": ("groq", "meta-llama/llama-4-maverick-17b-128e-instruct"),  # llama-3.3 retired 08/16/26 -> Llama 4 Maverick
        "groq_qwen_3_8_27b": ("groq", "qwen/qwen3.8-27b"),  # Qwen3 (deprecated) -> Qwen3.6 (superseded 2026-09-24) -> Qwen3.8 27B, Groq's current
        # openrouter is deprecated: map its legacy ids onto live equivalents so an
        # agent saved against them keeps working (and stops rate-limiting).
        "openrouter_gemma": ("google", "gemini-2.5-flash-lite"),
        "openrouter_gemma_26b": ("google", "gemini-2.5-flash-lite"),
    }
    
    # Build new provider entries
    for prov_id, prov_meta in LLM_PROVIDERS.items():
        # Get models for this provider
        models = [m for m in LLM_MODELS if m["provider"] == prov_id and m["status"] == "active"]
        # For new architecture, provider entry contains models list
        llm_catalog[prov_id] = {
            "kind": "llm",
            "id": prov_id,
            "display_name": prov_meta["display_name"],
            "provider": prov_meta["provider_type"],
            "provider_id": prov_id,
            "base_url": prov_meta["base_url"],
            "tier": prov_meta["tier"],
            "requires_key": prov_meta["requires_key"],
            "key_env": prov_meta["key_env"],
            "notes": prov_meta.get("notes", ""),
            "models": models,  # Rich model catalog
            "model_count": len(models),
            # For backward compat, keep single model field as first model
            "model": models[0]["model_id"] if models else "",
            "cost": {
                "per_1k_in": models[0]["input_price_per_1m"] / 1000 if models else 0,
                "per_1k_out": models[0]["output_price_per_1m"] / 1000 if models else 0,
            } if models else {},
            "options": {
                "model": [m["model_id"] for m in models],
            },
        }
    
    # Add backward compat old ids
    for old_id, (new_prov, new_model) in old_id_mapping.items():
        model_meta = _get_llm_model_v2(new_prov, new_model)
        if not model_meta:
            # Try by model_id alone
            model_meta = _get_llm_model_v2(new_prov, new_model) or next((m for m in LLM_MODELS if m["model_id"] == new_model), None)
        prov_meta = LLM_PROVIDERS.get(new_prov, {})
        if model_meta:
            llm_catalog[old_id] = {
                "kind": "llm",
                "id": old_id,
                "display_name": f"{model_meta['display_name']} (legacy id, use {new_prov} provider)",
                "provider": prov_meta.get("provider_type", new_prov),
                "provider_id": new_prov,
                "base_url": model_meta["base_url"],
                "model": model_meta["model_id"],
                "model_meta": model_meta,  # Rich metadata
                "tier": prov_meta.get("tier", "paid"),
                "requires_key": prov_meta.get("requires_key", True),
                "key_env": prov_meta.get("key_env", ""),
                "cost": {
                    "per_1k_in": model_meta["input_price_per_1m"] / 1000,
                    "per_1k_out": model_meta["output_price_per_1m"] / 1000,
                },
                "options": {
                    "model": [model_meta["model_id"]],
                },
                "notes": f"Legacy id for backward compat. New: provider={new_prov}, model={new_model}. {model_meta.get('notes','')}",
                "legacy": True,
                "new_provider": new_prov,
                "new_model": new_model,
            }
        else:
            # If model not found, keep minimal entry to avoid breaking existing agents
            llm_catalog[old_id] = {
                "kind": "llm",
                "id": old_id,
                "display_name": old_id,
                "provider": new_prov,
                "provider_id": new_prov,
                "base_url": prov_meta.get("base_url"),
                "model": new_model,
                "tier": "paid",
                "requires_key": True,
                "key_env": prov_meta.get("key_env", ""),
                "cost": {"per_1k_in": 0.15, "per_1k_out": 0.60},
                "options": {"model": [new_model]},
                "notes": f"Legacy id, maps to {new_prov}:{new_model}",
                "legacy": True,
            }
    
    return llm_catalog

CATALOG["llm"] = _build_llm_catalog_v2_with_compat()

# ---------------------------------------------------------------------------
# Helper functions - V2 architecture with backward compat
# ---------------------------------------------------------------------------
def providers_of(kind: str) -> List[Dict[str, Any]]:
    """Return provider list for kind, each with id embedded.
    
    For LLM, filter out legacy ids from main catalog list to avoid cluttering UI
    with 'GPT-4o Mini (legacy id, use openai provider)' etc. Legacy ids still
    exist in CATALOG['llm'] for backward compat (old agents), but are hidden from
    provider dropdown. Frontend V2 uses llm_providers (3 providers) + llm_by_provider
    for model selection. Legacy mapping still works for existing agents.
    """
    out = []
    for pid, spec in CATALOG.get(kind, {}).items():
        # For LLM, hide legacy ids from providers_of to clean UI
        if kind == "llm" and spec.get("legacy"):
            continue
        # Hide deprecated providers (e.g. the OpenRouter TTS entries) from the
        # picker; get_provider() still resolves them for saved agents.
        if spec.get("deprecated"):
            continue
        item = dict(spec)
        item["id"] = pid
        out.append(item)
    return out

def get_provider(kind: str, provider_id: str) -> Optional[Dict[str, Any]]:
    """Get provider by kind and id. Supports both new and legacy ids."""
    if kind == "llm":
        # Try new catalog first
        if provider_id in CATALOG["llm"]:
            return CATALOG["llm"][provider_id]
        # Try to parse provider:model format
        if ":" in provider_id:
            prov, model = provider_id.split(":", 1)
            model_meta = _get_llm_model_v2(prov, model)
            if model_meta:
                prov_meta = LLM_PROVIDERS.get(prov, {})
                return {
                    "kind": "llm",
                    "id": provider_id,
                    "display_name": model_meta["display_name"],
                    "provider": prov_meta.get("provider_type", prov),
                    "provider_id": prov,
                    "base_url": model_meta["base_url"],
                    "model": model_meta["model_id"],
                    "model_meta": model_meta,
                    "tier": prov_meta.get("tier", "paid"),
                    "requires_key": True,
                    "key_env": prov_meta.get("key_env", ""),
                    "cost": {
                        "per_1k_in": model_meta["input_price_per_1m"] / 1000,
                        "per_1k_out": model_meta["output_price_per_1m"] / 1000,
                    },
                }
        # Try model_id alone
        model_meta = next((m for m in LLM_MODELS if m["model_id"] == provider_id), None)
        if model_meta:
            prov_meta = LLM_PROVIDERS.get(model_meta["provider"], {})
            return {
                "kind": "llm",
                "id": provider_id,
                "display_name": model_meta["display_name"],
                "provider": prov_meta.get("provider_type", model_meta["provider"]),
                "provider_id": model_meta["provider"],
                "base_url": model_meta["base_url"],
                "model": model_meta["model_id"],
                "model_meta": model_meta,
                "tier": prov_meta.get("tier", "paid"),
                "requires_key": True,
                "key_env": prov_meta.get("key_env", ""),
                "cost": {
                    "per_1k_in": model_meta["input_price_per_1m"] / 1000,
                    "per_1k_out": model_meta["output_price_per_1m"] / 1000,
                },
            }
    return CATALOG.get(kind, {}).get(provider_id)

def catalog_summary() -> Dict[str, Any]:
    """Return catalogue organised for frontend config UI - backward compat + new."""
    out: Dict[str, Any] = {}
    for kind in ("llm", "stt", "tts", "telephony"):
        out[kind] = providers_of(kind)
    # Add new V2 structure for LLM
    out["llm_v2"] = _llm_catalog_summary_v2()
    from .llm_catalog import list_providers as _active_llm_providers
    out["llm_providers"] = _active_llm_providers()
    out["llm_models"] = LLM_MODELS
    out["llm_by_provider"] = {pid: [m for m in LLM_MODELS if m["provider"] == pid] for pid in LLM_PROVIDERS}
    return out

# ---------------------------------------------------------------------------
# New V2 API for LLM - Provider → Multiple Models
# ---------------------------------------------------------------------------
def get_llm_provider(provider_id: str) -> Optional[Dict[str, Any]]:
    return _get_llm_provider_v2(provider_id)

def get_llm_model(provider: str, model_id: str) -> Optional[Dict[str, Any]]:
    return _get_llm_model_v2(provider, model_id)

def list_llm_providers() -> List[Dict[str, Any]]:
    return _list_llm_providers_v2()

def list_llm_models_for_provider(provider: str) -> List[Dict[str, Any]]:
    return _list_llm_models_for_provider_v2(provider)

def validate_llm_provider_model(provider: str, model_id: str) -> tuple[bool, str]:
    return _validate_llm_provider_model(provider, model_id)

def calculate_llm_cost(provider: str, model_id: str, input_tokens: int, cached_input_tokens: int, output_tokens: int) -> Dict[str, float]:
    model = get_llm_model(provider, model_id)
    if not model:
        return {"input_cost": 0, "output_cost": 0, "total_llm_cost": 0}
    return _calculate_llm_cost_v2(model, input_tokens, cached_input_tokens, output_tokens)

def get_model_pricing(provider: str, model_id: str) -> Optional[Dict[str, Any]]:
    model = get_llm_model(provider, model_id)
    if not model:
        return None
    return {
        "provider": model["provider"],
        "model_id": model["model_id"],
        "display_name": model["display_name"],
        "input_price_per_1m": model["input_price_per_1m"],
        "cached_input_price_per_1m": model["cached_input_price_per_1m"],
        "output_price_per_1m": model["output_price_per_1m"],
        "context_window": model["context_window"],
        "max_output_tokens": model["max_output_tokens"],
        "reasoning_supported": model["reasoning_supported"],
        "reasoning_default": model["reasoning_default"],
        "streaming_supported": model["streaming_supported"],
        "tool_calling_supported": model["tool_calling_supported"],
        "structured_output_supported": model["structured_output_supported"],
        "expected_speed": model["expected_speed"],
        "status": model["status"],
        "capabilities": model["capabilities"],
        "notes": model["notes"],
        "base_url": model["base_url"],
    }
