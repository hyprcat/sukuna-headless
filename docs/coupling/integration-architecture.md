# Integration Architecture

How the backend (sukuna-headless), sandbox (sukuna-sandbox), and frontend connect.

## Architecture Position

```
Backend:   control plane, source of truth, billing authority, reconciliation owner
Sandbox:   runtime data plane, direct client stream/HITL/cancel surface, local execution state, callback outbox
Contract:  signed manifest in, scoped capability tokens for clients, signed ordered callbacks out
```

## Components

```
┌──────────────────────────┐     ┌──────────────────────────┐
│  Frontend (Dashboard)    │     │  SDKs (future)           │
│  Astro 5                 │     │  TypeScript / Python     │
│  Developer dashboard     │     │  Run creation + stream   │
│  Agent lifecycle CRUD    │     │  HITL responses          │
│  Read-only run history   │     │  Rating submission       │
└────────┬─────────────────┘     └────────┬────────┬────────┘
         │ GraphQL                         │        │
         │ (session auth)                  │        │
         ▼                                 │        │
┌──────────────────────────────────────────┤        │
│  Backend (Control Plane)                 │        │
│  Django 6 + Strawberry                   │        │
│                                          │        │
│  Owns: orgs, workspaces, agents, tools,  │        │
│    knowledge, end users, schedules,      │        │
│    policies, billing, run source of truth│        │
│  Creates: runs, billing holds, manifests │        │
│  Mints: capability JWTs                  │        │
│  Ingests: signed callbacks from sandbox  │        │
│  Reconciles: stale runs, holds, pools    │        │
│  Spawns: sandboxes via E2B SDK           │        │
└──────────────────┬───────────────────────┘        │
                   │ E2B SDK                         │
                   │ (spawn / resume / manifest)     │
                   ▼                                 │
┌──────────────────────────────────────────┐        │
│  Caddy Reverse Proxy                    │        │
│  *.run.midsphere.com                    │        │
│  Rewrites {id}.run.midsphere.com        │        │
│  → 8000-{id}.e2b.app                   │        │
│  Sub-ms overhead, no auth logic         │◄───────┘
└──────────────────┬───────────────────────┘  SDK connects
                   │                          directly via
                   ▼                          Caddy domain
┌──────────────────────────────────────────┐
│  Sandbox (Runtime)                       │
│  Django 6 + Exo Framework                │
│  E2B microVM                             │
│                                          │
│  Validates: signed manifest, cap. JWTs   │
│  Executes: agent, tools, MCP, Ralph      │
│  Streams: SSE events to SDK directly     │
│  Handles: HITL, cancel, files, MCP       │
│  Stores: local SQLite (events, outbox)   │
│  Sends: signed callbacks → backend       │
│  Enforces: lease limits locally          │
│  Reports: usage checkpoints              │
└──────────────────────────────────────────┘

Two paths — SDK never sees an E2B URL:
  Control (commands):  SDK → Backend (GraphQL) → E2B SDK → Sandbox
  Hot path (runtime):  SDK → Caddy (*.run.midsphere.com) → Sandbox
  Durable sync:        Sandbox → Backend (signed HTTP callbacks)
```

## Decided Integration Model

| Concern | Decision | Rationale |
|---|---|---|
| Data coupling | Separate databases | Backend owns its Postgres. Sandbox uses local SQLite/append-log. No shared tables, no managed=False models for backend tables. |
| Hot path (stream, HITL, cancel, files) | Direct to sandbox via Caddy | SDK connects to `{sandboxId}.run.midsphere.com`. Caddy proxies to `8000-{sandboxId}.e2b.app`. Sub-ms overhead. Capability JWT auth validated locally by sandbox. |
| Control path (run creation, wake, billing) | Backend GraphQL | startRun, wakeForRun, refreshSandboxToken, billing, dashboard reads. API key auth at backend. |
| Run authorization | Signed RunManifest | Backend assembles and signs a versioned manifest with all execution context. Sandbox validates signature, expiry, and binding before executing. |
| Client auth against sandbox | Capability JWT | Short-lived (30 min), run-scoped, validated locally by sandbox. No API key validation or DB reads at sandbox. |
| Durable projection | Signed callbacks | Sandbox sends ordered, signed event callbacks to backend. Backend validates and projects into durable state. |
| Billing | Reservation + metering | Backend creates hold pre-execution. Sandbox enforces lease locally, reports usage via callbacks. Backend settles from validated usage. |
| URL masking | Caddy reverse proxy | `*.run.midsphere.com` → `8000-*.e2b.app`. E2B-documented setup. Zero runtime cost beyond sub-ms proxy hop. |
| Scope hierarchy | Organization → Workspace | Organization = billing + policy boundary. Workspace = project-level resource container. |
| Frontend scope | Dashboard only | No run creation, no streaming, no HITL. SDK concerns. |
| Insights | Plug-and-play layer | Insights model exists. Generation agent writes to the table. Dashboard reads and displays. |

