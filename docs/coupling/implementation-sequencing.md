# Implementation Sequencing

This document defines the order of work between `sukuna-headless` and
`sukuna-sandbox` for the separate-DB contract architecture.

The important point: the sandbox does **not** need to wait for the backend to
be fully implemented. It only needs the contracts to be patched and frozen
enough that both sides can build against them.

## Dependency Rule

Do not start broad sandbox rewiring until the backend maintainer has patched
and frozen the contract docs for:

- run manifest schema
- capability JWT claims, scopes, issuer, audience, signing strategy, and `kid` rotation rules
- callback envelope, event schemas, signature rules, and ack semantics
- normalized event names
- Caddy/E2B sandbox URL shape
- billing ownership and report-only metering semantics
- local dev modes under separate databases
- Exo memory decision (sandbox-local Postgres)

Once those are stable, backend and sandbox implementation can proceed in
parallel.

## Not The Required Sequence

Do not block sandbox work on full backend implementation.

This is the wrong sequence:

```text
backend fully implemented
  -> sandbox starts
```

It creates unnecessary idle time and makes integration risk show up late.

## Correct Sequence

Use this sequence:

```text
1. backend maintainer patches and freezes contracts
2. sandbox starts contract/local-store infrastructure
3. backend builds control-plane implementation
4. both sides integrate against the frozen contracts
5. old shared-DB sandbox paths are removed after the new path works
```

## Phase 0: Contract Freeze

Owner: backend maintainer, with sandbox maintainer review.

Outcome: docs and schema definitions are precise enough for implementation.

Must resolve the concerns in `verification-concerns.md`:

- use asymmetric signing with key IDs/public-key maps so transient sandboxes
  never receive global signing secrets
- verify Caddy/E2B port mapping for sandbox port `8000`
- define safe manifest rejection behavior
- sign the full callback envelope, not only the events array
- define contiguous `acked_through` semantics
- document current sandbox mismatches explicitly
- introduce report-only metering as a new protocol, not a fake billing backend
- define backend storage for callback verification material
- fix local dev wording so sandbox does not point at backend Postgres
- normalize event names or define a translation table
- require capability JWT auth on every direct sandbox endpoint
- document Exo memory backend: sandbox-local Postgres now, SQLiteMemoryStore later if desired

Contract freeze should produce one canonical source for each contract:

- `schema-alignment.md` for manifest/JWT/callback schemas
- `integration-architecture.md` for flow and ownership
- `backend-gaps.md` for backend implementation work
- `sandbox-todo.md` for sandbox implementation work

After freeze, changes to those contracts should be treated as versioned
contract changes, not casual doc edits.

## Phase 1: Sandbox Can Start After Contract Freeze

Owner: sandbox maintainer.

These tasks do not require the live backend to exist yet:

- add Pydantic models for `RunManifest`, capability JWT principal,
  `CallbackBatch`, and callback events
- add manifest signature/expiry/sandbox-binding validation
- add capability JWT validation and scope checks
- add canonical JSON/signature helpers matching the backend docs
- add local runtime store interface
- add SQLite local runtime store implementation
- add callback outbox models and retry state
- add fake callback receiver tests
- add report-only metering protocol
- add manifest toolkit resolver
- add manifest-based run start path behind a setting or separate endpoint

Do not remove legacy shared-DB models or old billing/persistence paths during
this phase. Keep the old path available until the new manifest/callback path is
working end-to-end.

## Phase 2: Backend Builds Control Plane In Parallel

Owner: backend maintainer.

Backend implementation can proceed while sandbox builds contract support:

- E2B SDK wrapper
- `SandboxInstance` model and pool manager
- manifest builder and signer
- callback verification material storage
- capability token minting and refresh
- callback ingestion endpoint
- run projection from callbacks
- backend-created billing holds
- billing settlement from validated terminal usage
- wake/resume flow
- schedule dispatcher integration
- reconciliation jobs

The backend should test these services against fake sandbox responses before
requiring a live sandbox implementation.

## Phase 3: Integration Slice

Owners: backend and sandbox maintainers.

First end-to-end slice:

```text
backend startRun
  -> creates Run and BillingHold
  -> spawns/acquires sandbox
  -> sends signed manifest

sandbox
  -> validates manifest
  -> emits run_started callback
  -> serves direct stream with capability JWT
  -> emits one usage_checkpoint
  -> emits one terminal callback

backend
  -> validates callbacks
  -> projects Run/RunEvent
  -> settles BillingHold
```

This slice should avoid complex tools, artifacts, MCP, and HITL until the basic
manifest/callback/billing loop works.

## Phase 4: Hot Path Features

After the basic integration slice works, add direct hot-path operations:

- HITL response via sandbox
- cancel via sandbox
- file/artifact operations
- MCP management
- token refresh during long runs
- `wakeForRun` retry flow
- stream reconnect and replay from sandbox local store

Each hot-path operation should emit a signed callback for backend durable
projection where product history requires it.

## Phase 5: Cleanup

Only after the separate-DB path is fully working:

- remove sandbox `managed=False` models that point at backend tables
- remove old shared-DB billing hold writes
- remove old backend table persistence sync
- remove raw API-key validation for client-originated sandbox requests
- remove old toolkit resolver paths that query backend tables
- remove backend DB connection requirements from sandbox deployment

Cleanup should be done with targeted tests so the new path remains stable.

## Practical Start Signal

Sandbox work can start when the backend maintainer says:

```text
Contract freeze complete:
- manifest schema frozen
- callback schema frozen
- capability JWT schema frozen
- signing, key rotation, and ack semantics frozen
- Caddy URL shape verified
- metering protocol accepted
```

At that point, the sandbox maintainer can begin `sandbox-todo.md` Phase 1
without waiting for the full backend implementation.

## Summary

The backend maintainer should work immediately on patching/freezing the
contracts and backend control-plane plan.

The sandbox maintainer should start implementation immediately after contract
freeze, beginning with contract models, validation, local store, callback
outbox, and report-only metering.

Backend and sandbox should then proceed in parallel and meet at the first
end-to-end manifest/callback/billing integration slice.
