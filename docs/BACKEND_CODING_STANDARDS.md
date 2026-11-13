# Midsphere — Backend Coding Standards

These rules apply to any backend code written for the Midsphere stack — the API behind the product, internal services, jobs, and scripts. They're loaded by `SKILL.md` so an agent working in Claude Code follows them automatically.

The stack is **Django 6 + Strawberry GraphQL**, async-first, with PostgreSQL and Redis. **Django Admin (with `django-unfold`) is the operational source of control.** Background work runs on the **Django tasks framework**; Celery is permitted **only for beat schedules**. These rules assume that baseline.

---

## 1. Maximum performance, minimal memory

Both are defaults, not optimization passes. The API is hot-path code; every request is on someone's critical path, and every long-running worker is sharing a box with others.

### Performance

- **Database is the bottleneck. Treat it that way.** Every endpoint has a query budget. Soft cap: ≤5 queries per request, ≤50ms total DB time at p95. Profile with `django-debug-toolbar` in dev and OpenTelemetry traces in staging.
- **Kill N+1 on sight.** `select_related` for forward FKs/OneToOne, `prefetch_related` for reverse and M2M. Use `Prefetch(...)` with an explicit queryset when filtering inside the prefetch. Configure DataLoaders in Strawberry resolvers so GraphQL nesting doesn't fan out into per-row queries.
- **Only fetch what you render.** `.only()` / `.defer()` / `.values()` when the type doesn't need the full row.
- **Indexes match access patterns.** Every `filter`, `order_by`, and join column has an index. Composite indexes match query order. `EXPLAIN ANALYZE` before merging anything that touches a >100k-row table.
- **Bulk over loops.** `bulk_create`, `bulk_update`, `update()`, `delete()` on querysets. Never `for obj in qs: obj.save()` for >10 rows.
- **Cursor pagination** for any list field that can exceed 1000 rows. Relay-style connections via Strawberry. Offset only for admin-bounded lists.
- **Async where I/O dominates.** Strawberry resolvers are `async def` when they fan out. `asyncio.gather` for parallel awaits — no awaiting in a loop.
- **Connection pooling on.** psycopg 3 pool, sized to actual concurrency. One pool per process.
- **Caching tiers, in order:** request-local memoization → Redis (`cache.get_or_set`) → CDN edge for public reads. Explicit TTLs. Cache keys carry a version segment.
- **Background tasks for anything >100ms** that doesn't block the response. Django tasks framework. Celery for beat schedules only.
- **Latency budget.** p50 <80ms, p95 <200ms, p99 <500ms reads. p95 <400ms writes. Cold start <1s.

### Memory

- **Iterate, don't materialize.** `.iterator(chunk_size=...)` on any queryset that could exceed a few hundred rows.
- **Generators over lists** where the consumer is also iterative. `yield` early.
- **Streaming responses** for large exports — never load a 100MB file into memory to send it.
- **No module-level caches that grow unbounded.** If you cache in a dict, bound it (`functools.lru_cache(maxsize=...)`) or use Redis.
- **Watch the obvious leaks.** `__del__` methods, circular refs holding large objects, listeners/observers without teardown, accumulating logger handlers.
- **`__slots__` on hot in-memory classes.** Pydantic v2 already does this — prefer Pydantic models over plain classes for high-cardinality data.
- **Worker hygiene.** Recycle workers on memory growth (`gunicorn --max-requests` + jitter). Per-worker RSS cap: ≤300MB at p95.

## 2. Maximize shared code

DRY is non-negotiable. **If a piece of logic has any probability of being needed elsewhere — or anything similar is needed — factor it on the first use, not the second.** This is stricter than the frontend rule, deliberately.

- **One source of truth per concept.** A `User`, a `Run`, an `Invoice` is defined once in `models/`, exposed once via the GraphQL schema, validated once via Pydantic at non-GraphQL boundaries. No parallel definitions in different apps.
- **Reusable querysets and managers.** Common filters (`active()`, `for_user(user)`, `with_latest_run()`) live as methods on a custom `Manager` / `QuerySet`. Never copy-pasted.
- **Mixins for cross-cutting model behavior.** `TimestampedModel`, `SoftDeleteModel`, `OwnedModel`, `AuditedModel` — defined once, mixed in everywhere.
- **Shared Pydantic schemas.** Inherit (`Base` → `Create` / `Update` / `Out`). Never redeclare the same fields in three places.
- **Shared exceptions.** `DomainError`, `NotFound`, `PermissionDenied`, `Conflict`, `BillingError` — defined once, mapped to GraphQL `UserError`s by a single resolver-level handler.
- **Wrap third-party clients.** `integrations/dodo_payments.py`, `integrations/openai.py`, `integrations/e2b.py`. Never import a vendor SDK directly into a resolver, model, or task.
- **No dead code.** Every module, helper, service, schema, and admin class must be imported or registered by at least one live code path. When a feature is rewritten and its old modules are no longer referenced, delete them in the same change. Don't leave orphaned files, unused imports, commented-out functions, or vestigial utilities for a future cleanup — the cleanup is now.

