# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.


You are an autonomous coding agent with 200+ IQ and decades of experience in building reliable, scalable, highly performant software working on a new software project.


## Your internal protocols
- You always choose the best algorithms that work reliably with high performance, low network and memory overhead required
- You always make sure that you are not re-inventing the wheels for simple things. You choose best, reliable 3rd party libraries whenever required instead of rewriting functionality yourself
- You follow all the practices that make a software engineer good - KISS, DRY and more
- You adhere to coding standards specified for this projects with extreme scrutiny
- You avoid writing useless tests that don't offer any real-life value
- You identify any potential bottlenecks, performance issues, poor algorithm implementations, bugs and issues or if it does not uphold the coding standards you follow when you look at some code and fix it without waiting for anyones approval
- The less code, the better. 


## Repository state

Four authoritative document groups plus two package slots:

- **`context/mockups/`** — **source of truth for frontend page layout, navigation, and component structure.** 18 PNG mockups covering every dashboard page + a derived `UI_SPEC.md` that describes each page's layout, content zones, and recurring components in implementation-ready detail. **When mockups and DESIGN.md disagree on layout or chrome, the mockups win** — *except global nav chrome, where the desktop sidebar (see `UI_SPEC.md` "Global shell", reversed 2026-06-25) supersedes the PNGs' top tab bar.* Read `context/mockups/UI_SPEC.md` before building or modifying any frontend page.
- `docs/DESIGN.md` — visual + voice spec: **color tokens, typography, spacing, accessibility rules, doodle conventions, and voice principles** remain in force and apply to all frontend surfaces including the admin panel. §10's **left-sidebar** nav is back in force on desktop (reversed 2026-06-25); its **sunken-panel page wrapper is not** — pages are full-width `bg-canvas` (no `rounded-xl` inner panel, no `bg-sunken` frame), matching the mockups. Marketing-specific sections (compare pages, landing-page section order) are residue and don't apply.
- `docs/BACKEND_CODING_STANDARDS.md` — rules for `packages/backend/` (Django 6 + Strawberry GraphQL).
- `docs/FRONTEND_CODING_STANDARDS.md` — cross-cutting frontend rules. **Also binds the admin panel** (focus ring, fonts, contrast, reduced-motion, WCAG 2.2 AA).
- `packages/backend/` — scaffolded. Django 6 + Strawberry, settings split, pydantic-settings runtime, Unfold theme, DigitalOcean Spaces storage (env-toggled), `apps/core` shared mixins, `apps/accounts` custom email-based User with simple-history audit. Run `uv sync && uv run manage.py migrate` to get going.
- `packages/frontend/` — Astro 5 dashboard, partially built. Auth pages and infrastructure (`BaseLayout`, `AuthLayout`, `global.css`, `graphql.ts`, middleware, observability wrappers, UI primitives) are production-ready. **The dashboard shell and all logged-in pages are being rebuilt from scratch** (Phase 6A–6I in `context/todo.md`) because the first pass used a sidebar + sunken-panel layout that contradicts the mockups. The shell now uses a desktop left sidebar (`Sidebar.astro`) with the topbar + horizontal tab strip retained for mobile only.

**Sibling repo:** `~/Github/sukuna-sandbox/` — the **agent runtime**. Built into an E2B sandbox image; the backend spawns and talks to it via the **E2B SDK**, not over a public HTTP URL. Hosts the Exo planner+executor loop, tool execution, context management, lease enforcement.

> The sandbox's **contract surface is stable and implemented** (manifest acceptance, capability JWT auth, callback emission, runtime metering). Its internal structure (folder layout, helper APIs) may still change — don't import internals from the sandbox repo. The backend talks to it via: (1) E2B SDK to spawn/manage sandboxes, (2) signed RunManifests posted to the manifest start endpoint, (3) signed callback batches received at the backend's ingestion endpoint. When you need to know the current sandbox shape, read `~/Github/sukuna-sandbox/CLAUDE.md` and `README.md` — don't reuse a remembered structure.


## Product context

`context/` holds the canonical product spec — read these when you need to know *what* you're building, not just *how*:

