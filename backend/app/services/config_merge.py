"""Merge layer: DB snapshot + code catalogs -> sync getters.

Extracted from the old monolithic config_store — behavior unchanged.
Import via ``app.services.config_store`` (the façade re-exports everything).

Granularity contract (unchanged): code catalog entries for stt/tts/telephony
are keyed by *catalog id*, DB Provider rows by *slug*, and CatalogModel rows by
``catalogId``; the merge functions below reconcile all three levels.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .. import catalog as code_catalog
from .. import llm_catalog as code_llm
from .config_core import get_snapshot

logger = logging.getLogger("voice-agent-saas-config-store")


# ---------------------------------------------------------------------------
# Sync getters used by pipeline/billing — always safe, always fast
# ---------------------------------------------------------------------------


from .config_billing import(
    get_billing  # re-export  split to its own module,
)


def get_providers_of(kind: str) -> List[Dict[str, Any]]:
    """Picker list for a kind in code-catalog shape, DB snapshot merged over it.

    Granularity contract: code catalog entries for stt/tts/telephony are keyed
    by *catalog id* (e.g. ``deepgram_nova2``) while DB Provider rows are keyed
    by *provider slug* (``deepgram``) and CatalogModel rows by ``catalogId``.
    This function merges all three levels so customers see exactly the admin's
    choices — one entry per catalog id — and so admin-added provider rows
    (Fish/MiniMax/OpenAI TTS, …) appear as pickable entries when enabled.
    """
    snap = get_snapshot()
    code_provs = code_catalog.providers_of(kind)
    if snap.source != "db":
        return code_provs

    prov_rows = snap.providers.get(kind) or {}
    model_rows = snap.models.get(kind) or []

    out: List[Dict[str, Any]] = []
    seen: set = set()
    for p in code_provs:
        cid = p["id"]
        # provider slug: code entry's "provider" field (uuid slugs for stt/tts);
        # for LLM provider entries the slug IS the id.
        slug = p.get("provider_slug") or (p.get("provider_id") if kind == "llm" else None) \
            or p.get("provider") or cid
        prov_row = prov_rows.get(slug) or (prov_rows.get(cid) if cid in prov_rows else None)
        merged = dict(p)
        if prov_row is not None:
            merged.update(_provider_row_to_catalog_dict(prov_row, merged))
        if kind != "llm":
            mrow = next((m for m in model_rows if m.get("catalogId") == cid), None)
            if mrow is not None:
                merged = _apply_model_row(merged, mrow)
        merged["id"] = cid
        out.append(merged)
        seen.add(cid)

    # DB-only provider rows → one picker entry per model row (catalog id).
    if kind != "llm":
        for mrow in model_rows:
            cid = mrow.get("catalogId") or ""
            if not cid or cid in seen:
                continue
            prov_row = prov_rows.get(mrow.get("providerSlug") or "") or {}
            entry = {
                "id": cid, "kind": kind,
                "display_name": mrow.get("displayName") or cid,
                "provider": prov_row.get("providerType") or mrow.get("providerSlug") or cid,
                "providerSlug": mrow.get("providerSlug"),
                "model": mrow.get("modelId") or "",
                "tier": mrow.get("tier") or prov_row.get("tier") or "paid",
                "requires_key": bool(prov_row.get("requiresKey", True)),
                "key_env": prov_row.get("keyEnv") or "",
                "deprecated": mrow.get("status") == "deprecated" or prov_row.get("status") == "deprecated",
                "status": mrow.get("status") or "active",
                "notes": mrow.get("_meta", {}).get("notes") or prov_row.get("notes") or "",
                "cost": {},
                "adapter": prov_row.get("providerType") or "",
                "base_url": prov_row.get("baseUrl") or "",
            }
            if mrow.get("costPerMin"):
                entry["cost"]["per_min"] = mrow["costPerMin"]
            if mrow.get("costPer1kChars"):
                entry["cost"]["per_1k_chars"] = mrow["costPer1kChars"]
            opts = (mrow.get("_meta") or {}).get("options")
            if opts:
                entry["options"] = opts
            _meta = mrow.get("_meta") or {}
            for sk in ("speed_min", "speed_max", "speed_default"):
                if _meta.get(sk) is not None:
                    try:
                        entry[sk] = float(_meta[sk])
                    except (TypeError, ValueError):
                        pass
            if mrow.get("customerPricePerMin"):
                entry["customer_price_per_min"] = mrow["customerPricePerMin"]
            entry["enabled"] = bool(mrow.get("enabled", True)) and bool(prov_row.get("enabled", True))
            out.append(entry)
            seen.add(cid)
    else:
        # LLM: DB-only provider rows (Qwen/Claude…) get a slug-level entry.
        for slug, prow in prov_rows.items():
            if slug in seen:
                continue
            entry = {
                "id": slug, "kind": "llm",
                "display_name": prow.get("displayName") or slug,
                "provider": prow.get("providerType") or slug,
                "provider_id": slug, "providerSlug": slug,
                "base_url": prow.get("baseUrl") or "",
                "tier": prow.get("tier") or "paid",
                "requires_key": bool(prow.get("requiresKey", True)),
                "key_env": prow.get("keyEnv") or "",
                "notes": prow.get("notes") or "",
                "enabled": bool(prow.get("enabled", True)),
                "status": prow.get("status") or "active",
            }
            out.append(entry)
            seen.add(slug)
    return out


def _apply_model_row(entry: Dict[str, Any], mrow: Dict[str, Any]) -> Dict[str, Any]:
    """Merge a CatalogModel row into a picker entry (display/cost/options/price)."""
    out = dict(entry)
    meta = mrow.get("_meta") or {}
    if mrow.get("displayName"):
        out["display_name"] = mrow["displayName"]
    cost = dict(out.get("cost") or {})
    if mrow.get("costPerMin"):
        cost["per_min"] = float(mrow["costPerMin"])
    if mrow.get("costPer1kChars"):
        cost["per_1k_chars"] = float(mrow["costPer1kChars"])
    if cost:
        out["cost"] = cost
    options = dict(meta.get("options") or out.get("options") or {})
    if options:
        out["options"] = options
    # Per-model TTS voice-speed range (Super Admin set on the Models page) →
    # the customer slider uses these bounds instead of the global Billing ones.
    for sk in ("speed_min", "speed_max", "speed_default"):
        if meta.get(sk) is not None:
            try:
                out[sk] = float(meta[sk])
            except (TypeError, ValueError):
                pass
    if mrow.get("customerPricePerMin"):
        out["customer_price_per_min"] = float(mrow["customerPricePerMin"])
        out["price_currency"] = mrow.get("priceCurrency") or "INR"
    if mrow.get("modelId"):
        out["model"] = mrow["modelId"]
    out["enabled"] = bool(mrow.get("enabled", True)) and bool(out.get("enabled", True))
    if mrow.get("status") == "deprecated":
        out["deprecated"] = True
    return out


def get_provider(kind: str, provider_id: str) -> Optional[Dict[str, Any]]:
    """Merged provider dict for (kind, catalog id). DB fields win when present."""
    snap = get_snapshot()
    base = code_catalog.get_provider(kind, provider_id)
    out = dict(base) if base else None
    slug = None
    if out is not None:
        slug = (out.get("provider_id") if kind == "llm" else None) or out.get("provider") or provider_id
    row = (snap.providers.get(kind) or {}).get(slug or provider_id)
    if row is None:
        row = (snap.providers.get(kind) or {}).get(provider_id)
    if out is None and row is not None:
        out = {"id": provider_id}
    if out is not None and row is not None:
        out.update(_provider_row_to_catalog_dict(row, out))
    if out is not None and kind != "llm":
        mrow = next((m for m in (snap.models.get(kind) or []) if m.get("catalogId") == provider_id), None)
        if mrow is not None:
            out = _apply_model_row(out, mrow)
    return out


def _provider_row_to_catalog_dict(row: Dict[str, Any], base: Dict[str, Any]) -> Dict[str, Any]:
    meta = row.get("_meta") if isinstance(row.get("_meta"), dict) else {}
    out: Dict[str, Any] = dict(meta)  # admin-editable extras last applied
    out.update({
        "display_name": row.get("displayName") or base.get("display_name") or row.get("slug"),
        "key_env": row.get("keyEnv") or base.get("key_env") or "",
        "tier": row.get("tier") or base.get("tier") or "paid",
        "requires_key": bool(row.get("requiresKey", base.get("requires_key", True))),
        "enabled": bool(row.get("enabled", True)),
        "status": row.get("status") or base.get("status", "active"),
        "notes": row.get("notes") or base.get("notes", ""),
        "adapter": row.get("providerType") or base.get("provider_type") or base.get("adapter") or "",
        "base_url": row.get("baseUrl") or base.get("base_url") or "",
    })
    # Cost overrides: only when the admin set a non-zero override.
    cost = dict(base.get("cost") or {})
    if row.get("costPerMin"):
        cost["per_min"] = float(row["costPerMin"])
    if row.get("costPer1kChars"):
        cost["per_1k_chars"] = float(row["costPer1kChars"])
    if cost:
        out["cost"] = cost
    if row.get("customerPricePerMin"):
        out["customer_price_per_min"] = float(row["customerPricePerMin"])
    out["providerSlug"] = row.get("slug")
    return out


def get_llm_meta(provider_slug: str, model_id: str) -> Optional[Dict[str, Any]]:
    """LLM model meta in code-catalog shape; DB row overrides pricing fields."""
    code_meta = code_llm.get_llm_model(provider_slug, model_id)
    snap = get_snapshot()
    row = None
    for m in snap.models.get("llm") or []:
        if m.get("providerSlug") == provider_slug and (m.get("modelId") or "") == (model_id or ""):
            row = m
            break
    if code_meta is None and row is None:
        return None
    out = dict(code_meta) if code_meta else {"provider": provider_slug, "model_id": model_id}
    if row:
        meta = row.get("_meta") if isinstance(row.get("_meta"), dict) else {}
        if row.get("displayName"):
            out["display_name"] = row["displayName"]
        if row.get("inputPricePer1M"):
            out["input_price_per_1m"] = float(row["inputPricePer1M"])
        if row.get("cachedInputPricePer1M"):
            out["cached_input_price_per_1m"] = float(row["cachedInputPricePer1M"])
        if row.get("outputPricePer1M"):
            out["output_price_per_1m"] = float(row["outputPricePer1M"])
        if row.get("enabled") is not None:
            out["enabled"] = bool(row.get("enabled", True))
        for k in ("context_window", "max_output_tokens", "reasoning_supported",
                  "reasoning_default", "expected_speed", "capabilities",
                  "streaming_supported", "tool_calling_supported",
                  "structured_output_supported", "notes"):
            if meta.get(k) is not None:
                out[k] = meta[k]
    return out


def list_llm_models() -> List[Dict[str, Any]]:
    """All LLM model metas as code-shaped dicts (code list + DB-only additions).

    Used by validation paths that must recognise admin-added models."""
    snap = get_snapshot()
    models: Dict[str, Dict[str, Any]] = {}
    for m in code_llm.list_all_models():
        models[f"{m['provider']}::{m['model_id']}"] = dict(m)
    for row in snap.models.get("llm") or []:
        key = f"{row.get('providerSlug')}::{row.get('modelId') or ''}"
        merged = get_llm_meta(row.get("providerSlug") or "", row.get("modelId") or "")
        if merged:
            models[key] = merged
    return list(models.values())


def get_api_key(kind: str, slug: str) -> Optional[str]:
    """Decrypted provider API key from the ACTIVE credential row, or None.

    One key per provider: the panel stores SHARED credentials (kind "") so a
    single Sarvam/OpenAI/… key serves that provider's LLM/STT/TTS alike.
    Kind-specific rows are still honoured first (they win over the shared one
    for their own kind). Blocking-callers never see this: decryption is
    memoised per snapshot ts to keep the hot path cheap (keys change only via
    admin mutations which bump the snapshot)."""
    snap = get_snapshot()
    # Combine BOTH lists: kind-specific first (higher precedence), then shared.
    # (Using `or` here was wrong: a kind-specific list holding only disabled
    # rows would shadow an ACTIVE shared credential.)
    creds = (snap.credentials.get(f"{kind}:{slug}") or []) + \
            (snap.credentials.get(f":{slug}") or [])
    for c in creds:
        if c.get("status") != "active":
            continue
        enc = c.get("encValue") or ""
        if not enc:
            continue
        try:
            from . import crypto

            return crypto.decrypt_secret(enc)
        except Exception as e:
            logger.error(f"provider key decrypt failed for {kind}:{slug}: {e!r}")
            return None
    return None

def provider_base_url(kind: str, slug: str) -> str:
    return (get_provider(kind, slug) or {}).get("base_url") or ""
