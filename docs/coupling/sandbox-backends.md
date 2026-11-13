# Sandbox Custom Backends

The sandbox (sukuna-sandbox) uses a Protocol + BackendRegistry pattern for swappable components. This document specifies the custom backend implementations needed in the sandbox codebase so it works with the headless backend's contract model.

The architecture decision is **separate databases, signed contracts**. The sandbox does NOT share the backend's Postgres. It uses local storage (SQLite/append-only log). Integration is via:

- **Signed RunManifest** (backend --> sandbox)
- **Capability JWTs** (backend mints, sandbox validates locally)
- **Signed ordered callbacks** (sandbox --> backend)

Custom implementations are registered via `register_<family>_backend("name", impl, default=True)` or Django settings. Protocol definitions are in `agent_server/backends/` (server-layer) and `tools/core/backends.py` (tool-layer).

---

## 1. RuntimeMeteringBackend

**Replaces:** `LocalCreditBillingBackend` (default `"local_credit"`)
**Protocol:** New `RuntimeMeteringProtocol` — NOT routed through the existing `BillingBackend` protocol. The old protocol is hold/debit/refund oriented and does not model report-only metering. This is a new protocol with a new registration key.
**Registration:** `AGENT_SERVER_METERING_BACKEND = "midsphere_metering"`

### Why

The sandbox must NOT create holds, debit wallets, write ledgers, settle holds, or refund holds. Those are backend responsibilities. The backend creates the BillingHold before execution begins and settles it after the run terminates. The sandbox's only billing job is to classify usage, track it locally, enforce lease limits, and report usage to the backend via signed callbacks.

The existing `BillingBackend` protocol is hold/debit/refund oriented. It assumes methods like `create_hold`, `bill_tool_call`, `settle_hold_for_run`, `refund_hold_for_run`. That protocol does not model the separate-DB architecture cleanly. Rather than faking wallet debits inside the existing protocol, this backend implements a report-only metering abstraction.

### Methods

#### `classify_tool_call(tool_name, arguments, mcp_server_names) -> ToolCallClassification`

Classify a tool invocation into a usage tier (standard, premium, etc.). Uses the same classification logic as the default backend. The classification determines rate-card lookup for cost estimation.

No DB reads. The rate card comes from the RunManifest or is embedded in the backend configuration at sandbox startup.

#### `track_usage(run_id, event_type, usage_delta)`

Accumulate usage into the run's local usage tracker. Tracks:

- input/output tokens by model
- tool call count by tier
- MCP tool call count
- elapsed wall-clock time
- estimated cost (from rate card)

Writes to local runtime store only. No backend interaction.

#### `enforce_lease(run_id) -> LeaseVerdict`

Check cumulative usage against lease limits from the RunManifest:

- `max_cost_usd` -- estimated cost exceeds budget
- `max_total_tokens` -- total tokens exceed cap
- `max_runtime_seconds` -- wall-clock time exceeds limit

Returns `CONTINUE`, `WARN` (approaching limit), or `TERMINATE` (limit exceeded). On `TERMINATE`, the runtime should gracefully stop execution and emit a `run_failed` terminal event with the specific error code: `lease_runtime_exceeded`, `lease_tokens_exceeded`, or `lease_cost_exceeded`. Do not emit `run_cancelled` for lease violations.

No DB reads. Lease limits come from the manifest.

#### `checkpoint_usage(run_id)`

Persist current cumulative usage to local runtime store and enqueue a signed `usage_checkpoint` callback for the backend. Called periodically (every N seconds or on meaningful usage increment).

The checkpoint includes: run_id, cumulative tokens, cumulative estimated cost, tool call counts, elapsed time, sequence number.

#### `emit_terminal_usage(run_id, terminal_status)`

Emit the final usage report as part of the terminal callback (`run_completed`, `run_failed`, `run_cancelled`). This is the last usage the backend receives and uses for hold settlement.

