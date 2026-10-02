#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# Convenience launcher for the Voice Agent SaaS demo.
#
# Usage:
#   ./scripts/run-all.sh            # runs LiveKit, backend, worker, frontend
#   ./scripts/run-all.sh backend    # backend only
#   ./scripts/run-all.sh worker     # LiveKit worker only
#   ./scripts/run-all.sh frontend   # Next.js only
#
# Prerequisites:
#   - LiveKit server binary on PATH (or use `livekit-server`)
#   - Python venv with backend deps installed (see backend/requirements.txt)
#   - `npm install` already run in frontend/
# -----------------------------------------------------------------------------
set -euo pipefail

ROOT="$( cd "$(dirname "$0")/.." && pwd )"
MODE="${1:-all}"

cleanup() {
  echo ""
  echo "Stopping processes..."
  jobs -p | xargs -r kill 2>/dev/null || true
}
trap cleanup EXIT INT TERM

start_livekit() {
  echo "▶ Starting LiveKit server..."
  ( cd "$ROOT" && livekit-server --config livekit.yaml 2>/dev/null & echo $! ) || echo "   (livekit-server not on PATH — start it manually)"
}

start_backend() {
  echo "▶ Setting up Prisma DB (db push + generate)..."
  ( cd "$ROOT/backend" && . .venv/bin/activate 2>/dev/null; \
     set -a; [ -f .env ] && . ./.env; set +a; \
     python -m prisma db push --schema schema.prisma; \
     python -m prisma generate --schema schema.prisma ) || echo "   (Prisma setup failed — check DATABASE_URL / schema provider)"

  echo "▶ Starting FastAPI backend on :8000..."
  ( cd "$ROOT/backend" && . .venv/bin/activate 2>/dev/null; uvicorn app.main:app --host 0.0.0.0 --port 8000 ) &
}

start_worker() {
  echo "▶ Starting LiveKit agent worker (voice-agent-saas)..."
  ( cd "$ROOT/backend" && . .venv/bin/activate 2>/dev/null; python -m app.agents.worker ) &
}

start_frontend() {
  echo "▶ Starting Next.js frontend on :3000..."
  ( cd "$ROOT/frontend" && npm run dev ) &
}

case "$MODE" in
  livekit)  start_livekit ;;
  backend)  start_backend ;;
  worker)   start_worker ;;
  frontend) start_frontend ;;
  all)
    start_livekit
    start_backend
    start_worker
    start_frontend
    ;;
  *) echo "Unknown mode: $MODE"; exit 1 ;;
esac

echo ""
echo "--------------------------------------------------------------"
echo "  Backend  : http://localhost:8000            (FastAPI /docs)"
echo "  Frontend : http://localhost:3000"
echo "  LiveKit  : ws://localhost:7880"
echo "--------------------------------------------------------------"
echo "Press Ctrl+C to stop everything."
wait
