"""
Builds the LiveKit **v1** voice-runtime pieces from a customer-saved AgentConfig.

LiveKit v1 (livekit-agents 1.7.x) replaced ``VoicePipelineAgent`` with the
``Agent``/``AgentSession`` pair, and the per-turn RAG / cross-call memory hooks
moved to ``Agent`` methods. This package keeps the full import surface of the
old ``agent_builder.py`` module - same builders, same names.

All LiveKit plugin imports are done lazily inside functions so the FastAPI /
management layer can boot even when the livekit packages aren't installed in
that particular interpreter (e.g. a lightweight CI or a machine that only runs
the API).
"""
from __future__ import annotations  # noqa: F401

from .ab_config_access import (  # noqa: F401
    _provider_api_key,
    _provider_base_url,
    logger,
)
from .ab_voices import (  # noqa: F401
    _AGENT_LOCALES,
    _CHIRP3_VOICES,
    _resolve_tts_voice,
    locale_for_language,
)
from .ab_llm_instantiate import (  # noqa: F401
    _instantiate_llm,
)
from .ab_llm_pair import (  # noqa: F401
    _build_llm_from_pair,
)
from .ab_llm import (  # noqa: F401
    build_llm,
)
from .ab_stt import (  # noqa: F401
    _build_stt_from_pair,
    build_stt,
)
from .ab_tts_select import (  # noqa: F401
    _normalized_voice_speed,
    _tts_adapter_for_pair,
)
from .ab_tts_pair import (  # noqa: F401
    _build_tts_from_pair,
)
from .ab_tts import (  # noqa: F401
    build_tts,
)
from .ab_vad import (  # noqa: F401
    _VAD_CACHE_AGENT,
    _VAD_CACHE_LOCK_AGENT,
    _vad_tuning,
    build_vad,
)
from .ab_budgets import (  # noqa: F401
    _FAQ_BUDGET_CHARS,
    _FAQ_BUDGET_CHARS_DEFAULT,
    _FAQ_BUDGET_CHARS_DEFAULT_GROQ,
    _FAQ_BUDGET_CHARS_VOICE_RAG,
    _KB_BUDGET_CHARS,
    _KB_BUDGET_CHARS_DEFAULT,
    _KB_BUDGET_CHARS_DEFAULT_GROQ,
    _KB_BUDGET_CHARS_VOICE_RAG,
    _OWNER_PROMPT_BUDGET_CHARS,
    _OWNER_PROMPT_BUDGET_CHARS_DEFAULT,
    _OWNER_PROMPT_BUDGET_CHARS_DEFAULT_GROQ,
    _OWNER_PROMPT_BUDGET_CHARS_VOICE_RAG,
    _PRIOR_MEMORY_BUDGET_CHARS_VOICE_RAG,
    _effective_budgets,
)
from .ab_prompt import (  # noqa: F401
    DETERMINISTIC_CLOSING,
    DETERMINISTIC_CLOSING_EN,
    _ACK_REPLY_OUTPUTS,
    _FRAGMENT_TTL_S,
    _RAG_PREFIX,
    _SUPERSEDED_MERGE_MAX_AGE_S,
    _ack_reply_texts,
    _chat_msg_text,
    _find_chat_ctx,
    _frag_append_fresh,
    _frag_consume,
    _frag_norm,
    _get_closing_for_cfg,
    _rag_per_turn_enabled,
    _strip_trailing_ack_turns,
    _truncate,
)
from .ab_instructions import (  # noqa: F401
    _flatten_knowledge,
    build_instructions,
)
from .ab_opening import (  # noqa: F401
    speak_opening_line,
    wait_until_caller_can_hear,
    warm_agent_builder_schemas,
)
from .ab_agent import (  # noqa: F401
    build_voice_agent,
)
from .ab_announce import (  # noqa: F401
    build_announce_agent,
)

# Schema prewarm (was the tail of agent_builder.py): build the pydantic
# schemas once at import so the first real call never pays for it.
try:
    warm_agent_builder_schemas()
except Exception:
    pass
