# UI Specification — derived from mockups

This document is the **implementation-ready reference** for `packages/frontend/`. Every page described here maps 1:1 to a mockup PNG in this directory. When the mockup and `docs/DESIGN.md` disagree on layout or chrome, **the mockup wins** — DESIGN.md's color tokens, typography scale, accessibility rules, voice principles, and doodle conventions still apply.

> **2026-06-25 — nav chrome reversed to a sidebar.** The desktop shell now uses a **left vertical sidebar** (DESIGN.md §10's original pattern), not the horizontal tab bar the PNGs depict. The PNG mockups are **stale on global chrome only** — their per-page content zones (master-detail splits, stat tiles, insight cards, right-hand sidebars) are still authoritative. For the shell, this section and `Sidebar.astro` win over the PNGs.

---

## Global shell (every authenticated page)

Source: all mockups share this chrome.

### Sidebar (desktop, `lg` and up) — `Sidebar.astro`

A single left vertical column (`bg-canvas`, `border-r`), top to bottom:

| Zone | Content |
|---|---|
| **Top row** | "midsphere." wordmark (left, links to `/dashboard`) · circular user avatar (right — opens the account/workspace menu) |
| **Below** | Agent selector dropdown — current agent name + chevron; opens a picker to switch agents or view all. |
| **Nav** | Vertical list: `Overview · Runs · Tools · Knowledge · Schedules · Policies · End Users · Insights`. Active item: bold + lime left border (`border-l-2 border-accent`) + `bg-sunken`. **Settings is not in this list** — it's the footer gear (below). |
| **Footer** | Pinned to the bottom (`border-t`). A `bg-sunken` container with `$X credits · Y users` stats, then a profile row: avatar (opens the account/workspace menu, dropdown opens upward) + name + email, with a **settings gear icon button** on the right. |

### Settings dialog (`SettingsDialog.astro`)

The footer gear opens a **large modal** (≈`max-w-5xl` × `85vh`), not a separate page. Layout: header (`Settings` + close) over a body split into a left section rail (Workspace, Members, Billing, API Keys, Integrations, Danger zone — only sections with a real page are listed) and an **iframe** that loads the corresponding page in chrome-less "bare" mode (`?bare=1` → `DashboardLayout` renders content only, no shell, no shell query). Clicking a rail item swaps the iframe; Escape / backdrop / close button dismiss it; focus returns to the gear. **No-JS fallback:** the gear is a plain link to `/settings`, so it still works as a full page.

### Mobile (below `lg`)

The sidebar is hidden. Mobile keeps the original chrome: the `Topbar` (wordmark + agent selector + credits) above a **scrollable horizontal tab strip** (`TabNav` — the full nav, since the bottom bar only carries four destinations), plus the fixed bottom `MobileTabBar` (Home, Runs, End Users, Settings).

### Page body

White (`bg-canvas`) full-width content area below the tabs. No outer `bg-sunken` wrapper, no rounded `bg-canvas` panel inside a sunken container. Pages use whitespace and section headings for structure, not surface nesting.

---

## Page-by-page spec

### 1. Dashboard / Home (`home-dashboard.jpg`, `home-dashboard-mobile-view.jpg`)

**Route:** `/` or `/dashboard`

**Layout:** two-column (main left, stats + activity right).

**Left column:**
- Greeting: large bold "Good morning." (time-aware: morning/afternoon/evening).
- "Here's what I noticed today" subheading.
- **Insight cards** (vertical stack, 2–4 shown): each card has a **lime left-border accent** (4px), an icon, insight text (1–2 sentences, actionable), and a subtle action link. These are real `Insight` rows from the backend, filtered to `status=active`.

**Right column:**
- **"This week" stat row** — four inline stat tiles: Runs (icon + count), Active users, Spend ($), Avg rating. Small icons above each value, label below.
- **"Recent activity" table** — columns: Run ID (with end-user avatar), description/prompt, agent name, duration, cost, star rating, end-user avatar. Relay-paged, ~8 rows visible. No heavy borders — clean rows with hover highlight.

**Mobile (`home-dashboard-mobile-view.jpg`):**
- Single column, stacked: logo → agent selector → credits badge → insight card (single, with "Adjust limits →" lime CTA) → stat row (3 tiles: runs, users, spend) → "Recent activity" list (compact) → bottom tab bar (Home, Runs, End Users, Settings with icons).

---

### 2. Agent Overview (`agent-overview.jpg`)

**Route:** `/agents/[id]` (Overview tab active)

**Layout:** two-column (main left, sidebar right).

**Left column:**
- Agent name (large heading) + lime "Active" badge (or gray "Inactive").
- Description text (1–2 lines).
- **"Recent activity" table** — same format as Dashboard recent activity, scoped to this agent.
- **"Configuration" section** (bottom) — three horizontal cards:
  - **Tools (N)** — list of tool names as text.
  - **Knowledge bases (N)** — list of KB names.
  - **Policies** — list of policy names.
  Each card is a link to the corresponding tab.

**Right column (sidebar):**
- **"What I noticed in this area"** — insight cards with lime left-border (same component as Dashboard insights, scoped to this agent's `affected_agent_ids`).
- **"Currently running"** — live run cards showing active runs for this agent (run ID, end user, progress). Empty if none.
- **"Schedules"** — next upcoming schedules for this agent (name, next run time). Links to Schedules tab.

---

### 3. Tools (`agent-tools.jpg`)

**Route:** `/tools` (Tools tab active)

**Layout:** master-detail split (list left ~60%, editor right ~40%).

**Left panel:**
- "Tools" heading.
- Row: search input + **"+ New tool"** lime button + filter pills (All | Active | Draft).
- **Tool cards in 2-column grid**: each card shows:
  - Tool name (monospace-weight, bold).
  - Description (1 line, truncated).
  - Agent badges (small pills showing which agents use it).
  - Stats row: calls this week, success %, avg latency (e.g. "1,847 calls this week · 99.2% success · avg 340ms").
  - **Selected card** has a lime left-border accent.

**Right panel (detail/editor, shown when a tool is selected):**
- Tool name (editable field).
- Description (editable field).
- **"Tool spec"** — JSON Schema editor in a dark code block with syntax highlighting. This is the `parameters_schema` field.
- Agent assignments — list of agents using this tool (with checkboxes or pills).
- **"Save changes"** lime button at bottom.

---

### 4. Knowledge (`knowledge-home.jpg`)

**Route:** `/knowledge` (Knowledge tab active)

**Layout:** card grid (top) + expanded detail panel (bottom).

**Top section:**
- "Knowledge" heading + description.
- Row: search input + **"+ Add knowledge"** lime button.
- **Knowledge cards in 2×3 grid**: each card shows:
  - Title (bold).
  - Description (1–2 lines).
  - Stats: document count, last updated, agent count (e.g. "41 documents · Updated 2 days ago · 3 agents").
  - Agent avatars (small circles).

**Expanded detail panel (below grid, when a card is selected):**
- Knowledge name with sub-tabs: **Documents | Upload | Edit | Settings**.
- **Documents tab**: file list table — name, size, date, uploaded-by user. Rows have file-type icons.
- Drag-and-drop upload area.
- Footer note: "Editable by anyone on your team — no autopilot needed."

---

### 5. Schedules (`agent-schedules.jpg`)

**Route:** `/schedules` (Schedules tab active)

**Layout:** table left (~65%) + stats sidebar right (~35%).

**Left section:**
- "Schedules" heading + description.
- **"+ New schedule"** lime button.
- **Table** with columns:
  - Schedule name (bold) + agent badge + description (smaller text below name).
  - Frequency (human-readable: "Every Monday", "Every Hour", "Every day", "Specific_cron_def").
  - Trigger count.
  - Last run (relative time).
  - Next run (datetime).
  - Status (Active badge — lime, or gray).
- Pagination: "Showing 6 of 9 schedules."

**Right sidebar — "Schedule health":**
- **12** schedules running this week (large number).
- **"Run outcomes this week"** — stacked horizontal bar or counts (success/fail with counts like "1,847 Runs · 46 1,510").
- **"Run costs this week"** — small bar chart (lime bars, one per day).
- **"Next scheduled run"** — card with schedule name, time ("Today, 9:00 AM"), weekly cost.

---

### 6. Policies (`agent-policies.jpg`)

**Route:** `/policies` (Policies tab active)

**Layout:** master-detail split (list left ~45%, editor right ~55%).

**Left panel:**
- "Policies" heading + description ("What your agent is and isn't allowed to do.").
- **"+ New policy"** lime button.
- **Policy cards as list**: each card shows:
  - Policy name (bold).
  - Description (1 line).
  - Scope badge: "All agents" or specific agent names.
  - Status: "Active" lime badge.
  - **Selected card** has lime left-border accent.

**Right panel (editor):**
- Policy name (editable, bold heading).
- Description (editable field).
- **"Rule definition"** — dark code editor block with JSON/structured policy rules (array of action/condition objects).
- **"Scope / applies to"** — agent multi-select with checkboxes (Research Agent, Support Agent, Analytics Agent) + "Block from" toggle.
- **"Save changes"** lime button.
- Bottom note: "Policies are enforced at the context level — your agent can't violate them, even if asked."

---

### 7. End Users (`developer-end-user.jpg`)

**Route:** `/end-users` (End Users tab active)

**Layout:** full-width table + tier configuration section below.

**Top section:**
- "End Users" heading.
- Stats bar (inline): "1,247 active" · "89 active 24h" · "12.14 invites today" (or similar metric).
- Row: search input + Tier filter dropdown (All) + Status filter (Active) + **"+ Invite End User"** lime button.

**Table:**
- Columns: avatar + user ID/name/company, Tier (Free/Pro badge with colored background), Credits (count/limit with small progress bar), Runs today, Sandbox time, Run cap, Concurrency, Actions.
- Progress bars use **lime fill** for credits and limits.
- Rows have hover highlight.

**Bottom section — "Tier Configuration":**
- Three columns side by side: **Free**, **Pro**, **Enterprise**.
- Each column lists the tier's limits: credits, run cap, sandbox time, concurrency, model tier.
- "Manage tiers and limits in Settings" link (lime text).

---

### 8. End User Detail (`end-user-overview-expanded.jpg`)

**Route:** `/end-users/[id]`

**Layout:** two-column (main left, metadata sidebar right).

**Left column:**
- Breadcrumb: "End Users > user_8a392".
- Large avatar (circle with initials, e.g. "SC") + name ("Sarah Chen") + lime "Active" badge.
- Email, location, joined date (small text below name).
- **Tier badge** — large lime-background pill showing "Pro" + "Edit tier" link.
- **Stats row** — horizontal tiles: Credits (47/100 with progress), Runs (12, 2 unlimited), Run cap, Sandbox time (4m), Concurrency (1/3).
- **"Recent activity" table** — columns: description, agent, cost, rating (stars), date.
- "View all runs for this user" link.

**Right sidebar:**
- **"Metadata"** — key-value pairs: Company, Role, Department.
- **"Notes"** — editable text area (freeform operator notes).
- **"What I noticed"** — insight card with lime left-border, scoped to this end user.

---

### 9. Insights (`insights-history.jpg`)

**Route:** `/insights` (Insights tab active)

**Layout:** feed left (~65%) + stats sidebar right (~35%).

**Left section:**
- "Insights" heading + "Everything I've noticed" subtitle.
- **Filter tabs** (horizontal pills): Capability gaps | Tier optimization | Quality issues | Scheduled health | Cost anomalies.
- Date range selector (right-aligned).
- **Insight cards as vertical feed**: each card shows:
  - Category indicator (colored dot or icon).
  - Title (bold).
  - Description (2–3 lines of actionable text).
  - Timestamp.
  - Related context (affected agents/users/runs).

**Right sidebar — "Insight stats":**
- **48** total insights this month (large number).
- **68%** actioned rate (with small line/donut chart).
- Category breakdown list.
- "Dismiss patterns" and "Adjust alerts" links.

---

### 10. Run Execution Detail (`agent-run-execution.jpg`)

**Route:** `/runs/[id]`

**Layout:** timeline left (~60%), context sidebar right (~40%).

**Left column:**
- Breadcrumb: "Runs > Run #L8a3f2".
- Run header: "user_8a3f2 → Research task" + status icon + duration (2m 14s) + cost ($0.43) + star rating.
- **Vertical event timeline** — each event is a block:
  - **Plan:** — text block (the agent's plan).
  - **Tool call:** — tool name + dark code block showing arguments/payload.
  - **Reasoning:** — text block (agent's intermediate reasoning).
  - **Output:** — final output text.
  - Events are visually sequential with a thin vertical connector line.

**Right sidebar:**
- **"What I noticed in this run"** — insight card with lime border.
- **"Final output"** — expandable text block.
- **"User feedback"** — star rating display + comment text.
- **"Cost breakdown"** — line items (Plan, Search, Fetch, Save) with costs, total at bottom.

---

### 11. Billing (`agent-billing.jpg`)

**Route:** `/billing` (under Settings)

**Layout:** center-focused hero stat + charts below + modal overlay.

**Top section:**
- "Billing" heading.
- **Large center stat**: "Current credit balance: **$247.50**" (very large, mono or bold) + "Credits never expire." subtitle + **"+ Top up"** lime button.

**Middle section (two columns):**
- **Left: "Spend this month"** — $247.50 with a **line chart** (lime line, light grid, daily data points over the month). Below the chart: breakdown table (Agent actions, Knowledge retrieval, Tool execution, Scheduled runs, Total).
- **Right: "Recent transactions"** — list of recent charges/top-ups with amounts.

**Bottom section:**
- **"Usage by agent"** — horizontal bar chart (lime bars) showing cost per agent.
- Daily usage bar chart across the month.

**Top-up modal (overlay):**
- "Top up credits" heading.
- **"Select an amount"** — four preset buttons: **$20 | $50 | $100 | $500**. Selected button has lime background.
- "Custom amount" text input field below.
- **"Continue to payment"** lime button + "Cancel" link.

---

### 12. Settings — Workspace (`settings-home.jpg`)

**Route:** `/settings` (Settings tab, Workspace sub-tab)

**Layout:** form, single column with right-aligned avatar upload.

**Sub-tabs:** Workspace | Members | API Keys | Integrations | Danger zone.

**Form fields:**
- **Workspace details**: name (text), slug (text), public URL (read-only, derived from slug), description (textarea).
- **Workspace avatar** — large circle (letter initial or uploaded image) with "Upload logo" button, right-aligned.
- **Default model tier** — dropdown (Free / Pro / Enterprise).
- **Default per-user limits** — field grid:
  - Credits per period (number) + Runs per period (number) + Refresh schedule dropdown (Daily).
  - Sandbox time limit (number) + Concurrency cap (number).
- **Notifications** — checkboxes:
  - Alert me when an agent fails.
  - Alert me when a user hits their cap.
  - Daily summary email.
  - Weekly insights digest.
- **"Save changes"** lime button (bottom right).

---

### 13. Settings — API Keys (`settings-api-keys.jpg`)

**Route:** `/settings/api-keys` (or `/keys`)

**Layout:** table + modal.

- "API Keys" heading + description ("Use these to authenticate your SDK and integrations.").
- **"+ Create key"** lime button.
- **Table**: Key name, Key value (masked: `msph_live_*****abc`), Created date, Last used (relative), Permissions ("Full access" or scope list), Actions (View, Revoke — "Revoke" in red/destructive style).

**Secret reveal modal (shown once on creation):**
- "Your API key" heading.
- Full key displayed in a monospace text field with **Copy** button.
- **Yellow/lime warning banner**: "This is the only time you'll see this key. Copy it now."
- "Close" button.

---

### 14. Settings — Members (`org-team-members.jpg`)

**Route:** `/settings/members` (or `/workspace/members`)

**Layout:** invite form + members table + pending invites.

- "Members" heading + **"+ Invite member"** lime button (top right).
- **Invite form (inline)**: email text input + role dropdown (Editor default) + "Send invite" lime button.
- **Members table**: avatar (circular) + name + email, Role (badge: Admin / Editor / Viewer), Last active (relative), Actions (Change role dropdown, Remove — destructive).
- **"Pending invites" section** (below): email, invited date, Actions (Resend, Cancel).
- Footer note: "Only workspace admins can manage members and invites."

---

### 15. Empty States (`empty-states.jpg`)

Three empty-state card variants, each used on its corresponding page:

1. **"No runs yet"** — sleeping character doodle (zzz), "Your agent hasn't been called yet. Try the playground or invite a test user." Two buttons: "Open playground" (lime) + "Invite test user" (outline).
2. **"Nothing to report yet"** (Insights) — character-with-chart doodle, "I'll start surfacing patterns once your agent has 50+ runs. You're at 12." Progress bar (12/50, lime fill).
3. **"No scheduled runs"** — clock doodle, "Schedule your agent to run on its own — weekly digests, monitoring, daily prep." + "Create schedule" lime button.

Pattern: **doodle (hand-drawn, ~56–68px) + heading + description + CTA(s)**. Doodles explain the empty concept, not generic illustrations.

---

### 16. Onboarding (`onboarding.jpg`)

**Route:** `/onboarding` (shown after first signup, before workspace creation)

**Layout:** centered, narrow column (~480px max-width).

- "midsphere." logo at top.
- "Welcome to midsphere." large heading.
- "Let's get your first agent running." subtitle.
- **Three option cards** (vertical stack):
  1. **"Try a deployed agent"** — "Recommended" lime badge. Robot doodle. Description: "Pick from pre-built agents — research, analyst, support — and try them with your API key. Fastest way to feel what's possible." **"Open gallery →"** lime button.
  2. **"Start from scratch"** — terminal/code doodle. "Run `npx create-midsphere-app my-app` and you'll have a working agent locally in 60 seconds." Code snippet block.
  3. **"Add to existing app"** — puzzle piece doodle. "Already building? Use the SDK or let Claude Code integrate it for you." **"View install →"** link.
- Footer: "You have $10 in starting credits. They never expire."

---

### 17. SDK Components (`midsphere-typescript-sdk-components.jpg`)

**Route:** `/components` (linked from topbar "Components")

**Layout:** component grid + detail panel.

- "@midsphere/ui" heading.
- **Component cards in grid**: Streaming chat, Run viewer, Rating widget, Run status, Cost meter, Approval prompt, History sidebar, Artifact renderer. Each card is a small preview with title and 1-line description.
- **Selected component detail** (right or below): larger preview + Props table (dark code block showing TypeScript interface/props).
- Footer note about embedding.

---

## Recurring UI components

These components appear across multiple pages. Build them once, reuse everywhere.

### Insight card
- Lime left-border (4px solid `--ms-accent`).
- Icon (category-specific) + text (1–3 sentences) + optional action link.
- Used on: Dashboard, Agent Overview, Run Detail, End User Detail, Insights feed.

### Stat tile
- Icon (small, above or left of value) + large numeric value + label below.
- Horizontal row of 3–5 tiles.
- Used on: Dashboard, Agent Overview, End User Detail, Schedules sidebar.

### Agent badge
- Small rounded pill with agent name, colored dot or avatar.
- Used in: Tool cards, Schedule rows, Run rows, Knowledge cards.

### Status badge
- "Active" = lime background + dark text. "Inactive"/"Paused"/"Disabled" = gray.
- Used on: Agent Overview, Tools, Schedules, End Users.

### Star rating
- 5-star display (filled = lime or yellow, empty = gray outline).
- Used on: Run rows, Run Detail, End User activity.

### Progress bar
- Thin bar with lime fill showing usage against limit (e.g. credits 47/100).
- Used on: End Users table, empty state progress.

### Code editor block
- Dark background (`--ms-bg-inverse` or similar dark), syntax-highlighted.
- Used for: Tool JSON Schema, Policy rule definitions, Run tool-call payloads, SDK code snippets.

### Table row
- Clean rows, no heavy borders. Hover highlight. Avatar + text in first column.
- Consistent across: Dashboard activity, Agent activity, End Users, Members, API Keys, Schedules.

### Lime CTA button
- `bg-accent` (`#D7F25C`) + dark text. Rounded (`rounded-md` or `rounded-pill`).
- One per section max (restraint rule from DESIGN.md).
- Used for: "+ New X" creation actions, "Save changes", "Top up", primary empty-state action.

### Master-detail split
- List/grid on left (~45–60%), editor/detail panel on right (~40–55%).
- Selecting an item in the list populates the right panel.
- Used on: Tools, Policies. Knowledge uses a variant (grid + expanded panel below).

---

## Mobile behavior (from `home-dashboard-mobile-view.jpg`)

- Topbar simplifies: logo centered, agent selector below.
- Horizontal tabs become a scrollable strip.
- **Bottom tab bar** appears: four icons — Home, Runs, End Users, Settings.
- Two-column layouts collapse to single column.
- Master-detail splits become stacked (list → tap → detail page).
- Tables become card lists on narrow screens.

---

## What DESIGN.md §10 described vs. what the mockups show

| Aspect | DESIGN.md §10 | Mockups (source of truth) |
|---|---|---|
| Navigation | Gmail-style left sidebar with pill nav items | Horizontal tab bar below topbar, no sidebar |
| Page chrome | `bg-sunken` outer + `rounded-xl bg-canvas` inner panel | Full-width `bg-canvas`, no sunken wrapper |
| Card model | `surface="sunken"` on canvas content panel | Cards are white on white with subtle borders or lime accents |
| Sidebar items | `rounded-pill` active = `bg-canvas` + `shadow-1` | N/A — no sidebar |
| Topbar search | Wide `rounded-pill` `bg-canvas` form | Agent selector dropdown + credits/users stats |
| Stat tiles | `Card surface="sunken"` with `!p-5` | Inline stat row, no card wrapper |

**Resolution:** The mockups supersede DESIGN.md §10's layout rules. DESIGN.md's color tokens, typography, accessibility rules, voice, and doodle conventions remain in force. Build the shell and layout from the mockups; style with DESIGN.md's design system.
