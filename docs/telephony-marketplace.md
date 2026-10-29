# Telephony marketplace runbook

## What is implemented

- Agent creation requires **Purpose**: Outbound, Inbound, or Both.
- An agent may be assigned one active purchased number.
- Outbound calls/campaigns are blocked for inbound-only agents on both the
  frontend and backend.
- For an assigned number, the backend derives the LiveKit trunk, caller ID and
  VoiceLink dial prefix; the browser cannot override them.
- Customers use **Phone Numbers** in the workspace to start managed phone
  setup, complete KYC, move calling balance, browse/quote/buy a DID and retry
  activation.
- Provisioning creates or reuses the one VoiceLink SIP trunk allowed for the
  configured LiveKit SIP host, then creates per-DID VoiceLink routing, the
  LiveKit outbound trunk, a per-DID LiveKit inbound trunk and a trunk-scoped
  dispatch rule.
  SIP passwords are encrypted server-side; customer APIs omit provider/trunk
  identifiers and SIP credentials entirely, while Super Admin sees trunk IDs
  and only a masked password.
- Super Admin has **Telephony** for provider status, accounts/KYC, numbers,
  trunk/provisioning state, purchases, sync/retry, suspension and registering
  an already-provisioned DID manually. Its **Settings** tab stores the
  VoiceLink/SIP marketplace configuration in the `TelephonyConfig` database
  row (token/password encrypted), so telephony no longer needs
  `backend/.env` edits.
- `backend/app/agents/*` is untouched. Inbound dispatch uses the metadata
  contract the existing worker already parses.

## 1. VS Code setup (Windows PowerShell)

Stop any already-running backend/worker/frontend terminals first (`Ctrl+C`).
Open the repository root in VS Code and open **Terminal → New Terminal**
(PowerShell). Make sure this implementation is present:

```powershell
Test-Path backend\app\services\telephony_settings.py   # must print True
git status --short
```

Create/activate the backend virtual environment and install dependencies:

```powershell
cd backend
if (!(Test-Path .venv)) { py -m venv .venv }
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If PowerShell blocks `Activate.ps1`, run
`Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` once in that
terminal and activate again. If `py` is not recognized, use
`python -m venv .venv` when creating the environment.

In `backend/.env`, keep only the one-time bootstrap values that must exist
before the database/panel can start: `DATABASE_URL`, `JWT_SECRET`,
`LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` (shared with the
worker), and `ADMIN_CONFIG_ENC_KEY`. If the encryption key is blank, generate
one once and paste the output into `.env` (do not regenerate it later without
a key-rotation plan, and never share it):

```powershell
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Apply the Prisma schema and regenerate the Python client. This creates the
marketplace tables plus the new `TelephonyConfig` table:

```powershell
python -m prisma db push --schema schema.prisma
python -m prisma generate --schema schema.prisma
python -c "from prisma_client import Prisma; print(hasattr(Prisma(), 'telephonyconfig'))"
```

The last command must print `True`. If `backend/.env` points at the
production/Neon `DATABASE_URL`, `db push` changes that production database;
the schema change here is additive, but run it deliberately.

Then install/check both frontends in PowerShell:

```powershell
cd ..\frontend
npm install
npx tsc --noEmit
cd ..\super-admin
npm install
npx tsc --noEmit
```

Start each process in its own VS Code terminal:

```powershell
# Terminal 1 — backend (cwd: backend, venv active)
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Terminal 2 — worker (cwd: backend, venv active)
python -m app.agents.worker

# Terminal 3 — customer app (cwd: frontend)
npm run dev

# Terminal 4 — Super Admin (cwd: super-admin)
npm run dev
```

Check `http://localhost:8000/api/health`, customer app on `:3000`, and Super
Admin on `:3002`.

## 2. Configure telephony in Super Admin (not `.env`)

Log in to Super Admin and open **Telephony → Settings**.

- If telephony values already existed in `backend/.env`, opening this tab
  seeds them once into the `TelephonyConfig` database row (secrets encrypted). Verify
  the fields, click **Save settings**, then **Test saved connection**.
- On a new install, fill the panel directly:
  - VoiceLink API base URL: `https://app.voicelink.co.in/api/v1`
  - API token (preferred, without `Bearer `) **or** fallback
    username/password
  - VoiceLink SIP: `sip.voicelink.co.in`, port `3300`
  - Public LiveKit SIP: your Oracle SIP hostname, port `5060`
  - If VoiceLink already has its one allowed trunk for that LiveKit host,
    copy that existing trunk's SIP username/password into **Existing shared
    VoiceLink trunk username/password** because VoiceLink's trunk-list API
    may omit the password. Do not use the VoiceLink API-login credentials.
  - Tech prefix `45454`, transport `1 (UDP)`, audio formats `alaw,ulaw`
  - Optional default fallback trunk: the existing working `ST_...` trunk
  - Wallet bypass: **off**; client KYC final-submit: **off** until VoiceLink
    confirms the endpoint honours `client_id`
  - Customer app URL: `http://localhost:3000` locally or the production
    customer origin; Public API URL: blank locally or the production API
    origin behind a proxy
  - KYC terms URL / extra DigiLocker hosts: only when VoiceLink supplies them