### No module-level globals — Pydantic models for every grouped value

Module-level state hides lifecycle, breaks tests that share a process, and ties correctness to import order. The ban covers more than mutable singletons: **bare module-level constants are also out**. A `KEY_PREFIX_LENGTH = 8` next to a `_BEARER_PREFIX = "Bearer "` next to an `API_KEY_SCOPES: Final = frozenset({...})` is three different file-local conventions for the same idea — and none of them are typed, validated, discoverable, or overrideable per environment when an env override is later needed.

**Every grouped collection of values is a frozen `pydantic.BaseModel`.** Configuration, format constants, cost parameters, header names, vocabularies, magic numbers — all of it. Define a model with default-valued fields, instantiate it at the use site (`MyConfig()` is microseconds of work), or accept it as a parameter for dependency injection. The schema is discoverable, the values are typed, and overriding a field per-environment is a one-line change.

```python
# Banned at module level
KEY_PREFIX_LENGTH = 8
SECRET_NAMESPACE = "ms"
_BASE62_ALPHABET = string.digits + string.ascii_letters
API_KEY_SCOPES: Final[frozenset[str]] = frozenset({"runs:read", "runs:write"})

# Required: a frozen Pydantic model that owns the grouped values
class APIKeyFormat(BaseModel):
    model_config = ConfigDict(frozen=True)
    namespace: str = "ms"
    prefix_length: int = 8
    base62_alphabet: str = string.digits + string.ascii_letters

class APIKeyScopes(BaseModel):
    model_config = ConfigDict(frozen=True)
    values: frozenset[str] = frozenset({"runs:read", "runs:write"})
```

For shared client / runtime initialization, reach for these in this order:

1. **Use the library's own module-level singleton if it has one** (e.g. `posthog.api_key = ...`). It's already there; don't shadow it with a parallel one.
2. **`AppConfig.ready()` + `apps.get_app_config(...).attr`** for process-wide state that needs initialization (Sentry, OTel, custom clients). Django apps load once per process; `ready()` is the canonical hook.
3. **`functools.lru_cache(maxsize=1)`** on a parameterless factory function for lazy, cached construction — the cache lives inside the function object, not at module scope.
4. **Pass it in.** If a model method needs a client, accept it as an argument and let the caller resolve it.

**Allowed at module level**, narrowly:

- **Class definitions** — `pydantic.BaseModel` subclasses, `Enum` / `StrEnum` / `IntEnum`, exception classes, Django models, `Protocol`s, Django `TextChoices`. These are *definitions*, not *state*.
- **The pydantic-settings singleton** — `runtime = Runtime()` in `config/runtime.py`. The single, canonical, instantiation point and the only place env vars are read.
- **Logger handles** — `_log = structlog.get_logger(__name__)`, `logger = logging.getLogger(__name__)`. Library-provided, idempotent, free.
- **Library SDK module attributes you didn't write** — `posthog.api_key = ...`, `sentry_sdk.init(...)`'s internal hub. Flagging these would be performative.

**Disallowed at module level**, broadly:

- Bare constants of any kind: `KEY_PREFIX_LENGTH = 8`, `_BEARER_PREFIX = "Bearer "`, `_DEFAULT_SCOPES = ("runs:read",)`. Group them into a `BaseModel`.
- `Final`-tagged frozensets / tuples / `MappingProxyType` lookup tables. These become `BaseModel` fields.
- Module-level dataclass instances or any other named instance besides the four allowed above.
- "Initialized" booleans, lazy-construction flags, mutable caches, accumulator dicts.

`global` keyword is banned outside tests.

## 3. Fat models, thin everything else

The cardinal rule for this codebase: **Django models own their domain logic.** Everything that concerns a `User`, a `Run`, an `Invoice` lives on that model — methods, properties, classmethods, custom manager/queryset queries, invariants, lifecycle. This is the inverse of the "anemic model" pattern, and it's deliberate: domain logic stays next to the data invariants and constraints it depends on, and is discoverable from the model itself.

Services exist **only** for orchestration that genuinely spans multiple aggregates (e.g., "create a workspace, invite users, kick off provisioning"). If logic concerns one model, it lives on that model.

