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
2. **Preflights the agent config** (`app/preflight.py`): runs the worker's exact
   config→runtime path — `AgentConfig(**rec)` + `build_stt/build_llm/build_tts`
   (offline constructor build) — in a worker thread. A saved agent whose config
   no longer builds (model removed from the catalog, provider/model mismatch,
   missing API key) used to crash the worker job *after* the room existed: the
   caller sat in a silent room forever with no error anywhere. Now the call is
   rejected **before the room is created** with the real reason, which the UI
   shows and the user can act on. (Campaigns are prefetched the same way at
   start and on every dispatch tick, so a broken config can't burn wallet
   credits lead by lead.)
3. Checks **concurrency**: `COUNT(calls WHERE agent_id AND status='in-progress')`
   vs `max_concurrency` → 409 at limit.
4. Checks wallet balance > ₹0 → else 402.
5. Creates a `call` row (`status='planned'`), then:
   - **browser**: `telephony.create_browser_room()` → a join token with a
     `RoomAgentDispatch` (metadata = `{user_id, agent_id, call_id, mode, phone}`).
   - **sip**: `telephony.create_sip_call()` → creates the room **with an agent
     dispatch rule**, then dials the number via the LiveKit v1
     `LiveKitAPI.sip.create_sip_participant(..., trunk_id=trunk)`.

   Every LiveKit API call (create room, dispatch, SIP dial, delete room, list
   rooms) runs with a hard timeout (`telephony._lk`) so an unreachable LiveKit
   server surfaces a 503 "LiveKit server did not respond" instead of hanging
   the request / the worker's cleanup path forever.

When the caller joins, LiveKit spawns the worker for `agent_name="voice-agent-saas"`.

**Worker failure contract** (`worker.entrypoint`): *no silent failures.* Any
exception during job setup (agent load, provider build, session start) is
caught by the entrypoint wrapper, which (1) logs CRITICAL with the full
traceback, (2) marks the call `failed` in the DB with the reason in
`usage.error` (the UI polls the call while "waiting for agent" and shows the
caller the real error), (3) deletes the room (the browser disconnects instead
of hanging in a silent room), (4) shuts the job down (frees the worker process
for the next dispatch). A 90-second setup watchdog force-fails jobs whose
setup hangs, so one sick job cannot clog dispatch — the classic "first call
works, second goes silent" symptom. The UI additionally applies a 30-second
agent-join timeout with a "Try again" action for the case where no worker
process picks up the dispatch at all.

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
  **Latency:** retrieval is *precomputed* from each STT **interim** (session
  `transcription` event → BM25 in a thread, keyed by
  `rag.normalize_query(text)`), so by the time the session `await`s
  `on_user_turn_completed` before the LLM starts, the result is a cache hit
  (~0ms) instead of 30–100ms+ on the critical path. A miss (final text diverged
  from every interim) falls back to computing in the hook as before.
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

### Event-loop rules for startup warm-up

The worker aggressively pre-warms startup work (SSL context, VAD model, Google
credentials, hyphenator, provider SDK imports) because a 150-400ms synchronous
block on the agent loop delays audio and turn handling. Only **loop-independent**
work may be moved off that loop:

| Safe off-loop (thread) | Must stay on the agent loop |
| --- | --- |
| `ssl.create_default_context()` (cached, patched into httpx/livekit) | `texttospeech.TextToSpeechAsyncClient` (`_ensure_client()`) |
| service-account JSON + RSA parse (`loop_safety.warm_google_credentials`) | any `grpc.aio` channel / async provider client |
| silero VAD load, tokenizer/hyphenator warm, module imports | `prisma.connect()` (`app/db.py`) |
| `build_stt/build_llm/build_tts` (constructors are lazy) | `AgentSession.start()` |

An async gRPC channel keeps a reference to the loop that was running when it was
constructed. Building one inside `asyncio.new_event_loop()` on a worker thread
and then closing that loop leaves a client that fails every later call with
`RuntimeError: Event loop is closed` (`grpc/aio/_call.py` → `loop.create_task`),
which shows up as an agent that joins the room, transcribes fine, and never
speaks. The same mistake with Prisma binds the process-wide engine/httpx pool to
a dead loop, so the first query hangs until its timeout.

`app/agents/loop_safety.py` holds the helpers that enforce this:
`warm_google_credentials()` (blocking half only, cached per key-file + scope),
`guard_tts_client_loop()` (drops a cached TTS client bound to a closed/foreign
loop so the plugin rebuilds it on the right one), and `warm_tts_off_loop()` which
does both. `app/db.py` tracks the loop it connected on and reconnects if asked
from a different one. `backend/tests/` covers both.

### 4.1 Event-loop rules (why calls used to die silently)

The agent process pre-warms expensive startup work (SSL context, service-account
JSON/RSA, VAD model, provider SDK imports) so callers hear the greeting fast.
Two classes of "pre-warm" used to instead poison every call — they are the root
cause of `RuntimeError: Event loop is closed` in `grpc/aio/_call.py` and of the
first-query 3s timeouts. The rules the code now follows (enforced in practice by
`backend/app/agents/loop_safety.py`, the inline warm/guard calls in `worker.py`,
`backend/app/db.py`, and `backend/tests/`):

| Safe off-loop (thread) | Must happen ON the agent loop |
| --- | --- |
| `ssl.create_default_context()` (cached, patched into http_context / httpx **and** `httpx._transports.default`, which imports the name at module time — patching `httpx._config` alone never took effect) | `grpc.aio` client construction (`texttospeech.TextToSpeechAsyncClient`, i.e. Google plugin `_ensure_client()`) |
| service-account JSON + RSA parse (`loop_safety.warm_google_credentials`, cached per key-file + scope) | every async provider client that a plugin binds to a channel/session |
| silero VAD load, tokenizer/hyphenator warm, module imports | `prisma.connect()` (`app/db.py` — a client connected from a foreign loop makes the first query hang to ~3s) |
| `build_stt/build_llm/build_tts` *constructors* (they are lazy) | `AgentSession.start()` |

A gRPC-aio channel keeps a reference to the loop running when it was
constructed. Building one inside `asyncio.new_event_loop()` on a throwaway loop,
then closing that loop, leaves a client that fails every later call with
`Event loop is closed` — the agent joins, listens, transcribes, and never
speaks. Never prewarm async clients; warm only credentials and imports, and let
`warm_tts_off_loop()` drop any cached client bound to a dead/foreign loop so the
plugin rebuilds it on the right one.

Turn-taking is likewise API-owned: LiveKit `await`s the `on_user_turn_completed`
hook, so the old 2s busy-wait there stalled interruption handling and triggered
`speech not done in time after interruption, cancelling the speech arbitrarily`
(livekit/agents #5359). The hook is now log-only; endpointing/VAD/STT are tuned
in one place (`_vad_tuning()` + `VOICE_ENDPOINTING_*`/`VOICE_VAD_*`/`VOICE_STT_*`
envs) so the three layers agree on what 300–350ms of silence means.

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
