// @vitest-environment jsdom
import { describe, expect, it } from 'vitest';
import { act, renderHook, waitFor } from '@testing-library/react';
import { Midsphere } from '../src/index.js';
import { useAgent } from '../src/react/index.js';
import { happyPathEvents, jsonResponse, recordingFetch, sseResponse } from './helpers.js';

const RUN_UID = '44444444-4444-4444-4444-444444444444';
const RUN_ID = 'UnVuVHlwZToxMA==';
const SANDBOX_URL = 'https://sb4.run.midsphere.com';

function startRunOk() {
  return jsonResponse({
    data: {
      startRun: {
        success: true,
        errors: [],
        runId: RUN_ID,
        runUid: RUN_UID,
        sandboxUrl: SANDBOX_URL,
        capabilityToken: 'hook-token',
        tokenExpiresAt: '2026-06-21T06:00:00Z',
      },
    },
  });
}

function setup(handler: Parameters<typeof recordingFetch>[0]) {
  const { fetch, calls } = recordingFetch(handler);
  const client = new Midsphere({ apiKey: 'ms_test_x', fetch });
  return { client, calls };
}

describe('useAgent', () => {
  it('starts idle, streams events, and resolves to the done phase', async () => {
    const { client } = setup((call) =>
      call.url.endsWith('/graphql/') ? startRunOk() : sseResponse(happyPathEvents()),
    );
    const { result } = renderHook(() => useAgent(client, 'a1'));

    expect(result.current.phase).toBe('idle');
    expect(result.current.isActive).toBe(false);

    await act(async () => {
      await result.current.start({ endUserId: 'u1', prompt: 'hi' });
    });

    await waitFor(() => expect(result.current.phase).toBe('done'));
    expect(result.current.events.map((e) => e.type)).toEqual([
      'run_started',
      'tool_call',
      'tool_result',
      'usage_checkpoint',
      'run_completed',
    ]);
    expect(result.current.status).toBe('FINISHED');
    expect(result.current.outcome?.summary).toBe('done');
    expect(result.current.isActive).toBe(false);
  });

  it('surfaces a startRun domain failure through error/phase instead of throwing', async () => {
    const { client } = setup(() =>
      jsonResponse({
        data: {
          startRun: {
            success: false,
            errors: [{ code: 'INSUFFICIENT_CREDITS', field: null, message: 'No credits' }],
            runId: null,
            runUid: null,
            sandboxUrl: null,
            capabilityToken: null,
            tokenExpiresAt: null,
          },
        },
      }),
    );
    const { result } = renderHook(() => useAgent(client, 'a1'));

    await act(async () => {
      // start() never rejects — the failure lands in state.
      await result.current.start({ endUserId: 'u1', prompt: 'hi' });
    });

    await waitFor(() => expect(result.current.phase).toBe('error'));
    expect(result.current.error?.name).toBe('MidsphereUserError');
  });

  it('resumes from a snapshot and reuses its capability token', async () => {
    const { client, calls } = setup((call) =>
      call.url.endsWith('/graphql/') ? startRunOk() : sseResponse(happyPathEvents()),
    );

    // A server action would have produced this snapshot.
    const snapshot = (
      await client.run({ agentId: 'a1', endUserId: 'u1', prompt: 'hi' })
    ).toSnapshot();

    const { result } = renderHook(() => useAgent(client, 'a1'));
    await act(async () => {
      await result.current.resume(snapshot);
    });

    await waitFor(() => expect(result.current.phase).toBe('done'));
    const streamCall = calls.find((x) => x.url.includes('/stream'));
    expect(streamCall?.headers.authorization).toBe('Bearer hook-token');
  });

  it('reset returns the hook to idle', async () => {
    const { client } = setup((call) =>
      call.url.endsWith('/graphql/') ? startRunOk() : sseResponse(happyPathEvents()),
    );
    const { result } = renderHook(() => useAgent(client, 'a1'));

    await act(async () => {
      await result.current.start({ endUserId: 'u1', prompt: 'hi' });
    });
    await waitFor(() => expect(result.current.phase).toBe('done'));

    act(() => result.current.reset());
    expect(result.current.phase).toBe('idle');
    expect(result.current.events).toEqual([]);
    expect(result.current.outcome).toBeNull();
  });
});