## Data Flow: Starting a Run

```
SDK                          Backend                         Sandbox
 │                              │                               │
 │  startRun(apiKey, agentId,   │                               │
 │    endUserId, prompt, lease) │                               │
 │ ──────────────────────────►  │                               │
 │                              │  1. Validate API key (bcrypt) │
 │                              │  2. Load agent + tools +      │
 │                              │     knowledge + policy        │
 │                              │  3. Check end-user controls   │
 │                              │     (credits, concurrency,    │
 │                              │      model tier, allowed      │
 │                              │      tools/knowledge)         │
 │                              │  4. Check wallet balance      │
 │                              │  5. Acquire sandbox from      │
 │                              │     warm pool (or spawn)      │
 │                              │  6. In one DB transaction:    │
 │                              │     create/reuse Conversation,│
 │                              │     Run, BillingHold, signed  │
 │                              │     manifest, ManifestRecord  │
 │                              │  7. POST manifest to sandbox  │
 │                              │     via E2B SDK               │
 │                              │ ─────────────────────────►    │
 │                              │                               │  8. Validate manifest
 │                              │                               │     (size, key, signature,
 │                              │                               │      expiry, binding)
 │                              │                               │  9. Start agent execution
 │                              │                               │ 10. Update Run status →
 │                              │                               │     running (via callback)
 │                              │  ◄─────────────────────────── │ 11. Return {status: ok}
 │                              │                               │
 │                              │ 12. Mint capability JWT       │
 │                              │ 13. Build sandbox URL:        │
 │                              │     {sandboxId}.run.           │
 │                              │     midsphere.com             │
 │  ◄────────────────────────── │ 14. Return:                   │
 │  {runId, sandboxUrl,         │     {runId, sandboxUrl,       │
 │   capabilityToken, expiresAt}│      capabilityToken}         │
 │                              │                               │
 │  GET {sandboxUrl}/runs/{id}/stream?token={JWT}               │
 │ ─────────────────────── (via Caddy) ──────────────────────►  │
 │                              │                               │ Validate JWT locally
 │  ◄───────────────────────────────────────────────────────── │ Stream SSE events
 │  event: run_started          │                               │
 │  event: step                 │                               │
 │  event: tool_call            │                               │
 │  event: hitl_requested       │                               │
 │  ...                         │                               │
 │                              │                               │
 │                              │  ◄─────────────────────────── │ Signed callbacks
 │                              │  (batched events, usage       │ (async, not blocking
 │                              │   checkpoints, terminal)      │  the stream)
```

## Data Flow: HITL (Human-in-the-Loop)

```
SDK                                              Sandbox
 │                                                  │
 │  ◄──── SSE event: hitl_requested                  │
 │        {request_id, prompt, choices}              │
 │                                                  │
 │  POST {sandboxUrl}/runs/{id}/hitl/{request_id}   │
 │       Authorization: Bearer {capabilityJWT}       │
 │       Body: {response: "approve"}                │
 │  ────────────────── (via Caddy) ──────────────►  │
 │                                                  │ Validate JWT
 │                                                  │ Resume agent execution
 │  ◄──── SSE event: step (agent continues)          │
```

HITL goes direct to the sandbox — no backend hop. The capability JWT carries `hitl:respond` scope. If the sandbox is paused during a long HITL wait, the SDK gets connection-refused and calls `wakeForRun` on the backend (see Liveness Gate).

## Data Flow: Cancellation