- Click **Save settings**, then **Test saved connection**. The test reads the
  reseller profile and returns no credential.
- After a successful test, the old telephony lines may be removed/commented
  from `backend/.env`; restart the backend once to prove it now boots from
  the database row. Later panel-only changes need no restart (other backend
  instances pick them up within the 15-second settings cache).

Secret fields are write-only. The panel shows only configured/masked state;
leave a secret blank to keep it, type a new one to rotate it, or tick its
clear box to remove it.

For a real DigiLocker test, the panel's Public API URL (or request origin)
must be publicly reachable because VoiceLink redirects the browser to:

```text
<PUBLIC_API_URL>/api/telephony/kyc/return
```

That endpoint redirects to `<FRONTEND_URL>/phone-numbers?kyc=returned`; the
page then re-polls authoritative provider KYC status. A redirect alone never
marks Aadhaar verified.

Only bootstrap values remain in `.env`: `DATABASE_URL`, `JWT_SECRET`,
`ADMIN_CONFIG_ENC_KEY(S)`, CORS/startup values, and the LiveKit server
URL/API key/API secret used by both backend and the frozen voice worker.
The panel cannot securely store the encryption key that encrypts itself, and
the worker must know its LiveKit server before it can receive calls.

## 3. Register the existing single-tenant DID (optional, do this first)

This makes the already-working number selectable in the new agent form without
buying another number:

1. Open Super Admin → **Telephony → Manual number**.
2. Select the customer who owns the line.
3. Number: the existing E.164 DID from your deployment notes
4. LiveKit outbound trunk: the existing working `ST_...` trunk for that DID
5. Carrier tech prefix: `45454`
6. Channels: `2`
7. Expiry: `2026-10-31` (or the current provider expiry)
8. Leave the inbound trunk blank unless a separate per-DID inbound trunk has
   already been created.
9. Register it, then edit/create an agent, choose **Outbound** or **Both**,
   and assign the number.

### Edit or delete a manual number

Super Admin → **Telephony → Numbers**: rows whose source is **manual** have
**Edit** and **Delete** actions. Edit can change the number, LiveKit
inbound/outbound trunk IDs, carrier prefix, channels, and expiry; it does not
change the owner. Delete removes the local record, clears assigned agents,
and removes the number's own inbound dispatch rule. It does not delete the
carrier DID or shared LiveKit trunks, and it is blocked while an assigned
agent has an active call.

## 4. End-to-end test order

1. Start backend, frontend, Super Admin and the existing LiveKit/SIP stack.
2. Super Admin → **Plans**: create/verify the agent plan and KB packs, then
   set **Extra VoiceLink channel ₹/month**. The first channel is included;
   this price applies to each additional total channel selected on Billing.
3. Customer → **Billing**: buy the agent plan, select the total
   **VoiceLink channels**, and select any extra KB/FAQ packs.
4. Customer: open `/phone-numbers`, start phone setup and complete business
   KYC verification.
5. Add app-wallet funds; optionally move funds to calling balance.
6. Search → verify **Channels** (it defaults to the plan-selected total) →
   Get price → accept auto-renew → Confirm purchase. If more channels are
   entered here, the VoiceLink quote buys/prices the missing provider
   channels with that DID order.
7. Wait for the owned number to become **active**; use **Retry activation** if
   a provider/LiveKit step reports an error.
8. Create an agent, select purpose **Both**, assign the number and save.
   Selecting a multi-channel number raises the form's default max
   concurrency to that channel count.
9. Test one outbound SIP call; then call the DID from an external phone for
   inbound.
10. Check Super Admin → Telephony for account, KYC, purchase, provisioning
    step and trunk IDs. The SIP password should appear only masked/configured.

### Manage a customer's subscription in Super Admin

Super Admin → **Plans → Subscribers** supports create, edit, and delete for
customer subscription rows. Editable values are status, agent limit,
plan-selected VoiceLink channels, telephony-rented flag, extra KB
characters/FAQs, monthly renewal total, and renewal date. These are stored
in the same `Subscription` row read by the customer's **Billing → Your
current plan** dashboard, which shows the effective channels plus the
plan/provider/number breakdown. Clicking **Edit** freshly reads that
customer's stored DB row, including monthly total and extra KB/FAQ values,
before opening the form. Manual admin edits do not charge or refund
the wallet immediately; `monthly_total` is the amount future renewals use.
Deleting a subscription makes the customer dashboard show no active plan.
Every admin mutation is audit-logged.

