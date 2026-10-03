"""Shared pytest fixtures.

Prerequisites (handled by scripts/run-tests.sh):
  1. `prisma generate` has been run for the SQLite test schema.
  2. Env: DATABASE_URL=file:./data/test.db  (a disposable SQLite file)

Design notes:
* app/db.py binds the Prisma client to the *current* asyncio loop, so ALL async
  tests must run in ONE loop -> pytest-asyncio session-scoped loops (see
  pytest.ini options).
* The DB is wiped between tests (ordered delete_many) for isolation.
* A dedicated ADMIN_CONFIG_ENC_KEY is set for crypto tests.
"""
from __future__ import annotations

import os
import shutil

# --- test environment (before any app import) -------------------------------
os.environ.setdefault("DATABASE_URL", "file:./data/test.db")
os.environ.setdefault("JWT_SECRET", "pytest-secret")
os.environ["BILLING_INTERNAL_TOKEN"] = ""

import pytest
import pytest_asyncio


def _test_db_file() -> str:
    from app.config import BASE_DIR

    return str(BASE_DIR / "data" / "test.db")


@pytest.fixture(scope="session", autouse=True)
def _fs_setup():
    # The test.db file itself is created by scripts/run-tests.sh (prisma db push)
    # BEFORE pytest starts; tables are wiped between tests by `clean_db`.
    from app.config import BASE_DIR

    (BASE_DIR / "data").mkdir(parents=True, exist_ok=True)
    assert os.path.exists(_test_db_file()), (
        f"test database {_test_db_file()} missing — run via scripts/run-tests.sh"
    )
    yield
    shutil.rmtree(BASE_DIR / "data" / "__pycache__", ignore_errors=True)


async def _wipe_db():
    from app.db import init, get_prisma

    # live_client's lifespan teardown disconnects the shared client; be robust.
    await init()
    db = get_prisma()
    for table in ("transaction", "call", "agent", "adminauditlog", "providercredential",
                  "catalogmodel", "provider", "billingconfig", "user"):
        await getattr(db, table).delete_many()


@pytest_asyncio.fixture(loop_scope="session", scope="session", autouse=True)
async def app_db():
    """Connect the shared Prisma client and hand the loop over to tests."""
    from app.db import init, shutdown

    await init()
    await _wipe_db()
    # Fresh in-process config snapshot per test session
    from app.services import config_store

    config_store._reset_for_tests()
    yield
    await shutdown()


@pytest_asyncio.fixture(loop_scope="session", autouse=True)
async def clean_db(app_db):
    """Wipe all tables before every test function."""
    await _wipe_db()
    from app.services import config_store

    config_store._reset_for_tests()
    yield


@pytest_asyncio.fixture(loop_scope="session")
async def seeded(app_db):
    """Seed the dynamic catalog from code defaults and refresh the snapshot."""
    from app.services import catalog_service, config_store

    await catalog_service.seed_defaults_if_empty()
    snap = await config_store.refresh_if_stale(force=True)
    return snap


@pytest.fixture
def make_fernet_key():
    from cryptography.fernet import Fernet

    return Fernet.generate_key().decode()


@pytest_asyncio.fixture(loop_scope="session")
def api_client():
    """httpx AsyncClient bound to the FastAPI ASGI app (lifespan handled)."""
    import httpx
    from app.main import app

    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def _register_login(client, email: str, role: str = "USER"):
    """Helper: create a user with a given role and return (token, user_dict)."""
    from app.db import get_prisma
    from app import auth

    pw = "test-passw0rd"
    resp = await client.post("/api/auth/register", json={
        "email": email, "password": pw, "name": email.split("@")[0],
    })
    assert resp.status_code == 201, resp.text
    token = resp.json()["token"]
    if role != "USER":
        db = get_prisma()
        uid = resp.json()["user"]["id"]
        await db.user.update(where={"id": uid}, data={"role": role})
    me = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200, me.text
    return token, me.json()


@pytest_asyncio.fixture(loop_scope="session")
async def normal_user(api_client):
    return await _register_login(api_client, "normal@test.dev")


@pytest_asyncio.fixture(loop_scope="session")
async def super_admin(api_client):
    return await _register_login(api_client, "admin@test.dev", role="SUPER_ADMIN")
