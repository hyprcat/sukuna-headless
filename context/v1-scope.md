# V1 Scope

## In V1

### Agent runtime
- Multi-agent system built on Exo (Planner + Executor + Knowledge Manager)
- Plan-Act flow with mid-run steering
- File-based context management with self-spawning multi-agent swarms
- Recovery and retries
- Multi-model routing internal to the platform

### Operational substrate
- Per-user session isolation
- Multi-tenancy
- Cost caps and spend limits
- Durable execution
- Policy injection at the context level
- Artifact handling
- Firecracker microVM sandboxing

### Per-user controls
- Credits per user
- Run counts per day/week/month
- Wallet refresh schedules
- Sandbox time per run
- Concurrency caps
- Model tier access
- Tool access
- Knowledge access
- Configurable in code (SDK) and dashboard

### Scheduled execution
- Cron-style schedules per user, per workspace, or globally
- Failure handling, pause/resume, output routing
- Scheduled runs respect per-user controls

### Observability
- Per-user session logs (searchable, filterable)
- 1-5 rating system exposed via SDK to end users
- Analytics agent surfacing insights
- Cost and usage analytics
- Run history with step-by-step replay

### Definition surface
- Tools and knowledge editable in the dashboard
- Modifiable without redeploying
- Accessible to non-engineers

### SDKs
- TypeScript SDK with streaming, server actions, edge runtime, useAgent hook
- Python SDK with parity

### Component library
- @midsphere/ui CLI-installed components
- Streaming chat with agent steps
- Rating widget
- Artifact renderer
- Cost meter
- Run viewer
- Approval prompt
- Run status component
- History sidebar

### Auth integration
- Accept user IDs from developer's auth system (Supabase Auth, Clerk, NextAuth, custom)
- Optional metadata field on user records
- No direct database integration

### Pricing
- Prepaid credits, no subscription, credits don't expire
- Free tier: $5-10 in starting credits, 1-2 concurrent sessions
- Paid tiers: $20, $50, $100, $500 with 10-15 concurrent during early access
- Enterprise: custom

## Out of V1 (parked)

- Per-task pricing infrastructure (developer charges end users per agent task)
- Agent marketplaces
- Outcome-based billing
- Bring-your-own-credits sharing
- Agent-as-a-service publishing
- Webhook receivers for auth-system sync
- Direct database integration

## Known constraints

- E2B sandbox cap of 100 concurrent (drives the 10-15 concurrent paid tier limit during early access)
- Credit-doesn't-expire creates ongoing balance sheet liability
- Bundled credit pool blends margin streams; analytics agent compute cost compresses margin