# Internal Implementation Plan — Super Admin + Dynamic Configuration

> Working note for the session (authoritative user-facing docs are README / SUPER_ADMIN.md / SUPER_ADMIN_SETUP.md).

## Status (2026-10-02)

- ✅ Prisma engines unblocked in sandbox via GitHub mirror (`owengretzinger/prisma-engines-mirror`,
  commit `605197351a3c8bdd595af2d2a9bc3025bca48ea2` = Prisma CLI 5.22.0, debian-openssl-3.0.x).
  Runtime env kept in `/tmp/prisma-engines.env`: `PRISMA_VERSION=5.22.0`,
  `PRISMA_EXPECTED_ENGINE_VERSION=605197351a3c8bdd595af2d2a9bc3025bca48ea2`,
  `PRISMA_QUERY_ENGINE_BINARY` / `PRISMA_SCHEMA_ENGINE_BINARY` → `/tmp/prisma-engines-mirror/.../debian-openssl-3.0.x/`.
- ✅ schema.prisma extended: `User.role`/`disabled`, `Provider`, `CatalogModel`, `ProviderCredential`,
  `BillingConfig`, `AdminAuditLog` (codegen quirk: relation field must NOT be named `models`). Verified end-to-end vs SQLite.
- ✅ scripts/db-setup.sh supports `DB_PROVIDER=sqlite` (derives schema.sqlite.prisma, gitignored).
- ✅ services layer written: `services/crypto.py` (Fernet, key ids, rotation), `services/tts_speed.py`,
  `services/config_store.py` (snapshot + sync getters with code fallback).

## Next steps (execution order)

1. `services/credential_service.py` (mask + CRUD encrypting), `services/catalog_service.py`
   (scaffold: Provider/CatalogModel rows per code catalog, merge into api_payload shapes, user filters),
   `services/admin_service.py` (users/billing/audit/keys/stats).
2. `app/admin/{deps,schemas,routes}.py` — `/api/admin/*` with SUPER_ADMIN guard.
3. surgical edits: auth.py (role guard dep + login block disabled), repo.py, main.py
   (include admin router; init config_store in lifespan; wire pipeline-config through
   catalog_service user payload), billing.py (sync getters via config_store),
   agent_builder.py (remove temperature send; resolve api keys via config_store; voice speed via tts_speed),
   models.py (drop temperature from planning config; add voiceSpeed), llm_catalog.py (drop temperature keys),
   catalog.py (no-op; data moved by admin_service scaffold but code fallback must stay identical),
   campaign.py/worker.py/minimal edits.
4. frontend: AgentConfigForm (temperature removal, voiceSpeed, language template msg), App.tsx (role, admin link),
   apiClient (admin calls), types (+role, +voiceSpeed, +admin DTOs).
5. `/super-admin` Next.js app (Overview, Users, User detail, LLM, STT, TTS Models, Providers,
   API Keys, Billing, Usage, Audit Logs, Providers).
6. tests (crypto/tts_speed/validation + FastAPI route tests with in-memory DB via Prisma observable),
   docs (.env.example, SUPER_ADMIN.md, SUPER_ADMIN_SETUP.md, README updates).

## Env classification (summary)

STATIC_SECRET: DATABASE_URL, JWT_SECRET, ADMIN_CONFIG_ENC_KEY(S), *provider API keys (master fallback env)*, BACKEND_SECRET.
STATIC_INFRA: LIVEKIT_URL/KEY/SECRET, PORT, SMTP_*, CALL_WEBHOOK_URL...
DYNAMIC (admin panel): enabled flags, model ids, customer prices + per-kind costs, languages/voices,
server_cost_per_min, min_client_price, profit_margin, wallet topup amounts, provider API keys (credentials DB).
DEPRECATED: none found.

## Sandbox verification

venv `backend/.venv` (no livekit by design); run:
`source /tmp/prisma-engines.env; cd backend && . .venv/bin/activate && DB_PROVIDER=sqlite DATABASE_URL=file:./data/app.db python -m prisma db push --schema schema.sqlite.prisma && python -m prisma generate --schema schema.sqlite.prisma`
Then pytest + uvicorn import checks.
