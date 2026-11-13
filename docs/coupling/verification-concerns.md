# Verification Concerns

This note records issues found while re-reading the current coupling docs
against the existing `sukuna-sandbox` codebase and current E2B documentation.
It is intended as a fix list for the architecture docs before implementation.

Status: resolved in the contract docs. This file is retained as the historical
audit trail explaining why the current contract uses asymmetric signing,
port-prefixed Caddy routing, full-envelope callback signatures, contiguous
acks, and sandbox-local storage.

## 1. Avoid Shared Symmetric Secrets In Sandboxes

Earlier drafts used global symmetric signing material for both manifest
validation and capability JWT validation.

If every sandbox has those secrets, a compromised sandbox could potentially
forge manifests or mint capability JWTs globally.

Recommended change:

- backend signs manifests with a private key
- backend signs capability JWTs with a private key
- sandbox verifies both using a public key or JWKS endpoint/bundled key set
- callback auth remains per-run HMAC because it only authorizes callbacks for
  that run

Per-run callback secrets are acceptable. Global signing secrets inside
transient sandboxes are not.

## 2. Verify Caddy URL Mapping Includes The Sandbox Port

The sandbox starts the agent server on port `8000` in
`sukuna-sandbox/e2b/start_command.sh`.

Earlier drafts described an unprefixed E2B target host:

```text
{sandboxId}.run.midsphere.com -> unprefixed E2B sandbox host
```

E2B's custom-domain documentation shows port-prefixed hosts:

```text
8080-sandboxid.mydomain.com -> 8080-sandboxid.e2b.app
```

The current contract proxies the stable public subdomain to the E2B host for
port `8000`:

```text
{sandboxId}.run.midsphere.com -> 8000-{sandboxId}.e2b.app
```

The docs should not assume an unprefixed E2B host reaches the agent server
unless that has been tested.

Source: <https://e2b.dev/docs/sandbox/custom-domain>

## 3. Manifest Rejection Must Not Use Untrusted Callback Credentials

`schema-alignment.md` says an invalid manifest should fire a `run_failed`
callback with `error_code: "manifest_rejected"`.

That is unsafe for invalid signatures. If the manifest signature is invalid,
the sandbox cannot trust the `callback_auth` inside the manifest.

Recommended rule:

- invalid signature: return synchronous invoke error to backend, emit no
  callback
- expired manifest: return synchronous invoke error, emit no callback unless
  the signature and callback auth were verified first
- wrong sandbox binding: return synchronous invoke error
- valid manifest but runtime rejects supported configuration: callback is
  allowed because callback credentials are trusted

The backend should mark the run failed from the invoke error when the manifest
cannot be trusted.

## 4. Callback Signature Should Cover The Full Envelope

The current callback schema signs only `events`.

That leaves envelope metadata outside the signature:

- `manifest_id`
- `run_id`
- `sandbox_id`
- `batch_id`
- `schema_version`

Recommended change:

Sign canonical JSON of the full callback envelope excluding only the
`signature` field. Also include a `sent_at` timestamp in the signed envelope.

The signed payload should cover:

- `manifest_id`
- `run_id`
- `sandbox_id`
- `batch_id`
- `schema_version`
- `sent_at`
- `events`

## 5. Acknowledgment Semantics Need Contiguous Ordering

`acked_through` is only safe if it means "highest contiguous sequence number
durably written."

If the backend receives events `1` and `3` but not `2`, it must not return:

```json
{ "acked_through": 3 }
```

because the sandbox would mark event `2` acknowledged even though it was never
written.

Recommended rules:

- sequence numbers start at a defined value, preferably `1`
- backend processes events in order
- backend rejects sequence gaps or returns `expected_sequence`
- `acked_through` means highest contiguous durable sequence only
- replayed duplicate events are idempotent by `event_id`

## 6. Current Sandbox Code Does Not Match The New Protocol Yet

This is expected, but the todo/docs should call it out explicitly.

Current sandbox mismatches:

- `StartRunRequest` uses `task`, `model`, `instructions`, `metadata`; it does
  not accept a signed `RunManifest`
- current JWT issuer/audience are `sukuna-backend` /
  `sukuna-sandbox-stream`, while docs use `midsphere-backend` /
  `midsphere-sandbox`
- cancel currently uses `run:admin`; docs use `run:cancel`
- current stream endpoint is `/runs/{id}/stream`; old drafts sometimes used a
  legacy events-path name
- current stream event type is `hitl_request`; docs use `hitl_requested`
- current event sequence starts at `0`; docs say callback sequence starts at
  `1`
- current billing protocol creates/settles/refunds holds
- current persistence still writes `SandboxEvent` and old backend sync paths
- current Exo memory backend defaults to Postgres, not SQLite

