#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# Set up the Prisma database (create schema + generate the Python client).
#
# Usage (from repo root):
#   bash scripts/db-setup.sh          # uses DATABASE_URL from backend/.env
#   DATABASE_URL="postgresql://..." bash scripts/db-setup.sh
#
# For a LOCAL SQLITE demo, set provider="sqlite" + url="file:./data/app.db"
# in backend/schema.prisma first (see README).
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

echo "▶ Creating/pushing Prisma schema (db push)..."
python -m prisma db push --schema schema.prisma

echo "▶ Generating Prisma Client Python..."
python -m prisma generate --schema schema.prisma

echo "✅ Prisma DB ready. Start the API: uvicorn app.main:app --port 8000"
