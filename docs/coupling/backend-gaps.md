# Backend Gaps: What Needs to Be Built

Everything the backend (sukuna-headless) is missing to support the separate-database sandbox integration. The sandbox has its own local runtime store, plus sandbox-local Exo memory storage when needed; all durable business state lives on the backend's Postgres. Integration is via signed RunManifest, capability JWTs, and signed callbacks.

Cross-reference: `schema-alignment.md` for table-level detail, `sandbox-backends.md` for sandbox-side Protocol implementations, `integration-architecture.md` for data flow.

---

## New Django Apps

### 1. `apps/organizations/`

Organization-to-workspace hierarchy. Organizations are the billing and policy boundary; workspaces are project-level resource containers within an org.

**Models:**

- `Organization` -- name, slug, owner, billing_email, suspended_at
- `OrgAgentPolicy` -- blocked_tools, blocked_tool_groups, require_hitl_for (1:1 per org)

**Impact on existing code:**

- `Workspace` gains an `organization` FK (nullable initially for migration, then required)

**Admin:**

- `OrganizationAdmin` -- list display, member count, workspace count, suspend action
- `OrgAgentPolicyAdmin` -- inline JSON editor for blocked tools + HITL rules

**GraphQL:**

```graphql
type Query {
  organization(id: ID!): Organization
}

type Mutation {
  createOrganization(input: CreateOrganizationInput!): MutationResult!
  updateOrganization(id: ID!, input: UpdateOrganizationInput!): MutationResult!
  updateOrgAgentPolicy(orgId: ID!, input: OrgAgentPolicyInput!): MutationResult!
}

type Organization {
  id: ID!
  name: String!
  slug: String!
  workspaces(first: Int, after: String): WorkspaceConnection!
  agentPolicy: OrgAgentPolicy
}
```

---

### 2. `apps/integrations/`

Messaging platform links (Telegram, Slack) that let the sandbox receive and respond to messages from external platforms.

**Models:**

- `TelegramLink` -- user-to-telegram_chat_id binding
- `SlackLink` -- user-to-slack_user_id binding
- `OrgSlackApp` -- org-level Slack bot config (Fernet-encrypted bot_token)

**Admin:**

- Read-mostly admin views. Link/unlink actions. Slack app setup wizard (admin action to configure OAuth).

**GraphQL:**

- `linkTelegram`, `unlinkTelegram`, `linkSlack`, `unlinkSlack` mutations
- `setupSlackApp` mutation (org admin only)
- `integrationStatus` query

---

### 3. `apps/compliance/`

DLP scanning policies and audit logging. Organization-scoped.

**Models:**

- `DLPPolicy` -- org FK, patterns (regex list JSONField), action (mask/block/log), active flag
- `AuditLog` -- immutable append-only trail: event type, actor, resource_type, resource_id, metadata, timestamp

**Admin:**

- `DLPPolicyAdmin` -- JSON editor for scan patterns, test-against-sample action
- `AuditLogAdmin` -- read-only list with filters by action, actor, resource_type, timestamp

**GraphQL:**

- `updateDLPPolicy` mutation (org admin only)
- `auditLog` query (paginated, filtered by action/actor/date range)

---

### 4. `apps/files/`

File storage for workspace-level uploads and conversation attachments.

**Models:**

- `StoredFile` -- workspace FK, name (CharField 255), content_type (CharField 100), size_bytes (BigIntegerField), storage_path (CharField 500 -- S3/Spaces key), uploaded_by FK to User (nullable)
- `ConversationFile` -- conversation FK, stored_file FK

**Admin:**

- `StoredFileAdmin` -- list display with workspace, size, content_type filters

---

## New Models in Existing Apps

### `apps/runs/` -- add:

**`Conversation`**

```
id                    UUIDField, PK
workspace             FK -> Workspace
agent                 FK -> Agent
end_user              FK -> EndUser, nullable
title                 CharField(512), nullable
current_run           FK -> Run, nullable, SET_NULL
requires_user_input   BooleanField, default=False
created_at            DateTimeField, auto_now_add
updated_at            DateTimeField, auto_now
```

