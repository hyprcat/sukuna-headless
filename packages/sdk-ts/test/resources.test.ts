import { describe, expect, it } from 'vitest';
import { Midsphere } from '../src/index.js';
import { MidsphereUserError } from '../src/errors.js';
import { jsonResponse, recordingFetch } from './helpers.js';

function client(handler: Parameters<typeof recordingFetch>[0]) {
  const { fetch, calls } = recordingFetch(handler);
  return { client: new Midsphere({ apiKey: 'ms_test_x', fetch }), calls };
}

describe('endUsers', () => {
  it('creates an end user and returns the projected row', async () => {
    const { client: c, calls } = client(() =>
      jsonResponse({
        data: {
          createEndUser: {
            success: true,
            errors: [],
            endUser: {
              id: 'EU:1',
              externalUserId: 'auth_123',
              displayName: 'Ada',
              tierLabel: 'pro',
              metadata: {},
              isActive: true,
            },
          },
        },
      }),
    );
    const user = await c.endUsers.create({ externalUserId: 'auth_123', displayName: 'Ada' });
    expect(user.externalUserId).toBe('auth_123');
    // Only provided keys are sent.
    const body = JSON.parse(calls[0]!.body!);
    expect(body.variables.input).toEqual({ externalUserId: 'auth_123', displayName: 'Ada' });
  });

  it('surfaces a domain failure as MidsphereUserError', async () => {
    const { client: c } = client(() =>
      jsonResponse({
        data: {
          createEndUser: {
            success: false,
            errors: [{ code: 'CONFLICT', field: 'externalUserId', message: 'Already exists' }],
            endUser: null,
          },
        },
      }),
    );
    await expect(c.endUsers.create({ externalUserId: 'dup' })).rejects.toBeInstanceOf(
      MidsphereUserError,
    );
  });

  it('getByExternalId exact-matches the fuzzy search results', async () => {
    const { client: c } = client(() =>
      jsonResponse({
        data: {
          endUsers: {
            edges: [
              {
                node: {
                  id: 'EU:1',
                  externalUserId: 'auth_1',
                  displayName: '',
                  tierLabel: '',
                  metadata: {},
                  isActive: true,
                },
              },
              {
                node: {
                  id: 'EU:2',
                  externalUserId: 'auth_12',
                  displayName: '',
                  tierLabel: '',
                  metadata: {},
                  isActive: true,
                },
              },
            ],
          },
        },
      }),
    );
    const user = await c.endUsers.getByExternalId('auth_1');
    expect(user?.id).toBe('EU:1');
  });
});

describe('ratings', () => {
  it('maps runUid to the runId GraphQL field', async () => {
    const { client: c, calls } = client(() =>
      jsonResponse({ data: { submitRating: { success: true, errors: [] } } }),
    );
    await c.ratings.submit({ runUid: 'run-uuid', score: 5, comment: 'great' });
    const body = JSON.parse(calls[0]!.body!);
    expect(body.variables.input).toEqual({ runId: 'run-uuid', score: 5, comment: 'great' });
  });
});
