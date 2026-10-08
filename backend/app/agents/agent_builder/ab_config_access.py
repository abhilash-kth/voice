from __future__ import annotations

import logging

logger = logging.getLogger("voice-agent-saas-agent-builder")

_LAST_MISS = ""


def _mask(key: str) -> str:
    """Log-safe display form — the key itself is never written to logs."""
    k = (key or "").strip()
    return f"…{k[-4:]}" if len(k) >= 4 else "(unreadable)"


def _key_miss_reason() -> str:
    """Why the last _provider_api_key() missed — append to raised errors so a
    failing call is self-diagnosing (UI shows this text)."""
    return _LAST_MISS


def _diag(kind: str, slug: str) -> str:
    """Pinpoint WHY the panel credential did not resolve: snapshot not loaded
    vs row missing/inactive vs decrypt failure."""
    try:
        from ...services import config_core, crypto
        snap = config_core.get_snapshot()
        if getattr(snap, "source", "code") != "db":
            return (" [diag: worker config snapshot NOT loaded from DB "
                    f"(source={snap.source}) — panel keys can't be found; check "
                    "DATABASE_URL / DB reachability from the worker, then redial]")
        rows = (snap.credentials.get(f"{kind}:{slug}") or []) + \
               (snap.credentials.get(f":{slug}") or [])
        if not rows:
            have = sorted({k.split(":", 1)[1] for k in (snap.credentials or {})})
            return (f" [diag: DB snapshot loaded but has no credential row for "
                    f"'{slug}' (have: {', '.join(have) or 'none'}) — add the key in "
                    "the panel exactly under this provider]")
        r = rows[0]
        if r.get("status") != "active":
            return f" [diag: credential for '{slug}' is '{r.get('status')}' — re-activate it in the panel]"
        if not (r.get("encValue") or ""):
            return f" [diag: credential for '{slug}' has an EMPTY stored value — re-add it in the panel]"
        try:
            crypto.decrypt_secret(r["encValue"])
        except Exception as e:
            return (f" [diag: credential for '{slug}' FAILED decryption: {e!r} — backend and worker "
                    "must share the same ADMIN_CONFIG_ENC_KEY(S)/JWT_SECRET]")
        return " [diag: key decrypts but lookup returned empty — please report this]"
    except Exception as e:
        return f" [diag unavailable: {e!r}]"


def _provider_api_key(kind: str, slug: str) -> str:
    """Provider API key = the Super Admin panel credential ONLY.

    Single source of truth: the encrypted ProviderCredential row the super
    admin saved (decrypted from the in-process config snapshot). .env is
    never consulted — a key that is not in the panel is simply missing, and
    the builders raise a panel-directed error instead of silently falling
    back to whatever happens to be exported on the host.
    """
    global _LAST_MISS
    _LAST_MISS = ""
    try:
        from ...services import config_store
        key = (config_store.get_api_key(kind, slug) or "").strip()
        if key:
            logger.info(f"🔑 {kind}:{slug} API key — Super Admin credential ({_mask(key)})")
            return key
    except Exception as e:
        logger.error(f"🔑 {kind}:{slug} credential lookup failed: {e!r}")
    _LAST_MISS = _diag(kind, slug)
    logger.error(
        f"⛔ No API key for provider '{slug}' ({kind}). Set it in the Super Admin "
        f"panel (Providers / Credentials) — provider keys are NOT read from .env.{_LAST_MISS}"
    )
    return ""


def _provider_base_url(kind: str, slug: str) -> str:
    try:
        from ...services import config_store
        return config_store.provider_base_url(kind, slug)
    except Exception:
        return ""
