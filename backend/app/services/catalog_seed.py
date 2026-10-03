"""Catalog seeding: reproduces the code catalog into the DB (idempotent).

Extracted from the old monolithic catalog_service — behavior unchanged.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from .. import catalog as code_catalog
from .. import llm_catalog as code_llm
from ..db import get_prisma
from .config_store import ConfigSnapshot
from .catalog_public import _now  # shared timestamp helper (lives with the public renderers)
from .catalog_seeds_data import EXTRA_PROVIDER_SEEDS

logger = logging.getLogger("voice-agent-saas-catalog-service")

def _dump(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False)


def _load(s: Optional[str]) -> dict:
    if not s:
        return {}
    try:
        return json.loads(s)
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Seed data — providers that only exist in the dynamic catalog (not in code)
# ---------------------------------------------------------------------------
# LLM providers requested by product: OpenAI, Qwen, Claude, Google Gemini
# (OpenAI/Gemini/Groq/Sarvam come from the code catalog; Qwen + Claude are
# added here). TTS additions: Fish Voice, MiniMax Voice, OpenAI TTS. These are
# seeded DISABLED — the Super Admin turns them on explicitly and sets the API
# key, so nothing new appears in the customer UI until the platform wants it.
async def seed_defaults_if_empty() -> None:
    db = get_prisma()
    if await db.provider.count() > 0:
        return
    logger.info("🌱 Seeding dynamic catalog from code defaults …")
    rows = 0

    # --- STT / TTS / Telephony from the code catalog -------------------------
    provider_ids: Dict[Tuple[str, str], str] = {}

    async def _provider(kind: str, slug: str, defaults: dict) -> str:
        key = (kind, slug)
        if key in provider_ids:
            return provider_ids[key]
        p = await db.provider.upsert(
            where={"kind_slug": {"kind": kind, "slug": slug}},
            data={
                "create": {
                    "kind": kind, "slug": slug,
                    "displayName": defaults.get("display_name") or slug,
                    "providerType": defaults.get("adapter") or defaults.get("provider") or slug,
                    "baseUrl": defaults.get("base_url") or "",
                    "keyEnv": defaults.get("key_env") or "",
                    "tier": defaults.get("tier") or "paid",
                    "requiresKey": bool(defaults.get("requires_key", True)),
                    "enabled": bool(defaults.get("enabled", True)),
                    "status": defaults.get("status") or ("deprecated" if defaults.get("deprecated") else "active"),
                    "notes": defaults.get("notes") or "",
                    "sortOrder": int(defaults.get("sort_order", 0) or 0),
                    "createdAt": _now(), "updatedAt": _now(),
                },
                "update": {},
            },
        )
        provider_ids[key] = p.id
        return p.id

    for kind in ("stt", "tts", "telephony"):
        for cid, spec in code_catalog.CATALOG.get(kind, {}).items():
            slug = spec.get("provider") or cid
            pid = await _provider(kind, slug, {
                "display_name": spec.get("display_name"),
                "provider": spec.get("provider"),
                "key_env": spec.get("key_env"),
                "tier": spec.get("tier"),
                "requires_key": spec.get("requires_key", True),
                "deprecated": spec.get("deprecated", False),
            })
            meta = {
                "options": spec.get("options") or {},
                "voice": spec.get("voice") or "",
                "language": spec.get("language") or "",
                "notes": spec.get("notes") or "",
            }
            status = "deprecated" if spec.get("deprecated") else "active"
            await db.catalogmodel.upsert(
                where={"kind_catalogId_providerSlug_modelId": {
                    "kind": kind, "catalogId": cid, "providerSlug": slug,
                    "modelId": spec.get("model") or "",
                }},
                data={
                    "create": {
                        "kind": kind, "providerId": pid, "providerSlug": slug,
                        "catalogId": cid, "modelId": spec.get("model") or "",
                        "displayName": spec.get("display_name") or cid,
                        "enabled": not spec.get("deprecated", False) or bool(spec.get("legacy_shown", False)),
                        "status": status,
                        "tier": spec.get("tier") or "paid",
                        "costPerMin": float((spec.get("cost") or {}).get("per_min") or 0),
                        "costPer1kChars": float((spec.get("cost") or {}).get("per_1k_chars") or 0),
                        "meta": _dump(meta),
                        "sortOrder": rows,
                        "createdAt": _now(), "updatedAt": _now(),
                    },
                    "update": {},
                },
            )
            rows += 1

    # --- LLM providers + models from the code LLM catalog --------------------
    for slug, prov in code_llm.LLM_PROVIDERS.items():
        pid = await _provider("llm", slug, {
            "display_name": prov.get("display_name"),
            "adapter": prov.get("provider_type"),
            "base_url": prov.get("base_url"),
            "key_env": prov.get("key_env"),
            "tier": prov.get("tier"),
            "requires_key": prov.get("requires_key", True),
            "status": prov.get("status", "active"),
            "notes": prov.get("notes", ""),
        })
        for m in [x for x in code_llm.LLM_MODELS if x["provider"] == slug]:
            meta = {k: m.get(k) for k in (
                "context_window", "max_output_tokens", "reasoning_supported",
                "reasoning_default", "expected_speed", "capabilities",
                "streaming_supported", "tool_calling_supported",
                "structured_output_supported", "notes",
            ) if m.get(k) is not None}
            await db.catalogmodel.upsert(
                where={"kind_catalogId_providerSlug_modelId": {
                    "kind": "llm", "catalogId": slug, "providerSlug": slug,
                    "modelId": m["model_id"],
                }},
                data={
                    "create": {
                        "kind": "llm", "providerId": pid, "providerSlug": slug,
                        "catalogId": slug, "modelId": m["model_id"],
                        "displayName": m.get("display_name") or m["model_id"],
                        "enabled": m.get("status") != "deprecated",
                        "status": m.get("status", "active"),
                        "tier": prov.get("tier") or "paid",
                        "inputPricePer1M": float(m.get("input_price_per_1m") or 0),
                        "cachedInputPricePer1M": float(m.get("cached_input_price_per_1m") or 0),
                        "outputPricePer1M": float(m.get("output_price_per_1m") or 0),
                        "meta": _dump(meta),
                        "sortOrder": rows,
                        "createdAt": _now(), "updatedAt": _now(),
                    },
                    "update": {},
                },
            )
            rows += 1

    # --- Extra providers (Qwen / Claude / Fish / MiniMax / OpenAI TTS) --------
    for seed in EXTRA_PROVIDER_SEEDS:
        pid = await _provider(seed["kind"], seed["slug"], seed)
        for m in seed.get("models", []):
            await db.catalogmodel.upsert(
                where={"kind_catalogId_providerSlug_modelId": {
                    "kind": seed["kind"], "catalogId": seed["slug"],
                    "providerSlug": seed["slug"], "modelId": m["model_id"],
                }},
                data={
                    "create": {
                        "kind": seed["kind"], "providerId": pid,
                        "providerSlug": seed["slug"], "catalogId": seed["slug"],
                        "modelId": m["model_id"],
                        "displayName": m.get("display_name") or m["model_id"],
                        "enabled": bool(m.get("enabled", False)),
                        "status": "active",
                        "tier": seed.get("tier") or "paid",
                        "meta": _dump(m.get("meta") or {}),
                        "sortOrder": rows,
                        "createdAt": _now(), "updatedAt": _now(),
                    },
                    "update": {},
                },
            )
            rows += 1

    # --- Billing defaults (mirror env constants; zero behaviour change) -------
    from .. import config as _cfg

    await db.billingconfig.upsert(
        where={"id": "global"},
        data={
            "create": {
                "id": "global",
                "serverCostPerMin": _cfg.SERVER_COST_PER_MIN,
                "minClientPrice": _cfg.MIN_CLIENT_PRICE,
                "profitMarginPercent": _cfg.PROFIT_MARGIN_PERCENT,
                "walletTopupAmounts": json.dumps(_cfg.WALLET_TOPUP_AMOUNT),
                "updatedAt": _now(),
            },
            "update": {},
        },
    )

    logger.info(f"🌱 Dynamic catalog seeded ({rows} catalog rows).")


async def seed_credentials_from_env() -> int:
    """Opt-in import of provider keys from env vars into encrypted credentials.

    Runs only when SEED_PROVIDER_API_KEYS_FROM_ENV=true at API startup. For each
    provider whose ``keyEnv`` env var is set and that has no active credential
    yet, an encrypted credential row is created (masked in the UI from then on).
    The env var remains as a fallback until removed — the DB row wins.
    """
    import os

    if os.getenv("SEED_PROVIDER_API_KEYS_FROM_ENV", "").lower() != "true":
        return 0
    from . import crypto, credential_service

    db = get_prisma()
    created = 0
    providers = await db.provider.find_many()
    for p in providers:
        key_env = p.keyEnv or ""
        value = os.getenv(key_env, "").strip() if key_env else ""
        if not value:
            continue
        existing = await db.providercredential.find_first(
            where={"providerSlug": p.slug, "kind": p.kind, "status": "active"}
        )
        if existing:
            continue
        enc, masked = crypto.encrypt_secret(value)
        await db.providercredential.create(data={
            "providerId": p.id, "providerSlug": p.slug, "kind": p.kind,
            "label": f"seeded from {key_env}", "encValue": enc, "maskedValue": masked,
            "createdAt": _now(), "updatedAt": _now(),
        })
        created += 1
    if created:
        logger.info(f"🔑 Seeded {created} provider credential(s) from env vars.")
    return created


