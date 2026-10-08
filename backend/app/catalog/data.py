"""Code-level STT/TTS/telephony provider catalog (static reference data).

Extracted from catalog.py. LLM entries are populated separately by
``llm_compat`` from the llm_catalog package (never hardcoded here).
"""
from __future__ import annotations

from typing import Any, Dict, List


# Legacy STT/TTS/Telephony catalog (code-level reference data)
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
        "cartesia_sonic3": {
            "kind": "tts",
            "display_name": "Cartesia Sonic 3 (ultra-low-latency, 40+ languages)",
            "provider": "cartesia",
            "model": "sonic-3",
            "voice": "4459a9a5-69d6-4680-b970-e13dc51845b6",  # Indian female — gender default
            "language": "hi",
            "tier": "paid",
            "requires_key": True,
            "key_env": "CARTESIA_API_KEY",
            "cost": {"per_1k_chars": 4.2},
            "options": {
                "model": ["sonic-3", "sonic-2", "sonic-turbo", "sonic"],
                # Indian-accent voices from the operator's Cartesia account
                # (play.cartesia.ai/voices). Sonic voices are multilingual: any
                # voice below speaks every language in the `language` list.
                "voice": [
                    "4459a9a5-69d6-4680-b970-e13dc51845b6",  # female (Indian)
                    "01fc5e31-71e9-40dc-a220-06dbd4b4ed7e",  # female (Indian)
                    "32b0f12b-67c3-421d-8850-b46c019ced91",  # female (Indian)
                    "cb9c954d-bcaa-43ed-82bf-aeb5e88a3cb5",  # male (Indian)
                    "e6b71342-48f1-4c70-a13a-d197b176ff24",  # extra (Indian)
                ],
                # shown in the frontend dropdown next to the id
                "voice_labels": {
                    "4459a9a5-69d6-4680-b970-e13dc51845b6": "Female 1 (Indian)",
                    "01fc5e31-71e9-40dc-a220-06dbd4b4ed7e": "Female 2 (Indian)",
                    "32b0f12b-67c3-421d-8850-b46c019ced91": "Female 3 (Indian)",
                    "cb9c954d-bcaa-43ed-82bf-aeb5e88a3cb5": "Male 1 (Indian)",
                    "e6b71342-48f1-4c70-a13a-d197b176ff24": "Voice 5 (Indian)",
                },
                # Bare ISO-639-1 codes (Cartesia rejects full locales like hi-IN).
                "language": ["hi", "en", "bn", "ta", "te", "kn", "ml", "gu", "mr", "pa", "or", "ur", "es", "fr", "de", "pt", "zh", "ja"],
                "genders": ["female", "male", "neutral"],
            },
            "notes": "₹4.2/1k chars (~$50/1M). WebSocket streaming with sub-100ms first audio; Sonic 3 handles Hinglish code-mix. Gender picks the Indian voice (female→4459a9a5…, male→cb9c954d…); the agent language drives the spoken language. More Indian-accent voices: copy their id from play.cartesia.ai/voices into the voice list.",
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