Older purchased subscriptions may show a stored monthly total of ₹0 because
plan/KB prices were once read with the wrong key during purchase. That is
fixed for new purchases. For an old row, Edit prefills a suggested monthly
total only when the stored agent/KB allowances match exactly one current
plan/KB price; review it and click Save once to store the corrected amount.

The channel column is the effective maximum of plan-selected channels,
VoiceLink-account allocated channels, and the highest active DID's channels.
If it unexpectedly shows `1`, first restart the backend after pulling, then
check the small `plan · provider · number` breakdown and confirm that the
VoiceLink account and active DID belong to the same customer as the
subscription.

### Increase channels on the same number

Yes: after taking a plan and buying/activating a number, the customer can
open **Phone Numbers → Your phone numbers → Increase channels on this same
number**, enter the new total, and get a price before confirming.

Example: current effective channels `2`, target `5`, Super Admin price
`₹250` per extra channel/month. The billable increase is `3`, so the
subscription increases by `₹750/month`. The amount charged immediately is
prorated for the days left until the current subscription renewal; the full
`₹750` increment is included in later monthly renewals. Channels already
granted by the plan, provider account, or another DID are not charged again.

On confirmation the backend verifies/raises the VoiceLink client's channel
allocation, charges the app wallet, sets that DID's `channels`, and updates
the subscription's plan channels/monthly total. The agent's separate
**Max concurrent calls** must then be set no higher than the DID channels
(for example, set it to `5` after upgrading the DID to 5).

### Phone hangup + concurrent SIP calls

For a two-call test, the assigned DID's **Channels** and the agent's
**Max concurrent calls** must both be at least `2`. There is no longer a
separate plan "lines" blocker: channels selected with the plan, bought with
the DID, allocated on the VoiceLink account, or set on a manual DID all feed
the same effective channel entitlement. Then, on the customer Call page:

1. Dial the first mobile number in SIP mode and answer it.
2. The button changes to **Dial another number (1/2)**; enter a second
   mobile number and dial it without ending the first call.
3. Both calls appear with independent **End** buttons. Hanging up either
   phone should remove only that call within a few seconds; the other call
   remains live.
4. With only one call active, hanging up on the phone should return the page
   to the ended/summary state without a browser refresh or clicking End.

## 5. Backend tests

The disposable test database is SQLite, so the test run temporarily
generates the Prisma client from a SQLite copy of the schema. In the backend
PowerShell terminal (venv active):

```powershell
(Get-Content schema.prisma -Raw) -replace 'provider = "postgresql"', 'provider = "sqlite"' |
  Set-Content schema.sqlite.prisma -Encoding utf8
$env:DATABASE_URL = "file:./data/test.db"
python -m prisma db push --schema schema.sqlite.prisma
python -m prisma generate --schema schema.sqlite.prisma
python -m pip install pytest pytest-asyncio   # only if pytest is missing
python -m pytest tests/test_telephony_marketplace.py tests/test_services_and_repos.py tests/test_contact.py -v
Remove-Item Env:DATABASE_URL
python -m prisma generate --schema schema.prisma
```

The final `generate` is required before starting the Postgres/Neon backend
again. In a Git Bash/WSL checkout, `bash scripts/run-tests.sh
tests/test_telephony_marketplace.py tests/test_services_and_repos.py tests/test_contact.py -v` does the SQLite
setup/test part; still regenerate from `schema.prisma` afterwards.

## Known provider gates — do not guess these

- The panel's **VoiceLink confirmed client KYC final-submit** switch must
  stay off until VoiceLink confirms in writing that final-submit honours the
  per-customer `client_id`. Completed steps remain saved; the UI explains
  the gate instead of risking a tenant-level submission.
- Transport code `1` assumes the inferred SDK mapping `1=UDP`. Confirm it
  against a live VoiceLink trunk readback before changing it in the panel.
- VoiceLink's trunk-list response may omit the existing trunk's SIP
  password. In that case activation stops until the operator copies the
  existing trunk's credentials into the panel's SIP routing fields; it does
  not rotate the shared trunk password automatically.
- Confirm trial-plan DID/channel entitlements. VoiceLink allows only one
  trunk per SIP server host, so activation reuses the existing trunk that
  already points at the configured LiveKit SIP host; confirm shared-trunk
  call billing/client attribution with VoiceLink before broad self-service.
  That trunk's **Peer Monitoring** toggle must be ON in the VoiceLink portal
  because the API cannot set it.
- Wallet-bypass semantics must be confirmed with VoiceLink before enabling
  that panel switch.

## Security notes

- Rotate the previously exposed LiveKit API secret and VoiceLink SIP password
  before production, updating LiveKit server/SIP, backend, CLI and the
  VoiceLink/LiveKit trunk credentials together.
- Restrict public SIP exposure where the carrier supports source allowlisting;
  keep RTP/firewall rules intentional and document any change.
- Never paste reseller tokens, SIP passwords or identity documents into logs,
  tickets or chat.
