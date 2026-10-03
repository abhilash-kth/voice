"""Catalog service façade.

The implementation is split by responsibility:

* ``catalog_seed.py``   — DB seeding: reproduces the code catalog into the
  Provider / CatalogModel tables the first time (idempotent), plus extra
  disabled providers (Qwen, Claude, Fish, MiniMax, OpenAI TTS) and
  env→credential seeding.
* ``catalog_public.py`` — builds the config snapshot from the DB and renders
  the user-facing (enabled-filtered) catalog payloads for /api/catalog and
  /api/llm/*.

This module re-exports everything so existing imports keep working::

    from app.services import catalog_service            # unchanged
    catalog_service.seed_defaults_if_empty()            # unchanged
    catalog_service.build_user_catalog()                # unchanged
"""
from .catalog_seed import (
    seed_defaults_if_empty,
    seed_credentials_from_env,
    EXTRA_PROVIDER_SEEDS,
)
from .catalog_public import (
    _now,
    build_snapshot_from_db,
    build_user_catalog,
    llm_providers_public,
    llm_models_for_provider_public,
    llm_model_details_public,
    validate_llm,
)

__all__ = [
    "seed_defaults_if_empty",
    "seed_credentials_from_env",
    "EXTRA_PROVIDER_SEEDS",
    "_now",
    "build_snapshot_from_db",
    "build_user_catalog",
    "llm_providers_public",
    "llm_models_for_provider_public",
    "llm_model_details_public",
    "validate_llm",
]