**`ConversationPlan`**

```
id                UUIDField, PK
conversation      FK -> Conversation
phases            JSONField, default=list
current_phase_id  CharField(100), blank
sandbox_id        CharField(100), blank
created_at        DateTimeField, auto_now_add
updated_at        DateTimeField, auto_now
```

**`SandboxInstance`**

```
sandbox_id                  CharField, unique (E2B sandbox ID)
workspace                   FK -> Workspace
agent                       FK -> Agent, nullable (pool affinity)
conversation_id             UUIDField, nullable, db_index (conversation affinity)
sandbox_state               CharField(20) -- spawning/booting/paused/running/terminated
sandbox_url                 CharField(500), blank (internal -- never exposed to clients directly, used for Caddy routing reference)
current_run                 FK -> Run, nullable, SET_NULL
last_run_finished_at        DateTimeField, nullable
delayed_termination_at      DateTimeField, nullable
boot_started_at             DateTimeField, nullable
boot_completed_at           DateTimeField, nullable
pause_count                 PositiveIntegerField, default=0
resume_count                PositiveIntegerField, default=0
created_at                  DateTimeField, auto_now_add
updated_at                  DateTimeField, auto_now
```

Indexes: `(agent, sandbox_state)` for pool queries, `(conversation_id)` for affinity lookup, `(sandbox_state, last_run_finished_at)` for idle sweep.

**`RunManifestRecord`**

Stores the manifest metadata and encrypted callback auth needed for callback verification after the manifest is sent. The backend must be able to verify callbacks without re-deriving the manifest.

```
id                        UUIDField, PK
manifest_id               UUIDField, unique (same as the manifest's manifest_id)
run                       FK -> Run, CASCADE
sandbox_id                CharField(100)
signing_key_id            CharField(100)
manifest_hash             CharField(64) (SHA-256 of the signed manifest for audit)
callback_auth_encrypted   BinaryField (Fernet-encrypted per-run HMAC key)
schema_version            PositiveSmallIntegerField
expires_at                DateTimeField
created_at                DateTimeField, auto_now_add
```

The callback ingestion service loads this record by `manifest_id` + `run_id`, decrypts `callback_auth`, and verifies the callback batch signature.

Lifecycle: acquire the sandbox ID, then in one database transaction create the `Run` and `BillingHold`, generate `callback_auth` with a CSPRNG, assemble/sign the manifest, and create `RunManifestRecord` before posting the manifest. Retain records for 30 days after the run reaches a terminal state; a daily cleanup job can delete older records after callback gaps are resolved or manually waived.

**Modify `Run`:**

- Add `conversation` FK -> Conversation (nullable, SET_NULL)
- Add `manifest_id` UUIDField (tracks which manifest was used)
- Add `last_callback_at` DateTimeField (nullable -- last time a callback was received for this run)
- Add `last_projected_sequence` IntegerField (default=0 -- highest **contiguous** callback sequence number projected)

**Modify `RunEvent`:**

- Add `callback_event_id` UUIDField (UNIQUE constraint -- dedup key for callback ingestion)
- Add `batch_id` UUIDField (nullable -- tracks which callback batch delivered this event)

---

### `apps/billing/` -- add:

**`BillingHold`**

```
id                    UUIDField, PK
wallet                FK -> CreditWallet, PROTECT
run                   FK -> Run, CASCADE
amount_reserved_usd   Decimal(12,4)
amount_consumed_usd   Decimal(12,4), default=0
status                CharField(20) -- active/settled/released/expired
settled_at            DateTimeField, nullable
expires_at            DateTimeField
metadata              JSONField, default=dict
created_at            DateTimeField, auto_now_add
updated_at            DateTimeField, auto_now
```

