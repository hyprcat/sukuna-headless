import { describe, expect, it } from 'vitest';
import { Midsphere } from '../src/index.js';
import { MidsphereUserError } from '../src/errors.js';
import { jsonResponse, recordingFetch } from './helpers.js';

function client(handler: Parameters<typeof recordingFetch>[0]) {
  const { fetch, calls } = recordingFetch(handler);
  return { client: new Midsphere({ apiKey: 'ms_test_x', fetch }), calls };
}

/** A complete KnowledgeType payload as the backend returns it. */
const baseKnowledge = {
  id: 'KB:1',
  name: 'Product Docs',
  description: 'Official product documentation',
  kind: 'DOCUMENT',
  fileName: 'docs.pdf',
  fileSizeBytes: 204800,
  contentType: 'application/pdf',
  sourceEndpoint: '',
  isActive: true,
  createdAt: '2026-01-01T00:00:00Z',
  updatedAt: '2026-01-02T00:00:00Z',
  lastIndexedAt: '2026-01-02T01:00:00Z',
  deactivatedAt: null,
};

describe('knowledge', () => {
  it('list returns mapped nodes from edges and sends kind/isActive/first variables', async () => {
    const { client: c, calls } = client(() =>
      jsonResponse({
        data: {
          knowledgeBases: {
            edges: [{ node: baseKnowledge }],
          },
        },
      }),
    );

    const result = await c.knowledge.list({ kind: 'document', isActive: true, first: 10 });

    expect(result).toHaveLength(1);
    expect(result[0]!.id).toBe('KB:1');
    expect(result[0]!.kind).toBe('DOCUMENT');

    const body = JSON.parse(calls[0]!.body!);
    expect(body.variables).toEqual({ kind: 'document', isActive: true, first: 10 });
  });

  it('list sends null defaults when no filters are provided', async () => {
    const { client: c, calls } = client(() =>
      jsonResponse({
        data: { knowledgeBases: { edges: [] } },
      }),
    );

    await c.knowledge.list();

    const body = JSON.parse(calls[0]!.body!);
    expect(body.variables).toEqual({ kind: null, isActive: null, first: 50 });
  });

  it('get returns the knowledge base by id', async () => {
    const { client: c, calls } = client(() =>
      jsonResponse({
        data: { knowledgeBase: baseKnowledge },
      }),
    );

    const result = await c.knowledge.get('KB:1');

    expect(result).not.toBeNull();
    expect(result!.name).toBe('Product Docs');

    const body = JSON.parse(calls[0]!.body!);
    expect(body.variables).toEqual({ id: 'KB:1' });
  });

  it('get returns null when backend returns null', async () => {
    const { client: c } = client(() =>
      jsonResponse({
        data: { knowledgeBase: null },
      }),
    );

    const result = await c.knowledge.get('KB:missing');
    expect(result).toBeNull();
  });

  it('create returns the projected knowledge and sends only the provided keys', async () => {
    const { client: c, calls } = client(() =>
      jsonResponse({
        data: {
          createKnowledge: {
            success: true,
            errors: [],
            knowledge: baseKnowledge,
          },
        },
      }),
    );

    const result = await c.knowledge.create({ name: 'Product Docs', kind: 'document' });

    expect(result.id).toBe('KB:1');
    expect(result.kind).toBe('DOCUMENT');

    const body = JSON.parse(calls[0]!.body!);
    // Only the two required keys — no undefineds leaked in
    expect(body.variables.input).toEqual({ name: 'Product Docs', kind: 'document' });
  });

  it('create includes optional fields when provided', async () => {
    const { client: c, calls } = client(() =>
      jsonResponse({
        data: {
          createKnowledge: {
            success: true,
            errors: [],
            knowledge: {
              ...baseKnowledge,
              description: 'A great doc',
              sourceEndpoint: 'https://example.com',
            },
          },
        },
      }),
    );

    await c.knowledge.create({
      name: 'Product Docs',
      kind: 'document',
      description: 'A great doc',
      sourceEndpoint: 'https://example.com',
      sourceConfig: { token: 'abc' },
    });

    const body = JSON.parse(calls[0]!.body!);
    expect(body.variables.input).toEqual({
      name: 'Product Docs',
      kind: 'document',
      description: 'A great doc',
      sourceEndpoint: 'https://example.com',
      sourceConfig: { token: 'abc' },
    });
  });

  it('create surfaces a domain failure as MidsphereUserError', async () => {
    const { client: c } = client(() =>
      jsonResponse({
        data: {
          createKnowledge: {
            success: false,
            errors: [{ code: 'INVALID_INPUT', field: 'kind', message: 'Invalid kind value' }],
            knowledge: null,
          },
        },
      }),
    );

    await expect(c.knowledge.create({ name: 'Bad KB', kind: 'document' })).rejects.toBeInstanceOf(
      MidsphereUserError,
    );
  });

  it('update sends only provided keys plus the id variable', async () => {
    const updated = { ...baseKnowledge, name: 'Renamed Docs', updatedAt: '2026-02-01T00:00:00Z' };
    const { client: c, calls } = client(() =>
      jsonResponse({
        data: {
          updateKnowledge: {
            success: true,
            errors: [],
            knowledge: updated,
          },
        },
      }),
    );

    const result = await c.knowledge.update('KB:1', { name: 'Renamed Docs' });

    expect(result.name).toBe('Renamed Docs');

    const body = JSON.parse(calls[0]!.body!);
    expect(body.variables.id).toBe('KB:1');
    // Only the one provided key — description/sourceEndpoint/sourceConfig not present
    expect(body.variables.input).toEqual({ name: 'Renamed Docs' });
  });

  it('activate returns the updated knowledge base', async () => {
    const activated = { ...baseKnowledge, isActive: true, deactivatedAt: null };
    const { client: c, calls } = client(() =>
      jsonResponse({
        data: {
          activateKnowledge: {
            success: true,
            errors: [],
            knowledge: activated,
          },
        },
      }),
    );

    const result = await c.knowledge.activate('KB:1');

    expect(result.isActive).toBe(true);
    const body = JSON.parse(calls[0]!.body!);
    expect(body.variables).toEqual({ id: 'KB:1' });
  });

  it('deactivate returns the updated knowledge base with deactivatedAt set', async () => {
    const deactivated = {
      ...baseKnowledge,
      isActive: false,
      deactivatedAt: '2026-06-21T00:00:00Z',
    };
    const { client: c, calls } = client(() =>
      jsonResponse({
        data: {
          deactivateKnowledge: {
            success: true,
            errors: [],
            knowledge: deactivated,
          },
        },
      }),
    );

    const result = await c.knowledge.deactivate('KB:1');

    expect(result.isActive).toBe(false);
    expect(result.deactivatedAt).toBe('2026-06-21T00:00:00Z');
    const body = JSON.parse(calls[0]!.body!);
    expect(body.variables).toEqual({ id: 'KB:1' });
  });

  it('reindex sends the id and returns knowledge with updated lastIndexedAt', async () => {
    const reindexed = {
      ...baseKnowledge,
      lastIndexedAt: '2026-06-21T12:00:00Z',
      updatedAt: '2026-06-21T12:00:00Z',
    };
    const { client: c, calls } = client(() =>
      jsonResponse({
        data: {
          reindexKnowledge: {
            success: true,
            errors: [],
            knowledge: reindexed,
          },
        },
      }),
    );

    const result = await c.knowledge.reindex('KB:1');

    expect(result.lastIndexedAt).toBe('2026-06-21T12:00:00Z');
    const body = JSON.parse(calls[0]!.body!);
    expect(body.variables).toEqual({ id: 'KB:1' });
  });
});
