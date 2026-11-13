/**
 * Create, read, and manage the workspace's knowledge bases.
 */

import type { GraphQLClient } from '../graphql.js';
import { ensureSuccess } from '../internal/mutation.js';
import type { Knowledge, CreateKnowledgeInput, UpdateKnowledgeInput, UserError } from '../types.js';

// ---------------------------------------------------------------------------
// Shared fragment string
// ---------------------------------------------------------------------------

const KNOWLEDGE_FIELDS =
  'id name description kind fileName fileSizeBytes contentType sourceEndpoint isActive createdAt updatedAt lastIndexedAt deactivatedAt';

// ---------------------------------------------------------------------------
// Queries & mutations
// ---------------------------------------------------------------------------

const LIST_KNOWLEDGE_BASES = /* GraphQL */ `
  query KnowledgeBases($kind: String, $isActive: Boolean, $first: Int) {
    knowledgeBases(kind: $kind, isActive: $isActive, first: $first) {
      edges {
        node {
          ${KNOWLEDGE_FIELDS}
        }
      }
    }
  }
`;

const GET_KNOWLEDGE_BASE = /* GraphQL */ `
  query KnowledgeBase($id: ID!) {
    knowledgeBase(id: $id) {
      ${KNOWLEDGE_FIELDS}
    }
  }
`;

const CREATE_KNOWLEDGE = /* GraphQL */ `
  mutation CreateKnowledge($input: CreateKnowledgeInput!) {
    createKnowledge(input: $input) {
      success
      errors { code field message }
      knowledge { ${KNOWLEDGE_FIELDS} }
    }
  }
`;

const UPDATE_KNOWLEDGE = /* GraphQL */ `
  mutation UpdateKnowledge($id: ID!, $input: UpdateKnowledgeInput!) {
    updateKnowledge(id: $id, input: $input) {
      success
      errors { code field message }
      knowledge { ${KNOWLEDGE_FIELDS} }
    }
  }
`;

const ACTIVATE_KNOWLEDGE = /* GraphQL */ `
  mutation ActivateKnowledge($id: ID!) {
    activateKnowledge(id: $id) {
      success
      errors { code field message }
      knowledge { ${KNOWLEDGE_FIELDS} }
    }
  }
`;

const DEACTIVATE_KNOWLEDGE = /* GraphQL */ `
  mutation DeactivateKnowledge($id: ID!) {
    deactivateKnowledge(id: $id) {
      success
      errors { code field message }
      knowledge { ${KNOWLEDGE_FIELDS} }
    }
  }
`;

const REINDEX_KNOWLEDGE = /* GraphQL */ `
  mutation ReindexKnowledge($id: ID!) {
    reindexKnowledge(id: $id) {
      success
      errors { code field message }
      knowledge { ${KNOWLEDGE_FIELDS} }
    }
  }
`;

// ---------------------------------------------------------------------------
// Internal payload types
// ---------------------------------------------------------------------------

interface KnowledgePayload {
  success: boolean;
  errors: UserError[];
  knowledge: Knowledge | null;
}

// ---------------------------------------------------------------------------
// Resource class
// ---------------------------------------------------------------------------

/**
 * Create, read, and manage the workspace's knowledge bases.
 *
 * Knowledge bases are document stores, datasets, or connected sources that
 * agents can retrieve context from during a run. The lifecycle is
 * activate/deactivate — there is no hard-delete.
 *
 * Access requires the `knowledge:read` scope for queries and
 * `knowledge:write` for mutations.
 */
export class KnowledgeBases {
  constructor(private readonly gql: GraphQLClient) {}

  /**
   * Returns all knowledge bases in the workspace, optionally filtered.
   *
   * @param opts.kind - When set, only returns knowledge bases of that kind
   *   (e.g. `'document'`, `'dataset'`, `'connected_source'`).
   * @param opts.isActive - When set, only returns knowledge bases with that
   *   active status.
   * @param opts.first - Maximum number of results to return (default 50).
   * @param opts.signal - Optional abort signal to cancel the request.
   */
  async list(
    opts: { kind?: string; isActive?: boolean; first?: number; signal?: AbortSignal } = {},
  ): Promise<Knowledge[]> {
    const o = opts.signal ? { signal: opts.signal } : undefined;
    const res = await this.gql.request<{
      knowledgeBases: { edges: { node: Knowledge }[] };
    }>(
      LIST_KNOWLEDGE_BASES,
      { kind: opts.kind ?? null, isActive: opts.isActive ?? null, first: opts.first ?? 50 },
      o,
    );
    return res.knowledgeBases.edges.map((e) => e.node);
  }

  /**
   * Returns the knowledge base with the given relay global ID, or `null` if
   * not found.
   *
   * @param id - Relay global ID of the knowledge base.
   * @param opts.signal - Optional abort signal to cancel the request.
   */
  async get(id: string, opts: { signal?: AbortSignal } = {}): Promise<Knowledge | null> {
    const o = opts.signal ? { signal: opts.signal } : undefined;
    const res = await this.gql.request<{ knowledgeBase: Knowledge | null }>(
      GET_KNOWLEDGE_BASE,
      { id },
      o,
    );
    return res.knowledgeBase ?? null;
  }

