/**
 * Full CRUD lifecycle for the workspace's tools — create, read, activate, and
 * deactivate. There is no hard-delete; lifecycle is activate/deactivate only.
 */

import type { GraphQLClient } from '../graphql.js';
import { ensureSuccess } from '../internal/mutation.js';
import type { Tool, CreateToolInput, UpdateToolInput, UserError } from '../types.js';

// ---------------------------------------------------------------------------
// Shared fragment string
// ---------------------------------------------------------------------------

const TOOL_FIELDS =
  'id name description parametersSchema executionEndpoint isSensitive isActive createdAt updatedAt deactivatedAt';

// ---------------------------------------------------------------------------
// Queries & mutations
// ---------------------------------------------------------------------------

const LIST_TOOLS = /* GraphQL */ `
  query Tools($isActive: Boolean, $first: Int) {
    tools(isActive: $isActive, first: $first) {
      edges {
        node {
          ${TOOL_FIELDS}
        }
      }
    }
  }
`;

const GET_TOOL = /* GraphQL */ `
  query Tool($id: ID!) {
    tool(id: $id) {
      ${TOOL_FIELDS}
    }
  }
`;

const CREATE_TOOL = /* GraphQL */ `
  mutation CreateTool($input: CreateToolInput!) {
    createTool(input: $input) {
      success
      errors { code field message }
      tool { ${TOOL_FIELDS} }
    }
  }
`;

const UPDATE_TOOL = /* GraphQL */ `
  mutation UpdateTool($id: ID!, $input: UpdateToolInput!) {
    updateTool(id: $id, input: $input) {
      success
      errors { code field message }
      tool { ${TOOL_FIELDS} }
    }
  }
`;

const ACTIVATE_TOOL = /* GraphQL */ `
  mutation ActivateTool($id: ID!) {
    activateTool(id: $id) {
      success
      errors { code field message }
      tool { ${TOOL_FIELDS} }
    }
  }
`;

const DEACTIVATE_TOOL = /* GraphQL */ `
  mutation DeactivateTool($id: ID!) {
    deactivateTool(id: $id) {
      success
      errors { code field message }
      tool { ${TOOL_FIELDS} }
    }
  }
`;

// ---------------------------------------------------------------------------
// Internal payload types
// ---------------------------------------------------------------------------

interface ToolPayload {
  success: boolean;
  errors: UserError[];
  tool: Tool | null;
}

// ---------------------------------------------------------------------------
// Resource class
// ---------------------------------------------------------------------------

/**
 * Full CRUD lifecycle for the workspace's tools.
 *
 * Tools can be created, updated, activated, and deactivated. There is no
 * hard-delete — lifecycle is activate/deactivate only.
 *
 * Requires the `tools:read` scope for queries and `tools:write` for mutations.
 */
export class Tools {
  constructor(private readonly gql: GraphQLClient) {}

  /**
   * Returns all tools in the workspace, optionally filtered by active status.
   *
   * @param opts.isActive - When set, only returns tools with that active status.
   * @param opts.first - Maximum number of tools to return (default 50).
   * @param opts.signal - Optional abort signal to cancel the request.
   */
  async list(
    opts: { isActive?: boolean; first?: number; signal?: AbortSignal } = {},
  ): Promise<Tool[]> {
    const o = opts.signal ? { signal: opts.signal } : undefined;
    const res = await this.gql.request<{ tools: { edges: { node: Tool }[] } }>(
      LIST_TOOLS,
      { isActive: opts.isActive ?? null, first: opts.first ?? 50 },
      o,
    );
    return res.tools.edges.map((e) => e.node);
  }

  /**
   * Returns the tool with the given relay global ID, or `null` if not found.
   *
   * @param id - The relay global ID of the tool.
   * @param opts.signal - Optional abort signal to cancel the request.
   */
  async get(id: string, opts: { signal?: AbortSignal } = {}): Promise<Tool | null> {
    const o = opts.signal ? { signal: opts.signal } : undefined;
    const res = await this.gql.request<{ tool: Tool | null }>(GET_TOOL, { id }, o);
    return res.tool ?? null;
  }

