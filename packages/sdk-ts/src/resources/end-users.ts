/**
 * Create, read, and configure the developer's end users.
 */

import type { GraphQLClient } from '../graphql.js';
import { ensureSuccess } from '../internal/mutation.js';
import type { EndUser, EndUserControls, UserError } from '../types.js';

// ---------------------------------------------------------------------------
// Shared fragment string
// ---------------------------------------------------------------------------

const END_USER_FIELDS = 'id externalUserId displayName tierLabel metadata isActive';

// ---------------------------------------------------------------------------
// Queries & mutations
// ---------------------------------------------------------------------------

const LIST_END_USERS = /* GraphQL */ `
  query EndUsers($search: String, $isActive: Boolean, $first: Int) {
    endUsers(search: $search, isActive: $isActive, first: $first) {
      edges {
        node {
          ${END_USER_FIELDS}
        }
      }
    }
  }
`;

const GET_END_USER = /* GraphQL */ `
  query EndUser($id: ID!) {
    endUser(id: $id) {
      ${END_USER_FIELDS}
    }
  }
`;

const CREATE_END_USER = /* GraphQL */ `
  mutation CreateEndUser($input: CreateEndUserInput!) {
    createEndUser(input: $input) {
      success
      errors { code field message }
      endUser { ${END_USER_FIELDS} }
    }
  }
`;

const UPDATE_END_USER = /* GraphQL */ `
  mutation UpdateEndUser($id: ID!, $input: UpdateEndUserInput!) {
    updateEndUser(id: $id, input: $input) {
      success
      errors { code field message }
      endUser { ${END_USER_FIELDS} }
    }
  }
`;

const UPDATE_END_USER_CONTROLS = /* GraphQL */ `
  mutation UpdateEndUserControls($input: UpdateEndUserControlsInput!) {
    updateEndUserControls(input: $input) {
      success
      errors { code field message }
      endUser { ${END_USER_FIELDS} }
    }
  }
`;

// ---------------------------------------------------------------------------
// Internal payload types
// ---------------------------------------------------------------------------

interface EndUserPayload {
  success: boolean;
  errors: UserError[];
  endUser: EndUser | null;
}

// ---------------------------------------------------------------------------
// Resource class
// ---------------------------------------------------------------------------

/** Create, read, and configure the developer's end users. */
export class EndUsers {
  constructor(private readonly gql: GraphQLClient) {}

  /**
   * Creates a new end user. Throws a `MidsphereUserError` if the backend
   * returns domain errors (e.g. duplicate `externalUserId`).
   *
   * @param input.externalUserId - Your system's stable identifier for this user.
   * @param opts.signal - Optional abort signal to cancel the request.
   */
  async create(
    input: {
      externalUserId: string;
      displayName?: string;
      tierLabel?: string;
      metadata?: Record<string, unknown>;
    },
    opts: { signal?: AbortSignal } = {},
  ): Promise<EndUser> {
    const mutationInput: Record<string, unknown> = { externalUserId: input.externalUserId };
    if (input.displayName !== undefined) mutationInput['displayName'] = input.displayName;
    if (input.tierLabel !== undefined) mutationInput['tierLabel'] = input.tierLabel;
    if (input.metadata !== undefined) mutationInput['metadata'] = input.metadata;

    const o = opts.signal ? { signal: opts.signal } : undefined;
    const res = await this.gql.request<{ createEndUser: EndUserPayload }>(
      CREATE_END_USER,
      { input: mutationInput },
      o,
    );
    const payload = ensureSuccess(res.createEndUser);
    // ensureSuccess guarantees success=true, so endUser is present on the payload
    return payload.endUser!;
  }

  /**
   * Updates mutable fields on an existing end user. Omit any field you don't
   * want to change.
   *
   * @param id - Relay global ID of the end user.
   * @param opts.signal - Optional abort signal to cancel the request.
   */
  async update(
    id: string,
    input: { displayName?: string; tierLabel?: string; metadata?: Record<string, unknown> },
    opts: { signal?: AbortSignal } = {},
  ): Promise<EndUser> {
    const mutationInput: Record<string, unknown> = {};
    if (input.displayName !== undefined) mutationInput['displayName'] = input.displayName;
    if (input.tierLabel !== undefined) mutationInput['tierLabel'] = input.tierLabel;
    if (input.metadata !== undefined) mutationInput['metadata'] = input.metadata;

    const o = opts.signal ? { signal: opts.signal } : undefined;
    const res = await this.gql.request<{ updateEndUser: EndUserPayload }>(
      UPDATE_END_USER,
      { id, input: mutationInput },
      o,
    );
    const payload = ensureSuccess(res.updateEndUser);
    // ensureSuccess guarantees success=true, so endUser is present on the payload
    return payload.endUser!;
  }

