# Contract Schemas: Backend ↔ Sandbox

The backend (Django, `sukuna-headless`) and the sandbox (agent runtime, `sukuna-sandbox`) run in separate processes with **separate databases**. There are no `managed=False` models pointing at the other system's tables. All data exchange happens through four mechanisms:

1. **Run Manifest** — signed execution authorization (backend → sandbox)
2. **Capability JWT** — short-lived token for SDK ↔ sandbox auth (backend → SDK → sandbox)
3. **Callback Events** — signed state projections (sandbox → backend)
4. **Backend Acknowledgment** — durable-write confirmation (backend → sandbox)

---

## 1. Run Manifest

The manifest is the signed, versioned execution authorization the backend sends to the sandbox when starting a run. It contains everything the sandbox needs to execute: prompt, tools, knowledge, lease limits, and callback credentials.

### Schema

```
manifest_version      int           Currently 1.
manifest_id           UUID          Unique per manifest. Used for idempotency and audit.
signing_key_id        str           Key ID for the Ed25519 public key the sandbox must use.
signature             str           Ed25519 signature over the canonical JSON body.
expires_at            datetime      Manifest is rejected after this time.

run_id                UUID          Backend-created. The canonical run identifier across both systems.
sandbox_id            str           E2B sandbox ID. The sandbox rejects manifests not addressed to it.
workspace_id          int           Owning workspace.
agent_id              int           Agent configuration to execute.
end_user_id           int           The developer's end user who initiated the run.
conversation_id       UUID          Groups multi-turn runs into a conversation.

prompt                str           The end user's input.
system_prompt         str           Compiled agent system prompt (includes persona, instructions).
policy_block          str           Rendered policy restrictions injected into the system prompt.

lease:
  max_runtime_seconds int           Hard wall-clock cap.
  max_total_tokens    int           Combined input + output token budget.
  max_cost_usd        Decimal       Dollar ceiling. Sandbox stops when any lease dimension is hit.

model_tier            str           "free", "pro", or "enterprise". Determines which models the sandbox may use.
hitl_mode             str           "interactive", "auto_deny", or "fail_closed".

tools:                list
  - id                int           Backend tool PK.
  - name              str           Display name.
  - description       str           Natural-language description for the agent.
  - parameters_schema dict          JSON Schema for the tool's input.
  - execution_endpoint str          URL the sandbox calls to execute the tool.
  - is_sensitive      bool          If true, tool calls require HITL approval.

knowledge:            list
  - id                int           Backend knowledge PK.
  - name              str           Display name.
  - kind              str           "document", "dataset", or "connected_source".
  - source            str           URL or fetch reference for retrieval.

callback_url          str           Where the sandbox sends callback event batches.
callback_auth         str           Backend-generated per-run HMAC key the sandbox uses to sign callback payloads.
```

### Signing

```
signature = Ed25519.sign(MIDSPHERE_MANIFEST_PRIVATE_KEY, canonical_json(manifest_body))
```

`canonical_json` sorts keys, strips whitespace, and uses deterministic float/decimal encoding. The signature covers the full manifest body excluding the `signature` field itself.

The backend signs with its active private key (`MIDSPHERE_MANIFEST_PRIVATE_KEY`) and includes `signing_key_id` in the signed body. The sandbox selects the verifying public key from `MIDSPHERE_MANIFEST_PUBLIC_KEYS[signing_key_id]`. The sandbox never has a manifest private key — a compromised sandbox cannot forge manifests for other sandboxes. During rotation, sandboxes keep the current and previous public keys until the overlap window expires.

### Constraints

- **Size limit:** 1 MB. If the manifest exceeds this (large tool schemas, many knowledge entries), the backend must fail the `startRun` mutation with a clear error rather than silently truncating. The sandbox must also reject any received manifest over 1 MB synchronously before execution.
- **Callback URL:** The backend constructs an absolute HTTPS URL from the stable public backend origin plus `CALLBACK_INGESTION_PATH`. It must not derive this from an arbitrary request host.
- **HITL mode:** SDK-started runs use `interactive`. Scheduled runs use `auto_deny` or `fail_closed`; they do not wait for live end-user approval.
- **Validation (sandbox side):** The sandbox checks, in order: (1) raw manifest size is at most 1 MB, (2) `signing_key_id` is known, (3) signature is valid (Ed25519 with the selected manifest public key), (4) `expires_at` has not passed, (5) `sandbox_id` matches the current sandbox, (6) `manifest_version` is supported.
- **Rejection rules:**
  - **Invalid signature:** return synchronous error to backend via E2B SDK response. Do not emit any callback — the `callback_auth` inside the manifest is untrusted.
  - **Unknown `signing_key_id`:** return synchronous error. No callback.
  - **Expired manifest:** return synchronous error. No callback.
  - **Wrong sandbox binding:** return synchronous error. No callback.
  - **Oversized manifest:** return synchronous error. No callback.
  - **Valid signature, unsupported configuration:** emit `run_failed` callback with `error_code: "manifest_rejected"` — callback credentials are trusted because the signature was valid.