```
SDK                                              Sandbox
 │                                                  │
 │  DELETE {sandboxUrl}/runs/{id}                    │
 │  Authorization: Bearer {capabilityJWT}            │
 │  ────────────────── (via Caddy) ──────────────►  │
 │                                                  │ Validate JWT (run:cancel scope)
 │                                                  │ Cancel asyncio task
 │                                                  │ Emit terminal callback → backend
 │  ◄──── SSE event: run_cancelled                   │
 │  ◄──── {status: cancelled}                        │
```

Billing hold settlement happens when the backend receives and validates the terminal callback.

## Data Flow: Scheduled Run

```
Backend (Django task / Celery beat)               Sandbox
 │                                                   │
 │  Every minute: find schedules where                │
 │  status=active AND next_run_at <= now              │
 │                                                   │
 │  For each due schedule:                            │
 │  1. Load agent + end user                          │
 │  2. Check end-user controls                        │
 │  3. Check wallet balance                           │
 │  4. Spawn / acquire sandbox                        │
 │  5. In one DB transaction: create Run,             │
 │     BillingHold, ScheduleExecution, signed         │
 │     RunManifest, and RunManifestRecord             │
 │  6. RunManifest uses                              │
 │     (hitl_mode=auto_deny or fail_closed)           │
 │  7. POST manifest to sandbox                       │
 │ ────────────────────────────────────────────────►   │
 │                                                   │  (same as on-demand)
 │  8. Update Schedule.next_run_at                    │
 │                                                   │
 │  ◄──── signed callbacks (usage, terminal)          │
 │  9. Settle hold from terminal usage                │
 │ 10. Update ScheduleExecution outcome               │
```

No capability JWT is minted for scheduled runs — there is no live SDK client to give it to. Scheduled manifests must not require interactive HITL. The backend either compiles a policy that auto-denies approval requests (`hitl_mode=auto_deny`) or fails closed before dispatch (`hitl_mode=fail_closed`). If the sandbox still reaches a HITL-required path in a scheduled run, it emits `run_failed` with `error_code: "approval_unavailable"`.

## Run Manifest

The backend sends a signed, versioned manifest to the sandbox. This is the sandbox's execution authorization for a single run.

**Fields:**

```
manifest_version:     int (currently 1)
manifest_id:          UUID (unique, for logging and dedup)
signing_key_id:       str (selects manifest public key during rotation)
signature:            Ed25519 signature of the manifest body (backend signs with private key)
expires_at:           datetime (short-lived, e.g. 5 minutes from issue)

run_id:               UUID (backend-created)
sandbox_id:           str (E2B sandbox ID — manifest is bound to this sandbox)
workspace_id:         int
agent_id:             int
end_user_id:          int
conversation_id:      UUID

prompt:               str
system_prompt:        str
policy_block:         str (rendered policy restrictions)

lease:
  max_runtime_seconds:  int
  max_total_tokens:     int
  max_cost_usd:         Decimal

model_tier:           str (free/pro/enterprise)
hitl_mode:            str (interactive/auto_deny/fail_closed)

tools:                list of resolved tool definitions
  - id, name, description, parameters_schema, execution_endpoint, is_sensitive

knowledge:            list of resolved knowledge references
  - id, name, kind, source (URL or fetch reference)

callback_url:         str (absolute HTTPS backend endpoint for signed callbacks)
callback_auth:        str (backend-generated per-run HMAC key for callback signing)
```

**Signing:** `Ed25519.sign(MIDSPHERE_MANIFEST_PRIVATE_KEY, canonical_json(manifest_body))`. The manifest body includes `signing_key_id`; sandbox validates using `MIDSPHERE_MANIFEST_PUBLIC_KEYS[signing_key_id]`. The sandbox never has the private key — a compromised sandbox cannot forge manifests.

**Callback auth:** the backend generates `callback_auth` with a CSPRNG for each run, embeds it in the signed manifest, and stores it encrypted in `RunManifestRecord`. After the sandbox ID is known, the backend creates the `Run`, `BillingHold`, signed manifest, and `RunManifestRecord` in one database transaction before the manifest is posted.