  /**
   * Creates a new tool. Throws a `MidsphereUserError` if the backend returns
   * domain errors (e.g. invalid input, duplicate name).
   *
   * Only the keys you provide are sent in the mutation input.
   *
   * @param input.name - The tool's display name (required).
   * @param input.description - Optional human-readable description.
   * @param input.parametersSchema - JSON Schema describing the tool's parameters.
   * @param input.executionEndpoint - URL the backend calls to invoke this tool.
   * @param input.isSensitive - When true, output is redacted in run logs.
   * @param opts.signal - Optional abort signal to cancel the request.
   */
  async create(input: CreateToolInput, opts: { signal?: AbortSignal } = {}): Promise<Tool> {
    const mutationInput: Record<string, unknown> = { name: input.name };
    if (input.description !== undefined) mutationInput['description'] = input.description;
    if (input.parametersSchema !== undefined)
      mutationInput['parametersSchema'] = input.parametersSchema;
    if (input.executionEndpoint !== undefined)
      mutationInput['executionEndpoint'] = input.executionEndpoint;
    if (input.isSensitive !== undefined) mutationInput['isSensitive'] = input.isSensitive;

    const o = opts.signal ? { signal: opts.signal } : undefined;
    const res = await this.gql.request<{ createTool: ToolPayload }>(
      CREATE_TOOL,
      { input: mutationInput },
      o,
    );
    const payload = ensureSuccess(res.createTool);
    // ensureSuccess guarantees success=true, so tool is present on the payload
    return payload.tool!;
  }

  /**
   * Updates mutable fields on an existing tool. Omit any field you don't want
   * to change. Throws a `MidsphereUserError` on domain failure.
   *
   * @param id - Relay global ID of the tool.
   * @param input - Fields to update; omit any you don't want to change.
   * @param opts.signal - Optional abort signal to cancel the request.
   */
  async update(
    id: string,
    input: UpdateToolInput,
    opts: { signal?: AbortSignal } = {},
  ): Promise<Tool> {
    const mutationInput: Record<string, unknown> = {};
    if (input.name !== undefined) mutationInput['name'] = input.name;
    if (input.description !== undefined) mutationInput['description'] = input.description;
    if (input.parametersSchema !== undefined)
      mutationInput['parametersSchema'] = input.parametersSchema;
    if (input.executionEndpoint !== undefined)
      mutationInput['executionEndpoint'] = input.executionEndpoint;
    if (input.isSensitive !== undefined) mutationInput['isSensitive'] = input.isSensitive;

    const o = opts.signal ? { signal: opts.signal } : undefined;
    const res = await this.gql.request<{ updateTool: ToolPayload }>(
      UPDATE_TOOL,
      { id, input: mutationInput },
      o,
    );
    const payload = ensureSuccess(res.updateTool);
    // ensureSuccess guarantees success=true, so tool is present on the payload
    return payload.tool!;
  }

  /**
   * Activates a previously deactivated tool, making it available for runs.
   * Throws a `MidsphereUserError` if the tool does not exist or the transition
   * is not allowed.
   *
   * @param id - Relay global ID of the tool.
   * @param opts.signal - Optional abort signal to cancel the request.
   */
  async activate(id: string, opts: { signal?: AbortSignal } = {}): Promise<Tool> {
    const o = opts.signal ? { signal: opts.signal } : undefined;
    const res = await this.gql.request<{ activateTool: ToolPayload }>(ACTIVATE_TOOL, { id }, o);
    const payload = ensureSuccess(res.activateTool);
    // ensureSuccess guarantees success=true, so tool is present on the payload
    return payload.tool!;
  }

  /**
   * Deactivates a tool, preventing it from being used in future runs. The tool
   * is not deleted — it can be reactivated at any time.
   * Throws a `MidsphereUserError` if the tool does not exist or is already
   * deactivated.
   *
   * @param id - Relay global ID of the tool.
   * @param opts.signal - Optional abort signal to cancel the request.
   */
  async deactivate(id: string, opts: { signal?: AbortSignal } = {}): Promise<Tool> {
    const o = opts.signal ? { signal: opts.signal } : undefined;
    const res = await this.gql.request<{ deactivateTool: ToolPayload }>(DEACTIVATE_TOOL, { id }, o);
    const payload = ensureSuccess(res.deactivateTool);
    // ensureSuccess guarantees success=true, so tool is present on the payload
    return payload.tool!;
  }
}