Constraints: `CheckConstraint(amount_reserved_usd >= 0)`, `CheckConstraint(amount_consumed_usd >= 0)`, `CheckConstraint(amount_consumed_usd <= amount_reserved_usd)`.

**`BillingRate`**

```
id                    UUIDField, PK
category              CharField(20) -- tool/model/storage
key                   CharField(100) -- tool name or model ID
cost_per_unit_usd     Decimal(10,4)
unit                  CharField(50) -- call/1k_tokens/MB
markup                Decimal(4,2), default=1.0
is_active             BooleanField, default=True
created_at            DateTimeField, auto_now_add
updated_at            DateTimeField, auto_now
```

**Modify `CreditWallet`:**

- Add `version` IntegerField, default=0 (optimistic locking for concurrent hold creation)

---

## New Services

### `integrations/e2b.py` -- E2B SDK Wrapper

Single file, `lru_cache(maxsize=1)` client factory. The only module that imports the E2B SDK. All sandbox operations go through here. Prefer E2B's async Python client (`AsyncSandbox`). If a pinned SDK version lacks an async method, wrap the sync call with Django's async-safe threadpool boundary in this module only.

```python
def get_e2b_client() -> E2BClient: ...

async def spawn_sandbox(template_id: str, workspace_id: int, metadata: dict) -> SandboxInstance: ...
async def resume_sandbox(sandbox_id: str) -> None: ...
async def pause_sandbox(sandbox_id: str) -> None: ...
async def terminate_sandbox(sandbox_id: str) -> None: ...
async def get_sandbox_url(sandbox_id: str) -> str: ...
async def invoke_run(sandbox_id: str, manifest: SignedManifest) -> RunResponse: ...
async def health_check(sandbox_id: str) -> bool: ...
```

---

### `apps/runs/services/orchestrator.py` -- Run Lifecycle

```python
async def start_run(
    workspace: Workspace,
    agent: Agent,
    end_user: EndUser,
    prompt: str,
    lease_config: LeaseConfig | None = None,
    conversation_id: UUID | None = None,
    is_scheduled: bool = False,
) -> StartRunResult:
    """
    1. Check end_user ControlProfile (credits, run count, concurrency,
       model tier, allowed tools/knowledge)
    2. Check wallet balance >= estimated hold
    3. Acquire sandbox from warm pool (pool.acquire_sandbox)
    4. In one transaction, create/reuse Conversation, create Run
       (status=queued), create BillingHold, generate callback_auth,
       assemble/sign RunManifest, and create RunManifestRecord
    5. RunManifest includes tools, knowledge, policy, system prompt,
       lease, model tier, hitl_mode, callback URL, and callback auth
    6. POST signed manifest to sandbox via E2B SDK
    7. Mint capability JWT for non-scheduled SDK runs
    8. Build sandbox URL: {sandboxId}.run.midsphere.com
    9. Return {run_id, sandbox_url, capability_token, expires_at}

    On failure at step 6:
    - Mark Run failed, error="sandbox_invoke_failed"
    - Release BillingHold
    - Release sandbox back to pool
    """
```

Cancel is NOT here. Cancel goes direct from SDK to sandbox. The backend learns about it via the terminal callback.

---

### `apps/runs/services/manifest.py` -- Manifest Builder

```python
@dataclass(frozen=True)
class ManifestInput:
    run: Run
    agent: Agent
    end_user: EndUser
    conversation: Conversation
    tools: list[ResolvedTool]
    knowledge: list[ResolvedKnowledge]
    policy_block: str
    system_prompt: str
    lease: LeaseConfig
    sandbox_id: str
    callback_url: str
    callback_auth: str
    hitl_mode: Literal["interactive", "auto_deny", "fail_closed"]

def build_manifest(input: ManifestInput) -> dict:
    """Assembles the RunManifest with all resolved config."""

def sign_manifest(manifest_body: dict) -> SignedManifest:
    """Ed25519 signs with MIDSPHERE_MANIFEST_PRIVATE_KEY and signing_key_id."""
```

