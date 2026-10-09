#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# Set up the Prisma database (create schema + generate the Python client).
#
# Usage (from repo root):
#   bash scripts/db-setup.sh                    # production: Postgres/Neon via schema.prisma
#   DB_PROVIDER=sqlite bash scripts/db-setup.sh # local: SQLite file DB (zero setup)
#   DATABASE_URL="postgresql://..." bash scripts/db-setup.sh
#
# The production schema (backend/schema.prisma) is the source of truth. For
# SQLite the script derives backend/schema.sqlite.prisma from it by swapping
# the datasource provider — nothing to keep in sync by hand.
# -----------------------------------------------------------------------------
set -euo pipefail
ROOT="$( cd "$(dirname "$0")/.." && pwd )"
cd "$ROOT/backend"

# Load .env so DATABASE_URL is available to Prisma.
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

DB_PROVIDER="${DB_PROVIDER:-postgresql}"

if [ "$DB_PROVIDER" = "sqlite" ]; then
  mkdir -p data
  # Derive the SQLite variant from the production schema (source of truth).
  sed -e 's/provider = "postgresql"/provider = "sqlite"/' schema.prisma > schema.sqlite.prisma
  SCHEMA="schema.sqlite.prisma"
  export DATABASE_URL="${DATABASE_URL:-file:./data/app.db}"
  echo "▶ Using SQLite: $DATABASE_URL"
else
  SCHEMA="schema.prisma"
  echo "▶ Using provider from schema.prisma (postgresql)"
fi

echo "▶ Creating/pushing Prisma schema (db push)..."
python -m prisma db push --schema "$SCHEMA"

echo "▶ Generating Prisma Client Python..."
python -m prisma generate --schema "$SCHEMA"

echo "✅ Prisma DB ready. Start the API: uvicorn app.main:app --port 8000"
