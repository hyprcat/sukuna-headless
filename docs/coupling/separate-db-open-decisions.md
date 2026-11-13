# Separate-DB Open Decisions

This note records the current answers to the open architecture questions around
direct sandbox access, separate backend/sandbox databases, billing, HITL,
callbacks, and reconciliation.

There is no V1/V2 framing in this document. These are product semantics unless
explicitly changed later.

## 1. Direct Sandbox Access

SDK clients should call the sandbox directly for hot runtime operations once
the backend has started the run and returned the sandbox connection
descriptor. The dashboard/frontend reads the backend's projected run history
unless a separate capability-token flow is explicitly added later.

Direct sandbox operations include:

- stream events
- HITL responses
- cancellation
- files and artifacts where appropriate
- MCP/session operations where appropriate

The backend remains the control plane for:

- run creation
- wake/resume
- capability token refresh
- billing holds
- durable projection
- dashboard run history reads
- reconciliation

The backend should not proxy live streams or HITL/cancel hot paths.

## 2. HITL Pause, Resume, Kill, And Replacement

HITL state survives E2B pause/resume.

HITL state does not survive sandbox kill/replacement with the current runtime
shape. Current sandbox HITL depends on an in-process `asyncio.Future` tied to
the running agent coroutine. A persisted HITL row alone is not enough to resume
the blocked call stack in a different sandbox.

Product semantics:

- paused/resumed sandbox: HITL continues
- killed/replaced sandbox: pending HITL is lost
- normal idle/cost cleanup must not kill a sandbox with pending HITL
- if the sandbox is gone, the backend terminalizes the run according to policy
- a replacement sandbox starts a new run unless a real durable agent checkpoint
  system exists

Resumable HITL after sandbox replacement requires durable execution
checkpoints, not only persisted HITL request metadata.

## 3. E2B Pause/Resume Durability

E2B documentation says sandbox persistence preserves both filesystem and memory
across pause/resume. It also says killed sandboxes are terminal and cannot be
resumed.

This makes local SQLite/local runtime storage viable across pause/resume, but
not across kill/replacement.

Required validation before relying on it operationally:

```text
1. start sandbox
2. write SQLite event/outbox rows
3. create pending HITL request
4. pause sandbox
5. resume sandbox
6. verify SQLite rows remain
7. verify process/future state remains
8. reconnect SSE and replay events
9. flush callback outbox
```

Sources:

- <https://e2b.dev/docs/sandbox/persistence>
- <https://e2b.dev/docs/sandbox/auto-resume>

## 4. Callback Endpoint Reachability

The sandbox must receive the backend callback endpoint and callback
authentication metadata in the signed run manifest.

Production E2B sandboxes can make outbound HTTP requests, so callbacks to a
deployed backend are viable.

Local laptop backends need explicit dev modes because remote sandboxes cannot
call laptop `localhost` directly:

- local sandbox mode
- pull mode
- callback relay
- staging backend mode

Shared DB is not required to solve local development.

## 5. Billing Hold Ownership

The backend creates the billing hold before sandbox execution starts.

The sandbox must not create holds, debit wallets, write ledgers, settle holds,
or refund holds.

Execution flow:

```text
backend:
  check wallet and controls
  create Run
  create BillingHold/reservation
  send manifest to sandbox

sandbox:
  enforce lease locally
  track usage locally
  emit signed usage checkpoints
  emit signed terminal usage

backend:
  validate usage
  settle hold
  release unused reservation
```

Billing must not depend on a terminal callback arriving successfully. The hold
exists before execution, and reconciliation handles missing or delayed
callbacks.

## 6. Sandbox Billing Protocol Fit

The current sandbox `BillingBackend` protocol is hold/debit/refund oriented.
It assumes methods such as:

- `create_hold`
- `bill_tool_call`
- `settle_hold_for_run`
- `refund_hold_for_run`

That protocol does not cleanly model the separate-DB architecture.

Do not fake wallet debits inside the sandbox.

Instead, add or replace with a report-only metering abstraction:

```text
RuntimeMeteringBackend / UsageReporter
  classify tool/model usage
  track cumulative usage locally
  enforce lease limits
  persist local usage checkpoints
  enqueue signed usage callbacks
  emit terminal usage
```

The legacy billing backend can remain for legacy/shared-DB modes if still
needed, but the headless integration should use report-only metering.

## 7. Manifest Size And Tool Definitions

Embed resolved run configuration in the signed manifest by default.

For typical runs, a manifest containing system prompt, policy block, 15 tool
schemas, knowledge references, and model/lease metadata is small enough to send
as a normal HTTP request body.

