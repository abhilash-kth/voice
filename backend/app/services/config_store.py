"""Dynamic configuration store façade.

Why this exists
---------------
The voice pipeline's config resolution (agent_builder, billing) is *sync* and
runs deep inside the LiveKit worker where awaiting the database is not an
option. This package therefore keeps a process-wide **ConfigSnapshot** that is

* refreshed asynchronously (API startup, admin mutations, TTL refresh, worker
  bootstrap), and
* read **synchronously** by the pipeline and billing paths.

When no snapshot has been loaded yet — or database access fails entirely —
every getter falls back to the *code defaults* in ``app/catalog.py`` and
``app/llm_catalog/``. That means behaviour with zero DB connectivity is
exactly the pre-existing behaviour (safe degraded mode).

Layout (this module re-exports everything, so imports keep working unchanged):
* ``config_core.py``  — ConfigSnapshot dataclass + refresh/invalidate lifecycle.
* ``config_merge.py`` — merge layer + the sync getters (billing/providers/
  models/api keys) consumed by agent_builder and billing.

Nothing in here logs or returns secrets.
"""
from .config_core import (
    ConfigSnapshot,
    get_snapshot,
    invalidate,
    refresh_if_stale,
    init,
    _code_fallback_snapshot,
    _reset_for_tests,
    _now_fallback,
)
from .config_merge import (
    get_billing,
    get_providers_of,
    get_provider,
    get_llm_meta,
    list_llm_models,
    get_api_key,
    provider_base_url,
    _apply_model_row,
    _provider_row_to_catalog_dict,
)

__all__ = [
    "ConfigSnapshot",
    "get_snapshot",
    "invalidate",
    "refresh_if_stale",
    "init",
    "_code_fallback_snapshot",
    "_reset_for_tests",
    "_now_fallback",
    "get_billing",
    "get_providers_of",
    "get_provider",
    "get_llm_meta",
    "list_llm_models",
    "get_api_key",
    "provider_base_url",
    "_apply_model_row",
    "_provider_row_to_catalog_dict",
]
