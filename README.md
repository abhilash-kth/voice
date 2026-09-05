# Voice Agent SaaS — self-hosted LiveKit voice agents

A complete, self-hosted **voice-agent-as-a-service** platform. A customer signs up,
configures an agent (LLM / STT / TTS / telephony, knowledge base + FAQ, conversation
memory on/off, call recording on/off, max concurrent calls), recharges a wallet,
places a call (browser or real phone via SIP), and afterwards sees the **transcript**,
**recording**, **tokens used**, and the **cost per minute / total cost / profit**.

Three layers:

```
frontend/   Next.js dashboard  (login, configure, call, billing, transcripts)
backend/    FastAPI            (auth JWT, agents, wallet, calls, billing, Neon/SQLite)
            LiveKit worker     (builds + runs a LiveKit AgentSession/Agent per call)
livekit.yaml + livekit-egress  (self-hosted LiveKit + recording)
```

> The demo runs **fully self-hosted** (no LiveKit Cloud) and costs ₹0 on calls if you
> use the free-tier providers (Groq LLM + Deepgram STT + Google TTS + browser mode).

---

## 1. Prerequisites

- **Python 3.11+**
- **Node.js 18+**
- **LiveKit server** binary — self-hosted (see below), not LiveKit Cloud.
- **Neon** (Postgres) account **or** just use the built-in SQLite for a quick demo.
- Provider API keys (Groq for LLM, Deepgram for STT, a Google service-account JSON
  for TTS) — all have free tiers. Add others (OpenAI, ElevenLabs) when you want.

Self-hosted LiveKit is the key difference from the LiveKit-Cloud versions — everything
runs on your own machine / server and no calls go through a hosted service.

---

## 2. Run the 4 components

There is a convenience script: `bash scripts/run-all.sh`. Or run each piece yourself.

### 2.1 LiveKit server (self-hosted)

```bash
# Install the LiveKit server binary, e.g. via the official installer:
#   curl -sSL https://get.livekit.io | bash
#   (binary name: livekit-server, lives in ~/.livekit/bin)

# Copy the provided config and run it:
livekit-server --config livekit.yaml
# -> ws://localhost:7880
```

`livekit.yaml` already carries your `API key/secret` (APIVXWGm…/CHAhA7Z…). **Change
these for real deployments** and update the same values in `backend/.env`.

### 2.2 Recording (LiveKit Egress) — optional but needed for "recording on"

Recording uses **LiveKit Egress**, which is a separate self-hosted service that renders
the room to a file and uploads it to S3-compatible storage.

```bash
# 1) Run the Egress service container (self-hosted):
docker run --rm --network host \
  -e LIVEKIT_URL=ws://localhost:7880 \
  -e LIVEKIT_API_KEY=APIVXWGm6U8jdB2 \
  -e LIVEKIT_API_SECRET=CHAhA7ZTOtZj770TUMSOBwnLYEKXnByAQO3IblGbena \
  -e S3_ENDPOINT=<your-s3-endpoint> \
  -e S3_ACCESS_KEY=... -e S3_SECRET=... -e S3_BUCKET=voice-recordings \
  -e S3_REGION=us-east-1 \
  livekit/egress
```

Then set these in `backend/.env`:

```
EGRESS_ENABLED=true
EGRESS_S3_BUCKET=voice-recordings
EGRESS_S3_ENDPOINT=https://s3.<region>.amazonaws.com   # or MinIO / Cloudflare R2 endpoint
EGRESS_S3_REGION=us-east-1
EGRESS_PUBLIC_BASE_URL=https://cdn.example.com          # where recording files are publicly served
```

If `EGRESS_ENABLED=true` but storage isn't configured, the agent logs
`Recording enabled but Egress storage not configured — skipping` and the call still
runs (just without audio). Setting `EGRESS_ENABLED=false` disables it.
The worker writes the public URL into the call record's `recording_url`, which the
**Calls** tab renders as a 🎧 player link.

### 2.3 Database — Neon (Postgres) or local SQLite

**Option A — Neon (recommended for production):**

1. Create a Neon project and copy the **connection string**
   (`postgresql://user:pass@ep-xxx.region.aws.neon.tech/neondb?sslmode=require`).
2. Put it in `backend/.env`:

   ```
   DATABASE_URL=postgresql://user:pass@ep-xxx.region.aws.neon.tech/neondb?sslmode=require
   ```

   The schema (users, agents, calls, transactions) is created automatically on startup.

**Option B — local (zero setup):** leave `DATABASE_URL` as
`sqlite:///./data/app.db`. You get a fully working demo with a file DB.

