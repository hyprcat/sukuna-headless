# Separate-DB Sandbox Contracts

This note updates the coupling direction after reviewing the current
`sukuna-headless` backend, the current `sukuna-sandbox` runtime, and the
existing coupling proposal.

It is written as guidance for future architecture work. The important shift is
that the backend should remain the control plane, while the sandbox should own
the hot runtime data plane without sharing the backend database.

## Decision

Do not use shared PostgreSQL as the primary coupling mechanism between
`sukuna-headless` and `sukuna-sandbox`.

Use separate persistence boundaries:

```text
Backend DB
  durable business state, billing, run source of truth

Sandbox local store
  live runtime state, SSE replay, HITL state, callback outbox

Signed contracts
  run manifest into sandbox, ordered events out of sandbox
```

The backend starts, authorizes, leases, and reconciles runs. The sandbox
executes runs and serves live client traffic directly.

## Why Not Shared PostgreSQL

The earlier proposal used shared Postgres to avoid webhook delivery races and
let the sandbox write directly into backend-owned tables. That simplifies some
persistence paths, but it creates a tighter and riskier coupling than we want.

Shared DB access would make every E2B sandbox a database client for production
business tables. That creates several problems:

- backend and sandbox deploys become schema-lockstep
- backend migrations can break active sandboxes
- sandbox DB credentials carry too much authority
- transient E2B runtimes can pressure backend DB pools
- billing and policy logic can split across two applications
- tenant isolation becomes harder to reason about
- the sandbox starts behaving like a second backend process

The sandbox modularity refactor gives us a better path: keep the runtime core
and swap the integration backends to use signed API contracts instead of
managed-false ORM models over backend tables.

## Hot Path Requirement

The backend must not proxy high-volume or latency-sensitive runtime traffic.

After a run is started and the sandbox is alive, SDK clients should talk
directly to the sandbox for live interactions. The dashboard/frontend reads the
backend's projected run history unless a separate capability-token flow is
explicitly added later.

- SSE event stream
- HITL responses
- cancellation
- file and artifact operations where appropriate
- MCP/session operations where appropriate

The backend remains in the control path for run creation, wake/resume,
capability token minting, billing, durable state, and reconciliation.

Recommended topology:

```text
SDK/frontend -> backend
  startRun, wakeForRun, dashboard reads, billing, history

SDK -> sandbox
  stream, HITL, cancel, live files, active session operations

sandbox -> backend
  signed lifecycle, usage, artifact, audit, and terminal events
```

This avoids backend stream bottlenecks while preserving backend authority.

## Run Start Flow

The backend owns the run identity and policy decision.

```text
1. SDK calls backend startRun.
2. Backend validates API key/session and workspace ownership.
3. Backend checks end-user controls, wallet, concurrency, tools, knowledge,
   model tier, policy, and requested lease.
4. Backend creates Run in queued state.
5. Backend reserves spend with a BillingHold or equivalent reservation.
6. Backend creates or acquires a SandboxInstance through E2B.
7. Backend sends a signed RunManifest to the sandbox.
8. Sandbox validates the manifest and starts execution.
9. Backend returns sandbox URL plus short-lived capability token.
10. SDK connects directly to sandbox for stream and live operations.
```

The sandbox should not create the backend `Run`. It should execute a
backend-created run ID so all events bind to the backend source of truth.

## Run Manifest

The backend should send a signed, versioned manifest to the sandbox. The
manifest is the sandbox's execution authorization for a single run.

It should include at least:

- manifest version
- run ID
- sandbox instance ID
- workspace ID
- agent ID
- end-user ID
- conversation ID
- prompt or task input
- system prompt and rendered policy block
- lease limits
- allowed tool IDs and resolved tool definitions, or fetch references
- allowed knowledge IDs and resolved knowledge references, or fetch references
- model tier
- callback endpoint and callback authentication metadata
- expiration
- nonce or manifest ID

The sandbox should validate the signature, expiry, sandbox binding, and run ID
before executing.

