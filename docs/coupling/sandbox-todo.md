# Sandbox TODO: Separate-DB Contract Model

Handoff document for the `sukuna-sandbox` maintainer. This is your complete
work spec for the separate-DB contract integration with the headless backend.

## Start Signal

You can begin implementation once the backend maintainer confirms **contract
freeze** — the schemas for manifests, JWTs, callbacks, and ack semantics are
stable enough to build against. You do NOT need the backend to be fully
implemented. Both sides build in parallel and meet at the first end-to-end
integration slice. See `implementation-sequencing.md` for the full sequencing
model.

## Reference Documents

Read these before starting — they are your contract specifications:

| Document | What it tells you |
|---|---|
| `schema-alignment.md` | Full schemas for RunManifest, Capability JWT, callback events, ack format. JSON examples for every event type. |
| `integration-architecture.md` | Data flow diagrams (startRun, HITL, cancel, scheduled run), warm pool lifecycle, connection resilience, security model, Caddy config. |
| `sandbox-backends.md` | Detailed specs for each custom backend you need to implement: RuntimeMeteringBackend, CallbackPersistenceBackend, CapabilityJwtAuth, ManifestToolkitResolver, ManifestValidator, callback outbox, local runtime store. |
| `backend-gaps.md` | What the backend is building — so you know what it will send you (manifests) and what it expects from you (callbacks). |
| `verification-concerns.md` | Issues found during review. All resolved in the docs above. Read for context on why certain decisions were made. |
| `implementation-sequencing.md` | Sequencing rules — when you can start, what to do in parallel, where the integration slice happens. |
| `separate-db-sandbox-contracts.md` | Your original proposal that led to this architecture. Reference only. |

## Key Architecture Decisions

- **Asymmetric signing**: backend signs manifests and JWTs with Ed25519 private
  keys. Sandbox verifies with public-key maps keyed by `signing_key_id`
  (manifest) or JWT `kid`. You cannot forge manifests or mint tokens.
  Per-run callback HMAC stays symmetric (acceptable scope).
- **Callback signature covers full envelope**: sign everything except the
  `signature` field — not just the events array.
- **`acked_through` is contiguous**: backend returns highest contiguous sequence
  durably written. Never acks past a gap.
- **Manifest rejection**: if size/key lookup/signature/expiry/binding fails,
  return synchronous error — do NOT use callback credentials from untrusted
  manifests.
- **Caddy port mapping**: `{sandboxId}.run.midsphere.com` →
  `8000-{sandboxId}.e2b.app` (port-prefixed per E2B custom domain format).
- **Report-only metering**: new `RuntimeMeteringBackend` protocol — not routed
  through old `BillingBackend`. No wallet writes.
- **Exo memory**: use sandbox-local Postgres for the existing
  `PostgresMemoryStoreBackend`, NOT the backend's Postgres. A future
  SQLiteMemoryStore can replace it.
- **Scheduled HITL**: scheduled manifests use `hitl_mode=auto_deny` or
  `hitl_mode=fail_closed`; they never wait for a live SDK response.

## Phases

Ordered by dependency — complete each phase before starting the next.

---

## Phase 1: Contract Infrastructure (Foundation)

Everything else depends on these pieces. They replace the shared-DB
authentication and configuration paths with signed, self-contained contracts.

- [ ] **ManifestValidator module** -- validate signed RunManifest at run start.
  Check: manifest size <= 1MB, `signing_key_id` maps to
  `MIDSPHERE_MANIFEST_PUBLIC_KEYS`, Ed25519 signature, expiry, `sandbox_id`
  matches current sandbox, `run_id` present, schema version supported.
  Rejection rules: if size/key lookup/signature/expiry/binding fails, return
  synchronous error to backend — do NOT emit a callback (the `callback_auth`
  inside the manifest is untrusted). If signature is valid but configuration is
  unsupported, emit `run_failed` callback with `error_code:
  "manifest_rejected"` (credentials are trusted).

- [ ] **CapabilityJwtAuth** -- replace `BearerTokenAuthentication` with JWT
  validation. Validate: JWT header `kid` maps to `MIDSPHERE_JWT_PUBLIC_KEYS`,
  EdDSA (Ed25519) signature using that public key (sandbox never has private
  key), expiry, audience (`midsphere-sandbox`), issuer
  (`midsphere-backend`), `sub` matches run_id, `sandbox_id` matches current
  sandbox, scope matches endpoint. No DB reads needed. Must be enforced on
  every direct sandbox endpoint: stream, HITL, cancel, file upload/download,
  MCP management. No other direct endpoint is public in this contract unless
  it is added to the scope table first.

