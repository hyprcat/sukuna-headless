import { describe, expect, it } from 'vitest';
import { Midsphere } from '../src/index.js';
import { MidsphereUserError } from '../src/errors.js';
import type { StreamEvent } from '../src/index.js';
import { happyPathEvents, jsonResponse, recordingFetch, sseResponse } from './helpers.js';

const RUN_UID = '11111111-1111-1111-1111-111111111111';
const RUN_ID = 'UnVuVHlwZToxMjM=';
const SANDBOX_URL = 'https://sb1.run.midsphere.com';

function startRunOk() {
  return jsonResponse({
    data: {
      startRun: {
        success: true,
        errors: [],
        runId: RUN_ID,
        runUid: RUN_UID,
        sandboxUrl: SANDBOX_URL,
        capabilityToken: 'cap-token',
        tokenExpiresAt: '2026-06-21T01:00:00Z',
      },
    },
  });
}

function client(handler: Parameters<typeof recordingFetch>[0]) {
  const { fetch, calls } = recordingFetch(handler);
  return { client: new Midsphere({ apiKey: 'ms_test_x', fetch }), calls };
}

describe('Midsphere.run', () => {
  it('starts a run and exposes its identifiers', async () => {
    const { client: c } = client((call) =>
      call.url.endsWith('/graphql/') ? startRunOk() : sseResponse([]),
    );
    const run = await c.run({ agentId: 'a1', endUserId: 'u1', prompt: 'hi' });
    expect(run.uid).toBe(RUN_UID);
    expect(run.id).toBe(RUN_ID);
    expect(run.sandboxUrl).toBe(SANDBOX_URL);
    expect(run.tokenExpiresAt?.toISOString()).toBe('2026-06-21T01:00:00.000Z');
  });

  it('projects a startRun domain failure into MidsphereUserError', async () => {
    const { client: c } = client(() =>
      jsonResponse({
        data: {
          startRun: {
            success: false,
            errors: [{ code: 'INSUFFICIENT_CREDITS', field: null, message: 'No credits left' }],
            runId: null,
            runUid: null,
            sandboxUrl: null,
            capabilityToken: null,
            tokenExpiresAt: null,
          },
        },
      }),
    );
    await expect(c.run({ agentId: 'a1', endUserId: 'u1', prompt: 'hi' })).rejects.toMatchObject({
      name: 'MidsphereUserError',
      code: 'INSUFFICIENT_CREDITS',
    });
  });

  it('streams events in order and ends in FINISHED', async () => {
    const { client: c, calls } = client((call) =>
      call.url.endsWith('/graphql/') ? startRunOk() : sseResponse(happyPathEvents()),
    );
    const run = await c.run({ agentId: 'a1', endUserId: 'u1', prompt: 'hi' });

    const collected: StreamEvent[] = [];
    for await (const event of run.stream()) {
      collected.push(event);
    }

    expect(collected.map((e) => e.type)).toEqual([
      'run_started',
      'tool_call',
      'tool_result',
      'usage_checkpoint',
      'run_completed',
    ]);
    expect(run.status).toBe('FINISHED');

    // The stream hit the sandbox URL with the capability token.
    const streamCall = calls.find((c2) => c2.url.includes('/stream'));
    expect(streamCall?.url).toBe(`${SANDBOX_URL}/runs/${RUN_UID}/stream`);
    expect(streamCall?.headers.authorization).toBe('Bearer cap-token');
  });

  it('wait() resolves a terminal outcome', async () => {
    const { client: c } = client((call) =>
      call.url.endsWith('/graphql/') ? startRunOk() : sseResponse(happyPathEvents()),
    );
    const run = await c.run({ agentId: 'a1', endUserId: 'u1', prompt: 'hi' });
    const outcome = await run.wait();
    expect(outcome.status).toBe('FINISHED');
    expect(outcome.summary).toBe('done');
    expect(outcome.usage?.total_tokens).toBe(100);
    expect(outcome.lastEvent.type).toBe('run_completed');
  });

  it('cancel() issues a DELETE to the sandbox and marks the run cancelled', async () => {
    const { client: c, calls } = client((call) => {
      if (call.url.endsWith('/graphql/')) return startRunOk();
      return jsonResponse({ status: 'cancelling', run_id: RUN_UID });
    });
    const run = await c.run({ agentId: 'a1', endUserId: 'u1', prompt: 'hi' });
    await run.cancel();
    expect(run.status).toBe('CANCELLED');
    const del = calls.find((c2) => c2.method === 'DELETE');
    expect(del?.url).toBe(`${SANDBOX_URL}/runs/${RUN_UID}`);
  });

  it('respond() posts a HITL decision', async () => {
    const { client: c, calls } = client((call) => {
      if (call.url.endsWith('/graphql/')) return startRunOk();
      return jsonResponse({ status: 'ok', request_id: 'req1' });
    });
    const run = await c.run({ agentId: 'a1', endUserId: 'u1', prompt: 'hi' });
    await run.respond('req1', 'approve');
    const post = calls.find((c2) => c2.url.includes('/hitl/'));
    expect(post?.url).toBe(`${SANDBOX_URL}/runs/${RUN_UID}/hitl/req1`);
    expect(post?.body).toBe(JSON.stringify({ response: 'approve' }));
  });
});
