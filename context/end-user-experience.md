# End User Experience

The end user is the developer's user, not a Midsphere user. They never see Midsphere branding directly. Their experience is entirely shaped by the developer's product.

## Via the SDK and components

- Invoke the agent through the developer's app (chat box, button, scheduled trigger)
- See streaming output as the agent works (multi-step plans, tool calls, intermediate results, artifacts)
- Rate the run 1-5 stars after completion (if developer exposes the rating widget)
- See cost meter (if developer exposes it)
- Approve sensitive actions (if developer configures approval flow)
- View their past run history (if developer exposes the history sidebar)

## What's hidden from them

- Midsphere infrastructure
- Agent loop internals
- Logs (those go to the developer)
- Other users' data (multi-tenant isolation)
- Cost details beyond what the developer chooses to surface

## Constraints they hit

- Per-user credits (they may run out and need to upgrade or wait for refresh)
- Run count limits (they may hit daily/weekly cap)
- Concurrency cap (they may need to wait if they have multiple runs in flight)
- Model tier (their tier determines which models the agent uses)
- Tool access (their tier may limit which capabilities the agent has for them)

## Errors they may see

- Quota exceeded ("you've reached your daily limit")
- Tier-restricted action ("this capability requires the Pro plan")
- Approval needed ("the agent wants to do X — approve?")
- Run failed (with the developer's chosen error message)

These errors are surfaced via the developer's UI using the components from @midsphere/ui or the developer's custom UI built against SDK error responses.