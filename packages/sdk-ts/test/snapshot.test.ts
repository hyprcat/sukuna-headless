import { describe, expect, it } from 'vitest';
import { Midsphere } from '../src/index.js';
import type { StreamEvent } from '../src/index.js';
import { happyPathEvents, jsonResponse, recordingFetch, sseResponse } from './helpers.js';

const RUN_UID = '33333333-3333-3333-3333-333333333333';
const RUN_ID = 'UnVuVHlwZTo3ODk=';
const SANDBOX_URL = 'https://sb3.run.midsphere.com';

function startRunOk() {
  return jsonResponse({
    data: {
      startRun: {
        success: true,
        errors: [],
        runId: RUN_ID,
        runUid: RUN_UID,
        sandboxUrl: SANDBOX_URL,
        capabilityToken: 'snap-token',
        tokenExpiresAt: '2026-06-21T04:00:00Z',
      },
    },
  });
}

function client(handler: Parameters<typeof recordingFetch>[0]) {
  const { fetch, calls } = recordingFetch(handler);
  return { client: new Midsphere({ apiKey: 'ms_test_x', fetch }), calls };
}

describe('Run snapshots (server-action boundary)', () => {
  it('serializes a run handle to a plain, JSON-safe object', async () => {
    const { client: c } = client((call) =>
      call.url.endsWith('/graphql/') ? startRunOk() : sseResponse([]),
    );
    const run = await c.run({ agentId: 'a1', endUserId: 'u1', prompt: 'hi' });

    const snap = run.toSnapshot();
    expect(snap).toEqual({
      runId: RUN_ID,
      runUid: RUN_UID,
      sandboxUrl: SANDBOX_URL,
      capabilityToken: 'snap-token',
      tokenExpiresAt: '2026-06-21T04:00:00Z',
      status: 'QUEUED',
    });
    // Survives the structured-clone / JSON trip a server action makes.
    expect(JSON.parse(JSON.stringify(snap))).toEqual(snap);
  });

  it('rebuilds a streamable handle from a snapshot with no network call', async () => {
    let graphqlCalls = 0;
    const { client: c, calls } = client((call) => {
      if (call.url.endsWith('/graphql/')) {
        graphqlCalls += 1;
        return startRunOk();
      }
      return sseResponse(happyPathEvents());
    });

    const original = await c.run({ agentId: 'a1', endUserId: 'u1', prompt: 'hi' });
    const before = graphqlCalls;

    const resumed = c.runFromSnapshot(original.toSnapshot());
    expect(graphqlCalls).toBe(before); // rebuilding hit the network zero times

    const collected: StreamEvent[] = [];
    for await (const event of resumed.stream()) collected.push(event);
    expect(collected.at(-1)?.type).toBe('run_completed');
    expect(resumed.status).toBe('FINISHED');

    const streamCall = calls.find((x) => x.url.includes('/stream'));
    expect(streamCall?.url).toBe(`${SANDBOX_URL}/runs/${RUN_UID}/stream`);
    expect(streamCall?.headers.authorization).toBe('Bearer snap-token');
  });

  it('captures the refreshed token in later snapshots', async () => {
    const { client: c } = client((call) => {
      if (call.body?.includes('RefreshSandboxToken')) {
        return jsonResponse({
          data: {
            refreshSandboxToken: {
              success: true,
              errors: [],
              capabilityToken: 'rotated-token',
              tokenExpiresAt: '2026-06-21T05:00:00Z',
            },
          },
        });
      }
      return call.url.endsWith('/graphql/') ? startRunOk() : sseResponse([]);
    });

    const run = await c.run({ agentId: 'a1', endUserId: 'u1', prompt: 'hi' });
    await run.refreshToken();
    expect(run.toSnapshot().capabilityToken).toBe('rotated-token');
    expect(run.toSnapshot().tokenExpiresAt).toBe('2026-06-21T05:00:00Z');
  });
});