**Callback URL:** the backend constructs `callback_url` from a stable configured public origin (`BACKEND_PUBLIC_URL`) plus `CALLBACK_INGESTION_PATH`. It must not depend on per-request host headers; load balancers route that stable URL to any healthy backend instance.

**Manifest rejection rules:**
- **Invalid signature:** return synchronous error to backend via E2B SDK response. Do not emit any callback (the `callback_auth` inside the manifest is untrusted if the signature is invalid).
- **Unknown `signing_key_id`:** return synchronous error. No callback.
- **Expired manifest:** return synchronous error. No callback.
- **Wrong sandbox binding:** return synchronous error. No callback.
- **Oversized manifest:** return synchronous error. No callback.
- **Valid signature but unsupported configuration:** emit `run_failed` callback with `error_code: "manifest_rejected"` (callback credentials are trusted because the signature was valid).

The backend marks the run failed from the synchronous invoke error when the manifest cannot be trusted.

**Size:** embed everything by default. Conservative limit: 1MB. The backend fails `startRun` if the signed manifest would exceed 1MB. The sandbox also rejects any received manifest over 1MB synchronously before execution. Fetch-by-reference can be added later if manifests grow too large.

## Capability JWT

Minted by the backend, validated locally by the sandbox.

**Claims:**
```json
{
  "iss": "midsphere-backend",
  "aud": "midsphere-sandbox",
  "sub": "run_id",
  "sandbox_id": "e2b_sandbox_id",
  "workspace_id": "workspace_id",
  "end_user_id": "end_user_id",
  "conversation_id": "conversation_id",
  "scope": ["stream:read", "hitl:respond", "run:cancel", "files:rw", "mcp:manage"],
  "exp": 1234567890,
  "iat": 1234567000,
  "jti": "unique-token-id"
}
```

**Signing:** EdDSA (Ed25519) with `MIDSPHERE_JWT_PRIVATE_KEY` (backend signs). JWT headers include `alg: "EdDSA"` and `kid`; sandbox verifies using `MIDSPHERE_JWT_PUBLIC_KEYS[kid]`. The sandbox never has the private key — a compromised sandbox cannot mint capability JWTs.

The example scope array shows the complete current scope vocabulary. Tokens should be minted with only the scopes the caller needs and is allowed to use.

**Usage:** SDK passes as `Authorization: Bearer {jwt}` or query param `?token={jwt}` on all direct sandbox requests.

**Sandbox validates:**
- `kid` maps to a configured public key
- Signature
- Expiry
- Audience and issuer
- `sub` matches the run ID
- `sandbox_id` matches the current sandbox
- `scope` matches the endpoint
- Optional conversation/end-user/workspace claims

**Token refresh:** long runs and HITL waits can outlive the 30-minute TTL. Open SSE connections continue — the token was valid at connect time. Reconnects need a fresh token via `refreshSandboxToken(runId)` on the backend.

## Callback Protocol

The sandbox sends ordered, signed HTTP callbacks to the backend for durable state projection. Callbacks are the async sync path — not the user hot path.

### Event Types

| Event | Priority | Backend action |
|---|---|---|
| `run_started` | Immediate | Update Run status → running |
| `step` | Batched | Append to run event history |
| `tool_call` | Batched | Append to run event history |
| `tool_result` | Batched | Append to run event history |
| `hitl_requested` | Batched | Append to run event history |
| `hitl_responded` | Batched | Append to run event history |
| `artifact_created` | Batched | Record artifact metadata |
| `usage_checkpoint` | Batched | Update cumulative usage on Run |
| `run_completed` | Immediate | Settle hold, update Run terminal state |
| `run_failed` | Immediate | Settle hold, update Run terminal state |
| `run_cancelled` | Immediate | Settle hold, update Run terminal state |

Token deltas are stream-only — not callbacked unless a product requirement needs durable token replay.

### Callback Envelope

```json
{
  "manifest_id": "uuid",
  "run_id": "uuid",
  "sandbox_id": "str",
  "batch_id": "uuid",
  "schema_version": 1,
  "events": [
    {
      "event_id": "uuid",
      "sequence_no": 42,
      "event_type": "tool_call",
      "emitted_at": "2026-05-08T12:00:00Z",
      "payload": { ... }
    }
  ],
  "sent_at": "2026-05-08T12:00:05Z",
  "signature": "HMAC-SHA256 of the full envelope excluding the signature field"
}
```

