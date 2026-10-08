"""Local diagnostic: can THIS environment resolve the Super-Admin panel keys?

Run from the backend directory with the SAME venv + .env the worker uses:

    ..\\.venv\\Scripts\\python check_panel_keys.py        (Windows)
    ../.venv/bin/python check_panel_keys.py              (Linux/Mac)

It prints, for every provider the panel has: whether the DB snapshot loads,
whether the credential row is in it, and whether decryption works. If this
prints OK but a call still fails, the worker process has a different env/DB.
"""
from __future__ import annotations

import asyncio
import sys

sys.path.insert(0, ".")

from app import config  # noqa: F401  (loads .env exactly like the app)


async def main() -> int:
    from app.db import init as db_init
    from app.services import config_store

    await db_init()
    snap = await config_store.refresh_if_stale(force=True)
    print(f"snapshot: source={snap.source} "
          f"providers={sum(len(v) for v in snap.providers.values())} "
          f"models={sum(len(v) for v in snap.models.values())} "
          f"credentials={sorted(snap.credentials)}")
    if snap.source != "db":
        print(f"!! snapshot did NOT load from the DB — last refresh error: "
              f"{config_store.last_refresh_error() or 'none recorded'}\n"
              "   check DATABASE_URL above this line.")
        return 1
    if not snap.credentials:
        print("!! DB snapshot loaded but ZERO credential rows — the panel keys "
              "are not in THIS database (worker and panel may use different DBs).")
        return 1

    ok = True
    for key in sorted(snap.credentials):
        kind, slug = key.split(":", 1)
        try:
            value = (config_store.get_api_key(kind, slug) or "").strip()
        except Exception as e:
            value, err = "", repr(e)
        else:
            err = ""
        if value:
            print(f"OK   {key or '(shared)'} -> resolves, ends …{value[-4:]}")
        else:
            ok = False
            print(f"FAIL {key or '(shared)'} -> NOT resolvable {err}")
    for slug in ("deepgram", "sarvam", "groq", "cartesia", "openai"):
        key = (config_store.get_api_key("stt", slug) or "").strip()
        print(f"probe stt:{slug:<12} ->", ("OK …" + key[-4:]) if key else "missing")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