See `integration-architecture.md` for the full manifest field spec.

---

### `apps/runs/services/capability_token.py` -- JWT Minting

```python
def mint_capability_token(
    run: Run,
    sandbox_id: str,
    workspace_id: int,
    end_user_id: int,
    conversation_id: UUID | None,
    scopes: list[str] = ("stream:read", "hitl:respond", "run:cancel"),
    ttl: int = 1800,
) -> str:
    """
    Mint EdDSA (Ed25519) JWT using MIDSPHERE_JWT_PRIVATE_KEY.
    JWT header includes kid=MIDSPHERE_JWT_KEY_ID.
    Claims: iss, aud, sub=run_id, sandbox_id, workspace_id,
    end_user_id, conversation_id, scope, exp, iat, jti.
    Other scopes (files:rw, mcp:manage) are minted only when the caller
    is authorized for those direct sandbox operations.
    """

def refresh_capability_token(run: Run) -> str:
    """
    Mint a fresh token for an existing run.
    Used when the original expires during long runs/HITL waits.
    """
```

---

### `apps/runs/services/callback_ingestion.py` -- Callback Processing

```python
def ingest_callback_batch(batch: CallbackBatch) -> AckResponse:
    """
    1. Load RunManifestRecord by manifest_id + run_id
    2. Decrypt callback_auth from RunManifestRecord
    3. Verify HMAC signature over full envelope (excluding signature field)
    4. Verify run_id and sandbox_id binding
    5. Dedup on event_id (UNIQUE constraint on RunEvent.callback_event_id)
    6. Reject sequence regressions; detect gaps
    7. Project events into backend state:
       - run_started         -> update Run status
       - step/tool_call/tool_result/hitl_*/artifact -> append RunEvent
       - usage_checkpoint    -> update Run cumulative usage
       - run_completed/failed/cancelled -> settle BillingHold, update Run terminal state
    8. Return { acked_through: highest_contiguous_sequence_no }
       If gap detected, include expected_sequence in response.
    """
```

---

### `apps/runs/services/sandbox_pool.py` -- Pool Management

```python
async def acquire_sandbox(
    agent: Agent,
    conversation_id: UUID | None = None,
) -> SandboxInstance:
    """
    Assignment order:
    1. Conversation affinity check
    2. Agent pool check
    3. Cold start if empty
    """

async def release_sandbox(instance: SandboxInstance) -> None:
    """Pause and return to pool."""

async def resume_sandbox(instance: SandboxInstance) -> SandboxInstance:
    """Resume via E2B SDK, health check."""

async def spawn_sandbox(agent: Agent) -> SandboxInstance:
    """Cold start path."""

async def wake_for_run(run_uid: UUID) -> WakeResult:
    """
    Called by SDK when sandbox is unreachable.
    Resume or replace sandbox, return {sandbox_url, fresh_capability_token}.
    """

async def terminate_sandbox(instance: SandboxInstance) -> None:
    """Kill via E2B SDK, update state."""
```

---

### `apps/runs/services/pool_maintenance.py` -- Background Jobs

```python
async def pre_warm_for_agent(agent: Agent, target: int) -> None: ...
async def pre_warm_pools() -> int: ...
async def sweep_idle_sandboxes() -> int: ...
async def reap_orphan_runs() -> int: ...
async def reap_orphan_hitl() -> int: ...
async def reconcile_sandbox_state() -> int: ...
def compute_target_pool_size(agent: Agent) -> int: ...
async def reconcile_billing_holds() -> int: ...
async def detect_callback_gaps() -> list: ...
async def nightly_reconciliation() -> None: ...
```

---

### `apps/schedules/services/dispatcher.py` -- Schedule Execution

```python
async def dispatch_due_schedules() -> list[DispatchResult]:
    """
    Called every minute by Django tasks / Celery beat.
    Query active schedules where next_run_at <= now,
    call orchestrator.start_run(is_scheduled=True) for each,
    update next_run_at via croniter.
    """
```