- [ ] **ManifestToolkitResolver** -- replace `resolve_toolkit_for_run()`. Read
  tool definitions, knowledge references, policy block, system prompt, and model
  tier from the RunManifest instead of ORM queries against backend tables.

- [ ] **Run start endpoint update** -- accept a signed RunManifest instead of a
  bare request + API key. Validate manifest, then proceed with existing
  execution flow using manifest-provided config.

---

## Phase 2: Local Store + Metering (Runtime Data Plane)

Local durable storage and usage reporting. The sandbox becomes self-sufficient
for runtime state -- no writes to backend-owned tables.

- [ ] **Local runtime store** -- SQLite database (or append-only log) for
  sandbox-local state. Tables/stores for: events (SSE replay), callback outbox,
  usage checkpoints, HITL pending requests, artifact metadata, run-local state
  snapshots. SSE `id:` must equal the per-run `sequence_no` so
  `Last-Event-ID` replay is exact. Verify SQLite durability across E2B
  `pause()` / `resume()` cycles.

- [ ] **RuntimeMeteringBackend** -- replace `LocalCreditBillingBackend` with a
  report-only metering abstraction. Methods: classify tool/model usage, track
  cumulative usage locally, enforce lease limits (max_cost_usd, max_total_tokens,
  max_runtime_seconds), persist local usage checkpoints, emit usage data for
  callbacks. Must NOT create holds, debit wallets, write ledgers, settle, or
  refund. The backend is the billing authority.

- [ ] **Usage checkpoint emission** -- periodically (every N seconds or on
  meaningful usage increment) write a usage checkpoint to local store and mark
  for callback delivery.

---

## Phase 3: Callback System (Durable Sync)

The mechanism for sandbox -> backend state synchronization. The backend projects
durable run state from these callbacks.

- [ ] **Callback outbox table** -- local SQLite table: event_id (UUID), run_id,
  sequence_no, event_type, payload (JSON), emitted_at, callback_status
  (pending/sent/acked), acked_at, retry_count, next_retry_at.

- [ ] **Callback signing** -- HMAC-SHA256 sign each callback batch using the
  per-run `callback_auth` key from the RunManifest. The signature must cover
  the **full envelope** excluding only the `signature` field: manifest_id,
  run_id, sandbox_id, batch_id, schema_version, sent_at, and the events
  array. Do not sign only the events — envelope metadata must be inside the
  signed boundary to prevent tampering.

- [ ] **Callback sender** -- async task that: batches non-terminal events (step,
  tool_call, tool_result, hitl_*, artifact, usage_checkpoint) with a flush
  interval (~5s), sends lifecycle/terminal events immediately (run_started,
  run_completed, run_failed, run_cancelled), retries with exponential backoff on
  failure, marks events as acked only after backend returns acknowledgment with
  `acked_through` sequence number. `acked_through` is the highest contiguous
  per-run sequence durably written, so never mark events past a gap as acked.
  Enforce a per-run terminal latch so only one terminal event is emitted.

- [ ] **CallbackPersistenceBackend** -- replace `DjangoRunPersistenceBackend`.
  Instead of writing to backend-owned Run/RunEvent tables, this backend: appends
  events to local store, streams to connected SSE clients, enqueues events in
  callback outbox. The backend projects durable state from callbacks.

---

## Phase 4: Cleanup (Remove Shared-DB Artifacts)

Remove everything that assumed shared database access. Only do this after
Phases 1-3 are working -- the old paths are the fallback until then.

- [ ] **Remove all `managed=False` models** that pointed to backend tables:
  DjangoOrganization, DjangoWorkspace, DjangoAgent, DjangoTool,
  DjangoKnowledge, DjangoPolicy, DjangoEndUser, DjangoControlProfile,
  DjangoApiKey, DjangoAuthToken, DjangoCreditWallet, DjangoLedgerEntry,
  DjangoBillingHold, DjangoRun, DjangoRunEvent, and any others. The sandbox no
  longer reads backend tables.

- [ ] **Remove `MidsphereUsdBillingBackend`** (if implemented) -- replaced by
  RuntimeMeteringBackend.

- [ ] **Remove `MidsphereRunPersistenceBackend`** (if implemented) -- replaced
  by CallbackPersistenceBackend.