Set the manifest size limit to `1MB` and fail clearly if exceeded.

Do not pass large manifests through environment variables.

Fetch-by-reference can be added when manifests become too large, but it adds a
backend round trip and another failure mode. Start with embedded manifests.

## 8. Callback Versus Stream Event Classification

Token deltas should be stream-only unless a product requirement needs durable
token replay.

The following events should be sent to the backend as signed callbacks:

- `run_started`
- `step`
- `tool_call`
- `tool_result`
- `hitl_requested`
- `hitl_responded`
- `artifact_created`
- `usage_checkpoint`
- `run_completed`
- `run_failed`
- `run_cancelled`

Lifecycle and terminal events are high priority and should be retried until
acknowledged.

Step/tool/HITL events should be callbacked so the developer dashboard can show
useful run history. They can be batched to reduce write volume.

## 9. Callback Batching And Outbox

The current sandbox already has:

- per-run event persistence
- sequence numbers
- SSE replay from stored events
- usage flush thresholds

It does not currently have the signed callback batching/outbox needed for the
separate-DB architecture.

Required new infrastructure:

- local callback outbox table/store
- callback event IDs
- HMAC/JWT signing
- ordered sequence handling
- retry with backoff
- durable ack tracking
- batch send for non-terminal events
- immediate send for lifecycle/terminal events

Recommended event flow:

```text
1. append event to local runtime store
2. stream to connected clients
3. enqueue callback event
4. send callback or batch
5. mark acknowledged only after backend durable write
```

## 10. Dashboard Lag

The dashboard reads backend-projected durable state, not live sandbox memory.

That means the dashboard may lag behind the live sandbox by the callback flush
interval. This is acceptable for developer-facing history and monitoring, but
the UI should communicate freshness.

Recommendations:

- project `run_started` immediately
- project terminal events immediately
- batch noisy step/tool events
- expose `last_callback_at`
- expose `last_projected_sequence`
- show a lightweight "last updated" indicator on run detail/list views

The live SDK experience still comes from direct sandbox streaming.

## 11. Token Refresh During Long Runs

Sandbox capability JWTs are short-lived and scoped. Long runs and HITL waits
can outlive the token TTL.

Open SSE connections do not need to be interrupted only because the original
token expires. Reconnects do need a fresh token.

Expose token refresh separately from wake:

```graphql
refreshSandboxToken(runId): SandboxConnectionResult
wakeForRun(runId): SandboxConnectionResult
```

Both should return:

- current sandbox URL
- fresh capability token
- token expiry
- sandbox state

SDK behavior:

- use `refreshSandboxToken` when token is expired or near expiry
- use `wakeForRun` when sandbox direct request fails due to pause/unreachability
- retry the original sandbox request with the fresh connection descriptor

## 12. Reconciliation Scope

Reconciliation is the cost of not sharing the backend database. It is required,
not optional.

Group the work into focused services instead of many unrelated jobs:

- run and hold reconciler
- sandbox lifecycle reconciler
- callback gap/outbox monitor
- HITL timeout reconciler

The backend reconciler should handle:

- queued runs with no sandbox
- running runs beyond lease
- active holds with no recent usage
- missing terminal callbacks
- callback sequence gaps
- sandboxes missing or killed in E2B
- paused sandboxes past policy threshold
- stale HITL requests

## 13. Documentation Impact

If this model is accepted, the existing shared-DB coupling docs need a major
rewrite or supersession notice.

Impacted docs:

- `integration-architecture.md`
- `schema-alignment.md`
- `backend-gaps.md`
- `sandbox-backends.md`

The shared-DB assumptions to remove:

- sandbox `managed=False` models as primary integration
- sandbox writes to backend-owned tables
- sandbox validates backend API keys through backend DB reads
- sandbox billing backend creates/settles/refunds backend holds
- unified backend/sandbox event table

The replacement assumptions:

- backend-created run and hold
- signed run manifest
- direct sandbox hot path
- capability JWTs
- sandbox-local runtime store
- signed ordered callbacks
- backend reconciliation

## Final Architecture Position

Use this ownership boundary:

```text
Backend:
  control plane
  source of truth
  billing authority
  reconciliation owner

Sandbox:
  runtime data plane
  direct client stream/HITL/cancel surface
  local execution state
  local callback outbox

Contract:
  signed manifest in
  scoped capability tokens for clients
  signed ordered callbacks out
```

This preserves the low-latency direct sandbox experience without making
transient E2B runtimes direct clients of backend-owned production tables.