The backend marks the run failed from the synchronous invoke error when the manifest cannot be trusted.

---

## 2. Capability JWT

A short-lived token minted by the backend, handed to the SDK as part of the `startRun` response or a token-refresh response, and presented by the SDK to the sandbox for streaming and interaction endpoints. The sandbox validates it locally — no callback to the backend required.

### Claims

```json
{
  "iss": "midsphere-backend",
  "aud": "midsphere-sandbox",
  "sub": "<run_id>",
  "sandbox_id": "<e2b_sandbox_id>",
  "workspace_id": "<workspace_id>",
  "end_user_id": "<end_user_id>",
  "conversation_id": "<conversation_id>",
  "scope": ["stream:read", "hitl:respond", "run:cancel", "files:rw", "mcp:manage"],
  "exp": "<unix_timestamp>",
  "iat": "<unix_timestamp>",
  "jti": "<unique_token_id>"
}
```

### Signing and Lifecycle

- **Algorithm:** EdDSA (Ed25519).
- **Header:** JWT header includes `alg: "EdDSA"` and `kid: "<key_id>"`.
- **Keys:** Backend signs with `MIDSPHERE_JWT_PRIVATE_KEY`. Sandbox verifies with `MIDSPHERE_JWT_PUBLIC_KEYS[kid]`. The sandbox never has the private key — a compromised sandbox cannot mint capability JWTs for other sandboxes.
- **TTL:** 30 minutes from `iat`.
- **Scopes:** Tokens are minted with only the scopes the caller is allowed to use. The example above shows the complete current scope vocabulary, not a required minimum for every token.
- **Refresh:** The SDK calls `refreshSandboxToken(runId)` on the backend GraphQL API to get a fresh token before expiry. The backend re-validates that the run is still active and the caller still has access before issuing a new token.

### Sandbox Validation

The sandbox checks, in order:

1. `kid` is present and maps to a configured JWT public key.
2. Signature is valid (Ed25519 with the selected JWT public key).
3. `exp` has not passed.
4. `aud` is `"midsphere-sandbox"`.
5. `iss` is `"midsphere-backend"`.
6. `sub` matches the `run_id` of the endpoint being accessed.
7. `sandbox_id` matches the current sandbox's E2B ID.
8. The request's endpoint requires a scope that is present in `scope`.

### Scope Mapping

| Endpoint | Required scope |
|---|---|
| `GET /runs/{id}/stream` | `stream:read` |
| `POST /runs/{id}/hitl/{request_id}` | `hitl:respond` |
| `DELETE /runs/{id}` | `run:cancel` |
| `POST /uploads` | `files:rw` |
| `GET /files/*`, `PUT /files/*`, `DELETE /files/*` | `files:rw` |
| `GET /runs/{id}/mcp`, `POST /runs/{id}/mcp`, `DELETE /runs/{id}/mcp` | `mcp:manage` |

No other direct sandbox endpoints are public in this contract. If live status, message injection, or branching endpoints remain exposed later, they must be added to this table with explicit scopes before Caddy can route client traffic to them.

---

## 3. Callback Events

Signed HTTP POST callbacks from the sandbox to the backend's `callback_url` (provided in the manifest). These are the mechanism by which the sandbox projects durable state into the backend's database. The backend never polls the sandbox — all state flows through callbacks.

### Batch Envelope

Events are delivered in batches. Each batch is a single HTTP POST:

```json
{
  "manifest_id": "<uuid>",
  "run_id": "<uuid>",
  "sandbox_id": "<str>",
  "batch_id": "<uuid>",
  "schema_version": 1,
  "sent_at": "<ISO8601>",
  "events": [ ... ],
  "signature": "<HMAC-SHA256>"
}
```

The `signature` covers the full envelope (excluding the `signature` field itself), not just the events:

```
HMAC-SHA256(callback_auth, canonical_json({
  manifest_id, run_id, sandbox_id, batch_id,
  schema_version, sent_at, events
}))
```

