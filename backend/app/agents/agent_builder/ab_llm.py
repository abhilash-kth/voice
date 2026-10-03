from __future__ import annotations

import time
import asyncio
import logging
import os
import re
from typing import Any, Optional

from ...models import AgentConfig, KnowledgeBase
from ...config import (
    GROQ_API_KEY,
    OPENAI_API_KEY,
    DEEPGRAM_API_KEY,
    GOOGLE_APPLICATION_CREDENTIALS,
    OPENROUTER_API_KEY,
    GEMINI_API_KEY,
    SARVAM_API_KEY,
    CARTESIA_API_KEY,
    ANTHROPIC_API_KEY,
    QWEN_API_KEY,
    FISH_AUDIO_API_KEY,
    MINIMAX_API_KEY,
)

logger = logging.getLogger("voice-agent-saas-agent-builder")


# cross-module imports (auto-generated)
from .ab_llm_pair import _build_llm_from_pair

def build_llm(cfg: AgentConfig) -> Any:
    """Build LLM with optional fallback via LiveKit FallbackAdapter - V2 Provider → Multiple Models.
    
    Primary and fallback both support multiple models.
    Provider and model remain separate fields, no silent substitution.
    Logs explicit provider/model/base_url/fallback for 404 debugging.
    """
    # Get primary and fallback using new V2 methods if available
    try:
        primary_pair = cfg.providers.get_primary_llm()
        fallback_pair = cfg.providers.get_fallback_llm()
    except AttributeError:
        primary_pair = getattr(cfg.providers, "llm", None)
        fallback_pair = getattr(cfg.providers, "llm_fallback", None)
        if not fallback_pair:
            try:
                fp = getattr(cfg, "fallback_providers", None)
                if fp and getattr(fp, "llm", None):
                    fallback_pair = fp.llm
            except Exception:
                pass

    if not primary_pair:
        from ...models import ProviderPair
        primary_pair = ProviderPair(id="openai_gpt4o_mini", config={})

    # Log LLM PROVIDER CONFIG for primary
    try:
        prov, model, base_url = primary_pair.resolve_llm_provider_model()
        logger.info(f"🤖 LLM PRIMARY CONFIG provider={prov} model={model} base_url={base_url or 'https://api.openai.com/v1'} raw_id={primary_pair.id}")
    except Exception as e:
        logger.warning(f"Could not log primary LLM config: {e}")

    if fallback_pair:
        try:
            prov, model, base_url = fallback_pair.resolve_llm_provider_model()
            logger.info(f"🤖 LLM FALLBACK CONFIG provider={prov} model={model} base_url={base_url or 'https://api.openai.com/v1'} raw_id={fallback_pair.id}")
        except Exception as e:
            logger.warning(f"Could not log fallback LLM config: {e}")

    def _pm_attach(inst, pair):
        # 12:28 attribution fix: stamp each LLM instance with ITS OWN
        # provider/model/base_url. The worker's timing wrapper used to hand the
        # PRIMARY's provider_info to every FallbackAdapter inner instance, so an
        # OpenAI fallback completion logged (and priced) as
        # provider=groq model=qwen/qwen3.8-27b — including real cached tokens
        # (1152/1536 — OpenAI 128-token cache blocks) appearing on "Groq"
        # records. With the stamp, the wrapper reads identity from the instance
        # that actually served; usage can never be attributed to the chain head.
        try:
            pr, mo, bu = pair.resolve_llm_provider_model()
            inst._prov_meta = {"provider": pr, "model_id": mo, "base_url": bu or ""}
        except Exception:
            try:
                inst._prov_meta = {"provider": pair.id, "model_id": (pair.config or {}).get("model", ""), "base_url": ""}
            except Exception:
                pass

    # Build primary with exact model, no silent substitution
    primary = _build_llm_from_pair(primary_pair, getattr(cfg, "language", "hi"))
    _pm_attach(primary, primary_pair)

    # Cache fix v3: make prompt_cache_key per-agent so that per-agent owner/KB/FAQ
    # content is genuinely identical for same key. Global key voice-gpt-4.1-mini-v1
    # caused cross-agent thrashing and violated "identical for same cache key"
    # principle when stable included per-agent content. Per-agent key restores
    # reliable within-agent caching while still using native_explicit mode.
    try:
        _agent_short = (getattr(cfg, "id", "") or getattr(cfg, "name", "") or "")[:12]
        _agent_short = "".join(c for c in _agent_short if c.isalnum())[:8] or "agent"
        # Resolve model_id for key
        try:
            _, _model_id_for_key, _ = primary_pair.resolve_llm_provider_model()
        except Exception:
            _model_id_for_key = (primary_pair.config or {}).get("model", "gpt-4.1-mini")
        _per_agent_key = f"voice-{_model_id_for_key}-{_agent_short}-v1"
        # Only for OpenAI (native_explicit)
        try:
            from ...llm_catalog import get_prompt_cache_capability as _gcc_key
            _cap_for_key = _gcc_key("openai", _model_id_for_key)
            if _cap_for_key.get("mode") == "native_explicit":
                if hasattr(primary, "_opts") and hasattr(primary._opts, "prompt_cache_key"):
                    primary._opts.prompt_cache_key = _per_agent_key
                    logger.info(f"🔧 Per-agent prompt_cache_key={_per_agent_key} (agent {_agent_short}) for reliable caching — identical for same agent across turns")
        except Exception as _ke:
            logger.debug(f"Per-agent cache key setup skipped: {_ke!r}")
    except Exception as _e:
        logger.debug(f"Per-agent cache key outer skipped: {_e!r}")

    # Build fallback chain - supports multiple models, provider/model separate
    fallbacks = []
    if fallback_pair:
        # Validate fallback is not same as primary (same provider and model)
        try:
            p_prov, p_model, _ = primary_pair.resolve_llm_provider_model()
            f_prov, f_model, _ = fallback_pair.resolve_llm_provider_model()
            if not (p_prov == f_prov and p_model == f_model):
                fallbacks.append(fallback_pair)
            else:
                logger.info(f"Fallback same as primary ({p_prov}:{p_model}), skipping")
        except Exception:
            # Fallback to old comparison
            if not (fallback_pair.id == primary_pair.id and (fallback_pair.config or {}).get("model") == (primary_pair.config or {}).get("model")):
                fallbacks.append(fallback_pair)

    # Safety net for Groq 120b 404 - add 20b if 120b present and 20b not, with explicit logging
    try:
        chain_ids = []
        try:
            p_prov, p_model, _ = primary_pair.resolve_llm_provider_model()
            chain_ids.append(f"{p_prov}:{p_model}")
        except Exception:
            chain_ids.append(primary_pair.id)
        for fb in fallbacks:
            try:
                f_prov, f_model, _ = fb.resolve_llm_provider_model()
                chain_ids.append(f"{f_prov}:{f_model}")
            except Exception:
                chain_ids.append(fb.id)
        
        has_120b = any("gpt-oss-120b" in cid for cid in chain_ids)
        has_20b = any("gpt-oss-20b" in cid for cid in chain_ids)
        if has_120b and not has_20b:
            from ...models import ProviderPair
            safety_pair = ProviderPair(id="groq", config={"model": "openai/gpt-oss-20b", "max_tokens": 80, "provider": "groq"})
            fallbacks.append(safety_pair)
            logger.info(f"🛡️ Added safety fallback groq:openai/gpt-oss-20b because chain contains gpt-oss-120b which observed 404 recovery failed")
    except Exception as e:
        logger.debug(f"Could not add safety fallback: {e}")

    if not fallbacks:
        logger.info(f"🤖 LLM single provider (no fallback): primary={primary_pair.id}")
        return primary

    fallback_instances = []
    fallback_ids = []
    for fb_pair in fallbacks:
        try:
            inst = _build_llm_from_pair(fb_pair, getattr(cfg, "language", "hi"))
            _pm_attach(inst, fb_pair)
            # Per-agent cache key for fallback too (same agent short as primary)
            try:
                _agent_short_fb = (getattr(cfg, "id", "") or getattr(cfg, "name", "") or "")[:12]
                _agent_short_fb = "".join(c for c in _agent_short_fb if c.isalnum())[:8] or "agent"
                try:
                    _, _model_id_fb, _ = fb_pair.resolve_llm_provider_model()
                except Exception:
                    _model_id_fb = (fb_pair.config or {}).get("model", "gpt-4.1-mini")
                _per_agent_key_fb = f"voice-{_model_id_fb}-{_agent_short_fb}-v1"
                try:
                    from ...llm_catalog import get_prompt_cache_capability as _gcc_fb
                    _cap_fb = _gcc_fb("openai", _model_id_fb)
                    if _cap_fb.get("mode") == "native_explicit":
                        if hasattr(inst, "_opts") and hasattr(inst._opts, "prompt_cache_key"):
                            inst._opts.prompt_cache_key = _per_agent_key_fb
                except Exception:
                    pass
            except Exception:
                pass
            fallback_instances.append(inst)
            fallback_ids.append(fb_pair.id)
        except Exception as e:
            logger.error(f"❌ Could not build LLM fallback {fb_pair.id}: {e} - clear config error, no silent substitution")
            # Do not silently skip, log error but continue to try other fallbacks
            # If all fallbacks fail, primary will be used alone

    if not fallback_instances:
        logger.warning(f"⚠️ No valid fallback built, using primary only")
        return primary

    try:
        from livekit.agents import llm as llm_agents
        all_llms = [primary] + fallback_instances
        # ── FallbackAdapter lifecycle (livekit-agents 1.8.2) — DOCUMENTED, not
        # patched (per task spec). Exactly what the log sequence means:
        #  FallbackLLMStream._run() walks the chain; per available instance it
        #  calls llm.chat() — a WRAPPED call, one "LLM REQUEST START … primary/
        #  0-of-2". Groq's 429 raises inside that attempt; the adapter logs
        #  "…failed, switching to next LLM", marks the instance unavailable and
        #  starts a BACKGROUND RECOVERY PROBE (_try_recovery →
        #  _try_generate(check_recovery=True) → another real chat() on primary/
        #  0-of-2 — the line seen while the fallback is still streaming; NOT a
        #  duplicate turn request. It is labelled 🧪 [LLM_RECOVERY_PROBE] here,
        #  kept out of turn accounting, latency state, generation ids and
        #  customer billing (it is provider-infra cost, not the caller's).
        #  Then _run continues to the next instance: "fallback/1-of-2" answers —
        #  one valid active generation per turn, no retry on the 429'd model
        #  (max_retry_per_llm=0 default), attempt_timeout=5.0s. A failed probe
        #  leaves the instance unhealthy until the "all failed" pass of the
        #  NEXT real request re-tries it.
        adapter = llm_agents.FallbackAdapter(all_llms)
        # Log full chain with exact provider/model/base_url
        try:
            chain_details = []
            for pair in [primary_pair] + fallbacks:
                try:
                    prov, model, base_url = pair.resolve_llm_provider_model()
                    chain_details.append(f"{prov}:{model} @ {base_url or 'https://api.openai.com/v1'} (id={pair.id})")
                except Exception:
                    chain_details.append(f"{pair.id}")
            chain_str = " -> ".join([primary_pair.id] + fallback_ids)
            logger.info(f"🔁 LLM FallbackAdapter armed: {chain_str} | Details: {' -> '.join(chain_details)} | Provider and model remain separate, no silent substitution")
        except Exception:
            chain_str = " -> ".join([primary_pair.id] + fallback_ids)
            logger.info(f"🔁 LLM FallbackAdapter armed: {chain_str} (provider/model separate)")
        return adapter
    except Exception as e:
        logger.error(f"❌ Could not build LLM FallbackAdapter {fallback_ids}: {e} - using primary only, error: {e}")
        return primary