The terminal usage is the authoritative sandbox-side cost report. The backend validates it against the hold, rate card, lease limits, and previous checkpoints before settling.

### Tables Accessed

None in the backend database. Local runtime store only (usage checkpoints, cumulative counters).

---

## 2. CallbackPersistenceBackend

**Replaces:** `DjangoRunPersistenceBackend` (default, in `agent_server/runtime/persistence.py`)
**Protocol:** `RunPersistenceBackend`
**Registration:** via `RunPersistenceDependencies` or `register_persistence_backend("midsphere_callback", ...)`

### Why

The default backend writes to backend-owned `Run`/`RunEvent` tables via `managed=False` models. In the separate-DB architecture, the sandbox stores events locally and sends signed callbacks to the backend. The sandbox never writes to backend tables.

### Methods

#### `persist_event_locally(run_id, sequence_no, event_type, payload) -> EventRecord`

Append the event to the local runtime store (SQLite). Assigns a monotonic sequence number per run. The local store serves SSE replay, debugging, and the callback outbox.

#### `stream_to_clients(run_id, event)`

Push the event to all connected SSE clients for this run. Reads from the in-memory event channel (StateStore). This is the hot path -- it happens immediately after local persistence, before any backend callback.

#### `enqueue_callback(run_id, event_record)`

Add the event to the callback outbox. The outbox is a durable local table with columns for: event_id, run_id, sequence_no, event_type, payload, created_at, acked_at, retry_count.

Non-terminal events are batched. Terminal/lifecycle events are sent immediately.

#### `flush_callback_batch(run_id)`

Send a batch of queued non-terminal callback events to the backend. Called periodically or when the batch reaches a size/time threshold.

Non-terminal event types (batched): `step`, `tool_call`, `tool_result`, `hitl_requested`, `hitl_responded`, `artifact_created`, `usage_checkpoint`.

#### `send_immediate_callback(run_id, event_record)`

Send a single high-priority callback immediately without waiting for batch flush.

Lifecycle/terminal event types (immediate): `run_started`, `run_completed`, `run_failed`, `run_cancelled`.

These are retried until the backend acknowledges them.

### The Callback Outbox Pattern

```
1. append event to local store
2. stream event to connected SSE clients
3. enqueue callback in outbox
4. send batch (non-terminal) or immediate (lifecycle/terminal)
5. mark event as acked only after backend confirms durable write
6. retry unacked events with exponential backoff
```

### Tables Accessed

None in the backend database. Local SQLite only (event store, callback outbox).

---

## 3. CapabilityJwtAuth

**Replaces:** `BearerTokenAuthentication` in `agent_server/auth.py`
**Not a Protocol/Registry backend** -- replaces a Django Ninja auth class.

### Why

The sandbox never validates raw API keys. All client requests (stream, HITL, cancel, files, MCP) carry a capability JWT minted by the backend. The sandbox validates the JWT locally using configured Ed25519 public keys. No database reads needed.

### Validation

The sandbox checks:

- **Key ID:** JWT header `kid` must map to a configured public key in `MIDSPHERE_JWT_PUBLIC_KEYS`.
- **Signature:** EdDSA (Ed25519) using the selected JWT public key. The sandbox never has the private key — it can verify tokens but cannot mint them.
- **Expiry:** reject expired tokens
- **Audience:** `"midsphere-sandbox"`
- **Issuer:** `"midsphere-backend"`
- **Subject:** `sub` must match the `run_id` for the requested endpoint
- **Sandbox binding:** `sandbox_id` claim must match the current sandbox instance
- **Scope:** `scope` claim must include the required scope for the endpoint

No database reads. Just the JWT public-key map from configuration.

### Endpoint Auth Audit

Caddy carries no auth logic — every direct sandbox endpoint must enforce capability JWT validation locally. No endpoint should accept the old static sandbox API key or raw backend API key for client-originated hot-path requests.

Endpoints that must enforce JWT validation:

