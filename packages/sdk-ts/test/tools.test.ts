import { describe, expect, it } from 'vitest';
import { Midsphere } from '../src/index.js';
import { MidsphereUserError } from '../src/errors.js';
import { jsonResponse, recordingFetch } from './helpers.js';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function client(handler: Parameters<typeof recordingFetch>[0]) {
  const { fetch, calls } = recordingFetch(handler);
  return { client: new Midsphere({ apiKey: 'ms_test_x', fetch }), calls };
}

/** A complete, realistic ToolType fixture. */
const fakeTool = {
  id: 'T:1',
  name: 'web_search',
  description: 'Search the web and return results.',
  parametersSchema: {
    type: 'object',
    properties: { query: { type: 'string' } },
    required: ['query'],
  },
  executionEndpoint: 'https://tools.example.com/web_search',
  isSensitive: false,
  isActive: true,
  createdAt: '2026-06-21T00:00:00Z',
  updatedAt: '2026-06-21T00:00:00Z',
  deactivatedAt: null,
};

// ---------------------------------------------------------------------------
// list
// ---------------------------------------------------------------------------

describe('tools.list', () => {
  it('returns the mapped nodes from edges', async () => {
    const { client: c } = client(() =>
      jsonResponse({
        data: {
          tools: {
            edges: [{ node: fakeTool }],
          },
        },
      }),
    );
    const tools = await c.tools.list();
    expect(tools).toHaveLength(1);
    expect(tools[0]).toEqual(fakeTool);
  });

  it('sends isActive and first variables', async () => {
    const { client: c, calls } = client(() => jsonResponse({ data: { tools: { edges: [] } } }));
    await c.tools.list({ isActive: true, first: 10 });
    const body = JSON.parse(calls[0]!.body!);
    expect(body.variables).toEqual({ isActive: true, first: 10 });
  });

  it('defaults isActive to null and first to 50', async () => {
    const { client: c, calls } = client(() => jsonResponse({ data: { tools: { edges: [] } } }));
    await c.tools.list();
    const body = JSON.parse(calls[0]!.body!);
    expect(body.variables).toEqual({ isActive: null, first: 50 });
  });
});

// ---------------------------------------------------------------------------
// get
// ---------------------------------------------------------------------------

