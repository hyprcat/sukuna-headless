# AGENTS.md

This file provides guidance to Codex and other coding agents working in this repository.

## Operating Principles

- Build reliable, scalable, performant software. Prefer simple, well-tested designs over clever machinery.
- Use proven third-party libraries for solved problems instead of reimplementing common functionality.
- Follow KISS, DRY, and the project coding standards with scrutiny.
- Fix obvious local issues you uncover while working in the touched area, especially bugs, bottlenecks, poor algorithms, and standard violations.
- Avoid low-value tests that do not exercise real behavior.
- Keep edits scoped. Do not refactor unrelated code unless it is necessary to complete the task safely.
- The less code, the better it is to manage

## Claude TODO Audit Workflow

When auditing Claude's work against `context/todo.md`, work one objective or sub-objective at a time.

- If the user says only "start" in a fresh session, immediately begin auditing the next unaudited item. Do not ask what to audit. Read `context/audit-tracker.md` and `context/todo.md`, infer the next item in TODO order from the tracker, default to Phase 2 unless the tracker or user says otherwise, and start verification.
- Start from the current audit phase named by the user, currently Phase 2 unless redirected, and preserve the order in `context/todo.md`.
- Keep `context/audit-tracker.md` current for implemented or partially implemented items. After each completed audit that verifies real implementation work, append a tracker entry with the exact checklist item, audit status, audited files/behaviors, fixes made, verification commands, what was not audited, and the next item to audit.
- Read the selected checklist item, its parent section, the ordering principle at the top of `context/todo.md`, and the relevant files from `context/` and `docs/` before judging the implementation.
- Treat a checked box as a claim, not proof. Verify the implementation from source code, migrations, admin configuration, factories, tests, settings, and integration boundaries as applicable.
- First decide whether the selected item is implemented, partially implemented, or not implemented. If it is not implemented, report the gap in the response, do not update `context/audit-tracker.md`, and do not build the missing feature unless the user asks for implementation work.
- If it is implemented or partially implemented, audit Claude's implementation for bugs, logical errors, security issues, data integrity failures, concurrency/idempotency risks, performance bottlenecks, memory/CPU/network waste, N+1 queries, migration safety, and violations of `docs/BACKEND_CODING_STANDARDS.md`, `docs/FRONTEND_CODING_STANDARDS.md`, and `docs/DESIGN.md`.
- Apply scoped fixes when the audit finds a real issue in the touched area. Add or adjust tests when the fix changes behavior, protects an invariant, or covers a regression risk.
- When completing an audit, clearly mark the exact checklist item, files, and behaviors that were audited, and separately mark what was not audited or remains pending. Do not imply a whole phase, app, or adjacent surface was audited when only one item or slice was checked.
- Do not pre-implement later TODO items, add stubs/fakes/placeholders, or couple this repo to unstable internals of `~/Github/sukuna-sandbox/`.

## Repository State

Three authoritative documents plus two package slots:

- `docs/DESIGN.md` - visual and voice spec for `packages/frontend/`. It opens with "marketing site" framing from another project, but it is the spec for this dashboard. Marketing-only sections are residue; the visual system, voice principles, accessibility rules, and doodle conventions apply. It also applies to the Django/Unfold admin panel.
- `docs/BACKEND_CODING_STANDARDS.md` - rules for `packages/backend/` using Django 6 and Strawberry GraphQL.
- `docs/FRONTEND_CODING_STANDARDS.md` - cross-cutting frontend rules. Also binds the admin panel for focus rings, fonts, contrast, reduced motion, and WCAG 2.2 AA.
- `packages/backend/` - scaffolded Django 6 + Strawberry backend with split settings, `pydantic-settings`, Unfold theme, DigitalOcean Spaces storage, `apps/core`, and `apps/accounts`.
- `packages/frontend/` - Astro 5 dashboard, partially built. Auth pages and infrastructure (BaseLayout, AuthLayout, global.css, graphql.ts, middleware, observability wrappers, UI primitives) are production-ready. The dashboard shell and all logged-in pages are being rebuilt from scratch (Phase 6A-6I in `context/todo.md`) because the first pass used a sidebar layout that contradicts the mockups. Phase 6B (shell chrome) is the next work unit.

Sibling repo:

- `~/Github/sukuna-sandbox/` - agent runtime built into an E2B sandbox image. The backend spawns and talks to it through the E2B SDK, not a public HTTP URL.
- The sandbox data model is stable, but its internal folder layout, endpoint names, and helper APIs are expected to change. Do not hard-code paths from `sukuna-sandbox/agent_server/` into this repo. When touching integration code, read `~/Github/sukuna-sandbox/CLAUDE.md` and `README.md` that day.