> All the API code is DB-agnostic (Prisma). Switching SQLite ⇄ Neon is just the
> `DATABASE_URL` string.

### 2.4 Database setup (Prisma)

```bash
cd backend
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env      # edit keys + DATABASE_URL + JWT_SECRET
```

**Neon / Postgres** (production): in `schema.prisma` keep `provider = "postgresql"`,
set your `DATABASE_URL` in `.env`, then:

```bash
DATABASE_URL="postgresql://user:pass@ep-xxx.region.aws.neon.tech/neondb?sslmode=require" \
  python -m prisma db push --schema schema.prisma
python -m prisma generate --schema schema.prisma
```

**Local SQLite** (zero-setup demo): in `schema.prisma` set `provider = "sqlite"` and
`url = "file:./data/app.db"`, set `DATABASE_URL=file:./data/app.db`, then run the
same two commands.

There's a helper that loads `.env`, pushes the schema, and generates the client:

```bash
bash scripts/db-setup.sh
```

> **Why `String` JSON?** Prisma's `Json` column type is Postgres-only. To keep one
> schema that runs on both SQLite and Postgres/Neon, JSON blobs (providers,
> knowledge, transcripts, usage, cost) are stored as `String` and (de)serialized in
> `app/repo.py`. You still get structured field access in code.

### 2.5 Backend API

```bash
cd backend && source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000
# -> http://localhost:8000   (interactive docs at /docs, health at /api/health)
```

### 2.6 LiveKit agent worker

```bash
cd backend
source .venv/bin/activate
python -m app.agents.worker
# registers agent_name = "voice-agent-saas" with the LiveKit server
```

This is the process that picks up a dispatched call, builds a LiveKit **v1**
`AgentSession` + `Agent` (the successor to the removed `VoicePipelineAgent`) for
the customer's selected providers, runs RAG over their knowledge base, records
the transcript, and posts the cost back to FastAPI. It uses the LiveKit v1 API
(`AgentSession`, `Agent`, `AgentSession.say()`), not the removed
`livekit.agents.pipeline` module.