The implementation plan should include an explicit compatibility/migration
section for these mismatches.

## 7. RuntimeMeteringBackend Needs A New Protocol

`sandbox-backends.md` says `RuntimeMeteringBackend` replaces
`LocalCreditBillingBackend`, whose protocol is currently hold/debit/refund
oriented.

The separate-DB design needs report-only metering, not fake wallet debits.

Recommended change:

- introduce a new `RuntimeMeteringBackend` or `UsageReporter` protocol
- stop routing headless metering through the old `BillingBackend` protocol
- keep the old billing backend only for legacy/shared-DB modes if still needed

The new protocol should cover:

- classify usage
- track cumulative usage
- enforce lease limits
- write local checkpoints
- enqueue usage callbacks
- emit terminal usage

It should not expose:

- create hold
- debit wallet
- settle hold
- refund hold

## 8. Backend Must Store Callback Verification Material

The backend needs to verify callbacks after sending the manifest.

The docs add `manifest_id` on `Run`, but they do not clearly state where the
backend stores `callback_auth` or the manifest metadata needed for verification.

Recommended backend model or encrypted record:

```text
RunManifestRecord
  manifest_id
  run
  sandbox_id
  manifest_hash
  callback_auth_encrypted
  schema_version
  expires_at
  created_at
```

The callback ingestion service should load this record by `manifest_id` and
`run_id`, decrypt `callback_auth`, verify the signature, then project events.

## 9. Local Development Mode Has A Leftover Shared-DB Assumption

`integration-architecture.md` says local sandbox mode runs backend and sandbox
locally, both talking to local Postgres.

That conflicts with the separate-DB architecture.

Recommended wording:

- backend uses local Postgres
- sandbox uses local SQLite/runtime store
- sandbox may use sandbox-local Postgres only if Exo memory still requires it
- sandbox never points at the backend's Postgres in the separate-DB contract
  model

## 10. E2B Pause/Resume Supports Local Store, But Kill Does Not

E2B docs confirm that pause/resume preserves filesystem and memory, including
running processes and loaded variables. They also state that network clients are
disconnected during pause and must reconnect after resume.

This supports SQLite/local runtime storage across pause/resume.

It does not support recovery after sandbox kill/replacement. Killed sandboxes
are terminal.

Required test before implementation:

```text
1. write SQLite event/outbox rows
2. create pending HITL request
3. pause sandbox
4. resume sandbox
5. verify SQLite rows remain
6. verify process/future state remains
7. reconnect SSE and replay events
8. flush callback outbox
```

Sources:

- <https://e2b.dev/docs/sandbox/persistence>
- <https://e2b.dev/docs/sandbox/auto-resume>

## 11. Callback Event Naming Should Be Normalized

The current sandbox emits `hitl_request`, while the new callback docs use
`hitl_requested`.

Similarly, current stream events and durable callback events may not be the
same exact contract.

Recommended rule:

- define callback event names separately from live stream event names, or
- normalize the sandbox stream event names to the durable callback names

Do not leave the same event concept with different names unless there is an
explicit translation table.

## 12. Caddy Has No Auth Logic, So Sandbox Auth Must Be Complete

The Caddy proxy is intentionally stateless and carries no auth logic. That is
fine, but it means every direct sandbox endpoint must enforce capability JWT
validation locally.

Check all direct endpoints:

- stream
- HITL
- cancel
- file upload/download/update/delete
- MCP management
- live status, message injection, or branching only if later added to the
  scope table with concrete paths

No endpoint should accept the old static sandbox API key or raw backend API key
for client-originated hot-path requests in the separate-DB model.

## 13. Exo Memory Backend Needs A Concrete Decision

The docs mention local SQLite for runtime state, but the current sandbox memory
backend defaults to `PostgresMemoryStoreBackend`.

Resolved decision:

- explicitly provision sandbox-local Postgres for Exo memory so the existing
  `PostgresMemoryStoreBackend` can remain the default
- evaluate Exo `SQLiteMemoryStore` later as a simplification, but keep it
  separate from the runtime event/outbox SQLite store unless there is a strong
  reason to merge them

Do not point `MemoryStoreBackend` at the backend's Postgres.

## Summary

The updated docs are directionally correct:

```text
backend = control plane and billing authority
sandbox = direct runtime data plane
contract = signed manifest + capability JWT + signed callbacks
storage = backend Postgres plus sandbox-local store
```

Before implementation, fix the concerns above so the docs are precise about
secrets, Caddy routing, manifest rejection, callback signing, ack ordering,
current-code mismatches, metering protocol shape, and local development.
