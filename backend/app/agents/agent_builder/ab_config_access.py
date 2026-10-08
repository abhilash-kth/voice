from __future__ import annotations

import logging

logger = logging.getLogger("voice-agent-saas-agent-builder")


def _mask(key: str) -> str:
    """Log-safe display form — the key itself is never written to logs."""
    k = (key or "").strip()
    return f"…{k[-4:]}" if len(k) >= 4 else "(unreadable)"


def _provider_api_key(kind: str, slug: str) -> str:
    """Provider API key = the Super Admin panel credential ONLY.

    Single source of truth: the encrypted ProviderCredential row the super
    admin saved (decrypted from the in-process config snapshot). .env is
    never consulted — a key that is not in the panel is simply missing, and
    the builders raise a panel-directed error instead of silently falling
    back to whatever happens to be exported on the host.
    """
    try:
        from ...services import config_store
        key = (config_store.get_api_key(kind, slug) or "").strip()
        if key:
            logger.info(f"🔑 {kind}:{slug} API key — Super Admin credential ({_mask(key)})")
            return key
    except Exception as e:
        logger.error(f"🔑 {kind}:{slug} credential lookup failed: {e!r}")
    stale_hint = ""
    try:
        from ...services import config_store
        if getattr(config_store.get_snapshot(), "source", "code") != "db":
            stale_hint = (" NOTE: the worker's config snapshot was NOT loaded from the DB for this job "
                          "(job-start refresh failed) — check DATABASE_URL / DB reachability from the "
                          "worker, then redial.")
    except Exception:
        pass
    logger.error(
        f"⛔ No API key for provider '{slug}' ({kind}). Set it in the Super Admin "
        f"panel (Providers / Credentials) — provider keys are NOT read from .env.{stale_hint}"
    )
    return ""


def _provider_base_url(kind: str, slug: str) -> str:
    try:
        from ...services import config_store
        return config_store.provider_base_url(kind, slug)
    except Exception:
        return ""
