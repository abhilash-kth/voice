#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# Run the backend test suite against a disposable SQLite database.
#
#   bash scripts/run-tests.sh            # full suite
#   bash scripts/run-tests.sh tests/test_crypto.py -v
#
# What it does: derives the SQLite schema variant from the production one,
# pushes it to backend/data/test.db, regenerates the Prisma client, then runs
# pytest. The production schema (backend/schema.prisma, postgres) is untouched.
# -----------------------------------------------------------------------------
set -euo pipefail
ROOT="$( cd "$(dirname "$0")/.." && pwd )"
cd "$ROOT/backend"

# use the repo venv if it exists
if [ -d .venv ]; then
  # shellcheck disable=SC1091
  . .venv/bin/activate
fi

export DATABASE_URL="${DATABASE_URL:-file:./data/test.db}"

# derive + push + generate (idempotent)
sed -e 's/provider = "postgresql"/provider = "sqlite"/' schema.prisma > schema.sqlite.prisma
echo "▶ prisma db push (sqlite test DB: $DATABASE_URL)"
python -m prisma db push --schema schema.sqlite.prisma
echo "▶ prisma generate"
python -m prisma generate --schema schema.sqlite.prisma

echo "▶ pytest"
exec python -m pytest "$@"