---

## Callback Ingestion Endpoint

This is a REST endpoint, not GraphQL. The sandbox POSTs signed callback batches here.

```
POST /webhooks/sandbox/callbacks
Content-Type: application/json
X-Midsphere-Run-Id: {run_id}
X-Midsphere-Manifest-Id: {manifest_id}

Body: CallbackBatch (see schema-alignment.md)

Response: { "acked_through": N, "status": "ok" }
```

- HMAC signature verified over the full envelope (excluding `signature` field) using the per-run callback_auth from RunManifestRecord
- Event IDs deduped with UNIQUE constraint on `RunEvent.callback_event_id`
- One transaction per batch
- Idempotent -- replaying the same batch is safe
- Returns `acked_through` as highest **contiguous** sequence number durably written

---

## GraphQL Surface

### Mutations (runs)

```graphql
type Mutation {
  startRun(input: StartRunInput!): StartRunResult!
  wakeForRun(runId: UUID!): SandboxConnectionResult!
  refreshSandboxToken(runId: UUID!): SandboxConnectionResult!
  runScheduleNow(scheduleId: ID!): MutationResult!
}

input StartRunInput {
  agentId: ID!
  endUserId: ID!
  prompt: String!
  conversationId: UUID
  leaseConfig: LeaseConfigInput
  idempotencyKey: String
}

type StartRunResult {
  success: Boolean!
  errors: [UserError!]!
  runId: UUID
  sandboxUrl: String
  capabilityToken: String
  tokenExpiresAt: DateTime
}

type SandboxConnectionResult {
  success: Boolean!
  errors: [UserError!]!
  sandboxUrl: String
  capabilityToken: String
  tokenExpiresAt: DateTime
  sandboxState: String
}
```

No `cancelRun` or `respondToHitl` mutations. Those go direct to sandbox via capability JWT. The backend learns about them via callbacks.

### Queries (new)

```graphql
type Query {
  conversation(id: UUID!): Conversation
  conversations(workspaceId: ID!, first: Int, after: String): ConversationConnection!
}

type Conversation {
  id: UUID!
  title: String
  currentRun: Run
  requiresUserInput: Boolean!
  runs(first: Int, after: String): RunConnection!
  createdAt: DateTime!
  updatedAt: DateTime!
}
```

---

## Configuration (`config/runtime.py`)

All new env vars to add:

```python
# E2B
E2B_API_KEY: str = ""
E2B_TEMPLATE_ID: str = ""

# Sandbox warm pool
SANDBOX_IDLE_PAUSE_AFTER_SECONDS: int = 120
SANDBOX_IDLE_TERMINATE_AFTER_SECONDS: int = 7200
SANDBOX_MAX_POOL_PER_AGENT: int = 5
SANDBOX_BOOT_TIMEOUT_SECONDS: int = 30
SANDBOX_RESUME_TIMEOUT_SECONDS: int = 10
SANDBOX_RESUME_RETRIES: int = 3

# Manifest signing (asymmetric — backend signs, sandbox verifies with public key)
MIDSPHERE_MANIFEST_KEY_ID: str = ""
MIDSPHERE_MANIFEST_PRIVATE_KEY: str = ""   # Ed25519 private key (PEM or base64)
MIDSPHERE_MANIFEST_PUBLIC_KEYS: dict[str, str] = {}  # kid -> Ed25519 public key
MANIFEST_EXPIRY_SECONDS: int = 300

# Capability JWT (asymmetric — backend signs, sandbox verifies with public key)
MIDSPHERE_JWT_KEY_ID: str = ""
MIDSPHERE_JWT_PRIVATE_KEY: str = ""        # Ed25519 private key (PEM or base64)
MIDSPHERE_JWT_PUBLIC_KEYS: dict[str, str] = {}       # kid -> Ed25519 public key
CAPABILITY_TOKEN_TTL_SECONDS: int = 1800

# Callback ingestion
BACKEND_PUBLIC_URL: str = "https://api.midsphere.com"
CALLBACK_INGESTION_PATH: str = "/webhooks/sandbox/callbacks"
CALLBACK_HMAC_SECRET_LENGTH: int = 32
RUN_MANIFEST_RECORD_RETENTION_DAYS: int = 30

# Caddy / URL masking
SANDBOX_DOMAIN: str = "run.midsphere.com"

# Sandbox connection
SANDBOX_REQUEST_TIMEOUT_SECONDS: int = 30

# Background jobs
SCHEDULE_DISPATCH_INTERVAL_SECONDS: int = 60
POOL_SWEEP_INTERVAL_SECONDS: int = 300
ORPHAN_RUN_REAP_INTERVAL_SECONDS: int = 60
ORPHAN_HITL_REAP_INTERVAL_SECONDS: int = 300
SANDBOX_STATE_RECONCILE_INTERVAL_SECONDS: int = 600
BILLING_HOLD_RECONCILE_INTERVAL_SECONDS: int = 600
CALLBACK_GAP_CHECK_INTERVAL_SECONDS: int = 300
PRE_WARM_POOLS_INTERVAL_SECONDS: int = 300
HITL_ORPHAN_TIMEOUT_SECONDS: int = 1800
NIGHTLY_RECONCILIATION_CRON: str = "0 3 * * *"

# Fernet key (backend-only, for encrypting callback_auth in RunManifestRecord)
FERNET_ENCRYPTION_KEY: str = ""
```