- [ ] **Remove `MidsphereApiKeyAuth` / `MidsphereHmacAuth`** (if implemented)
  -- replaced by CapabilityJwtAuth.

- [ ] **Remove `MidsphereToolkitResolver`** (if implemented) -- replaced by
  ManifestToolkitResolver.

- [ ] **Remove any backend DB connection config** -- the sandbox should not have
  `DATABASE_URL` pointing to the backend's Postgres. It uses its own local
  SQLite for runtime state. (Note: if MemoryStoreBackend needs Postgres, it
  should use a sandbox-local Postgres instance, not the backend's.)

---

## Phase 5: Configuration

- [ ] **Add settings for contract validation:**
  - `MIDSPHERE_MANIFEST_PUBLIC_KEYS` -- map of key ID to Ed25519 public key for
    manifest signature verification (private keys stay on backend only)
  - `MIDSPHERE_JWT_PUBLIC_KEYS` -- map of key ID to Ed25519 public key for
    capability JWT verification (private keys stay on backend only)
  - `CALLBACK_FLUSH_INTERVAL_SECONDS` -- how often to batch non-terminal
    callbacks (default: 5)
  - `CALLBACK_MAX_RETRIES` -- max retry attempts for failed callbacks
    (default: 10)
  - `CALLBACK_RETRY_BACKOFF_BASE` -- exponential backoff base in seconds
    (default: 2)

---

## Phase 6: Compatibility Migration

The current sandbox codebase has mismatches with the new contract protocol.
Address these explicitly during implementation:

- [ ] **StartRunRequest** -- currently uses `task`, `model`, `instructions`,
  `metadata`; must be replaced with signed `RunManifest` acceptance
- [ ] **JWT issuer/audience** -- currently `sukuna-backend` /
  `sukuna-sandbox-stream`; change to `midsphere-backend` / `midsphere-sandbox`
- [ ] **Cancel scope** -- currently `run:admin`; change to `run:cancel`
- [ ] **Stream endpoint name** -- verify consistency: use `/runs/{id}/stream`
  (not `/runs/{id}/events`) throughout
- [ ] **Event type names** -- current `hitl_request` must become
  `hitl_requested`; audit all event type names against the callback contract
  in `schema-alignment.md` and normalize
- [ ] **Sequence numbering** -- current events start at `0`; callback contract
  starts at `1`. Align to `1`.
- [ ] **Billing protocol** -- current backend creates/settles/refunds holds via
  shared protocol; replace with `RuntimeMeteringBackend` (report-only)
- [ ] **Persistence backend** -- current `SandboxEvent` and backend sync paths
  must be replaced with `CallbackPersistenceBackend`
- [ ] **Memory backend** -- current default is `PostgresMemoryStoreBackend`
  pointing at shared Postgres; provision sandbox-local Postgres and
  point the memory backend there. Do not point it at backend Postgres.

---

## Notes

- **E2B filesystem durability:** confirmed that E2B preserves filesystem and
  process memory across `pause()` / `resume()`. Network clients are
  disconnected during pause and must reconnect after resume. Killed sandboxes
  lose local state -- backend reconciler handles this.

- **Required verification test before relying on pause/resume:**
  1. Write SQLite event/outbox rows
  2. Create pending HITL request (asyncio.Future)
  3. Pause sandbox
  4. Resume sandbox
  5. Verify SQLite rows remain intact
  6. Verify process/Future state remains
  7. Reconnect SSE and replay events
  8. Flush callback outbox successfully

- **MemoryStoreBackend:** use a sandbox-local Postgres instance for Exo
  memory, NOT the backend's Postgres. SQLiteMemoryStore remains a future
  simplification option.

- **Backends that stay default:** StateStore, TaskBackend, FileBackend,
  ShellBackend, BrowserBackend, SearchBackend, ArtifactBackend,
  KnowledgeStoreBackend, MediaBackend, MobileBackend, ServerProcessBackend,
  WebProjectBackend, ObservabilitySink -- all in-sandbox, no backend
  interaction.

- **Manifest size:** backend embeds all resolved config (tools, knowledge,
  policy). Conservative limit 1MB. Backend must fail `startRun` if exceeded;
  sandbox must reject oversized manifests synchronously with no callback.

- **HITL semantics:** HITL state survives E2B pause/resume (in-process
  asyncio.Future preserved). Does NOT survive sandbox kill/replacement. Idle
  cleanup must not kill sandboxes with pending HITL.