Large or frequently changing configuration can be fetched from the backend with
a scoped bootstrap token instead of embedded directly in the manifest. The key
rule is that the sandbox should not read backend tables directly.

## Client Capability Tokens

SDK clients should not use backend API keys directly against sandbox live
endpoints.

The backend should mint short-lived sandbox capability JWTs with narrow scopes.

Example claims:

```json
{
  "iss": "midsphere-backend",
  "aud": "midsphere-sandbox",
  "sub": "run_id",
  "sandbox_id": "e2b_sandbox_id",
  "workspace_id": "workspace_id",
  "end_user_id": "end_user_id",
  "conversation_id": "conversation_id",
  "scope": ["stream:read", "hitl:respond", "run:cancel"],
  "exp": 1234567890,
  "iat": 1234567000,
  "jti": "unique-token-id"
}
```

The sandbox validates these locally. That keeps hot-path authorization fast and
removes the need for sandbox-side API-key bcrypt checks or shared DB reads.

The sandbox should enforce:

- token signature
- expiry
- audience and issuer
- `sub` matches the run ID
- `sandbox_id` matches the current sandbox
- scope matches the endpoint
- optional conversation/end-user/workspace claims where relevant

## Sandbox Local Store

The sandbox should use lightweight local durable storage for runtime state.

Good candidates:

- SQLite
- append-only local event log
- file-backed queue
- embedded durable queue behind a storage protocol

Do not rely on pure in-memory state for everything. The sandbox needs local
durability for reconnects, callback retry, pause/resume behavior, and debugging.

Use local storage for:

- SSE replay by sequence number
- local event stream
- HITL pending requests
- callback outbox
- usage checkpoints
- artifact metadata
- run-local state snapshots

Do not use local storage as authority for:

- wallet balance
- credits
- permissions
- allowed tools
- lease limits
- run ownership
- final billing without backend validation

Sandbox-local storage must be treated as untrusted cache. A local attacker who
can modify SQLite can likely modify files, process memory, logs, and outgoing
events. The backend must validate every durable claim from the sandbox.

Recommended sandbox event sequence:

```text
1. append event to local store
2. stream event to connected clients
3. enqueue backend callback
4. retry callback until backend acknowledges
```

## Signed Event Callbacks

The sandbox should send ordered, signed callbacks to the backend for durable
state projection.

Events should include:

- event ID
- run ID
- sandbox ID
- sequence number
- event type
- emitted timestamp
- schema version
- payload
- signature metadata

The backend should:

- verify signature
- verify timestamp freshness
- verify event ID idempotency
- verify run and sandbox binding
- validate schema
- reject sequence regressions or invalid terminal transitions
- project the event into backend state
- acknowledge only after durable write

Callbacks are not the user hot path. They are the durable sync path.

## Event Classes

Do not send every token delta to the backend unless there is a concrete product
requirement for durable token replay.

Suggested split:

- live token deltas: sandbox stream only
- user-visible step/tool/HITL events: sandbox stream and batched backend
  callback so dashboard/history has a durable timeline
- usage checkpoints: backend callback every N seconds or meaningful increment
- artifacts: backend callback with metadata and upload reference
- terminal event: backend callback, high priority, retried until acknowledged

This keeps direct stream latency low and limits backend write volume.

## Billing Model

Billing must not depend on a terminal webhook arriving successfully.

Use reservation semantics:

```text
run start:
  backend checks wallet and creates a hold/reservation

run execution:
  sandbox enforces lease locally and reports usage checkpoints

run terminal:
  sandbox reports final usage
  backend settles actual cost and releases remainder
```

If the sandbox dies or the network fails:

- the hold remains active
- backend reconciler checks E2B state and sandbox liveness
- backend settles from the last trusted usage checkpoint, runtime duration, and
  configured policy
- backend releases unused reservation only after the run is known terminal
- spend can never exceed the reserved amount

The backend is the billing authority. The sandbox reports usage, but the
backend validates it against:

