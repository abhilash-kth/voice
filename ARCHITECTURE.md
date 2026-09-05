# Architecture

How the self-hosted platform is wired.

```
┌──────────────┐  HTTPS/REST + Bearer  ┌──────────────────────────────────────┐
│  Next.js UI  │ ─────────────────────▶│  FastAPI backend (:8000)             │
│  (login/reg) │  /api/*               │  auth(JWT) · agents · wallet · calls │
└──────┬───────┘                       │  billing · knowledge · concurrency   │
       │ WebRTC                         └──────────────┬───────────────────────┘
       ▼                                             │ Prisma
┌──────────────┐   agent dispatch        ┌───────────▼───────────┐
│ LiveKit SVR  │ ◀───────────────────────│  Agent worker         │
│ (self-hosted,│   via token room config │  (voice-agent-saas)   │
│  :7880)      │                         └───────────┬───────────┘
└──────┬───────┘                                     │ uses
       │ Egress                                      ▼
       ▼                                    LLM · STT · TTS · KB · memory
┌──────────────┐   upload to S3   ┌──────────────┐   ┌───────────────────────┐
│ livekit-egress│ ────────────────▶│ S3-compatible│   │ Neon / SQLite DB      │
└──────────────┘                  └──────────────┘   └───────────────────────┘
```

## 1. Auth & tenants

- Register/login return a **JWT** (`sub` = user id). Store in `localStorage`.
- Every agents/wallet/calls endpoint uses `get_current_user` to scope rows to the
  user, so tenants are isolated. (`app/auth.py`.)

## 2. Agents (per-user config)

`Agent` rows store the customer's choices:
- `providers` (JSON): llm/stt/tts/telephony ids + option overrides.
- `knowledge` (JSON): `text`, `documents[]`, `system_prompt`, `faq[]`.
- `memory_enabled`, `recording_enabled`, `max_concurrency`, `client_rate_per_min`.

## 3. Call dispatch (browser + SIP)

`POST /api/calls`:
1. Checks agent is enabled.
2. Checks **concurrency**: `COUNT(calls WHERE agent_id AND status='in-progress')`
   vs `max_concurrency` → 409 at limit.
3. Checks wallet balance > ₹0 → else 402.
4. Creates a `call` row (`status='planned'`), then:
   - **browser**: `telephony.create_browser_room()` → a join token with a
     `RoomAgentDispatch` (metadata = `{user_id, agent_id, call_id, mode, phone}`).
   - **sip**: `telephony.create_sip_call()` → creates the room **with an agent
     dispatch rule**, then dials the number via the LiveKit v1
     `LiveKitAPI.sip.create_sip_participant(..., trunk_id=trunk)`.

When the caller joins, LiveKit spawns the worker for `agent_name="voice-agent-saas"`.

## 4. Worker (the agent runtime)

`app/agents/worker.py` reads the dispatch metadata, loads the agent + call from the
DB, and builds a LiveKit **v1** `AgentSession` + `Agent` via `agent_builder.py` (the
successor to the removed `VoicePipelineAgent`). Then:

- **Context sizing + RAG** on every user turn: the static system prompt carries
  only a CAPPED summary of the knowledge base (`VOICE_KB_BUDGET_CHARS` /
  `VOICE_FAQ_BUDGET_CHARS` / `VOICE_OWNER_PROMPT_BUDGET_CHARS`) — an uncapped
  prompt 429s Groq's free tier (8k TPM) and silently drops turns. The agent's
  `on_user_turn_completed(turn_ctx, msg)` then injects the question-specific
  `rag.py` chunks (BM25-scored, from `knowledge.text` + uploaded documents) into
  the turn, pruning the previous turn's RAG message. RAG stands down when
  `VOICE_PREEMPTIVE=1` (per-turn context mutation would invalidate preemptive
  generation).
- **Silence watchdog**: if no assistant reply lands within
  `VOICE_LLM_FALLBACK_DELAY` (default 12s) of a user turn — e.g. the LLM 429'd
  and the fail-fast retries gave up, or the model returned an empty completion —
  the worker speaks a fallback line instead of leaving the caller in dead air.
  Tool-call items are excluded from reply tracking.
- **Memory**: if `memory_enabled`, the initial `chat_ctx` is seeded with prior
  exchanges for this phone/room (`memory.py`) and the new ones are saved at the end.
- **Recording**: if `recording_enabled`, calls `start_egress()` (LiveKit Egress via
  `LiveKitAPI.egress.start_room_composite_egress`) on the room and stores the URL.
- **Interruptions / endpointing** set via `turn_handling={"interruption": {...},
  "endpointing": {...}}` in `agent_builder.py` / `worker.py`.
- **Greeting**: the agent's `on_enter` speaks the greeting after
  `room_io.wait_for_ready()` so outbound/SIP greetings aren't lost while dialing.
- On disconnect `finalize_billing()` computes the cost breakdown, writes the call
  record (transcript, usage, cost, recording_url), and POSTs to `/api/billing/log`.

## 5. Storage (Prisma)

`backend/schema.prisma` is the schema source of truth; the generated client
(`python -m prisma generate`) is imported by `app/db.py` as a shared async
singleton. `DATABASE_URL` + the datasource `provider` choose Neon/Postgres or
SQLite. Because Prisma's `Json` type is Postgres-only, JSON blobs (`knowledge`,
`providers`, `transcripts`, `usage`, `cost`) are stored as `String` and
serialized/deserialized in `app/repo.py` to keep one portable schema.
`app/memory.py` stores cross-call customer memory (JSON file under data/).

## 6. Billing

`app/billing.py` computes per-component cost; `repo.get_usage()` aggregates totals
for the Wallet/Billing tab.

## 7. Recording (Egress)

`worker.start_egress()` starts a room-composite Egress with an `MP4`/
`EncodedFileOutput` to S3 and returns `EGRESS_PUBLIC_BASE_URL + '/' + filepath` as
the `recording_url`. Requires the self-hosted `livekit-egress` service and
`EGRESS_*` env vars.

## 8. Extension points

- `catalog.py` — add/price providers.
- `repo.py` / `db.py` — storage (already Neon-ready via `DATABASE_URL`).
- `agent_builder.py` — behaviour knobs + new provider plugins.
- `telephony.py` — SIP carriers, inbound, DTMF.
- `main.py` — API surface.