  /**
   * Creates a new knowledge base. Throws a `MidsphereUserError` if the backend
   * returns domain errors (e.g. duplicate name, invalid kind).
   *
   * @param input.name - Human-readable name for the knowledge base.
   * @param input.kind - One of `'document'`, `'dataset'`, or `'connected_source'`.
   * @param input.description - Optional description.
   * @param input.sourceEndpoint - Optional URL for connected sources.
   * @param input.sourceConfig - Optional JSON config for connected sources.
   * @param opts.signal - Optional abort signal to cancel the request.
   */
  async create(
    input: CreateKnowledgeInput,
    opts: { signal?: AbortSignal } = {},
  ): Promise<Knowledge> {
    const mutationInput: Record<string, unknown> = { name: input.name, kind: input.kind };
    if (input.description !== undefined) mutationInput['description'] = input.description;
    if (input.sourceEndpoint !== undefined) mutationInput['sourceEndpoint'] = input.sourceEndpoint;
    if (input.sourceConfig !== undefined) mutationInput['sourceConfig'] = input.sourceConfig;

    const o = opts.signal ? { signal: opts.signal } : undefined;
    const res = await this.gql.request<{ createKnowledge: KnowledgePayload }>(
      CREATE_KNOWLEDGE,
      { input: mutationInput },
      o,
    );
    const payload = ensureSuccess(res.createKnowledge);
    // ensureSuccess guarantees success=true, so knowledge is present
    return payload.knowledge!;
  }

  /**
   * Updates mutable fields on an existing knowledge base. Omit any field you
   * don't want to change.
   *
   * @param id - Relay global ID of the knowledge base.
   * @param input - Fields to update; all optional.
   * @param opts.signal - Optional abort signal to cancel the request.
   */
  async update(
    id: string,
    input: UpdateKnowledgeInput,
    opts: { signal?: AbortSignal } = {},
  ): Promise<Knowledge> {
    const mutationInput: Record<string, unknown> = {};
    if (input.name !== undefined) mutationInput['name'] = input.name;
    if (input.description !== undefined) mutationInput['description'] = input.description;
    if (input.sourceEndpoint !== undefined) mutationInput['sourceEndpoint'] = input.sourceEndpoint;
    if (input.sourceConfig !== undefined) mutationInput['sourceConfig'] = input.sourceConfig;

    const o = opts.signal ? { signal: opts.signal } : undefined;
    const res = await this.gql.request<{ updateKnowledge: KnowledgePayload }>(
      UPDATE_KNOWLEDGE,
      { id, input: mutationInput },
      o,
    );
    const payload = ensureSuccess(res.updateKnowledge);
    // ensureSuccess guarantees success=true, so knowledge is present
    return payload.knowledge!;
  }

  /**
   * Activates a previously deactivated knowledge base, making it available to
   * agents during runs. Throws a `MidsphereUserError` on domain failure.
   *
   * @param id - Relay global ID of the knowledge base.
   * @param opts.signal - Optional abort signal to cancel the request.
   */
  async activate(id: string, opts: { signal?: AbortSignal } = {}): Promise<Knowledge> {
    const o = opts.signal ? { signal: opts.signal } : undefined;
    const res = await this.gql.request<{ activateKnowledge: KnowledgePayload }>(
      ACTIVATE_KNOWLEDGE,
      { id },
      o,
    );
    const payload = ensureSuccess(res.activateKnowledge);
    // ensureSuccess guarantees success=true, so knowledge is present
    return payload.knowledge!;
  }

  /**
   * Deactivates a knowledge base so it is no longer available to agents during
   * runs. There is no hard-delete — use `activate` to reverse this.
   * Throws a `MidsphereUserError` on domain failure.
   *
   * @param id - Relay global ID of the knowledge base.
   * @param opts.signal - Optional abort signal to cancel the request.
   */
  async deactivate(id: string, opts: { signal?: AbortSignal } = {}): Promise<Knowledge> {
    const o = opts.signal ? { signal: opts.signal } : undefined;
    const res = await this.gql.request<{ deactivateKnowledge: KnowledgePayload }>(
      DEACTIVATE_KNOWLEDGE,
      { id },
      o,
    );
    const payload = ensureSuccess(res.deactivateKnowledge);
    // ensureSuccess guarantees success=true, so knowledge is present
    return payload.knowledge!;
  }

  /**
   * Triggers a re-index of the knowledge base's content. Use this after
   * uploading new documents or updating a connected source. Returns the updated
   * knowledge base with a refreshed `lastIndexedAt`. Throws a
   * `MidsphereUserError` on domain failure.
   *
   * @param id - Relay global ID of the knowledge base.
   * @param opts.signal - Optional abort signal to cancel the request.
   */
  async reindex(id: string, opts: { signal?: AbortSignal } = {}): Promise<Knowledge> {
    const o = opts.signal ? { signal: opts.signal } : undefined;
    const res = await this.gql.request<{ reindexKnowledge: KnowledgePayload }>(
      REINDEX_KNOWLEDGE,
      { id },
      o,
    );
    const payload = ensureSuccess(res.reindexKnowledge);
    // ensureSuccess guarantees success=true, so knowledge is present
    return payload.knowledge!;
  }
}