### Backend Ingestion

1. Verify signature
2. Verify timestamp freshness
3. Dedup on `event_id` (UNIQUE constraint)
4. Verify run and sandbox binding
5. Reject sequence regressions
6. Project events into backend state (Run, RunEvent, billing)
7. Acknowledge only after durable write
8. Return `{ "acked_through": highest_contiguous_sequence_no }` — `acked_through` is the highest **contiguous** sequence number durably written, not the highest received. If events 1, 2, 5 are received but 3 and 4 are missing, return `{ "acked_through": 2 }`. Reject batches with unexpected sequence gaps or return `{ "acked_through": N, "expected_sequence": N+1 }`

### Callback Flow in the Sandbox

```
1. Append event to local SQLite store
2. Stream event to connected SSE clients
3. Enqueue event in callback outbox
4. Send callback batch (or immediately for lifecycle/terminal)
5. Mark acknowledged only after backend returns ack
6. Retry with exponential backoff on failure
```

## Sandbox Warm Pool

### The Problem

A fresh E2B sandbox requires: VM spawn → OS boot → agent_server startup → LLM provider preflight. This is 5–10 seconds before the first token reaches the SDK. Unacceptable for interactive use.

### The Solution: Pause / Resume

E2B supports `sandbox.pause()` and `sandbox.resume()`. A paused sandbox freezes the VM — filesystem and memory are preserved. The agent_server process is already running, connections are established, caches are warm. Resume unfreezes in ~1–2 seconds.

### Lifecycle

```
spawn → boot agent_server → pause()     ← warm pool entry
                               │
                    run request arrives
                               │
                          resume() → POST manifest → agent executes → run completes
                               │
                           pause()               ← back to warm pool
                               │
                    (idle too long, cost threshold exceeded)
                               │
                         terminate()             ← pool entry destroyed
```

### Pool Dimensions

The warm pool is **per-agent**, not per-workspace or per-conversation.

**Sizing signals:**

| Signal | Meaning | Pool action |
|---|---|---|
| Agent just created | Developer is likely testing imminently | Pre-warm 1 sandbox immediately |
| Agent has high recent run volume (e.g., 50 runs/day) | Sustained demand | Maintain N warm sandboxes proportional to peak concurrency |
| Agent has low run volume (e.g., 1 run/week) | Cold start is acceptable | Pool can be 0–1; spawn on demand |
| Agent untouched for 30+ days | Inactive | Pool = 0; terminate any remaining sandboxes |
| Burst beyond pool capacity | All warm sandboxes busy | Cold-start a new one (unavoidable); add to pool after run |

**Pool management runs as a background job on the backend:**
1. **Pre-warm:** spawn sandbox → wait for agent_server health check → `pause()`. Record as `SandboxInstance(sandbox_state="paused")`.
2. **Assign:** when a run comes in, grab a paused sandbox from the agent's pool → `resume()` → POST manifest.
3. **Return:** after run completes and sandbox goes idle → `pause()` back into pool.
4. **Scale up:** if pool is empty on demand, cold-start a new sandbox. It joins the pool after the run.
5. **Terminate:** paused sandboxes idle beyond a configurable cost threshold (e.g., 2 hours with no runs) → `terminate()`. Pool rebuilds lazily on next demand.

### Conversation Affinity

For multi-turn conversations, the **same sandbox** should be reused. It holds:
- Conversation state (message history, context window)
- Vital information (knowledge manager extractions)
- Agent memory (warm in-process caches)
- Active MCP server connections
- File system state (artifacts, user uploads)

**Assignment order:**
1. Check if a sandbox is already associated with this conversation → resume it
2. If not, grab any warm sandbox from the agent's pool
3. If pool is empty, cold-start

The `SandboxInstance` table tracks conversation affinity via a nullable `conversation_id` field.

### Liveness Gate

Every backend operation that touches a sandbox goes through a liveness check:

```
1. Look up SandboxInstance for this run / conversation / agent
2. If sandbox_state == "running" → proceed immediately
3. If sandbox_state == "paused"  → resume() via E2B SDK → health check → proceed
4. If sandbox_state == "terminated" or not found → cold-start → proceed
5. If resume / spawn fails after retries → fail the request with clear error
```

