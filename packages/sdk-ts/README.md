# @midsphere/sdk

The official TypeScript SDK for [midsphere](https://midsphere.com). Run agents, stream their progress, and manage end users and ratings — against the same GraphQL surface the dashboard uses.

Works in Node 18+, browsers, and edge runtimes (it relies only on the platform `fetch` and web streams).

## Install

```bash
npm install @midsphere/sdk
```

## Quick start

Initialize with a workspace API key, then run an agent in three lines:

```ts
import { Midsphere } from '@midsphere/sdk';

const client = new Midsphere({ apiKey: process.env.MIDSPHERE_API_KEY! });

const run = await client.run({
  agentId: 'QWdlbnRUeXBlOjE=', // global ID from the dashboard or `client.agents.list()`
  endUserId: 'RW5kVXNlclR5cGU6MQ==', // the end user this run acts on behalf of
  prompt: 'Summarize today’s signups',
});

for await (const event of run.stream()) {
  console.log(event.type, event.payload);
}
```

`run.stream()` yields the run's events in order and ends after the terminal event (`run_completed`, `run_failed`, or `run_cancelled`). Each event keeps the runtime's payload shape verbatim.

### Wait for the outcome instead of streaming

```ts
const outcome = await run.wait();
if (outcome.status === 'FINISHED') {
  console.log(outcome.summary, outcome.usage);
}
```

### Bind to an agent

```ts
const agent = client.agent('QWdlbnRUeXBlOjE=');
const run = await agent.run({ endUserId, prompt: 'Draft a reply' });
```

## End users

You pass user IDs from your own auth system. Resolve them to midsphere end users, or create them on first use:

```ts
const user = await client.endUsers.ensure({
  externalUserId: 'auth0|abc123',
  displayName: 'Ada Lovelace',
  tierLabel: 'pro',
});

await client.endUsers.setControls({
  id: user.id,
  credits: 500,
  concurrencyMax: 3,
  modelTier: 'pro',
});

const run = await client.run({ agentId, endUserId: user.id, prompt: 'Hello' });
```

## Tools and knowledge

Read and manage the workspace's tools and knowledge bases (both API-key accessible). Lifecycle is activate/deactivate — there is no hard delete.

```ts
const tool = await client.tools.create({
  name: 'search_orders',
  description: 'Look up a customer order by ID',
  parametersSchema: {
    type: 'object',
    properties: { orderId: { type: 'string' } },
    required: ['orderId'],
  },
  executionEndpoint: 'https://api.example.com/tools/search-orders',
});
await client.tools.deactivate(tool.id);

const kb = await client.knowledge.create({ name: 'Returns policy', kind: 'document' });
await client.knowledge.reindex(kb.id);
const active = await client.knowledge.list({ isActive: true });
```

## Human-in-the-loop

When the agent needs approval it emits a `hitl_requested` event. Respond with the request ID:

```ts
for await (const event of run.stream()) {
  if (event.type === 'hitl_requested') {
    await run.respond(event.payload.request_id, 'approve');
  }
}
```

## Ratings

End users rate completed runs 1–5:

```ts
await client.ratings.submit({ runUid: run.uid, score: 5, comment: 'Spot on' });
```

## Cancelling

```ts
await run.cancel();
```

## Resuming a run

`wakeForRun` reconnects to a non-terminal run started elsewhere — reviving its (possibly paused) sandbox and minting a fresh capability token. It returns a `Run` handle identical to the one `run()` gives you, so you can stream, wait, cancel, or respond.

The common shape is a server action that starts the run, then a client that picks it up to stream progress:

```ts
// server: kick off the run, hand the id to the browser
const run = await client.run({ agentId, endUserId, prompt });
return { runId: run.id };

// later, anywhere: resume from just the id
const resumed = await client.wakeForRun(runId);
for await (const event of resumed.stream()) console.log(event.type);
```

Passing the `runId` alone costs one extra round-trip to resolve the `runUid` and current `status`. If you already have them (e.g. captured from `startRun`), pass them inline to skip it:

```ts
const resumed = await client.wakeForRun({ runId, runUid, status: 'RUNNING' });
```

Waking a terminal, missing, or non-resumable run throws a `MidsphereUserError`.

### Handing a run across the server→client boundary

When the run is still live and you just need the same handle in another context (a Next.js server action that returns to a client component), skip `wakeForRun` and serialize the handle directly. `run.toSnapshot()` returns a plain, JSON-safe object — including the live capability token — that `client.runFromSnapshot()` rebuilds with no network round-trip:

```ts
// server action: start the run, return a serializable snapshot
'use server';
export async function launch(): Promise<RunSnapshot> {
  const run = await client.run({ agentId, endUserId, prompt });
  return run.toSnapshot();
}

// client component: rebuild and stream — zero extra requests
const run = client.runFromSnapshot(snapshot);
for await (const event of run.stream()) render(event);
```

The snapshot carries a short-lived bearer token scoped to that one run — treat it accordingly. Use a snapshot when the run is mid-flight and you hold the handle; use `wakeForRun` when all you have is a `runId` (or the sandbox was paused and needs reviving).

## React

`@midsphere/sdk/react` provides `useAgent`, which owns the run lifecycle and exposes it as reactive state. `react` is an optional peer dependency — install it only if you use this entry point.

```tsx
import { useAgent } from '@midsphere/sdk/react';

function AgentPanel({ client, agentId }: { client: Midsphere; agentId: string }) {
  const agent = useAgent(client, agentId);

  return (
    <>
      <button disabled={agent.isActive} onClick={() => agent.start({ endUserId, prompt })}>
        Run
      </button>
      {agent.phase === 'error' && <p>{agent.error?.message}</p>}
      <ol>
        {agent.events.map((e) => (
          <li key={e.eventId}>{e.type}</li>
        ))}
      </ol>
      {agent.outcome && <p>{agent.outcome.summary}</p>}
    </>
  );
}
```

`useAgent` returns the reactive state (`phase`, `status`, `events`, `outcome`, `error`, `isActive`) plus controls:

- `start(input)` — start a new run for this agent and stream it.
- `resume(snapshot)` — pick up a run from a `RunSnapshot` (e.g. handed over by a server action).
- `attach(run)` — drive an existing `Run` handle (e.g. one you got from `client.wakeForRun`).
- `cancel()` / `respond(requestId, decision)` — control the active run.
- `reset()` — abort streaming and clear back to idle.

`start` and `resume` never reject — failures surface through `error` and `phase === 'error'`, so a component never needs a `try/catch`. Streaming is torn down automatically on unmount.

## Error handling

Domain failures (insufficient credits, concurrency caps, permission denied) throw a `MidsphereUserError` carrying a stable `code`:

```ts
import { MidsphereUserError } from '@midsphere/sdk';

try {
  await client.run({ agentId, endUserId, prompt });
} catch (err) {
  if (err instanceof MidsphereUserError && err.has('INSUFFICIENT_CREDITS')) {
    // prompt the user to top up
  }
}
```

- `MidsphereUserError` — a domain failure surfaced through a mutation result.
- `MidsphereApiError` — transport or system failure (auth, rate limit, network, non-2xx).
- `MidsphereStreamError` — a failure talking directly to the sandbox (stream, cancel, HITL).

All extend `MidsphereError`.

## Configuration

```ts
new Midsphere({
  apiKey: 'ms_prod_…',
  baseUrl: 'https://api.midsphere.com', // override for self-host or local dev (http://localhost:8000)
  timeoutMs: 30_000, // per-request timeout; 0 disables
  fetch: customFetch, // bring your own fetch (proxies, tests, non-standard runtimes)
  headers: { 'x-trace': 'on' }, // extra headers on every GraphQL request
});
```

## Escape hatch

Anything not yet wrapped by a resource is reachable through the raw GraphQL transport:

```ts
const data = await client.gql.request<{ health: string }>(`{ health }`);
```

## Status

This package is under active development. Run execution, streaming, HITL, the `wakeForRun` resume flow, run snapshots, the React `useAgent` hook, end users, ratings, tools, and knowledge are implemented. Schedules, insights, workspaces, API-key management, and billing are session-only on the control plane (the dashboard owns them) and are intentionally not part of the API-key-authed SDK.
