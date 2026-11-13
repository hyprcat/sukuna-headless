import { describe, expect, it } from 'vitest';
import { Midsphere } from '../src/index.js';
import { MidsphereApiError } from '../src/errors.js';
import { jsonResponse, recordingFetch } from './helpers.js';

describe('GraphQL transport', () => {
  it('sends the API key as a Bearer token to the configured GraphQL endpoint', async () => {
    const { fetch, calls } = recordingFetch(() => jsonResponse({ data: { health: 'ok' } }));
    const client = new Midsphere({
      apiKey: 'ms_test_abc',
      baseUrl: 'http://localhost:8000',
      fetch,
    });

    const data = await client.gql.request<{ health: string }>('{ health }');

    expect(data.health).toBe('ok');
    expect(calls[0]?.url).toBe('http://localhost:8000/graphql/');
    expect(calls[0]?.headers.authorization).toBe('Bearer ms_test_abc');
  });

  it('throws MidsphereApiError on top-level GraphQL errors', async () => {
    const { fetch } = recordingFetch(() =>
      jsonResponse({ errors: [{ message: 'Not authenticated' }] }),
    );
    const client = new Midsphere({ apiKey: 'ms_test_abc', fetch });

    await expect(client.gql.request('{ health }')).rejects.toThrowError(MidsphereApiError);
  });

  it('throws MidsphereApiError with status on a non-2xx response', async () => {
    const { fetch } = recordingFetch(() =>
      jsonResponse({ errors: [{ message: 'Unauthorized' }] }, 401),
    );
    const client = new Midsphere({ apiKey: 'bad', fetch });

    await expect(client.gql.request('{ health }')).rejects.toMatchObject({
      name: 'MidsphereApiError',
      status: 401,
    });
  });

  it('requires an API key', () => {
    expect(() => new Midsphere({ apiKey: '' })).toThrowError(/apiKey/);
  });
});
