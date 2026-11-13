# midsphere

The official Python SDK for [midsphere](https://midsphere.com). Run agents, stream their progress, and manage end users and ratings — against the same GraphQL surface the dashboard uses.

Requires Python 3.10+ and an async runtime.

## Install

```bash
pip install midsphere
```

## Quick start

Initialize with a workspace API key, then run an agent in three lines:

```python
import asyncio
from midsphere import Midsphere


async def main():
    async with Midsphere(api_key="ms_prod_...") as client:
        run = await client.run(
            agent_id="QWdlbnRUeXBlOjE=",  # global ID from the dashboard or client.agents.list()
            end_user_id="RW5kVXNlclR5cGU6MQ==",  # the end user this run acts on behalf of
            prompt="Summarize today's signups",
        )
        async for event in run.stream():
            print(event.type, event.payload)


asyncio.run(main())
```

`run.stream()` is an async generator that yields events in order and returns after the terminal event (`run_completed`, `run_failed`, or `run_cancelled`). Each event keeps the runtime's payload shape verbatim.

### Wait for the outcome instead of streaming

```python
outcome = await run.wait()
if outcome.status == "FINISHED":
    print(outcome.summary, outcome.usage)
```

### Bind to an agent

```python
agent = client.agent("QWdlbnRUeXBlOjE=")
run = await agent.run(end_user_id=end_user_id, prompt="Draft a reply")
```

## End users

Pass user IDs from your own auth system. Resolve them to midsphere end users, or create them on first use:

```python
user = await client.end_users.ensure(
    external_user_id="auth0|abc123",
    display_name="Ada Lovelace",
    tier_label="pro",
)

await client.end_users.set_controls(
    id=user.id,
    credits=500,
    concurrency_max=3,
    model_tier="pro",
)

run = await client.run(agent_id=agent_id, end_user_id=user.id, prompt="Hello")
```

## Tools and knowledge

Read and manage the workspace's tools and knowledge bases. Lifecycle is activate/deactivate — there is no hard delete.

```python
tool = await client.tools.create(
    name="search_orders",
    description="Look up a customer order by ID",
    parameters_schema={
        "type": "object",
        "properties": {"orderId": {"type": "string"}},
        "required": ["orderId"],
    },
    execution_endpoint="https://api.example.com/tools/search-orders",
)
await client.tools.deactivate(tool.id)

kb = await client.knowledge.create(name="Returns policy", kind="document")
await client.knowledge.reindex(kb.id)
active = await client.knowledge.list(is_active=True)
```

## Human-in-the-loop

When the agent needs approval it emits a `hitl_requested` event. Respond with the request ID:

```python
async for event in run.stream():
    if event.type == "hitl_requested":
        await run.respond(event.payload["request_id"], "approve")
```

## Ratings

End users rate completed runs 1–5:

```python
await client.ratings.submit(run_uid=run.uid, score=5, comment="Spot on")
```

## Cancelling

```python
await run.cancel()
```

## Error handling

Domain failures (insufficient credits, concurrency caps, permission denied) raise `MidsphereUserError` carrying a stable `code`:

```python
from midsphere import MidsphereUserError

try:
    run = await client.run(agent_id=agent_id, end_user_id=end_user_id, prompt=prompt)
except MidsphereUserError as err:
    if err.has("INSUFFICIENT_CREDITS"):
        # prompt the user to top up
        pass
```

- `MidsphereUserError` — a domain failure surfaced through a mutation result.
- `MidsphereApiError` — transport or system failure (auth, rate limit, network, non-2xx).
- `MidsphereStreamError` — a failure talking directly to the sandbox (stream, cancel, HITL).

All extend `MidsphereError`.

## Configuration

```python
Midsphere(
    api_key="ms_prod_...",
    base_url="https://api.midsphere.com",  # override for self-host or local dev (http://localhost:8000)
    timeout=30.0,  # per-request timeout in seconds; pass None to disable
    headers={"x-trace": "on"},  # extra headers on every GraphQL request
    http_client=my_httpx_client,  # bring your own httpx.AsyncClient (proxies, tests)
)
```

When you supply `http_client`, the SDK uses it but does not close it on `aclose()` — the caller owns its lifecycle.

## Escape hatch

Anything not yet wrapped by a resource is reachable through the raw GraphQL transport:

```python
data = await client.gql.request("{ health }")
```

## Status

This package is the Python port of the official TypeScript SDK, with full parity on the core feature set: run execution, streaming, HITL, end users, ratings, tools, and knowledge. Schedules, insights, workspaces, API-key management, and billing are session-only on the control plane (the dashboard owns them) and are intentionally not part of the API-key-authed SDK.
