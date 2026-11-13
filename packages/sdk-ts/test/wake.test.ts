import { describe, expect, it } from 'vitest';
import { Midsphere } from '../src/index.js';
import type { StreamEvent } from '../src/index.js';
import { happyPathEvents, jsonResponse, recordingFetch, sseResponse } from './helpers.js';

const RUN_UID = '22222222-2222-2222-2222-222222222222';
const RUN_ID = 'UnVuVHlwZTo0NTY=';
const SANDBOX_URL = 'https://sb2.run.midsphere.com';

function wakeOk() {
  return jsonResponse({
    data: {
      wakeForRun: {
        success: true,
        errors: [],
        sandboxUrl: SANDBOX_URL,
        capabilityToken: 'wake-token',
        tokenExpiresAt: '2026-06-21T02:00:00Z',
      },
    },
  });
}

function runIdentityOk(status = 'RUNNING') {
  return jsonResponse({ data: { run: { runUid: RUN_UID, status } } });
}

/** Route a GraphQL POST by its operation name carried in the request body. */
function routeGraphql(body: string | null) {
  if (body?.includes('RunIdentity')) return 'identity';
  if (body?.includes('WakeForRun')) return 'wake';
  return 'other';
}

function client(handler: Parameters<typeof recordingFetch>[0]) {
  const { fetch, calls } = recordingFetch(handler);
  return { client: new Midsphere({ apiKey: 'ms_test_x', fetch }), calls };
}

describe('Midsphere.wakeForRun', () => {
  it('looks up the runUid + status from a bare runId, then resumes and streams', async () => {
    const { client: c, calls } = client((call) => {
      if (call.url.endsWith('/graphql/')) {
        const route = routeGraphql(call.body);
        if (route === 'identity') return runIdentityOk('RUNNING');
        if (route === 'wake') return wakeOk();
      }
      return sseResponse(happyPathEvents());
    });

    const run = await c.wakeForRun(RUN_ID);
    expect(run.id).toBe(RUN_ID);
    expect(run.uid).toBe(RUN_UID);
    expect(run.sandboxUrl).toBe(SANDBOX_URL);
    expect(run.status).toBe('RUNNING');
    expect(run.tokenExpiresAt?.toISOString()).toBe('2026-06-21T02:00:00.000Z');

    const collected: StreamEvent[] = [];
    for await (const event of run.stream()) collected.push(event);
    expect(collected.at(-1)?.type).toBe('run_completed');
    expect(run.status).toBe('FINISHED');

    const streamCall = calls.find((x) => x.url.includes('/stream'));
    expect(streamCall?.url).toBe(`${SANDBOX_URL}/runs/${RUN_UID}/stream`);
    expect(streamCall?.headers.authorization).toBe('Bearer wake-token');
  });

  it('skips the identity lookup when runUid is supplied inline', async () => {
    const { client: c, calls } = client((call) => {
      if (call.url.endsWith('/graphql/') && routeGraphql(call.body) === 'wake') return wakeOk();
      return sseResponse([]);
    });

    const run = await c.wakeForRun({ runId: RUN_ID, runUid: RUN_UID });
    expect(run.uid).toBe(RUN_UID);
    expect(run.status).toBe('RUNNING');

    const identityCall = calls.find((x) => routeGraphql(x.body) === 'identity');
    expect(identityCall).toBeUndefined();
  });

  it('projects a terminal/not-found wake failure into MidsphereUserError', async () => {
    const { client: c } = client((call) => {
      if (routeGraphql(call.body) === 'identity') return runIdentityOk('RUNNING');
      return jsonResponse({
        data: {
          wakeForRun: {
            success: false,
            errors: [{ code: 'CONFLICT', field: null, message: 'Run is already terminal.' }],
            sandboxUrl: null,
            capabilityToken: null,
            tokenExpiresAt: null,
          },
        },
      });
    });

    await expect(c.wakeForRun(RUN_ID)).rejects.toMatchObject({
      name: 'MidsphereUserError',
      code: 'CONFLICT',
    });
  });

  it('raises NOT_FOUND when the run lookup returns null', async () => {
    const { client: c } = client(() => jsonResponse({ data: { run: null } }));
    await expect(c.wakeForRun(RUN_ID)).rejects.toMatchObject({
      name: 'MidsphereUserError',
      code: 'NOT_FOUND',
    });
  });

  it('refreshes the capability token after waking', async () => {
    const { client: c, calls } = client((call) => {
      const route = routeGraphql(call.body);
      if (route === 'identity') return runIdentityOk('RUNNING');
      if (route === 'wake') return wakeOk();
      if (call.body?.includes('RefreshSandboxToken')) {
        return jsonResponse({
          data: {
            refreshSandboxToken: {
              success: true,
              errors: [],
              capabilityToken: 'fresh-token',
              tokenExpiresAt: '2026-06-21T03:00:00Z',
            },
          },
        });
      }
      return sseResponse([]);
    });

    const run = await c.wakeForRun(RUN_ID);
    await run.refreshToken();
    expect(run.tokenExpiresAt?.toISOString()).toBe('2026-06-21T03:00:00.000Z');

    for await (const _ of run.stream()) void _;
    const streamCall = calls.find((x) => x.url.includes('/stream'));
    expect(streamCall?.headers.authorization).toBe('Bearer fresh-token');
  });
});