where `callback_auth` is the per-run HMAC key from the manifest. The backend verifies this before processing any events in the batch. Signing the full envelope prevents metadata tampering (e.g., swapping `run_id` or `sandbox_id` outside the signed boundary).

### Common Event Fields

Every event in the `events` array has these fields:

```json
{
  "event_id": "<uuid>",
  "sequence_no": "<int>",
  "event_type": "<str>",
  "emitted_at": "<ISO8601>",
  "payload": { ... }
}
```

`sequence_no` is a monotonically increasing integer per run, starting at 1. The backend uses it for ordering and acknowledgment.

### Event Types

#### run_started

Emitted once when the sandbox begins executing the run.

```json
{
  "event_id": "uuid",
  "sequence_no": 1,
  "event_type": "run_started",
  "emitted_at": "ISO8601",
  "payload": {
    "model_tier": "pro",
    "sandbox_id": "abc123"
  }
}
```

#### step

Emitted for each reasoning step the agent produces.

```json
{
  "event_id": "uuid",
  "sequence_no": 2,
  "event_type": "step",
  "emitted_at": "ISO8601",
  "payload": {
    "step_index": 0,
    "reasoning": "str",
    "output": "str"
  }
}
```

#### tool_call

Emitted when the agent invokes a tool.

```json
{
  "event_id": "uuid",
  "sequence_no": 3,
  "event_type": "tool_call",
  "emitted_at": "ISO8601",
  "payload": {
    "call_id": "uuid",
    "tool_name": "str",
    "arguments": {},
    "is_mcp": false
  }
}
```

#### tool_result

Emitted when a tool invocation completes.

```json
{
  "event_id": "uuid",
  "sequence_no": 4,
  "event_type": "tool_result",
  "emitted_at": "ISO8601",
  "payload": {
    "call_id": "uuid",
    "tool_name": "str",
    "result": "str or object",
    "error": "str or null",
    "duration_ms": 123
  }
}
```

#### hitl_requested

Emitted when the agent requires human-in-the-loop approval (e.g., for a sensitive tool).

```json
{
  "event_id": "uuid",
  "sequence_no": 5,
  "event_type": "hitl_requested",
  "emitted_at": "ISO8601",
  "payload": {
    "request_id": "uuid",
    "prompt": "str",
    "choices": ["approve", "deny"]
  }
}
```

#### hitl_responded

