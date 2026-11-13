# Business Rules

## Per-user controls

Each end user has a control profile that determines what the agent can do for them. Control fields:

- credits: integer, total credits available
- run_count_limit: integer, max runs per refresh period
- run_count_period: 'day' | 'week' | 'month'
- sandbox_time_seconds: max seconds per run
- concurrency_max: max simultaneous runs
- model_tier: 'free' | 'pro' | 'enterprise' | custom
- allowed_tools: array of tool IDs accessible
- allowed_knowledge: array of knowledge base IDs accessible
- wallet_refresh_schedule: cron-style or preset (daily/weekly/monthly/never)

When an end user invokes the agent:
1. Check credits > 0; reject if not
2. Check run count under limit; reject if exceeded
3. Check concurrency under cap; queue or reject if at limit
4. Check tools requested are in allowed_tools
5. Check knowledge needed is in allowed_knowledge
6. Determine model tier and route accordingly
7. Apply sandbox_time_seconds as max execution time
8. Subtract credits as the run progresses
9. Record run, capture rating if submitted

## Scoping and policies

Policies are injected at the context level (system prompt) of every agent run for a given workspace. They enforce:

- Action restrictions ("never delete data", "never send external emails", etc.)
- Domain restrictions (which APIs / tools the agent is allowed to use)
- Output restrictions (max length, required format, prohibited content)

Policies are workspace-level by default; can be overridden per agent.

## Scheduled execution

A schedule defines:

- agent_id: which agent to run
- target_user_id: the end user the run is attributed to (counts against their controls)
- cron_expression: when to run
- failure_handling: 'retry' | 'skip' | 'alert' | 'log_silent'
- output_routing: webhook URL, email address, artifact storage path, internal store

Scheduled runs go through the same per-user control checks as on-demand runs. If the user is over their cap or out of credits, the schedule logs and skips (or alerts based on failure_handling).

## Billing

Workspace credit pool:
- Top-ups via Dodo Payments in $20, $50, $100, $500 increments (Merchant of Record — Dodo handles tax, PCI, dunning)
- Credits don't expire
- Spend deducts per run based on actual cost (compute + model tokens + analytics + observability storage)
- Free tier starts with $5-10 in credits

End user "credits" are conceptually different — they're an authorization counter the developer sets, not real money. The developer pays Midsphere; the end user has a quota relative to the developer's product.

## Approval flows

For actions marked sensitive in tool definitions:
- Agent pauses execution
- Sends approval request to end user (via developer's UI / approval prompt component)
- Waits up to a configurable timeout
- On approval: continues
- On denial or timeout: aborts the run, logs reason

## Rating capture

End user rates 1-5 via SDK widget. Rating is tied to the run. Stored in workspace database, fed into analytics agent on its next pass.