## Product Context

`context/` holds the canonical product spec. Read it when the task depends on product intent:

- `context/product.md` - Midsphere positioning and canonical description.
- `context/v1-scope.md` - V1 scope. Treat "Out of V1" as a hard line.
- `context/data-model.md` - core entities and model blueprint.
- `context/business-rules.md` - per-user controls, policy injection, scheduled execution, billing, approvals, rating capture.
- `context/user-roles.md` - Workspace Admin, Editor, Viewer, and End User permissions.
- `context/positioning-voice.md` - naming and copy rules. Use "agent", "tools", "knowledge", "run", "end user", and lowercase "midsphere." in copy.
- `context/end-user-experience.md` and `context/developer-experience.md` - UX surfaces for each audience.

The `context/` docs define the domain. The `docs/` files define how to render and ship it.

## Commands

There is no top-level monorepo runner. `cd packages/<name>` first.

Backend (`packages/backend/`):

```bash
uv sync
uv run manage.py migrate
uv run manage.py createsuperuser
uv run manage.py runserver
uv run manage.py <cmd>

uv run pytest
uv run pytest -k test_name
uv run pytest path/to/test_file.py::TestX
uv run pytest -x

uv run ruff check .
uv run ruff format .
uv run mypy .
```

Frontend (`packages/frontend/`):

```bash
npm install
npm run dev
npm run build
npm run preview
npm start

npm run test
npm run test:watch
npm run test:e2e

npm run lint
npm run format
npm run format:check
```

## Documentation Workflow

- Before writing or modifying code that uses a third-party library or framework, pull current docs first. Prefer any available docs MCP server for the exact library. If that is unavailable, use official documentation.
- Do not rely on memory for bleeding-edge stack details: Django 6, Strawberry, Astro 5+, Tailwind v4, Pydantic v2, E2B, and Unfold.
- If delegating work to subagents, explicitly require the same current-docs lookup before implementation.

## Architecture

Three deployables, one product:

- `packages/frontend/` - server-rendered dashboard in Astro.
- `packages/backend/` - Django 6 + Strawberry control plane for workspaces, agents, tools, knowledge, end users, runs metadata, schedules, ratings, billing, policies, and per-user controls.
- E2B microVM runtime - per-run or per-conversation sandbox hosting the Exo planner/executor loop, tools, metering, stream events, and lease enforcement.

Boundary rules:

- Backend owns the domain model. Domain logic belongs on Django models.
- Resolvers authenticate, delegate to model methods, and return domain objects or `MutationResult`.
- Backend is a thin proxy for the runtime. It does not run agents itself.
- Start/select sandboxes through the E2B SDK, invoke the runtime inside the sandbox, and return `run_id` plus a short-lived stream token.
- Wrap the E2B SDK behind a single backend sandbox-client module. Do not scatter SDK calls through resolvers or services.
- Treat `sukuna-sandbox` as a deployable runtime, not a Python library. Couple to the stable data contract only.
- SDKs come later. Do not pre-shape the GraphQL schema around imagined SDK clients.

## Backend Layout

Each business app under `apps/` follows this bounded-context shape:

```text
apps/<bounded-context>/
  models/      # fat models; domain logic lives here
  api/         # Strawberry types/resolvers; auth + delegate; no ORM access
  services/    # cross-aggregate orchestration only
  tasks/       # django.tasks wrappers; Celery only for beat schedules
  schemas/     # pydantic v2 DTOs for non-GraphQL boundaries
  admin/       # Unfold ModelAdmin + custom actions
```

Current scaffold: `apps/core` and `apps/accounts`. New bounded contexts map back to `context/data-model.md`.

## Backend Non-Negotiables