- `GET /runs/{id}/stream` — `stream:read`
- `POST /runs/{id}/hitl/{request_id}` — `hitl:respond`
- `DELETE /runs/{id}` — `run:cancel`
- `POST /uploads` — `files:rw`
- `GET /files/*`, `PUT /files/*`, `DELETE /files/*` — `files:rw`
- `GET /runs/{id}/mcp`, `POST /runs/{id}/mcp`, `DELETE /runs/{id}/mcp` — `mcp:manage`

No live status, message injection, or branching endpoints are public in this contract. If any are kept later, add concrete paths and scopes here before exposing them through Caddy.

### Scope Mapping

| Sandbox endpoint | Required scope |
|---|---|
| `GET /runs/{id}/stream` | `stream:read` |
| `POST /runs/{id}/hitl/{req}` | `hitl:respond` |
| `DELETE /runs/{id}` | `run:cancel` |
| `GET/POST/DELETE /files/*` | `files:rw` |
| `GET/POST/DELETE /runs/{id}/mcp` | `mcp:manage` |

### Tables Accessed

None. JWT validation is stateless and local.

---

## 4. ManifestToolkitResolver

**Replaces:** `resolve_toolkit_for_run()` in `agent_server/infra/toolkit.py`
**Not a Protocol/Registry backend** -- replaces a function.

### Why

The default toolkit resolver reads from multiple `managed=False` tables (Tool, Knowledge, Policy, Agent, etc.) to assemble the agent's execution context. In the separate-DB architecture, the sandbox has no access to backend tables. Instead, the backend assembles all resolved configuration into the signed RunManifest before sending it to the sandbox.

### Approach

The resolver reads everything from the RunManifest, not from ORM queries:

- **Tool definitions:** resolved tool schemas, endpoints, sensitivity flags, tier classifications
- **Knowledge references:** knowledge base identifiers, kinds, source references
- **Policy block:** rendered content policy and security policy as a text block for system prompt injection
- **System prompt:** the agent's system prompt with policy injected
- **Model tier:** which model class to use for this run

For dynamic MCP server management during a run (`POST /runs/{id}/mcp`), MCP configs remain ephemeral to the run session, managed in-process via StateStore. These are not part of the manifest.

### Tables Accessed

None. All configuration comes from the signed manifest.

---

## 5. Manifest Validation

Not a Protocol/Registry backend -- a new standalone module.

### Purpose

Validates the signed RunManifest at run start, before any execution begins. A malformed, expired, or misbound manifest must be rejected immediately.

### Checks

- **Size:** reject any manifest over 1 MB before execution.
- **Key ID:** `signing_key_id` must map to a configured public key in `MIDSPHERE_MANIFEST_PUBLIC_KEYS`.
- **Ed25519 signature:** verify the manifest body against the signature using the selected manifest public key. The sandbox never has the private key.
- **Expiry:** reject manifests past their expiration timestamp
- **Sandbox binding:** `sandbox_id` in the manifest must match the current sandbox instance ID
- **Run ID:** `run_id` must be present and well-formed
- **Schema version:** the manifest schema version must be supported by this sandbox version
- **Nonce/manifest ID:** present and unique (guards against replay if needed)

### On Failure

**If the manifest is oversized, has an unknown signing key, has an invalid signature, is expired, or is sandbox-misbound:** return a synchronous structured error to the backend via the E2B SDK response. Do not start execution. Do not emit any callback — the `callback_auth` inside the manifest is untrusted unless the signature verifies.

**If the signature is valid but the configuration is unsupported:** emit a `run_failed` callback with `error_code: "manifest_rejected"`. Callback credentials are trusted because the signature was verified.

The backend marks the run failed from the synchronous invoke error when the manifest cannot be trusted.

---

## 6. Callback Outbox Infrastructure

New infrastructure needed in the sandbox. Not a Protocol/Registry backend -- shared infrastructure used by `CallbackPersistenceBackend` and `RuntimeMeteringBackend`.