### Layering

- `api/` — Strawberry GraphQL resolvers. Auth check, type conversion, call a model/service method, return. **No ORM access in resolvers.**
- `models/` — Django models with full business logic, custom managers/querysets, `clean()`, computed properties, domain methods, lifecycle hooks. The center of gravity.
- `services/` — Cross-aggregate orchestration only. Each service is a thin coordinator that calls model methods.
- `tasks/` — Background jobs (Django tasks framework). Each task is a thin wrapper over a model/service method.
- `schemas/` — Pydantic schemas for non-GraphQL boundaries: webhook payloads, integration DTOs, task arguments, settings, cache values.
- `admin/` — `django-unfold` `ModelAdmin` configurations. Custom admin actions call model/service methods.

### Size caps — hard limits, enforced in CI

- **Functions and methods: ≤20 lines.** Includes resolvers, view methods, model methods, service functions, task bodies. Over 20, factor.
- **Files: 150–300 lines.** Below 150 means the file is too granular — merge. Over 300 means split.
- **Folders: 6–8 files.** Beyond 8, the folder is two folders. Group by domain, not by file type.
- Lint rules (Ruff `PLR0915`, custom plugin, or pre-commit script) enforce these. Build fails on violation.

### Other rules

- **Pydantic everywhere structured data crosses a boundary.** Settings via `pydantic-settings`, webhook payloads, integration request/response DTOs, task arguments, cache values, config files. Strawberry types are the GraphQL surface; when a payload also exists internally, the Pydantic model is the source of truth and the Strawberry type is generated via `strawberry.experimental.pydantic` or kept in lockstep.
- **No fat resolvers.** A resolver authenticates, calls a model/service method, returns. ≤20 lines, no exceptions.
- **No fat tasks.** Pull args, call a model/service method, log. ≤20 lines.
- **Side effects are explicit.** Models emit domain events via an explicit `record_event(...)` call. Signals are banned for domain logic — they hide control flow. Signals remain fine for framework concerns (`post_migrate`).
- **Transactions at the entry point.** Resolver or task wraps the call in `transaction.atomic()` for any multi-write operation. `select_for_update` where contention matters.
- **Naming.** `snake_case` for functions, modules, fields. `PascalCase` for models, schemas, exceptions, GraphQL types. `SCREAMING_SNAKE` for constants. Files match the primary export.

## 4. Sentry + PostHog + OpenTelemetry + structured logs

Four pillars, all wired before shipping a single endpoint.

- **Sentry** for errors and performance.
  - Init once in `settings.py` with the Django + Strawberry integrations. Environment-aware DSN.
  - Capture unhandled exceptions, slow transactions, slow DB queries.
  - Tag releases with the build SHA. Strip PII in `before_send` / `before_send_transaction`.
  - Sample rates: `traces_sample_rate=0.1` in prod, `1.0` in dev.

- **PostHog** for product analytics, server-side.
  - Identify after auth, never before. Stable user IDs.
  - Event names are `verb_object` snake_case (`agent_run_started`, `invoice_paid`). Properties flat and primitive-typed.
  - Capture from model/service methods, not from resolvers — the domain action is the truth, not the HTTP call.
  - Feature flags read at request start, with a safe default if PostHog is unreachable.

- **OpenTelemetry** is the tracing and metrics backbone — non-negotiable.
  - Auto-instrumentation for Django, Strawberry, psycopg, redis, httpx, the tasks framework. Manual spans on critical model methods (`@traced`).
  - W3C `traceparent` propagated to all outbound calls and into background tasks.
  - Metrics: RED (rate, errors, duration) per resolver; domain counters (`runs_started_total`, `invoices_finalized_total`).
  - Exporter routes to the central observability backend per environment.

- **Structured logging** via `structlog`. Plain-text logs are not acceptable.
  - Every log line carries: `request_id`, `trace_id`, `user_id` (when present), `operation`, `latency_ms`, `status`.
  - Bind context at the request boundary; child loggers inherit.
  - Log levels mean what they say.

- **All four are non-blocking.** A failure in any must not break a request. Wrap init in try/except. Background transports for Sentry and PostHog. OTel batch exporter.
- **Privacy.** PII scrubbed before send in all four. Honor data-residency requirements per environment.

## 5. Security, API contract, admin, and payments — from day one

Cross-cutting concerns wired in from the first commit.

### Security

