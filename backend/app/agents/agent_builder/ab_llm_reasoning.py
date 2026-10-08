"""Reasoning-mode + completion-token budget assembly for the LLM pair build
(gpt-5/o-family hidden-token budget safety; catalog defaults).
Extracted 1:1 from `agent_builder/ab_llm_pair.py` (<=300-line rule).
"""
from __future__ import annotations

import logging
import time

logger = logging.getLogger("voice-agent-saas-agent-builder")


def resolve_reasoning_budget(provider, model_id, overrides):
    low = model_id.lower()

    # Determine reasoning effort from model metadata or overrides
    # FIX: For voice, always use low reasoning to reduce TTFT variance (0.77s-1.33s observed for gpt-5.4-mini)
    # gpt-5.4-mini has reasoning_default medium which causes variable reasoning tokens before first token
    # Voice needs fast first token, so force low unless explicitly overridden
    try:
        from ...llm_catalog import get_llm_model
        meta = get_llm_model(provider, model_id)
        if meta:
            # For voice, override medium/high to low to reduce TTFT
            catalog_default = meta.get("reasoning_default") or ("low" if meta.get("reasoning_supported") else "none")
            # If model supports reasoning and catalog says medium/high, force low for voice low-latency
            if meta.get("reasoning_supported") and catalog_default in ("medium", "high"):
                default_reasoning = "low"
                # Log that we are reducing reasoning for voice
                logger.info(f"🔧 Voice reasoning override: model {model_id} catalog default {catalog_default} -> low for voice to reduce TTFT variance (0.77-1.33s -> more consistent)")
            else:
                default_reasoning = catalog_default
        else:
            if "qwen" in low or "gemma" in low:
                default_reasoning = "none"
            elif "gpt-oss" in low:
                default_reasoning = "low"
            else:
                default_reasoning = "none"
    except Exception:
        if "qwen" in low or "gemma" in low:
            default_reasoning = "none"
        elif "gpt-oss" in low:
            default_reasoning = "low"
        else:
            default_reasoning = "none"

    reasoning = overrides.get("reasoning_effort", default_reasoning)
    # Extra safety: if reasoning is medium/high for voice, downgrade to low
    if reasoning in ("medium", "high") and provider in ("openai", "groq", "openrouter", "google", "sarvam"):
        logger.info(f"🔧 Downgrading reasoning_effort {reasoning} -> low for voice model {model_id} to reduce TTFT")
        reasoning = "low"

    # Completion-token budget for a voice reply. Non-reasoning models: 80 is
    # plentiful (~60 spoken words) and keeps replies short. REASONING models
    # (gpt-5 family) spend HIDDEN reasoning tokens from the SAME budget —
    # first failure at cap 80, then AGAIN at cap 500 on a vague question
    # (2026-09-19 04:19: output=500/finish_reason=length with ZERO visible text
    # -> 6s watchdog apology). Diffuse prompts can burn >500 tokens of thinking;
    # 800 leaves headroom for think + reply without turning typical turns slow
    # (the model still stops early at natural completion).
    _cap_override = overrides.get("max_tokens")
    _reasoning_mdl = bool((meta or {}).get("reasoning_supported"))
    if _cap_override:
        _cap = int(_cap_override)
        if _reasoning_mdl and _cap < 500:
            logger.warning(
                f"⚠️ max_tokens={_cap} is too small for reasoning model {model_id}: the cap is spent on "
                "hidden reasoning tokens leaving ZERO text for the spoken reply (agent went silent). Raising to 800."
            )
            _cap = 800
    else:
        _cap = 800 if _reasoning_mdl else 80
    return low, meta, reasoning, _cap_override, _reasoning_mdl, _cap