> **LiveKit v1 notes** — the packages are the real PyPI names:
> `pip install "livekit-agents[openai,deepgram,google,silero]" livekit` installs
> the agent SDK (v1), the per-provider plugins and the server SDK (`livekit`, not
> `livekit-server-sdk`). The worker runs with the v1 `AgentSession`/`Agent` API,
> and on **Windows** it uses `multiprocessing_context="spawn"` (the default
> `"forkserver"` isn't available there).
>
> `python -m app.agents.worker` defaults to the **`start`** subcommand (the v1 CLI
> requires one; use `dev` for hot-reload or `console` for a local chat REPL). The
> worker reads `LIVEKIT_URL` / `LIVEKIT_API_KEY` / `LIVEKIT_API_SECRET` from
> `backend/.env`. You need real provider API keys (Deepgram/Google/Groq) for the
> agent to actually transcribe and reply — with placeholder keys the session still
> wires up and joins the room, but the STT/TTS/LLM calls will hit `401`.

### 2.7 Frontend

```bash
cd frontend
npm install
cp .env.example .env.local   # set NEXT_PUBLIC_BACKEND_URL=http://localhost:8000
npm run dev
# -> http://localhost:3000
```

---

## 3. Using the platform (flow)

1. **Sign up / log in** (JWT stored locally). New accounts start at ₹0.
2. **Agents → + New Agent**:
   - Pick **LLM**, **STT**, **TTS**, and **Telephony** providers (free tier = Groq
     Llama, Deepgram Nova-2, Google WaveNet, browser).
   - Set **greeting**, **personality**, **language**, and your **per-minute price**.
   - Toggle **conversation memory**, **call recording**, and set **max concurrent calls**.
   - Add a **knowledge base** (pasted text **and/or** a `.txt/.md/.csv/.json/.pdf` file)
     and **FAQ Q&A pairs**.
3. **Wallet → Add Balance** (the call is blocked with HTTP 402 if balance is ₹0).
4. **Call**: pick the agent, choose **Browser** (free) or **SIP** (real phone, enter
   the E.164 number), and start/dial.
5. After the call ends, open **Calls → view** to see the **transcript**, 🎧 **recording**,
   **tokens used**, and the cost breakdown (STT / LLM / TTS / server, your cost,
   customer bill, **cost per minute**, profit).

---

## 4. API reference

Auth endpoints return `{ token, user }`; call them with header
`Authorization: Bearer <token>`.

| Method         | Path                            | Body                                                    | Notes                                                                                                 |
| -------------- | ------------------------------- | ------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| POST           | `/api/auth/register`            | `{email,password,name}`                                 | create account → `{token,user}`                                                                       |
| POST           | `/api/auth/login`               | `{email,password}`                                      | → `{token,user}`                                                                                      |
| GET            | `/api/auth/me`                  | —                                                       | current user                                                                                          |
| GET            | `/api/catalog`                  | —                                                       | provider list + top-up amounts                                                                        |
| GET            | `/api/agents`                   | —                                                       | your agents + call stats + `active_calls`                                                             |
| POST           | `/api/agents`                   | AgentCreate (see below)                                 | create agent                                                                                          |
| GET/PUT/DELETE | `/api/agents/{id}`              | —                                                       | read / update / delete                                                                                |
| PUT            | `/api/agents/{id}/knowledge`    | `{text?,system_prompt?,faq?}`                           | set KB text/instructions/FAQ (keeps docs)                                                             |
| POST           | `/api/agents/{id}/knowledge`    | multipart `file`, or `text`, or `faq` JSON              | add a document                                                                                        |
| POST           | `/api/calls`                    | `{agent_id,mode:"browser"\|"sip",phone?,sip_trunk_id?}` | start a call; returns `{token,url,room,call_id}`                                                      |
| GET            | `/api/calls`, `/api/calls/{id}` | —                                                       | list / read calls                                                                                     |
| GET            | `/api/wallet`                   | —                                                       | balance + transactions                                                                                |
| POST           | `/api/wallet/recharge`          | `{add_amount}`                                          | credit balance                                                                                        |
| GET            | `/api/billing/usage`            | —                                                       | totals + recent calls                                                                                 |
| POST           | `/api/billing/log`              | call ledger                                             | **internal**: worker posts completed cost (set `X-Internal-Token` if `BILLING_INTERNAL_TOKEN` is set) |
| POST           | `/api/cost-preview`             | durations/tokens/provider ids                           | estimate cost & profit                                                                                |

### AgentCreate body

```json
{
  "name": "Kavya",
  "greeting": "Namaste! Main Kavya hoon...",
  "language": "hi",
  "voice_personality": "friendly",
  "client_rate_per_min": 2.5,
  "memory_enabled": true,
  "recording_enabled": true,
  "max_concurrency": 2,
  "enabled": true,
  "providers": {
    "llm": {
      "id": "groq_llama_3_3_70b",
      "config": { "model": "llama-3.3-70b-versatile" }
    },
    "stt": { "id": "deepgram_nova2", "config": { "language": "hi" } },
    "tts": {
      "id": "google_wavenet_hi",
      "config": { "voice": "hi-IN-Wavenet-A" }
    },
    "telephony": { "id": "browser", "config": {} }
  },
  "knowledge": {
    "text": "Kriscent Techno Hub, Kota. Founder Kapil Gautam, 2014.",
    "system_prompt": "Answer in one short Hindi sentence.",
    "faq": [{ "q": "Where is it?", "a": "Kota, Rajasthan" }]
  }
}
```

---

## 5. Provider catalogue & pricing

Edit `backend/app/catalog.py`. Each entry has a `tier` (`free`/`paid`), per-unit
`cost`, and `options` (models/voices/languages). The UI and cost engine read this
directly, so adding a provider / changing its price is just editing this file.

| Kind      | Free-tier                      | Paid                             |
| --------- | ------------------------------ | -------------------------------- |
| LLM       | Groq Llama 3.3 70B, Groq Qwen3 | OpenAI GPT-4o mini, GPT-OSS-120B |
| STT       | Deepgram Nova-2                | Deepgram Nova-3, Google STT      |
| TTS       | Google WaveNet (hi-IN)         | Google Neural2, ElevenLabs       |
| Telephony | Browser (free)                 | Telnyx, Twilio (SIP trunk)       |

---

## 6. Billing model

Per completed call the platform computes:

- **STT** = audio minutes × provider rate
- **LLM** = input tokens×in-rate + output tokens×out-rate
- **TTS** = spoken characters × per-1k-char rate
- **Server** = call minutes × `SERVER_COST_PER_MIN`
- **Your cost** = the sum above
- **Customer bill** = max(call minutes × agent price, min charge)
- **Profit** = customer bill − your cost

All of it (including `cost/min`, `bill/min`, tokens, transcript, recording URL) is
stored on the call and shown in the UI. Costs are computed in `backend/app/billing.py`.

---

## 7. Telephony (real phone calls via SIP)

Browser calls need nothing. To dial a real number:

1. Create a Telnyx/Twilio account and provision a number.
2. Create a **LiveKit SIP trunk** that routes to your carrier
   (`livekit-server` + `lk` CLI / API). Note the `trunk_id`.
3. Set `SIP_TRUNK_ID` in `backend/.env` (or pass it per call).
4. In the UI choose **SIP**, enter `+91...`, and **Dial Number**.

`backend/app/telephony.py` (LiveKit v1) creates the room with an **agent dispatch**
rule (so the `voice-agent-saas` worker is auto-dispatched), then creates an outbound
SIP participant through `LiveKitAPI.sip.create_sip_participant(...)` to dial the
number through the trunk.

---

## 8. Self-hosted vs LiveKit Cloud

- **No cloud dependency**: the server, worker, and egress all run on your infra.
- Realtime audio still flows through WebRTC (browser) or SIP (phone) directly to
  **your** LiveKit server.
- Only the LLM/STT/TTS providers are external SaaS (Groq/Deepgram/Google), which is
  where your ₹0 free-tier call cost comes from.

---

## 9. Schema & moving to production

`backend/schema.prisma` is the single source of truth (users, agents, calls,
transactions). `python -m prisma db push` creates/migrates it; `repo.py` is the only
module that touches the DB. Migrate with Prisma's migration workflow if you want
versioned migrations (`prisma migrate dev`) instead of `db push`.

Production notes:

- Set a strong `JWT_SECRET`.
- Set `BILLING_INTERNAL_TOKEN` and add the same to the worker's env so `/api/billing/log`
  is private.
- Put the API behind HTTPS; use Neon's pooled connection string.
- Serve recordings from a CDN.
- Commit `schema.prisma` but **not** the generated `prisma_client/` (regenerate on
  deploy).

---

## 10. Troubleshooting

| Symptom                                  | Cause / fix                                                                                                                                                                                                                               |
| ---------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Frontend shows "could not reach backend" | Start FastAPI on :8000; check `NEXT_PUBLIC_BACKEND_URL`.                                                                                                                                                                                  |
| Start Call → 503                         | `livekit` not installed (`pip install -r requirements.txt`). Note: `livekit-server-sdk` and `livekit-plugins` are **not** PyPI packages — the server SDK is now the plain `livekit` package and each plugin ships as `livekit-plugins-*`. |
| Start Call → 402                         | Wallet is ₹0 → recharge (or set a starting balance).                                                                                                                                                                                      |
| Start Call → 409                         | Agent is at `max_concurrency`. Reduce load / raise the limit.                                                                                                                                                                             |
| No audio / agent not joining             | The worker isn't running, or agent name mismatch. Run `python -m app.agents.worker`.                                                                                                                                                      |
| Agent goes silent mid-call (no reply)    | LLM 429 — Groq free tier is ~8k tokens/min per model, and an oversized knowledge base makes each turn 6-7k tokens. The worker now caps the static prompt (`VOICE_KB_BUDGET_CHARS`), injects only relevant KB chunks per turn (RAG), and speaks a fallback line after `VOICE_LLM_FALLBACK_DELAY` (12s) of silence. Permanent fixes: upgrade the Groq tier, switch model/provider (see `GROQ_MODEL`), or lower the budgets' token count. Watch for the worker's `🛟 No LLM reply within…` log line. |
| No recording                             | Egress service not running / S3 not configured (`EGRESS_*`).                                                                                                                                                                              |
| Browser mic issues                       | Use Chrome/Edge; allow mic + secure context (HTTPS or localhost).                                                                                                                                                                         |
| `prisma_client` import fails             | Run `python -m prisma generate --schema schema.prisma` (and `db push`).                                                                                                                                                                   |
| `DATABASE_URL` errors                    | Use a plain `postgresql://…` URL for Neon; for SQLite set provider=`"sqlite"` + `file:./data/app.db`.                                                                                                                                     |

See `ARCHITECTURE.md` for the full wiring.

<!-- LiveKit Server -->

cd C:\Users\neha arpita.ABHILASH\voice\voice-agent-saas
livekit-server.exe --config livekit.yaml

<!-- Backend / FastAPI -->

cd C:\Users\neha arpita.ABHILASH\voice\voice-agent-saas\backend
.venv\Scripts\activate
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000

<!-- Agent Worker -->

cd C:\Users\neha arpita.ABHILASH\voice\voice-agent-saas\backend
.venv\Scripts\activate
python -m app.agents.worker

<!-- Frontend -->

cd C:\Users\neha arpita.ABHILASH\voice\voice-agent-saas\frontend
npm run dev
"# voice" 