This gate applies to:
- `startRun` (orchestrator)
- `wakeForRun` (SDK-triggered sandbox resume)

**SDK reconnect after sandbox pause:** when a direct sandbox request fails (connection refused — sandbox was paused), the SDK calls `wakeForRun(runId)` on the backend. Backend resumes the sandbox and returns the current sandbox URL + fresh capability token. SDK retries the original request.

### HITL and Sandbox Lifecycle

- **Paused/resumed sandbox:** HITL state survives (in-process asyncio.Future is preserved across E2B pause/resume)
- **Killed/replaced sandbox:** pending HITL is lost (the Future is gone). Normal idle/cost cleanup must NOT kill a sandbox with pending HITL. If the sandbox is gone, backend terminalizes the run.
- **Resumable HITL after sandbox replacement** would require durable execution checkpoints — not in scope.

---

## Connection Resilience

### Connection Paths

```
SDK ──── GraphQL ────► Backend              (API key / session auth) — control path
SDK ──── direct ─────► Caddy ──► Sandbox    (capability JWT) — hot path
Sandbox ── HTTP ─────► Backend              (signed callbacks) — durable sync
Backend ── E2B SDK ──► Sandbox              (manifest signing) — spawn/invoke
```

### Failure Modes and Recovery

| Path | Failure | Impact | Recovery |
|---|---|---|---|
| SDK → sandbox SSE (via Caddy) | Network drop, client sleep, mobile background | SDK stops receiving events | SDK reconnects with `Last-Event-ID`. Events are in sandbox local store — replay is gapless. Sandbox keeps running regardless of listeners. |
| SDK → sandbox REST (HITL/cancel) | Sandbox paused | Connection refused | SDK calls backend `wakeForRun(runId)`. Backend resumes sandbox, returns URL + fresh token. SDK retries. |
| SDK → backend GraphQL | Network error | Command not processed | SDK retries with exponential backoff. `startRun` with same idempotency key returns existing run. |
| Sandbox → backend callbacks | Backend down or slow | Callbacks queue in sandbox outbox | Sandbox retries with exponential backoff. Events are durable in local SQLite. Backend catches up when available. |
| Sandbox → backend callbacks | Sandbox killed before flush | Undelivered callbacks lost | Backend reconciler detects missing terminal callback. Settles hold from last checkpoint + E2B runtime duration. |
| Backend → sandbox (E2B SDK) | Spawn or invoke fails | Run stuck in `queued` | Reaper job finds stale queued runs (>60s with no sandbox) and marks them `failed`. |
| Caddy down | SDK can't reach sandbox | Hot path blocked | Deploy 2+ Caddy instances behind a load balancer. Stateless — instant recovery. |

### Idempotency Requirements

| Operation | Idempotency key | Behavior on duplicate |
|---|---|---|
| `startRun` | `conversation_id` + client-provided idempotency key | Return existing run if one is active for this conversation |
| `cancelRun` (direct to sandbox) | `run_id` | No-op if already cancelled/failed/finished |
| HITL response (direct to sandbox) | `request_id` | No-op if already responded |
| Callback ingestion | `event_id` | Skip if event with this ID already projected |
| `bill_tool_call` (sandbox local) | `call_id` | Skip if already tracked locally |
| Top-up (Dodo) | `idempotency_key` on Topup model | Existing behavior |

### Orphan Detection (Backend Reconciler)

Grouped into focused services:

**Run and hold reconciler:**
- Queued runs with no sandbox assignment (>60s)
- Running runs beyond lease with no recent usage checkpoint
- Active billing holds with no recent usage
- Missing terminal callbacks (run appears alive but sandbox is gone)

**Sandbox lifecycle reconciler:**
- SandboxInstance records with no matching E2B sandbox
- Paused sandboxes past cost/time threshold
- Sandboxes with pending HITL excluded from idle termination

**Callback gap monitor:**
- Sequence number gaps in projected events
- Runs with callbacks that stopped mid-stream

**HITL timeout reconciler:**
- HITL requests pending beyond configurable timeout
- Auto-deny per policy when no SSE listener is connected