### Components

**Outbox store (SQLite table):**

| Column | Type | Purpose |
|---|---|---|
| `event_id` | UUID | Unique callback event identifier, used for backend-side dedup |
| `run_id` | UUID | Bound to the run |
| `sequence_no` | integer | Monotonic per run, enforces ordering |
| `event_type` | text | Event classification |
| `payload` | JSON | Event data |
| `created_at` | timestamp | When the event was created |
| `acked_at` | timestamp, nullable | When the backend acknowledged receipt |
| `retry_count` | integer | Number of send attempts |
| `next_retry_at` | timestamp, nullable | Exponential backoff schedule |

**Signing:** Each callback batch is HMAC-signed using the per-run `callback_auth` credentials from the RunManifest. The signature covers the full envelope excluding only the `signature` field: `manifest_id`, `run_id`, `sandbox_id`, `batch_id`, `schema_version`, `sent_at`, and the `events` array. Per-run HMAC is acceptable here — it only authorizes callbacks for that specific run, unlike the global signing keys which use asymmetric cryptography.

**Ordering:** Events are sent in sequence order. The backend rejects sequence regressions. Gaps trigger reconciliation.

**Batching rules:**

- Non-terminal events (`step`, `tool_call`, `tool_result`, `hitl_requested`, `hitl_responded`, `artifact_created`, `usage_checkpoint`): batched, flushed every N seconds or when batch reaches size threshold.
- Lifecycle/terminal events (`run_started`, `run_completed`, `run_failed`, `run_cancelled`): sent immediately, retried until acknowledged.

**Retry:** Exponential backoff with jitter. Max retry count configurable. After max retries, events remain in outbox for reconciliation pickup.

**Ack tracking:** Events are marked acked only after the backend confirms a durable write (HTTP 2xx with ack payload). `acked_through` means the highest contiguous per-run sequence durably written; never mark past a gap. Unacked events are retried.

**Terminal latch:** exactly one of `run_completed`, `run_failed`, or `run_cancelled` may be emitted per run. The persistence layer must make the first terminal transition win and suppress later terminal callbacks for that run.

---

## 7. Local Runtime Store

SQLite or append-only log providing local durable storage for the sandbox runtime. Persists across E2B pause/resume but NOT across sandbox kill/replacement.

### What it stores

| Data | Purpose |
|---|---|
| Run events (by sequence number) | SSE replay for client reconnects |
| Local event stream | Full event history for the run |
| HITL pending requests | In-progress human-in-the-loop state |
| Callback outbox | Durable queue for backend callbacks |
| Usage checkpoints | Cumulative usage snapshots |
| Artifact metadata | Local artifact references |
| Run-local state snapshots | Agent execution state for debugging |

For SSE replay, the event's `sequence_no` is also the SSE `id:` value. A client reconnect with `Last-Event-ID: N` receives stored events for that run with `sequence_no > N`.

### What it is NOT authority for

The local store is untrusted cache. A local attacker who can modify SQLite can likely modify files, process memory, and outgoing events. The backend validates every durable claim.

The local store is never the source of truth for:

- Wallet balance
- Credits
- Permissions
- Allowed tools or knowledge
- Lease limits (these come from the manifest, which is signed)
- Run ownership
- Final billing

---

## Backend Registration Entry Point

All custom backends live in a single module within the sandbox codebase.

### Module layout

```
agent_server/backends/midsphere/
  __init__.py          register_all() — called at startup
  metering.py          RuntimeMeteringBackend
  persistence.py       CallbackPersistenceBackend
  auth.py              CapabilityJwtAuth
  toolkit.py           ManifestToolkitResolver
  manifest.py          ManifestValidator
  outbox.py            CallbackOutbox
```

`register_all()` is called from `agent_server/api/startup.py` -> `init_server()` before any run processing begins.

Django settings approach:

