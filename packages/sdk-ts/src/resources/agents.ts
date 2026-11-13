/**
 * Read access to the workspace's agents.
 */

import type { GraphQLClient } from '../graphql.js';
import type { Agent } from '../types.js';

// ---------------------------------------------------------------------------
// Queries
// ---------------------------------------------------------------------------

const LIST_AGENTS = /* GraphQL */ `
  query Agents($isActive: Boolean, $first: Int) {
    agents(isActive: $isActive, first: $first) {
      edges {
        node {
          id
          name
          description
          defaultModelTier
          isActive
        }
      }
    }
  }
`;

const GET_AGENT = /* GraphQL */ `
  query Agent($id: ID!) {
    agent(id: $id) {
      id
      name
      description
      defaultModelTier
      isActive
    }
  }
`;

// ---------------------------------------------------------------------------
// Resource class
// ---------------------------------------------------------------------------

/** Read access to the agents configured in the workspace. */
export class Agents {
  constructor(private readonly gql: GraphQLClient) {}

  /**
   * Returns all agents in the workspace, optionally filtered by active status.
   *
   * @param opts.isActive - When set, only returns agents with that active status.
   * @param opts.first - Maximum number of agents to return (default 50).
   * @param opts.signal - Optional abort signal to cancel the request.
   */
  async list(
    opts: { isActive?: boolean; first?: number; signal?: AbortSignal } = {},
  ): Promise<Agent[]> {
    const o = opts.signal ? { signal: opts.signal } : undefined;
    const res = await this.gql.request<{ agents: { edges: { node: Agent }[] } }>(
      LIST_AGENTS,
      { isActive: opts.isActive ?? null, first: opts.first ?? 50 },
      o,
    );
    return res.agents.edges.map((e) => e.node);
  }

  /**
   * Returns the agent with the given relay global ID, or `null` if not found.
   *
   * @param id - The relay global ID of the agent.
   * @param opts.signal - Optional abort signal to cancel the request.
   */
  async get(id: string, opts: { signal?: AbortSignal } = {}): Promise<Agent | null> {
    const o = opts.signal ? { signal: opts.signal } : undefined;
    const res = await this.gql.request<{ agent: Agent | null }>(GET_AGENT, { id }, o);
    return res.agent ?? null;
  }
}