- reserved hold
- lease maximum
- rate card
- event sequence consistency
- known tool/model configuration
- E2B runtime duration
- previous acknowledged checkpoints

If reported usage is impossible or inconsistent, the backend should mark the run
for reconciliation instead of blindly settling.

## Local Development And Debugging

Remote E2B sandboxes cannot call a laptop `localhost` without an ingress path.
That is not a reason to use shared DB in production. Provide explicit dev
modes.

Recommended modes:

1. Local sandbox mode
   - Run backend and sandbox locally.
   - Best for contract tests and fast iteration.

2. Pull mode
   - Backend starts a remote E2B sandbox.
   - Local backend polls sandbox `/events?after=N`.
   - No ngrok required because traffic is outbound from laptop to E2B.

3. Callback relay
   - Sandbox posts callbacks to a public relay.
   - Local backend connects outbound to the relay and receives callbacks.
   - Similar operational model to Stripe CLI.

4. Staging mode
   - Deployed backend URL and real E2B sandbox callbacks.
   - This is the full-fidelity production path.

Debuggability requirements:

- every run has a correlation ID
- manifest ID is logged by backend and sandbox
- callback event IDs are visible in logs
- sequence numbers are visible in stream and backend projection
- sandbox exposes a debug bundle endpoint for authorized internal use
- backend can show last callback, last stream sequence, sandbox state, and hold
  state on run detail/admin pages

## Warm Pool And Wake

The warm-pool idea remains valid with separate DBs.

Backend owns sandbox lifecycle records and E2B operations:

- spawn
- health check
- pause
- resume
- terminate
- reconcile actual E2B state

SDKs may hold a sandbox URL returned by `startRun`. If a direct sandbox request
fails because the sandbox is paused, the SDK should call backend `wakeForRun`.

Flow:

```text
1. SDK direct request fails with connection error or sandbox-paused response.
2. SDK calls backend wakeForRun(runId).
3. Backend resumes or replaces the sandbox.
4. Backend returns current sandbox URL and fresh capability token.
5. SDK retries the original direct sandbox request.
```

## Reconciliation

The backend needs background jobs for:

- queued runs with no sandbox assignment
- running runs beyond lease
- active billing holds with no recent usage
- sandboxes missing in E2B but active in backend DB
- paused sandboxes past cost threshold
- callback sequence gaps
- missing terminal events
- stale HITL requests

The reconciler is what makes the async callback model reliable.

## Sandbox Integration Backends

The existing sandbox modularity should be used, but the custom backends should
target signed contracts rather than shared DB access.

Recommended adaptations:

- billing backend: enforce local lease and report usage; backend settles wallet
- persistence backend: write local runtime events and emit callbacks
- auth backend: validate capability JWTs locally
- toolkit resolver: use manifest or scoped backend fetch, not ORM reads
- artifact backend: write local artifacts and coordinate backend-owned storage
- HITL backend: serve live SDK responses and emit durable state callbacks

Legacy `managed=False` models for old backend tables should not be expanded as
the primary integration mechanism.

## Failure Semantics

The system should be designed around explicit failure behavior:

- callback delayed: user stream unaffected, backend catches up later
- callback lost: sandbox outbox retries with same event ID
- sandbox crashes: backend reconciles from hold, last checkpoint, and E2B state
- backend unavailable: sandbox keeps live stream if possible and retries outbox
- client disconnects: sandbox continues execution and supports stream replay
- local store tampered: backend rejects impossible or unauthorized events
- terminal event duplicated: backend dedupes and ignores duplicate terminal

## Summary

The recommended architecture is:

```text
Backend:
  control plane, source of truth, billing authority

Sandbox:
  data plane, live execution, direct client API

Coupling:
  signed run manifest in
  short-lived capability tokens for clients
  ordered signed callbacks out
  backend reconciliation for failure recovery
```

This keeps the low-latency SDK experience from the existing proposal while
avoiding shared production database coupling between transient E2B runtimes and
backend-owned business tables.