- **Authentication at the resolver boundary.** Auth directives or `permission_classes` on every field, or a schema-level default. Public fields are explicitly tagged and code-reviewed.
- **Authorization on the model.** Per the fat-model rule, the model knows who can read or mutate it (`obj.can_be_edited_by(user)`). Resolvers call these. Always check ownership — IDOR is the default failure mode if you skip this.
- **Validation at the boundary.** Pydantic for non-GraphQL inputs, Strawberry input types (with custom validators) for GraphQL. No raw dicts into models.
- **OWASP guardrails are non-negotiable.**
  - SQL: ORM only. Raw SQL is parameterized and reviewed.
  - XSS: Django's auto-escape stays on. JSON responses set correct content type.
  - SSRF: outbound HTTP goes through an allowlist or vetted egress proxy. Never fetch user-supplied URLs from a worker.
  - Pickle / `yaml.load` / SSTI: banned. Use `yaml.safe_load`, never `pickle` for untrusted data.
- **Secrets via env**, loaded with `pydantic-settings`. Never in code, never in the repo, never in logs. Rotation policy documented per secret.
- **Rate limiting** on every public field. Per-IP for unauthenticated, per-user for authenticated. GraphQL operation-cost limiting (Strawberry complexity analysis) on top of request-rate limiting.
- **CORS strictly allowlisted.** No `*`. No reflecting `Origin`.
- **Security headers** via `SecurityMiddleware`: HSTS (1y, preload), `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`, real CSP per surface.
- **Dependency scanning.** `pip-audit` in CI fails the build on known CVEs. Lockfile (`uv.lock`) committed.
- **Standard.** OWASP ASVS Level 2 is the bar.

### API contract (GraphQL)

- **The Strawberry schema is the source of truth.** Generated from Python types, exported on every build, diffed in CI.
- **Consistent shape on success and failure — mandatory across every operation.**
  - **Queries** return data; system failures surface as standard GraphQL `errors`.
  - **Mutations** always return a `MutationResult` interface. Concrete result types implement it with the uniform shape:
    ```graphql
    interface MutationResult {
      success: Boolean!
      errors: [UserError!]!
    }
    type UserError { code: String!, field: String, message: String! }
    ```
    Domain failures map to `UserError`s — they're part of the contract, not exceptions. Top-level GraphQL `errors` are reserved for system failures (auth, rate limits, internal errors).
  - **Error codes** are a closed enum, defined once in `errors.py`, used everywhere.
- **Persisted queries** for production clients. Clients send a hash; the server resolves to a registered operation. Saves bandwidth, locks the operation surface against arbitrary queries.
- **Pagination** is Relay-style cursor connections, uniform across all list fields. `first`/`after` for forward, `last`/`before` for backward.
- **Versioning via deprecation.** `@strawberry.field(deprecation_reason=...)` rather than versioned URLs. Deprecated fields stay at least 30 days before removal.
- **Backward compatibility.** Removing a field, narrowing a type, adding required input args — all breaking. Deprecate first, remove later.

### Admin panel — Django Admin with Unfold

**Django Admin with `django-unfold` is the operational source of control.** Not a debugging tool, not an afterthought — it's the primary interface for operators, support, and finance to act on the system.

- **Every business-meaningful model has a configured `ModelAdmin`** — list display, filters, search, inline relations, fieldsets grouped by operational workflow.
- **Custom admin actions for every multi-step domain operation** an operator might need: refund a charge, suspend a workspace, replay a webhook, force a re-sync. Actions call model/service methods — they never reimplement logic.
- **`django-unfold` is the only theme.** No mixing with other admin themes; no hand-rolled overrides that diverge from Unfold's components.
- **Permissions enforced.** Per-model and per-action `has_permission` checks. Admin is not a backdoor — staff status is not a free pass.
- **Audit log** of every mutation through admin via `django-simple-history` or equivalent. Who, what, when, before/after.
- **Exports** (CSV/JSON) on every list view that operators need to pull from.
- **No raw SQL in admin actions.** Everything routes through model methods, which means everything is testable.
- **Readonly in production for sensitive models** unless an explicit operational role is required to mutate.

### Payments and billing

This is the highest-risk surface in the codebase. **Triple-check every change. Read the provider's integration guide end-to-end before writing the first line, and follow their recommendations literally — their tips are production scars.**