---

## Background Jobs Summary

| Job | Interval | Service | Purpose |
|---|---|---|---|
| `dispatch_due_schedules` | 60s | schedules/dispatcher | Fire scheduled runs |
| `sweep_idle_sandboxes` | 300s | runs/pool_maintenance | Terminate long-idle paused sandboxes |
| `reap_orphan_runs` | 60s | runs/pool_maintenance | Fail queued runs with no sandbox |
| `reap_orphan_hitl` | 300s | runs/pool_maintenance | Auto-deny stale HITL requests |
| `reconcile_sandbox_state` | 600s | runs/pool_maintenance | Sync SandboxInstance with E2B reality |
| `reconcile_billing_holds` | 600s | runs/pool_maintenance | Settle/release holds with no recent activity |
| `detect_callback_gaps` | 300s | runs/pool_maintenance | Flag runs with sequence gaps |
| `pre_warm_pools` | 300s | runs/pool_maintenance | Maintain target pool sizes |
| `nightly_reconciliation` | daily | runs/pool_maintenance | Cross-check holds, ledgers, terminal runs, E2B sandbox count, and callback completeness |

---

## Caddy Infrastructure

Caddy deployment at `*.run.midsphere.com` masks E2B sandbox URLs from clients. See `integration-architecture.md` for the full Caddyfile config, security model, and data flow.

- Deploy 2+ stateless Caddy instances behind a load balancer for HA
- Cloudflare DNS for the `*.run.midsphere.com` wildcard domain
- Caddy handles TLS provisioning via Cloudflare DNS ACME challenge
- No application code -- pure infrastructure (no Redis, no database, no auth logic)

---

## Estimated Scope

| App | New models | Modified models | New services |
|---|---|---|---|
| organizations | 2 | -- | -- |
| integrations | 3 | -- | -- |
| compliance | 2 | -- | -- |
| files | 2 | -- | -- |
| runs | 4 (Conversation, ConversationPlan, SandboxInstance, RunManifestRecord) | 2 (Run, RunEvent) | 6 (orchestrator, manifest, capability_token, callback_ingestion, sandbox_pool, pool_maintenance) |
| billing | 2 (BillingHold, BillingRate) | 1 (CreditWallet) | -- |
| schedules | -- | -- | 1 (dispatcher) |
| integrations (E2B) | -- | -- | 1 (e2b.py) |

Plus the callback ingestion REST endpoint and Caddy infrastructure.
