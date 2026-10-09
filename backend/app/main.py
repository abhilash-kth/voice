"""
FastAPI management + call-dispatch server for the Voice Agent SaaS platform.

Storage is Prisma (Neon/Postgres, or SQLite for local). Run from backend/:

    python -m prisma db push --schema schema.prisma
    python -m prisma generate --schema schema.prisma
    uvicorn app.main:app --port 8000 --reload

Endpoints: auth, agents, knowledge, calls, wallet, billing.
The LiveKit worker (app.agents.worker) reports cost/usage/transcripts here.

The route handlers live in ``app/routes/*.py`` (auth / catalog / agents /
calls / campaigns / billing); this file keeps the app factory, lifespan
(pre-startup seeding + stale-call sweeper + campaign dispatcher), CORS and the
global exception handler.
"""
from __future__ import annotations

import os
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import repo
from . import telephony
from . import campaign_runner
from .db import init, shutdown
from .admin import routes as admin_routes
from .services import config_store
from .routes import (auth_routes, catalog_routes, agents_routes,
                     calls_routes, campaigns_routes, billing_routes,
                     setup_routes, subscription_routes)

logger = logging.getLogger("voice-agent-saas-api")

@asynccontextmanager
async def lifespan(app):
    await init()

    # Dynamic configuration: seed providers/models from code defaults on the very
    # first boot (idempotent) and load the in-process snapshot that the voice
    # pipeline's sync paths read from. Failures are non-fatal: every getter falls
    # back to the code catalogs, which is exactly the pre-existing behaviour.
    try:
        await config_store.init()
    except Exception as e:
        logger.warning(f"dynamic config init failed (code defaults in effect): {e!r}")
    try:
        from .services import catalog_service as _catalog_service
        await _catalog_service.seed_credentials_from_env()
    except Exception as e:
        logger.warning(f"credential env seeding failed: {e!r}")

    # Import the voice runtime (livekit agents + plugins) on the main thread in
    # the background so the first start_call's preflight is instant and so the
    # plugin-registration-on-main-thread rule is satisfied before any worker
    # thread touches the plugin modules.
    async def _warm_runtime():
        try:
            from . import preflight as _preflight
            await _preflight.warm_voice_runtime()
        except Exception as e:
            logger.warning(f"voice runtime warm failed: {e!r}")

    warm_task = asyncio.create_task(_warm_runtime())

    # Safety net: any "in-progress" call that never got finalized (worker crashed,
    # room never closed, caller vanished) is auto-marked "failed". We use LiveKit's
    # live rooms as the source of truth so a genuinely long, active call is never
    # killed — only calls whose room has actually ended get cleaned up. Falls back
    # to age-based cleanup if LiveKit is unreachable.
    stale_minutes = int(os.getenv("STALE_CALL_MINUTES", "15"))
    stale_poll = int(os.getenv("STALE_CALL_POLL_SECONDS", "60"))

    async def _cleanup_loop():
        while True:
            try:
                live = await telephony.list_live_active_rooms()
                n = await repo.fail_stale_calls(stale_minutes, active_rooms=live)
                if n:
                    logger.warning(f"🧹 Marked {n} ended call(s) as failed.")
            except Exception as e:
                logger.warning(f"stale-call cleanup error: {e}")
            await asyncio.sleep(stale_poll)

    # Bulk-call campaign dispatcher: dials queued leads up to each campaign's
    # concurrency, reconciling finished calls each tick.
    campaign_tick = int(os.getenv("CAMPAIGN_TICK_SECONDS", "3"))

    async def _campaign_loop():
        while True:
            try:
                await campaign_runner.run_tick()
            except Exception as e:
                logger.warning(f"campaign dispatcher error: {e}")
            await asyncio.sleep(campaign_tick)

    cleanup_task = asyncio.create_task(_cleanup_loop())
    campaign_task = asyncio.create_task(_campaign_loop())

    # Monthly subscription renewals: sweep every hour (past-due grace and
    # deactivation are date-based, so hourly resolution is plenty).
    sub_poll = int(os.getenv("SUBSCRIPTION_SWEEP_SECONDS", "3600"))

    async def _subscription_loop():
        from .services import subscription_service
        while True:
            try:
                await subscription_service.renew_due()
            except Exception as e:
                logger.warning(f"subscription renewal sweep error: {e}")
            await asyncio.sleep(sub_poll)

    subscription_task = asyncio.create_task(_subscription_loop())
    try:
        yield
    finally:
        cleanup_task.cancel()
        campaign_task.cancel()
        subscription_task.cancel()
        warm_task.cancel()
        await shutdown()


app = FastAPI(title="Voice Agent SaaS", version="0.4.0", lifespan=lifespan)
app.include_router(admin_routes.router)
app.include_router(setup_routes.router)   # hidden from /docs, key-protected
app.include_router(auth_routes.router)
app.include_router(catalog_routes.router)
app.include_router(agents_routes.router)
app.include_router(calls_routes.router)
app.include_router(campaigns_routes.router)
app.include_router(billing_routes.router)
app.include_router(subscription_routes.router)

# Credentialed-cookie sessions require explicit origins (browsers reject "*"
# with credentials) — and an explicit allowlist is better hygiene anyway.
# Server-to-server webhooks (Twilio/Exotel/SIP) are unaffected by CORS.
# Extra origins: set CORS_ORIGINS="https://app.example.com,https://admin.example.com"
_cors_origins = [o.strip() for o in os.getenv(
    "CORS_ORIGINS",
    "http://localhost:3000,http://localhost:3002,"
    "http://127.0.0.1:3000,http://127.0.0.1:3002",
).split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.exception("Unhandled server error: %s", exc)
    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc)},
        headers={"Access-Control-Allow-Origin": "*"},
    )


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@app.get("/api/health")
async def health():
    return {
        "ok": True,
        "service": "voice-agent-saas",
        "config_snapshot": config_store.get_snapshot().source,
    }


def run():
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")), reload=False)


if __name__ == "__main__":
    run()