Emitted when the end user responds to a HITL request (delivered via the capability JWT's `hitl:respond` scope).

```json
{
  "event_id": "uuid",
  "sequence_no": 6,
  "event_type": "hitl_responded",
  "emitted_at": "ISO8601",
  "payload": {
    "request_id": "uuid",
    "response": "approve",
    "responded_at": "ISO8601"
  }
}
```

#### artifact_created

Emitted when the agent produces a file artifact during the run.

```json
{
  "event_id": "uuid",
  "sequence_no": 7,
  "event_type": "artifact_created",
  "emitted_at": "ISO8601",
  "payload": {
    "artifact_id": "uuid",
    "name": "str",
    "content_type": "str",
    "size_bytes": 1234,
    "storage_ref": "str"
  }
}
```

#### usage_checkpoint

Periodic metering snapshot. Emitted at intervals during the run so the backend can track resource consumption and enforce lease limits proactively.

```json
{
  "event_id": "uuid",
  "sequence_no": 8,
  "event_type": "usage_checkpoint",
  "emitted_at": "ISO8601",
  "payload": {
    "runtime_seconds": 45,
    "total_tokens": 12000,
    "cost_usd": "0.0234",
    "tool_calls_count": 5
  }
}
```

#### run_completed

Terminal event. The run finished successfully.

```json
{
  "event_id": "uuid",
  "sequence_no": 15,
  "event_type": "run_completed",
  "emitted_at": "ISO8601",
  "payload": {
    "final_usage": {
      "runtime_seconds": 120,
      "total_tokens": 50000,
      "cost_usd": "0.1500"
    },
    "summary": "str"
  }
}
```

#### run_failed

Terminal event. The run failed due to an error.

```json
{
  "event_id": "uuid",
  "sequence_no": 15,
  "event_type": "run_failed",
  "emitted_at": "ISO8601",
  "payload": {
    "error_code": "lease_runtime_exceeded | lease_tokens_exceeded | lease_cost_exceeded | tool_failed | model_unavailable | manifest_rejected | approval_unavailable | internal_error",
    "message": "str",
    "final_usage": {
      "runtime_seconds": 120,
      "total_tokens": 50000,
      "cost_usd": "0.1500"
    }
  }
}
```

#### run_cancelled

Terminal event. The run was cancelled by the end user or by an inactivity timeout.

**When to use `run_cancelled` vs `run_failed`:** Lease violations (token cap, cost cap, runtime cap) always produce `run_failed` with the appropriate `lease_*` error code — they are enforcement errors, not cancellations. `run_cancelled` is reserved for voluntary cancellation (`user_requested`) or sandbox-level inactivity detection (`timeout`, e.g. no agent activity for N seconds). If in doubt, use `run_failed`.

```json
{
  "event_id": "uuid",
  "sequence_no": 15,
  "event_type": "run_cancelled",
  "emitted_at": "ISO8601",
  "payload": {
    "reason": "user_requested | timeout",
    "final_usage": {
      "runtime_seconds": 60,
      "total_tokens": 20000,
      "cost_usd": "0.0500"
    }
  }
}
```

---

## 4. Backend Acknowledgment

The backend responds to each callback batch with an acknowledgment:

```json
{
  "acked_through": 42,
  "status": "ok"
}
```

`acked_through` is the highest **contiguous** `sequence_no` the backend has durably written to its database. The sandbox marks all events with `sequence_no <= acked_through` as acknowledged in its outbox and stops retrying them.

**Contiguous ordering is critical.** If the backend receives events 1, 2, and 5 but not 3 or 4, it must return `{ "acked_through": 2 }`, not `{ "acked_through": 5 }`. Returning 5 would cause the sandbox to mark events 3 and 4 as acknowledged even though they were never written.

Rules:
- Sequence numbers start at 1 per run.
- Backend processes events in `sequence_no` order.
- `acked_through` means the highest contiguous sequence durably written.
- If a gap is detected, the backend may include `"expected_sequence": N` in the response to help the sandbox identify missing events.
- Replayed duplicate events are idempotent by `event_id`.

If the backend returns a non-2xx status or an `acked_through` lower than expected, the sandbox retains the unacknowledged events in its outbox and retries on the next flush cycle.

---

## 5. Event Delivery Rules

| Event type | Delivery | Retry policy |
|---|---|---|
| `run_started` | Immediate (own batch) | Retried until acked |
| `run_completed`, `run_failed`, `run_cancelled` | Immediate (own batch) | Retried until acked, high priority |
| `step`, `tool_call`, `tool_result` | Batched (flush interval ~5 seconds) | Retried until acked |
| `hitl_requested`, `hitl_responded` | Batched | Retried until acked |
| `artifact_created` | Batched | Retried until acked |
| `usage_checkpoint` | Batched | Retried until acked |
| Token-level deltas | Stream only (SSE to SDK) | **Not callbacked** — ephemeral, not durable |

**Ordering guarantees:** Events within a batch are ordered by `sequence_no`. Sequence numbers are scoped per run. The sandbox never sends a batch containing sequence N+1 before sequence N has been sent (though it may be unacknowledged). The backend processes events in `sequence_no` order and is idempotent on `event_id` — replayed batches after a retry are safe.

**SSE replay mapping:** the sandbox uses the callback `sequence_no` as the SSE `id:` value. SDK reconnects send `Last-Event-ID: <sequence_no>`, and the sandbox replays local events with greater sequence numbers.

**Terminal event rule:** The sandbox always sends `run_completed`, `run_failed`, or `run_cancelled` as the last event. Exactly one terminal event is emitted per run. The sandbox enforces this with a per-run terminal latch: the first terminal transition wins, and later terminal attempts are no-ops or diagnostics, not callbacks. The backend also enforces one terminal projection by state check. The terminal event's `final_usage` is the authoritative usage record for billing.

---

## 6. Removed: Shared Table Mapping

The previous version of this document mapped 32 sandbox `managed=False` Django models to backend PostgreSQL tables, assuming both systems would share a single database. That approach has been replaced entirely.

The sandbox has **no `managed=False` models for backend tables**. It does not read from or write to the backend's database. The two systems communicate exclusively through:

- The **run manifest** (backend tells the sandbox what to execute),
- **Capability JWTs** (backend authorizes SDK connections to the sandbox),
- **Signed callbacks** (sandbox tells the backend what happened), and
- **Acknowledgments** (backend confirms durable receipt).

This separation means either system's database schema can evolve independently, as long as the contract schemas defined in this document are honored. Version negotiation happens via `manifest_version` (manifests) and `schema_version` (callback batches).