**SSE reconnect ID:** the sandbox sets the SSE `id:` value to the callback `sequence_no` for the same event. `Last-Event-ID` is therefore the last per-run contiguous sequence number the SDK saw; replay returns events with a greater `sequence_no`.

---

## Latency Budget

### Per-Operation Targets

| Operation | Target | Hot path | Warm (resume) | Cold start |
|---|---|---|---|---|
| `startRun` → first SSE event | <1s | Sandbox running, POST manifest | ~1–2s resume + manifest | ~5–10s spawn + boot + manifest |
| SSE event delivery | <5ms from agent emit | Caddy sub-ms proxy | Same after resume | Same after boot |
| HITL response → agent resumes | <100ms | Direct POST to sandbox via Caddy | +1–2s if paused (SDK calls wakeForRun first) | N/A |
| Cancel → confirmation | <100ms | Direct DELETE to sandbox via Caddy | +1–2s if paused | N/A |
| API key validation (bcrypt) | ~150ms | Backend only, single bcrypt verify | Same | Same |
| Capability JWT validation | <1ms | Local Ed25519 verify at sandbox | Same | Same |
| Backend GraphQL query | <200ms p95 | Standard query budget | Same | Same |
| Backend GraphQL mutation | <400ms p95 | Standard query budget | Same | Same |
| Callback delivery | Best-effort, <5s typical | Async, non-blocking | Same | Same |

### No Double Bcrypt

SDK authenticates against the backend (bcrypt, ~150ms). For direct sandbox requests, the SDK uses a capability JWT (local Ed25519 verify, <1ms). The sandbox never validates raw API keys.

---

## Security & Trust Model

### Trust Boundaries

```
Untrusted          │  Trusted
                   │
SDK / Frontend ────┤──── Backend (auth boundary for control path)
                   │
                   ├──── Caddy (URL masking, no auth logic)
                   │
                   ├──── Sandbox (auth boundary for hot path, validates JWTs)
                   │         Has NO access to backend DB
                   │         Local store is untrusted cache
                   │
                   └──── Backend DB (no external access)
```

### Threat Model

| Threat | Mitigation |
|---|---|
| **SDK impersonation** | API key validated at backend (bcrypt). Capability JWT for hot path is short-lived (30 min) and scoped to a single run + sandbox. |
| **E2B URL leakage** | URL never returned to clients. Caddy masks it as `*.run.midsphere.com`. |
| **Capability JWT theft** | 30-min TTL. Scoped to single run + sandbox. Attacker can only interact with one run they already have access to. |
| **Sandbox compromise** | Sandbox has no backend DB credentials and no signing private keys (only public keys for verification). Local store is untrusted. Backend validates every callback (signature, sequence, billing plausibility). A compromised sandbox can report false usage — backend caps at the reserved hold amount. A compromised sandbox cannot forge manifests or mint capability JWTs for other sandboxes. |
| **Callback forgery** | Callbacks are HMAC-signed with a per-run key (delivered in the manifest). Backend verifies signature, timestamp, run binding, and sequence consistency. |
| **HITL injection** | Capability JWT with `hitl:respond` scope required. JWT is bound to `run_id` + `sandbox_id`. Idempotent on `request_id`. |
| **Cross-tenant access** | Each sandbox runs in an isolated E2B microVM. Sandbox only has what the manifest gave it — can't query other workspaces. |
| **Billing manipulation** | Sandbox reports usage but backend validates against: reserved hold, lease maximum, rate card, event sequence consistency, E2B runtime duration. If usage is impossible, backend marks for reconciliation instead of settling. |

### Key Rotation

