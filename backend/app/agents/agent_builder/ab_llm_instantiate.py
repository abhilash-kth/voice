from __future__ import annotations

import logging
from typing import Any


logger = logging.getLogger("voice-agent-saas-agent-builder")


def _instantiate_llm(provider_type: str, llm_kwargs: dict) -> Any:
    """Build the provider's native LLM plugin from normalised kwargs.

    OpenAI-compatible providers (openai, groq, openrouter, sarvam) all share
    ``livekit.plugins.openai.LLM`` (Sarvam's chat-completions endpoint is
    OpenAI-compatible). Google Gemini has its own plugin with different kwarg
    names, so translate rather than pass blindly: an unexpected kwarg raises
    TypeError while the turn is being built and the agent goes silent.
    """
    if provider_type == "google":
        try:
            from livekit.plugins.google import LLM as GoogleLLM
        except ImportError as e:
            raise RuntimeError(
                f"Gemini provider needs livekit-plugins-google ({e}). It is already "
                "pinned for Google TTS/STT; if missing run "
                "`pip install livekit-plugins-google>=1.7.1` in the worker venv."
            ) from e
        gk = {k: v for k, v in llm_kwargs.items() if k in ("model", "api_key")}
        if llm_kwargs.get("max_completion_tokens"):
            gk["max_output_tokens"] = int(llm_kwargs["max_completion_tokens"])
        return GoogleLLM(**gk)

    if provider_type == "anthropic":
        try:
            from livekit.plugins.anthropic import LLM as AnthropicLLM
        except ImportError as e:
            raise RuntimeError(
                f"Claude provider needs livekit-plugins-anthropic ({e}). Run "
                "`pip install livekit-plugins-anthropic` in the worker venv."
            ) from e
        ak = {k: v for k, v in llm_kwargs.items() if k in ("model", "api_key")}
        if llm_kwargs.get("max_completion_tokens"):
            ak["max_tokens"] = int(llm_kwargs["max_completion_tokens"])
        return AnthropicLLM(**ak)

    from livekit.plugins.openai import LLM as OpenAILLM
    return OpenAILLM(**llm_kwargs)