- **Idempotency keys on every charge, refund, subscription mutation.** No exceptions. Stored with the provider's idempotency-key header and our internal request ID.
- **Webhook signature verification** required. Reject unsigned, expired, or malformed webhooks at the edge.
- **Webhooks processed exactly once.** Dedup on event ID at the persistence layer with a `UNIQUE` constraint, not in-memory.
- **Reconciliation jobs** run nightly. Compare local state against the provider's source of truth. Alert on drift; automate nothing about resolution until a human has signed off on the playbook.
- **Money is `Decimal`, never `float`.** Currency code stored alongside every amount. No arithmetic across currencies without an explicit FX step.
- **Tax handled by the provider.** Dodo Payments is a Merchant of Record — tax collection, remittance, and compliance sit with them, not us. Never roll your own jurisdictions.
- **PCI scope minimized.** Card data never touches our servers — tokenization client-side, vault refs only on our side. SAQ A is the target.
- **Compliance.** PCI DSS via the provider's attestation. SOC 2 controls (access logging, change management) on every billing path. GDPR delete/export honors billing record retention rules per jurisdiction.
- **Edge cases that always need explicit handling and tests:** failed payment with active subscription (dunning), partial refunds, currency conversion, prorations on plan change, trials ending mid-cycle, deleted users with outstanding invoices, disputed charges (chargebacks), retries after 5xx from provider, clock drift on subscription billing dates, double-spend prevention on retried mutations, idempotency-key collisions, webhook delivery races (state changes arriving out of order).
- **Test mode parity.** Every billing path has automated tests against the provider's test mode. Recorded test mode runs are part of the PR.
- **Two-person review** on every PR that touches billing code. No exceptions, including for typos.

## 6. Don't reinvent the wheel

Lean on the ecosystem when something is genuinely solved. Writing your own queue, OAuth flow, admin theme, or migration tool is a tax, not a feature.

- **Reach for proven libraries** when the problem is hard, well-defined, and not differentiating: GraphQL (`strawberry-graphql` + `strawberry-django`), background work (Django tasks framework, with Celery beat for scheduling), admin theme (`django-unfold`), schemas/settings (`pydantic` v2, `pydantic-settings`), structured logs (`structlog`), tracing (`opentelemetry-distro` + instrumentations), HTTP client (`httpx` + `tenacity` for retries), auth (`django-allauth` for social, `django-otp` for 2FA), CORS (`django-cors-headers`), rate limiting (`django-ratelimit`), storage (`django-storages`), audit (`django-simple-history`), testing (`pytest-django`, `factory_boy`, `freezegun`, `respx`), search (Postgres FTS first, then Meilisearch/Typesense), feature flags (PostHog, already in §4).
- **Vetting checklist before adopting.** Active maintenance (commits in the last 6 months). Compatible with Django 6 and Python 3.13+. Reasonable footprint. Typed. License compatible (MIT/Apache/BSD/PSF). No GPL without legal sign-off.
- **Tension with §1.** Performance and memory still win. Justify every dep against the budget.
- **Do not depend on tiny utilities.** Write the four lines.
- **Wrap third-party clients.** Per §2.
- **Pin and audit.** Lockfile committed. `pip-audit` clean before merge.

---

## Stack defaults

When building inside this system:

- **Python 3.13+.** Type hints everywhere — `from __future__ import annotations` at the top of every module.
- **Django 6 + Strawberry GraphQL (with strawberry-django).** Async resolvers by default for I/O-bound fields.
- **PostgreSQL 16+.** psycopg 3 with binary extras and the built-in pool. No SQLite outside tests.
- **Redis 7+** for cache, rate-limit counters, idempotency keys.
- **Background work: Django 6 tasks framework.** Celery is permitted **only for beat schedules** — periodic triggers that enqueue tasks framework jobs.
- **Admin: Django Admin + `django-unfold`.** Mandatory theme, no alternatives.
- **Pydantic v2** everywhere structured data crosses a boundary (settings, webhooks, integrations, task args, cache values). `pydantic-settings` for config.
- **uv** for dependency management. `uv.lock` committed.
- **Ruff** for lint and format, with custom rules enforcing the 20-line / 150–300-line / 6–8-file caps. Pre-commit hook blocks unformatted or oversized code.
- **mypy** in strict mode on `models/` and `services/`. Type hints required everywhere; `Any` only with a `# type: ignore[reason]` comment.
- **pytest + pytest-django** for tests. `factory_boy` for fixtures, `freezegun` for time, `respx` for HTTP. Coverage gate ≥85% on `models/` and `services/`, 100% on billing paths.
- **Migrations.** One schema change per migration. Zero-downtime patterns: add nullable → backfill → enforce → drop. Never edit a merged migration. `RunPython` operations are reversible.
- **Settings split.** `settings/base.py`, `settings/dev.py`, `settings/prod.py`, `settings/test.py`. No `if DEBUG` branches in app code.
- **CI gates.** Ruff (incl. size caps), mypy, pytest, `pip-audit`, `manage.py makemigrations --check`, GraphQL schema diff, billing-path coverage check. All green before merge.