"""
LiveKit worker - the runtime that turns a customer-saved AgentConfig into a
live phone/browser call for a logged-in user.

It:
  * reads the dispatched room metadata to find user_id + agent_id + call_id,
  * loads the agent + call record from the DB (SQLite or Neon via DATABASE_URL),
  * builds a LiveKit **v1** ``AgentSession``+``Agent`` for that config,
  * respects per-agent toggles: conversation memory on/off, recording on/off,
  * runs RAG (text + documents + FAQ) against the customer's knowledge base,
  * records transcripts + usage, and
  * POSTs the per-component cost breakdown + recording URL back to FastAPI.

This package keeps the full import surface of the old ``worker.py`` module.
Importing this package runs the same top-level bootstrap, in the same order:
thread-limit env caps, plugin registration, SSL prewarm + http_context patch,
Google auth prewarm, and tokenize prewarm.

Run with:
    python -m app.agents.worker
"""

from __future__ import annotations

from .dep_imports import (  # noqa: F401
    AgentConfig,
    Any,
    BILLING_INTERNAL_TOKEN,
    EGRESS_ENABLED,
    EGRESS_PUBLIC_BASE_URL,
    EGRESS_S3_BUCKET,
    EGRESS_S3_ENDPOINT,
    EGRESS_S3_REGION,
    Iterator,
    LIVEKIT_API_KEY,
    LIVEKIT_API_SECRET,
    LIVEKIT_URL,
    Optional,
    _hl,
    _ssl_prewarm,
    _threading_prewarm,
    aiohttp,
    annotations,
    asyncio,
    calculate_call_cost,
    db_init,
    deepgram,
    json,
    leadfile,
    logger,
    logging,
    memory,
    openai,
    os,
    re,
    repo,
    setup_logging,
    silero,
    sys,
    time,
    traceback,
    uuid,
)
from .ssl_cert_patch import (  # noqa: F401
    _build_ssl_context,
    _prewarm_ssl_context,
    _ssl_context_cache,
    _ssl_context_lock,
)
from .gcp_env import (  # noqa: F401
    CLOUD_PLATFORM_SCOPE,
    CREDS_CACHE,
    CREDS_LOCK,
    _INNER_ATTRS,
    _INNER_LIST_ATTRS,
    _ORIG_LOAD_CREDS,
    threading,
)
from .gcp_credentials import (  # noqa: F401
    creds_cache_key,
    default_credentials_path,
    install_credential_cache,
    warm_google_credentials,
)
from .tts_prewarm import (  # noqa: F401
    client_bound_loop,
    google_tts_credentials_path,
    guard_tts_client_loop,
    iter_tts_instances,
    warm_tts_off_loop,
)
from .runtime_env import (  # noqa: F401
    BILLING_BACKEND_URL,
    DEFAULT_FALLBACK_RESPONSE,
    DETERMINISTIC_CLOSING_MESSAGE,
    DETERMINISTIC_CLOSING_MESSAGE_EN,
    FALLBACK_REPLY,
    LLM_FALLBACK_DELAY,
    WORKER_AGENT_NAME,
    _AGENT_CACHE,
    _AGENT_CACHE_TTL,
    _DB_INIT_DONE,
    _FAIL_THRESHOLD_SECONDS,
    _PREEMPTIVE_ENABLED_FOR_LOG,
    _VAD_CACHE,
    _VAD_CACHE_LOCK,
    _get_deterministic_closing,
    _item_is_tool_related,
    _mark_call_failed,
    _msg_text,
    clean_reply_text,
)
from .connection_options import (  # noqa: F401
    _build_conn_options,
)
from .llm_timing_factory import (  # noqa: F401
    _create_llm_timing_wrapper,
)
from .llm_failover_wrap import (  # noqa: F401
    _create_llm_failure_logging_wrapper,
)
from .assistant_mode_setup import (  # noqa: F401
    build_assistant_session,
)
from .session_announcer import (  # noqa: F401
    build_announcement_session,
    start_egress,
)
from .worker_entrypoint import (  # noqa: F401
    _entrypoint_body,
    entrypoint,
)
from .billing_turn_report import (  # noqa: F401
    _billing_report,
    _post_billing,
)
from .job_prewarm import (  # noqa: F401
    _worker_load,
    prewarm,
)
try:
    from .runtime_env import google  # noqa: F401
except Exception:
    from .dep_imports import google  # noqa: F401