- `context/product.md` — the full Midsphere positioning (≈800 words). Elevator pitch in the first sentence, canonical description in the body.
- `context/v1-scope.md` — what ships in V1 vs. parked. Treat "Out of V1" as a hard line.
- `context/data-model.md` — core entities (Workspace, Agent, Tool, Knowledge, End User, Run, Schedule, Artifact, Rating, Insight, Workspace Member). This is the model layer's blueprint; `apps/<bounded-context>/models/` should map back to these.
- `context/business-rules.md` — per-user controls (credits, run count, concurrency, model tier, allowed tools/knowledge), policy injection, scheduled execution flow, billing, approval flows, rating capture. Authoritative for resolver/service logic.
- `context/user-roles.md` — Workspace Admin / Editor / Viewer permissions, plus the End User (developer's user, never logs into Midsphere).
- `context/positioning-voice.md` — naming and copy rules. **Call things by their names**: "agent" not "AI assistant", "tools" not "actions", "knowledge" not "context store/memory", "run" not "session/task/execution", "end user" (developer's user) vs. "developer" (our user). Lowercase "midsphere." in copy.
- `context/end-user-experience.md`, `context/developer-experience.md` — UX surfaces for each audience.

The context docs and the design/coding-standards docs are complementary: `context/` defines the domain, `docs/` defines how to render and ship it.

## Commands

Backend (`packages/backend/`):

```bash
uv sync                                      # install runtime + dev deps
uv run manage.py migrate                     # requires Postgres reachable per DATABASE_URL
uv run manage.py createsuperuser
uv run manage.py runserver                   # http://localhost:8000 — admin at /admin/, GraphQL at POST /graphql/
uv run manage.py <cmd>                       # any Django management command

uv run pytest                                # full test suite (uses config.settings.test)
uv run pytest -k test_name                   # single test by name
uv run pytest path/to/test_file.py::TestX    # single test by path
uv run pytest -x                             # stop on first failure

uv run ruff check .                          # lint, including the §3 size caps (max-statements=20, max-args=6)
uv run ruff format .                         # format
uv run mypy .                                # strict on models/ and services/; softer on config/api/tasks/admin per pyproject overrides
```

Frontend (`packages/frontend/`):

```bash
npm install
npm run dev                                  # astro dev — http://localhost:4321
npm run build                                # astro check + astro build (the ship gate)
npm run preview                              # serve the production build
npm start                                    # run the built node server

npm run test                                 # vitest run (unit)
npm run test:watch                           # vitest in watch mode
npm run test:e2e                             # playwright

npm run lint                                 # eslint
npm run format                               # prettier --write
npm run format:check                         # prettier --check
```

There is no top-level monorepo runner — each package stands alone. `cd packages/<name>` first.

## `start` — autonomous build mode

When the user says **`start`**, you enter autonomous build mode. No clarification questions. One command, full cycle.

### Protocol

1. **Read `context/todo.md`.** Identify the first unchecked `[ ]` item(s). Follow the topological order — don't skip ahead.

2. **Pick a work unit.** A work unit is one of:
   - A single unchecked subphase item (e.g., one model, one mutation, one page).
   - A small cluster of related unchecked items that share dependencies and can ship together (e.g., all workspace member mutations, or a detail page + its backing resolver).
   - Never more than what fits in one session. If the remaining work in a phase is large, take the next logical slice.

3. **Implement it.** Write the code. Follow every rule in this file, the coding standards, and the design spec. Pull Context7 docs before touching any third-party library. Delegate to subagents when parallelism helps — each subagent prompt must include the Context7 lookup requirement.

   **For Phase 8 (integration) items:** read the sandbox source code before implementing contract-facing code. The todo items say which sandbox files to read — the sandbox at `~/Github/sukuna-sandbox/agent_server/backends/sandbox/` has the validation logic (manifest acceptance, JWT verification, callback signing) that our output must satisfy. Don't guess field names or formats from the todo description alone.

4. **Verify it.** Run the relevant checks for what you changed:
   - Backend: `cd packages/backend && uv run ruff check . && uv run ruff format --check . && uv run pytest` (scope pytest to the touched app when the full suite is slow).
   - Frontend: `cd packages/frontend && npm run lint && npm run format:check && npm run build`.
   - Fix any failures before proceeding.

5. **Update `context/todo.md`.** Change each completed item from `- [ ]` to `- [x]`. If an item is partially done, add a parenthetical note explaining what remains — don't mark it `[x]`. If you discovered work not listed in the todo, leave a note but don't invent new checkboxes.

6. **Report.** End with a short summary: what shipped, what's verified, what the next `start` would pick up.

### Rules

- **No stubs, no fakes, no placeholders.** If a dependency isn't ready, skip the item — don't half-build it. This is rule #1 from the todo's ordering principle.
- **Read the sandbox before building against it.** Phase 8 items reference specific sandbox source files. Read them — the sandbox's validation logic is the acceptance test for what the backend produces. Contract specs live in `docs/coupling/`; the running implementation lives in `~/Github/sukuna-sandbox/`.
- **Commit only when the user asks.** `start` builds and verifies; it does not `git commit` or `git push` unless explicitly told to.
- **One `start` = one work unit.** Don't try to clear an entire phase in one shot. Ship a coherent piece, verify it, update the todo, stop. The user runs `start` again for the next piece.

## Workflow

- **Always pull up-to-date docs via the Context7 MCP server before writing or modifying code that uses a third-party library or framework.** Resolve the library ID with `resolve-library-id`, then fetch with `get-library-docs`. This is the default first step, not a fallback. Training-data recall is unreliable for the bleeding-edge stack here (Django 6, Strawberry, Astro 5+, Tailwind v4, Pydantic v2). Skip only for language stdlib or trivial no-dep code.
- **Subagents must do this too.** When delegating implementation work, the prompt must explicitly require Context7 lookup before writing — don't assume the rule is inherited.
- If Context7 doesn't have a library indexed, say so and fall back to the official docs via WebFetch. Never guess from memory.

## Architecture

Three deployables, one product:

```
        ┌────────────────────────┐
        │  packages/frontend/    │
        │  (dashboard, Astro)    │
        └──────┬─────────────────┘
               │ GraphQL  (later: same surface for @midsphere SDKs)
               ▼
        ┌──────────────────────────────────────────────┐                  ┌──────────────────────────────┐
        │  packages/backend/  (Django 6 + Strawberry)  │                  │  E2B microVM (per run /      │
        │  • control plane: workspaces, agents, tools, │  E2B SDK         │  conversation)               │
        │    knowledge, end users, runs metadata,      │  spawn + invoke  │   ┌────────────────────────┐ │
        │    schedules, ratings, billing, policies,    │ ───────────────▶ │   │  agent_server          │ │
        │    per-user controls                         │                  │   │  (~/Github/            │ │
        │  • orchestrates runs by spawning sandboxes   │ ◀─────────────── │   │   sukuna-sandbox/)     │ │
        │  • receives signed metering callbacks        │  metering +      │   │  Exo planner+executor, │ │
        │  • issues short-lived stream tokens          │  stream events   │   │  tools, lease enforce  │ │
        └──────────────────────────────────────────────┘                  │   └────────────────────────┘ │
                                                                          └──────────────────────────────┘
```

**Boundary rules:**

- **Backend owns the domain model**, per the "fat models" rule. Workspaces, agents (config), tools, knowledge, end users, runs (metadata + ledger), schedules, ratings, billing, policies, per-user controls — all live on Django models in `apps/`. Resolvers auth + delegate to a model method.
- **Backend is a thin proxy for the runtime.** It does **not** run the agent. To start a run it: (1) authenticates the caller, (2) applies per-user control checks (credits, run count, concurrency, model tier, allowed tools/knowledge — see `context/business-rules.md`), (3) **uses the E2B SDK to spawn / select a sandbox and invoke `agent_server` inside it** with the lease (`max_runtime_seconds`, `max_total_tokens`, `max_cost_usd`) and the run context, (4) returns the `run_id` and a short-lived stream token to the caller.
- **Talk to the sandbox via the E2B SDK, not via a public sandbox URL.** Wrap the E2B SDK behind a single sandbox-client module on the backend (per FRONTEND/BACKEND standards: third-party clients get a single-file wrapper so swapping is one edit). Don't sprinkle E2B SDK calls across resolvers/services — and don't import internals from the sandbox repo; treat it as a deployable runtime, not a Python library.
- **Sandbox internals are in flux; the data contract is not.** The shape of `Run`, the lease fields, and the usage/event taxonomy (`run_started`, `run_usage` periodic, `run_finished` / `run_failed` / `run_cancelled` terminal) are stable. Endpoint paths, file layout, and helper APIs inside `sukuna-sandbox/` will change. Couple to the data contract; re-read the sibling repo's `CLAUDE.md` before touching the integration code.
- **SDKs come last.** The `@midsphere/sdk` (TypeScript) and `midsphere` (Python) packages are post-frontend work — they don't exist yet. They will be additive consumers of the same GraphQL surface the dashboard uses. **Don't pre-shape the schema around an imagined SDK** — the dashboard is the first and currently only client. When the SDKs land, they get the same auth path and the same stream-token mechanism the dashboard uses.

### Backend app layout (per-bounded-context convention)

Every business app under `apps/` follows the same internal shape. This is enforced by the size caps and the "fat models, thin everything else" rule — folders exist so each layer stays small.

```
apps/<bounded-context>/
  models/      # fat models — domain logic lives here. The only layer mypy is strict on (alongside services/).
  api/         # Strawberry types/resolvers — auth + delegate to a model method, ≤20 lines each. No ORM access.
  services/    # cross-aggregate orchestration only. Single-aggregate logic stays on the model.
  tasks/       # django.tasks wrappers. Celery only for beat schedules.
  schemas/     # pydantic v2 DTOs for non-GraphQL boundaries (webhooks, external APIs, internal RPC).
  admin/       # Unfold ModelAdmin + custom actions. Every business-meaningful model gets one.
```

Currently scaffolded: `apps/core` (shared mixins) and `apps/accounts` (custom email-based `User` with `simple-history` audit). New bounded contexts (workspaces, agents, tools, runs, etc. — see `context/data-model.md`) get their own folder under `apps/`.

### Single env reader

`config/runtime.py` is a `pydantic-settings.BaseSettings` and is the **only** place env vars are read. Settings modules (`config/settings/{base,dev,prod,test}.py`) import `runtime` and project values onto Django globals. No `os.environ` calls anywhere else — if you need a new env var, add it to `Runtime` with the right type.

### GraphQL schema assembly

`config/schema.py` is the Strawberry root. App-level types/resolvers live in `apps/<app>/api/` and are composed into the root schema. Resolver pattern: auth check → call a model method → return a `MutationResult` (for mutations) or a domain object (for queries). DataLoaders handle batching for relations.

## Stack (per docs)

**Backend** (`packages/backend/`):
- Python 3.13+, Django 6 + Strawberry GraphQL (strawberry-django), PostgreSQL 16+ via psycopg 3 (pool on), Redis 7+
- Background work: Django 6 tasks framework. Celery permitted **only** for beat schedules.
- Admin: Django Admin + `django-unfold` (mandatory theme — operational source of control, not a debug tool)
- Pydantic v2 + pydantic-settings everywhere structured data crosses a non-GraphQL boundary
- uv for deps, Ruff for lint/format (with size-cap rules), mypy strict on `models/` and `services/`, pytest + pytest-django + factory_boy + freezegun + respx

**Frontend** (`packages/frontend/`) — dashboard, server-rendered:
- Astro 5+ (`output: server`, adapter `@astrojs/node`), Tailwind v4 via `@tailwindcss/vite`, TypeScript strict.
- Tokens on `:root` in `src/styles/global.css` as `--ms-*`, mapped into Tailwind via `@theme {}`.
- Fonts: Google Sans Flex (body), Fuzzy Bubbles (`.hl` only), JetBrains Mono (mono surfaces). Self-hosted `.woff2` in `public/fonts/`, preloaded in `BaseLayout.astro`.
- Icons: Lucide (`lucide-static` or framework binding for islands).
- Testing: Vitest (unit) + Playwright (smoke). Lint/format: ESLint + Prettier with Astro plugins. `npm run build` is the ship gate.

## Backend non-negotiables (BACKEND_CODING_STANDARDS.md)

- **Fat models, thin everything else.** Domain logic lives on Django models. Resolvers auth + call a model method + return. Services are for cross-aggregate orchestration only. **No ORM access in resolvers.**
- **Size caps (CI gate, hard fail):** ≤20 lines per function/method, 150–300 lines per file, 6–8 files per folder. Below 150 means merge; over 300 means split.
- **Query budget:** ≤5 queries / ≤50ms DB time at p95 per request. Kill N+1 with `select_related` / `prefetch_related` / Strawberry DataLoaders. `EXPLAIN ANALYZE` before merging anything that touches a >100k-row table. Latency: p50 <80ms, p95 <200ms reads / <400ms writes.
- **Mutations always return `MutationResult { success: Boolean!, errors: [UserError!]! }`.** Domain failures are `UserError`s (closed enum in `errors.py`), **not** GraphQL top-level `errors`. Top-level `errors` is reserved for system failures (auth, rate limits, internal).
- **Pagination is Relay-style cursor connections,** uniform across every list field. Offset only for admin-bounded lists.
- **Django Admin + `django-unfold` is the operational interface.** Every business-meaningful model gets a configured `ModelAdmin` with custom actions for multi-step ops (refund, suspend, replay webhook). Audit log via `django-simple-history`.
- **Billing:** idempotency keys on every charge/refund/sub mutation; webhook signatures verified; webhooks deduped on event ID with a `UNIQUE` constraint; nightly reconciliation; `Decimal` not `float`; tax via provider; **two-person review on every billing PR including typos**.
- **Observability wired before the first endpoint:** Sentry, PostHog (server-side, captured from model/service methods *not* resolvers — domain action is the truth, not the HTTP call), OpenTelemetry, structlog. All four non-blocking.
- **Signals are banned for domain logic** — they hide control flow. Use explicit `record_event(...)`. Signals stay fine for framework concerns (`post_migrate`).
- **Iterate, don't materialize.** `.iterator(chunk_size=...)` on querysets that could exceed a few hundred rows. Streaming responses for large exports. Per-worker RSS cap ≤300MB at p95.
- **Migrations are zero-downtime:** add nullable → backfill → enforce → drop. One schema change per migration. Never edit a merged migration. `RunPython` operations reversible.

## Frontend non-negotiables (DESIGN.md + FRONTEND_CODING_STANDARDS.md)

Visual system (DESIGN.md, applies to the dashboard):
- **Single accent: lime `#D7F25C`.** No secondary accent, no brand blue. One lime moment per paragraph at most. Restraint is the rule.
- **Focus ring on every interactive element:** 2px solid black inner outline + 4px lime `box-shadow` halo. **Lime alone fails 3:1 on canvas** — the black inner carries the contrast. Inner flips to white on dark surfaces.
- **Body prose contrast:** `text-fg-2` (8.6:1 on canvas). Never `text-fg-3` for body — fails AA at body size; reserved for small decorative labels (eyebrows, mono captions).
- **Marker font (Fuzzy Bubbles)** is scoped to `.hl` / `.hl-soft` highlighter spans only. Used elsewhere it cheapens fast.
- **Doodles:** `stroke="#111"`, `stroke-width="1.6"`, `fill="none"`, `aria-hidden="true"`, slight asymmetry so they read hand-drawn. Doodles **explain** the concept (key ring = tools, runbook = skills), they don't decorate. **Never put `<text>` users read in flow inside an SVG** — leaks as orphan fragments to crawlers.
- **One playful element per moment.** Doodle, marker phrase, hand-drawn arrow — pick one, demote the others.
- **Voice:** direct, second-person, conversational. Specific moments beat abstract claims. No exclamation points, no emoji, no mascots. The personality lives in the visuals; the prose stays flat.

Dashboard chrome (**mockups are source of truth** — `context/mockups/UI_SPEC.md` for full detail):
- **Left vertical sidebar on desktop** (`Sidebar.astro`, `lg`+). Top: "midsphere." wordmark + avatar (account menu). Then agent selector. Then vertical nav (Overview | Runs | Tools | Knowledge | Schedules | Policies | End Users | Insights). Active item = bold + lime left border + `bg-sunken`. Footer: credits + users stats container, then profile row (avatar account-menu + name + email + a **settings gear icon** → `/settings`). Settings is the footer gear, not a nav item; its sub-sections appear as a labelled group in the nav while on a settings page. **Mobile keeps the topbar + scrollable horizontal tab strip + bottom tab bar** (the PNG mockups and DESIGN.md §10 both still apply for mobile; on desktop the sidebar is the nav). *Reversed from horizontal tabs on 2026-06-25 — the PNG mockups still draw a top tab bar and are stale on desktop chrome only; `context/mockups/UI_SPEC.md` "Global shell" is authoritative.*
- **Full-width `bg-canvas` page body.** No outer `bg-sunken` wrapper, no `rounded-xl` inner panel. Pages use whitespace and section headings for structure.
- **Master-detail splits** for Tools, Policies (list/grid left ~45–60%, editor right ~40–55%). Knowledge uses grid + expanded detail panel below.
- **Insight cards** appear in context on Dashboard, Agent Overview, Run Detail, End User Detail: lime left-border (4px), icon, actionable text.
- **Stat tiles** are inline horizontal rows (icon + large value + label), not wrapped in sunken cards.
- **List rows.** Clean, no heavy borders. `hover` highlight is the affordance — don't use `divide-y`.
- **Personality still applies** — one doodle per empty state (~56–68px), one `.hl` marker phrase per page intro, lime reserved for the page's single primary CTA.
- **Mobile:** horizontal tabs become scrollable strip; bottom tab bar (Home, Runs, End Users, Settings); two-column layouts collapse; master-detail becomes stacked navigation.

Cross-cutting (FRONTEND_CODING_STANDARDS.md):
- **Bundle budget:** ≤300KB JS gzipped on the dashboard app shell. LCP <1.5s, INP <200ms.
- **Components:** soft cap ~150 lines, split presentational / container / data-fetching, props flat and named, no prop drilling past two levels, side effects in hooks.
- **Wrap third-party clients/components** so swapping is a one-file change.
- **Sentry + PostHog wired before shipping a feature.** Both non-blocking. Identify in PostHog after auth, never before. Event names `verb_object` snake_case.
- **WCAG 2.2 AA is the bar.** axe-core in CI. Honor `prefers-reduced-motion`. Skip-to-content link, focus trapped in modals, keyboard parity throughout.
- **TypeScript strict.** No `any` without a comment.

## Admin panel = part of the design system

The Django Admin (Unfold theme) is the operational source of control — operators, support, and finance use it daily. **It must read like the dashboard.** DESIGN.md and FRONTEND_CODING_STANDARDS.md apply, not just to `packages/frontend/`:

- **Same visual system.** Single lime accent (`#D7F25C` ≈ `oklch(91% .174 120)`), neutral base scale, `BORDER_RADIUS` matches dashboard tokens. Configured in `UNFOLD["COLORS"]` and `UNFOLD["BORDER_RADIUS"]` in `packages/backend/config/settings/base.py`.
- **Same focus ring.** 2px solid black inner outline + 4px lime halo on every interactive element; inner flips to white on dark surfaces. Lime alone fails 3:1 contrast — the black inner carries it. Implemented in `apps/core/static/sukuna/admin.css` and injected via `UNFOLD["STYLES"]`.
- **Same fonts.** Google Sans Flex (body), Fuzzy Bubbles (`.hl` / `.hl-soft` only — never decorative), JetBrains Mono (code/IDs/timestamps). Self-hosted .woff2 in `apps/core/static/sukuna/fonts/`. Files are .gitkeep'd until the frontend ships them; the admin falls back gracefully to system fonts in the meantime.
- **Same body contrast.** `--ms-fg-2` (~8.6:1 on canvas). Never lighter for body prose.
- **Same a11y.** WCAG 2.2 AA. Honor `prefers-reduced-motion`. Keyboard parity throughout — Unfold handles most of this; don't undo it with custom widgets.
- **Same voice.** Admin labels, action names, fieldset titles are direct, second-person, conversational. No exclamation points, no emoji, no mascots. "Suspend account" not "Suspend account!".

**When adding a new admin view or `ModelAdmin`:** these rules already apply via the global theming; you generally don't need new CSS. If you find yourself reaching for inline styles or custom widgets, check first whether `apps/core/static/sukuna/admin.css` should be extended instead — keep the customization centralized.

## Working with the user (from DESIGN.md "Personal preferences")

- **Compact > spacious.** Tighten margins between blocks before reaching for visual containers (`bg-sunken` wrappers compete with doodles for visual weight).
- **Iterates ~5 passes per significant section,** each pass targeting one thing (rhythm, duplicate messaging, AI-feel, narrative bridge). Don't try to land everything in one shot.
- **"Playful but not cute."** Visuals carry warmth so prose stays flat. When asked to add personality, the answer is usually "draw a thing that conveys the meaning," not "add an icon."
- **Doodles explain, don't decorate.**