```python
# agent_server/settings/midsphere.py
AGENT_SERVER_METERING_BACKEND = "midsphere_metering"
AGENT_SERVER_PERSISTENCE_BACKEND = "midsphere_callback"

# Asymmetric keys — sandbox only has public keys
MIDSPHERE_MANIFEST_PUBLIC_KEYS = {"2026-05": "..."}   # kid -> Ed25519 public key
MIDSPHERE_JWT_PUBLIC_KEYS = {"2026-05": "..."}        # kid -> Ed25519 public key
```

---

## Backends That Stay Default

These sandbox backends work as-is and don't need custom implementations for the headless integration:

| Backend | Default Implementation | Why It Works |
|---|---|---|
| `StateStore` | `LocalStateStore` | Process-local state (channels, HITL futures, run tasks). No DB interaction. |
| `MemoryStoreBackend` | `PostgresMemoryStoreBackend` | Agent memory store -- uses its own tables, not shared with backend. **Current decision:** provision sandbox-local Postgres for Exo memory so the existing backend can stay default. Do NOT point at the backend's Postgres. A future `SQLiteMemoryStore` can replace this, but SQLite local runtime store and Exo agent memory should remain separate schemas/files unless there is a strong reason to merge them. |
| `TaskBackend` | `LocalAsyncioTaskBackend` or `DjangoTasksBackend` | Background tasks (title generation). In-sandbox only. |
| `FileBackend` | `LocalFileBackend` | In-sandbox file operations. No backend interaction. |
| `ShellBackend` | `LocalShellBackend` | In-sandbox shell execution. No backend interaction. |
| `BrowserBackend` | `PlaywrightBrowserBackend` | In-sandbox browser. No backend interaction. |
| `SearchBackend` | `DefaultSearchBackend` | Web search via external API. No backend interaction. |
| `ArtifactBackend` | `DefaultArtifactBackend` | In-sandbox artifact creation. No backend interaction. |
| `KnowledgeStoreBackend` | `DefaultKnowledgeStoreBackend` | In-sandbox knowledge file storage. No backend interaction. |
| `MediaBackend` | Default (image/video/audio) | Perception tools. No backend interaction. |
| `MobileBackend` | `ExpoMobileBackend` | Expo project management. No backend interaction. |
| `ServerProcessBackend` | `LocalServerProcessBackend` | Dev server management. No backend interaction. |
| `WebProjectBackend` | `LocalWebProjectBackend` | Web project scaffolding. No backend interaction. |
| `ObservabilitySink` | `StructlogObservabilitySink` | Logging. No backend interaction. |

All tool-layer backends are in-sandbox operations and don't touch backend tables.

---

## Models to Remove

All `managed=False` models that pointed to backend tables should be removed from the sandbox codebase. The sandbox no longer reads backend tables. These models were the primary integration mechanism in the shared-DB architecture and are replaced by the signed manifest and callback contracts.

Models to remove include any `managed=False` Django model that referenced backend-owned tables:

- Organization/workspace models (e.g., `DjangoOrganization`, `DjangoWorkspace`)
- Agent/tool/knowledge models (e.g., `DjangoAgent`, `DjangoTool`, `DjangoKnowledge`)
- Policy models (e.g., `DjangoDLPPolicy`, `DjangoOrgAgentPolicy`)
- Billing models (e.g., `DjangoCreditWallet`, `DjangoBillingHold`, `DjangoLedgerEntry`, `DjangoBillingRate`)
- Run models pointing to backend tables (e.g., `DjangoRun` if it referenced backend's `runs_run`)
- End-user/control-profile models (e.g., `DjangoEndUser`, `DjangoControlProfile`)
- Conversation models pointing to backend tables
- Sandbox lifecycle models (e.g., `DjangoE2bSandbox`)
- Audit/DLP models (e.g., `DjangoAuditLog`)

The sandbox retains its own `managed=True` models for local runtime state (events, outbox, usage, HITL state, memory store, etc.).