describe('tools.get', () => {
  it('returns the tool when found', async () => {
    const { client: c } = client(() => jsonResponse({ data: { tool: fakeTool } }));
    const tool = await c.tools.get('T:1');
    expect(tool).toEqual(fakeTool);
  });

  it('returns null when the backend returns null', async () => {
    const { client: c } = client(() => jsonResponse({ data: { tool: null } }));
    const tool = await c.tools.get('T:nonexistent');
    expect(tool).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// create
// ---------------------------------------------------------------------------

describe('tools.create', () => {
  it('returns the projected tool on success', async () => {
    const { client: c } = client(() =>
      jsonResponse({
        data: {
          createTool: { success: true, errors: [], tool: fakeTool },
        },
      }),
    );
    const tool = await c.tools.create({
      name: 'web_search',
      executionEndpoint: 'https://tools.example.com/web_search',
    });
    expect(tool).toEqual(fakeTool);
  });

  it('sends only the provided keys in variables.input', async () => {
    const { client: c, calls } = client(() =>
      jsonResponse({
        data: {
          createTool: { success: true, errors: [], tool: fakeTool },
        },
      }),
    );
    await c.tools.create({
      name: 'web_search',
      executionEndpoint: 'https://tools.example.com/web_search',
    });
    const body = JSON.parse(calls[0]!.body!);
    expect(body.variables.input).toEqual({
      name: 'web_search',
      executionEndpoint: 'https://tools.example.com/web_search',
    });
  });

  it('includes all provided optional fields in the input', async () => {
    const { client: c, calls } = client(() =>
      jsonResponse({
        data: {
          createTool: { success: true, errors: [], tool: fakeTool },
        },
      }),
    );
    await c.tools.create({
      name: 'web_search',
      description: 'Search the web.',
      parametersSchema: { type: 'object' },
      executionEndpoint: 'https://tools.example.com/web_search',
      isSensitive: false,
    });
    const body = JSON.parse(calls[0]!.body!);
    expect(body.variables.input).toEqual({
      name: 'web_search',
      description: 'Search the web.',
      parametersSchema: { type: 'object' },
      executionEndpoint: 'https://tools.example.com/web_search',
      isSensitive: false,
    });
  });

  it('surfaces a domain failure as MidsphereUserError', async () => {
    const { client: c } = client(() =>
      jsonResponse({
        data: {
          createTool: {
            success: false,
            errors: [{ code: 'INVALID_INPUT', field: 'name', message: 'Name is required.' }],
            tool: null,
          },
        },
      }),
    );
    await expect(c.tools.create({ name: '' })).rejects.toBeInstanceOf(MidsphereUserError);
  });

  it('exposes the error code on the thrown MidsphereUserError', async () => {
    const { client: c } = client(() =>
      jsonResponse({
        data: {
          createTool: {
            success: false,
            errors: [
              { code: 'CONFLICT', field: 'name', message: 'A tool with this name already exists.' },
            ],
            tool: null,
          },
        },
      }),
    );
    const err = await c.tools.create({ name: 'web_search' }).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(MidsphereUserError);
    expect((err as MidsphereUserError).code).toBe('CONFLICT');
  });
});

// ---------------------------------------------------------------------------
// update
// ---------------------------------------------------------------------------

describe('tools.update', () => {
  it('returns the updated tool on success', async () => {
    const updated = { ...fakeTool, name: 'web_search_v2' };
    const { client: c } = client(() =>
      jsonResponse({
        data: { updateTool: { success: true, errors: [], tool: updated } },
      }),
    );
    const tool = await c.tools.update('T:1', { name: 'web_search_v2' });
    expect(tool.name).toBe('web_search_v2');
  });

  it('sends only provided keys plus the id variable', async () => {
    const { client: c, calls } = client(() =>
      jsonResponse({
        data: { updateTool: { success: true, errors: [], tool: fakeTool } },
      }),
    );
    await c.tools.update('T:1', { description: 'Updated description.' });
    const body = JSON.parse(calls[0]!.body!);
    expect(body.variables.id).toBe('T:1');
    expect(body.variables.input).toEqual({ description: 'Updated description.' });
  });

  it('does not include omitted fields in the mutation input', async () => {
    const { client: c, calls } = client(() =>
      jsonResponse({
        data: { updateTool: { success: true, errors: [], tool: fakeTool } },
      }),
    );
    await c.tools.update('T:1', { isSensitive: true });
    const body = JSON.parse(calls[0]!.body!);
    expect(body.variables.input).toEqual({ isSensitive: true });
    expect(body.variables.input).not.toHaveProperty('name');
    expect(body.variables.input).not.toHaveProperty('description');
  });
});

// ---------------------------------------------------------------------------
// activate
// ---------------------------------------------------------------------------

describe('tools.activate', () => {
  it('sends the id and returns the tool', async () => {
    const active = { ...fakeTool, isActive: true, deactivatedAt: null };
    const { client: c, calls } = client(() =>
      jsonResponse({
        data: { activateTool: { success: true, errors: [], tool: active } },
      }),
    );
    const tool = await c.tools.activate('T:1');
    expect(tool.isActive).toBe(true);
    const body = JSON.parse(calls[0]!.body!);
    expect(body.variables).toEqual({ id: 'T:1' });
  });
});

// ---------------------------------------------------------------------------
// deactivate
// ---------------------------------------------------------------------------

describe('tools.deactivate', () => {
  it('sends the id and returns the deactivated tool', async () => {
    const inactive = { ...fakeTool, isActive: false, deactivatedAt: '2026-06-21T12:00:00Z' };
    const { client: c, calls } = client(() =>
      jsonResponse({
        data: { deactivateTool: { success: true, errors: [], tool: inactive } },
      }),
    );
    const tool = await c.tools.deactivate('T:1');
    expect(tool.isActive).toBe(false);
    expect(tool.deactivatedAt).toBe('2026-06-21T12:00:00Z');
    const body = JSON.parse(calls[0]!.body!);
    expect(body.variables).toEqual({ id: 'T:1' });
  });
});