| Secret | Rotation strategy |
|---|---|
| `MIDSPHERE_JWT_KEY_ID` + `MIDSPHERE_JWT_PRIVATE_KEY` / `MIDSPHERE_JWT_PUBLIC_KEYS` | Backend signs with the active private key and writes `kid` into the JWT header. Sandbox verifies against a configured public-key map containing current and previous keys during a 1-hour overlap. After overlap, drop the old public key. Private key never leaves the backend. |
| `MIDSPHERE_MANIFEST_KEY_ID` + `MIDSPHERE_MANIFEST_PRIVATE_KEY` / `MIDSPHERE_MANIFEST_PUBLIC_KEYS` | Backend writes `signing_key_id` into the signed manifest body. Sandbox selects the verifying public key by that ID. Same current/previous overlap strategy. Private key never leaves the backend. |
| `callback_auth` (per-run) | Embedded in the manifest. Unique per run. No rotation needed — dies with the run. |
| API keys (`ms_live_*`) | Developer-initiated via dashboard. Old key soft-deleted with grace period. |
| E2B API key | Platform credential. Rotate via E2B dashboard. Only used by backend's E2B SDK wrapper. |

---

## Caddy Reverse Proxy

### What It Is

A Caddy instance that maps `*.run.midsphere.com` to `8000-*.e2b.app` (port-prefixed per E2B custom domain format). E2B documents this setup. It adds sub-millisecond latency and carries no business logic.

### Caddyfile

```caddyfile
*.run.midsphere.com {
    tls {
        dns cloudflare {env.CLOUDFLARE_API_TOKEN}
    }

    vars sandboxId {labels.3}

    reverse_proxy 8000-{vars.sandboxId}.e2b.app:443 {
        header_up Host 8000-{vars.sandboxId}.e2b.app
        header_up X-Real-IP {remote_host}
        header_up X-Forwarded-For {remote_host}
        header_up X-Forwarded-Proto {scheme}
        header_up X-Forwarded-Host {host}

        transport http {
            tls
            tls_server_name 8000-{vars.sandboxId}.e2b.app
        }
    }
}
```

Streaming uses SSE over ordinary HTTP. This Caddyfile does not need special WebSocket upgrade handling for the run stream. If WebSocket endpoints are added later, they need explicit proxy tests before contract freeze for that endpoint.

### Deployment

- One small VM or container. Stateless — deploy 2+ behind a load balancer for HA.
- Cloudflare DNS for `*.run.midsphere.com` pointing to the Caddy instance(s).
- Caddy handles TLS certificate provisioning via the Cloudflare DNS ACME challenge.
- No Redis, no database, no auth logic, no application code.

---

## Local Development

Remote E2B sandboxes can't call a laptop localhost. This is not a reason to use shared DB in production. Dev modes:

| Mode | Description | Best for |
|---|---|---|
| **Local sandbox** | Backend uses local Postgres. Sandbox uses local SQLite for runtime store and sandbox-local Postgres for Exo memory. Sandbox never points at the backend's Postgres. | Fast iteration, contract tests |
| **Pull mode** | Backend pulls pending callback batches from a sandbox-only debug endpoint instead of receiving callbacks | No ngrok needed — traffic is outbound from laptop to E2B |
| **Callback relay** | Sandbox posts to a public relay (like Stripe CLI). Local backend connects outbound. | Testing callback flow with remote sandbox |
| **Staging** | Deployed backend URL + real E2B sandbox callbacks | Full-fidelity production path |

**Debuggability:**
- Every run has a correlation ID (the `run_id`)
- `manifest_id` logged by both backend and sandbox
- Callback `event_id`s and `sequence_no`s visible in logs
- Backend admin shows: last callback, last projected sequence, sandbox state, hold state per run

---

## Frontend Responsibilities (Dashboard Only)

The frontend is a developer-facing dashboard. It does NOT interact with the sandbox.

**What it does:**
- Agent lifecycle: create, configure (tools, knowledge, policy), activate/deactivate, clone
- Tool/Knowledge/Schedule/Policy/EndUser CRUD
- Run history: read-only list + detail (from backend-projected callbacks)
- Billing: wallet balance, top-up via Dodo checkout, ledger history
- Workspace settings, member management, API key management
- Insights: display active insights (generated by a separate insights agent)
- Organization management (multi-workspace)

**What it does NOT do:**
- Start runs (SDK only)
- Stream run events (SDK only)
- Handle HITL requests (SDK only)
- Submit ratings (SDK only)
- Connect to the sandbox in any way

**Dashboard lag:** run history reflects backend-projected state, which lags behind the live sandbox by the callback flush interval (typically <5s). Terminal events are projected immediately. The UI should show a "last updated" indicator on run detail views.