  /**
   * Returns all end users in the workspace.
   *
   * @param opts.search - Fuzzy search string (matched against displayName / externalUserId).
   * @param opts.isActive - When set, filters by active status.
   * @param opts.first - Maximum number of end users to return (default 50).
   * @param opts.signal - Optional abort signal to cancel the request.
   */
  async list(
    opts: { search?: string; isActive?: boolean; first?: number; signal?: AbortSignal } = {},
  ): Promise<EndUser[]> {
    const o = opts.signal ? { signal: opts.signal } : undefined;
    const res = await this.gql.request<{ endUsers: { edges: { node: EndUser }[] } }>(
      LIST_END_USERS,
      { search: opts.search ?? null, isActive: opts.isActive ?? null, first: opts.first ?? 50 },
      o,
    );
    return res.endUsers.edges.map((e) => e.node);
  }

  /**
   * Returns the end user with the given relay global ID, or `null` if not found.
   *
   * @param id - Relay global ID of the end user.
   * @param opts.signal - Optional abort signal to cancel the request.
   */
  async get(id: string, opts: { signal?: AbortSignal } = {}): Promise<EndUser | null> {
    const o = opts.signal ? { signal: opts.signal } : undefined;
    const res = await this.gql.request<{ endUser: EndUser | null }>(GET_END_USER, { id }, o);
    return res.endUser ?? null;
  }

  /**
   * Looks up an end user by your system's external identifier. Returns `null`
   * if no match is found.
   *
   * The backend `search` filter is a fuzzy icontains match, so this method
   * performs an exact match locally after fetching candidates.
   *
   * @param externalUserId - Your system's stable identifier for this user.
   * @param opts.signal - Optional abort signal to cancel the request.
   */
  async getByExternalId(
    externalUserId: string,
    opts: { signal?: AbortSignal } = {},
  ): Promise<EndUser | null> {
    const found = await this.list({
      search: externalUserId,
      first: 50,
      ...(opts.signal ? { signal: opts.signal } : {}),
    });
    return found.find((u) => u.externalUserId === externalUserId) ?? null;
  }

  /**
   * Returns the existing end user with the given `externalUserId`, or creates
   * one if none exists. Useful for idempotent user provisioning at run time.
   *
   * @param input.externalUserId - Your system's stable identifier for this user.
   * @param opts.signal - Optional abort signal to cancel the request.
   */
  async ensure(
    input: {
      externalUserId: string;
      displayName?: string;
      tierLabel?: string;
      metadata?: Record<string, unknown>;
    },
    opts: { signal?: AbortSignal } = {},
  ): Promise<EndUser> {
    const existing = await this.getByExternalId(input.externalUserId, opts);
    if (existing) return existing;
    return this.create(input, opts);
  }

  /**
   * Updates the per-user control levers (credits, rate limits, model tier,
   * allowed tools/knowledge). Only the keys you provide are changed.
   *
   * @param input.id - Relay global ID of the end user.
   * @param opts.signal - Optional abort signal to cancel the request.
   */
  async setControls(
    input: { id: string } & EndUserControls,
    opts: { signal?: AbortSignal } = {},
  ): Promise<EndUser> {
    const mutationInput: Record<string, unknown> = { id: input.id };
    if (input.credits !== undefined) mutationInput['credits'] = input.credits;
    if (input.creditGrantPerPeriod !== undefined)
      mutationInput['creditGrantPerPeriod'] = input.creditGrantPerPeriod;
    if (input.runCountLimit !== undefined) mutationInput['runCountLimit'] = input.runCountLimit;
    if (input.runCountPeriod !== undefined) mutationInput['runCountPeriod'] = input.runCountPeriod;
    if (input.sandboxTimeSeconds !== undefined)
      mutationInput['sandboxTimeSeconds'] = input.sandboxTimeSeconds;
    if (input.concurrencyMax !== undefined) mutationInput['concurrencyMax'] = input.concurrencyMax;
    if (input.modelTier !== undefined) mutationInput['modelTier'] = input.modelTier;
    if (input.creditRefreshSchedule !== undefined)
      mutationInput['creditRefreshSchedule'] = input.creditRefreshSchedule;
    if (input.allowedToolIds !== undefined) mutationInput['allowedToolIds'] = input.allowedToolIds;
    if (input.allowedKnowledgeIds !== undefined)
      mutationInput['allowedKnowledgeIds'] = input.allowedKnowledgeIds;

    const o = opts.signal ? { signal: opts.signal } : undefined;
    const res = await this.gql.request<{ updateEndUserControls: EndUserPayload }>(
      UPDATE_END_USER_CONTROLS,
      { input: mutationInput },
      o,
    );
    const payload = ensureSuccess(res.updateEndUserControls);
    // ensureSuccess guarantees success=true, so endUser is present on the payload
    return payload.endUser!;
  }
}