- Fat models, thin everything else. No ORM access in resolvers.
- Function/method size cap: 20 lines. File target: 150-300 lines. Folder target: 6-8 files.
- Query budget: no more than 5 queries and 50ms DB time at p95 per request. Use `select_related`, `prefetch_related`, and Strawberry DataLoaders to prevent N+1s.
- Run `EXPLAIN ANALYZE` before merging work touching tables expected to exceed 100k rows.
- Mutations return `MutationResult { success: Boolean!, errors: [UserError!]! }`. Domain failures are `UserError`s, not GraphQL top-level errors.
- Pagination is Relay-style cursor connections except for admin-bounded lists.
- Every business-meaningful model gets a configured Unfold `ModelAdmin` with meaningful actions and simple-history audit.
- Billing work requires idempotency keys, signature verification, webhook event dedupe by unique event ID, nightly reconciliation, `Decimal` for money, provider-managed tax, and two-person review for every billing PR.
- Observability belongs in model/service methods, not resolvers: Sentry, PostHog server-side, OpenTelemetry, and structlog. Keep them non-blocking.
- Signals are banned for domain logic. Use explicit `record_event(...)`. Framework-only signals are acceptable.
- Iterate large querysets with `.iterator(chunk_size=...)`; use streaming responses for large exports.
- Migrations are zero-downtime: add nullable, backfill, enforce, drop. One schema change per migration. Never edit a merged migration. `RunPython` operations must be reversible.
- `config/runtime.py` is the only env reader. Add new env vars to `Runtime`; do not use `os.environ` elsewhere.

## Frontend Non-Negotiables

Design system:

- Single accent: lime `#D7F25C`. No secondary accent and no brand blue.
- Focus ring on every interactive element: 2px solid black inner outline plus 4px lime halo. Inner flips to white on dark surfaces.
- Body prose uses `text-fg-2`. Do not use `text-fg-3` for body text.
- Fuzzy Bubbles is only for `.hl` and `.hl-soft` highlighter spans.
- Doodles explain concepts; they do not decorate. Use `stroke="#111"`, `stroke-width="1.6"`, `fill="none"`, `aria-hidden="true"`, and slight asymmetry.
- Never put readable flow text inside SVG.
- Use one playful element per moment: doodle, marker phrase, or hand-drawn arrow.
- Voice is direct, second-person, conversational. No exclamation points, emoji, or mascots.

Dashboard chrome (`context/mockups/UI_SPEC.md` is the source of truth):

- Horizontal tab navigation, no sidebar. Topbar: logo (left), agent selector dropdown (center), credits + users stats, avatar (right). Below: horizontal tab bar (Overview | Runs | Tools | Knowledge | Schedules | Policies | End Users | Insights | Settings). Active tab = bold + underline.
- Full-width `bg-canvas` page body. No outer `bg-sunken` wrapper, no `rounded-xl` inner panel. Pages use whitespace and section headings for structure.
- Master-detail splits for Tools, Policies (list/grid left ~45-60%, editor right ~40-55%). Knowledge uses grid + expanded detail panel below.
- Insight cards: lime left-border (4px), icon, actionable text.
- Stat tiles are inline horizontal rows (icon + large value + label), not wrapped in sunken cards.
- List rows are clean, no heavy borders. Hover highlight is the affordance. Do not use `divide-y`.
- One doodle per empty state (~56-68px), one `.hl` marker phrase per page intro. Reserve lime for the page's single primary CTA.
- Mobile: horizontal tabs become scrollable strip; bottom tab bar (Home, Runs, End Users, Settings); two-column layouts collapse; master-detail becomes stacked navigation.

Cross-cutting frontend:

- Dashboard app shell budget: 300KB JS gzipped.
- Targets: LCP under 1.5s, INP under 200ms.
- Components should stay around 150 lines where practical. Split presentational, container, and data-fetching concerns.
- Wrap third-party clients/components so replacement is a one-file edit.
- Wire Sentry and PostHog before shipping a feature. PostHog identifies only after auth. Event names are `verb_object` snake_case.
- WCAG 2.2 AA is required. Include skip-to-content, keyboard parity, modal focus traps, reduced-motion support, and axe checks in CI.
- TypeScript strict. No `any` without a reason comment.

## Admin Panel

The Django Admin with Unfold is an operational product surface, not a debug panel. It must follow `DESIGN.md` and `FRONTEND_CODING_STANDARDS.md`.

- Use the same lime accent, neutral scale, border radius, focus ring, fonts, contrast, a11y, and voice as the dashboard.
- Global admin theme lives in `UNFOLD["COLORS"]`, `UNFOLD["BORDER_RADIUS"]`, and `apps/core/static/sukuna/admin.css`.
- Prefer extending centralized admin CSS over inline styles or custom widgets.
- Admin labels and action names should be direct and conversational, with no exclamation points, emoji, or mascots.

## Working With Affan

- Compact beats spacious. Tighten margins before adding visual containers.
- Significant sections typically need several passes, each targeting one concern such as rhythm, duplicate messaging, AI feel, or narrative bridge.
- Aim for playful but not cute. Visuals carry warmth so prose can stay flat.
- Doodles explain; they do not decorate.
