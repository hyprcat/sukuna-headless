/**
 * The midsphere client — the single entry point. Construct it with a workspace
 * API key, then run agents and manage end users and ratings:
 *
 * ```ts
 * const client = new Midsphere({ apiKey: process.env.MIDSPHERE_API_KEY! });
 * const run = await client.run({ agentId, endUserId, prompt: 'Summarize today’s signups' });
 * for await (const event of run.stream()) console.log(event.type);
 * ```
 */
import { resolveConfig, type MidsphereConfig, type ResolvedConfig } from './config.js';
import { GraphQLClient, type RequestOptions } from './graphql.js';
import { MidsphereUserError } from './errors.js';
import { Agents } from './resources/agents.js';
import { EndUsers } from './resources/end-users.js';
import { KnowledgeBases } from './resources/knowledge.js';
import { Ratings } from './resources/ratings.js';
import { Tools } from './resources/tools.js';
import { Run } from './run/run.js';
import type { RunSnapshot } from './run/run.js';
import type { Agent, RunStatus, StartRunInput, UserError, WakeForRunInput } from './types.js';

interface StartRunPayload {
  success: boolean;
  errors: UserError[];
  runId: string | null;
  runUid: string | null;
  sandboxUrl: string | null;
  capabilityToken: string | null;
  tokenExpiresAt: string | null;
}

interface RefreshTokenPayload {
  success: boolean;
  errors: UserError[];
  capabilityToken: string | null;
  tokenExpiresAt: string | null;
}

interface WakeForRunPayload {
  success: boolean;
  errors: UserError[];
  sandboxUrl: string | null;
  capabilityToken: string | null;
  tokenExpiresAt: string | null;
}

const START_RUN = /* GraphQL */ `
  mutation StartRun($input: StartRunInput!) {
    startRun(input: $input) {
      success
      errors {
        code
        field
        message
      }
      runId
      runUid
      sandboxUrl
      capabilityToken
      tokenExpiresAt
    }
  }
`;

const REFRESH_TOKEN = /* GraphQL */ `
  mutation RefreshSandboxToken($runId: ID!) {
    refreshSandboxToken(runId: $runId) {
      success
      errors {
        code
        field
        message
      }
      capabilityToken
      tokenExpiresAt
    }
  }
`;

const WAKE_FOR_RUN = /* GraphQL */ `
  mutation WakeForRun($runId: ID!) {
    wakeForRun(runId: $runId) {
      success
      errors {
        code
        field
        message
      }
      sandboxUrl
      capabilityToken
      tokenExpiresAt
    }
  }
`;

const RUN_IDENTITY = /* GraphQL */ `
  query RunIdentity($id: ID!) {
    run(id: $id) {
      runUid
      status
    }
  }
`;

export class Midsphere {
  private readonly config: ResolvedConfig;

  /** Low-level GraphQL transport. Use for operations not yet wrapped by a resource. */
  readonly gql: GraphQLClient;
  /** Read access to the workspace's agents. */
  readonly agents: Agents;
  /** Create, read, and configure tools. */
  readonly tools: Tools;
  /** Create, read, and configure knowledge bases. */
  readonly knowledge: KnowledgeBases;
  /** Create, read, and configure end users. */
  readonly endUsers: EndUsers;
  /** Submit end-user ratings for completed runs. */
  readonly ratings: Ratings;

  constructor(config: MidsphereConfig) {
    this.config = resolveConfig(config);
    this.gql = new GraphQLClient(this.config);
    this.agents = new Agents(this.gql);
    this.tools = new Tools(this.gql);
    this.knowledge = new KnowledgeBases(this.gql);
    this.endUsers = new EndUsers(this.gql);
    this.ratings = new Ratings(this.gql);
  }

  /**
   * Start a run. Returns a {@link Run} handle you can stream, wait on, cancel,
   * or respond to (for human-in-the-loop). The agent executes in an isolated
   * sandbox; events stream directly from it via a short-lived capability token.
   */
  async run(input: StartRunInput, options: RequestOptions = {}): Promise<Run> {
    const variables = { input: buildStartRunInput(input) };
    const res = await this.gql.request<{ startRun: StartRunPayload }>(
      START_RUN,
      variables,
      options,
    );
    const payload = res.startRun;
    if (!payload.success) {
      throw new MidsphereUserError(payload.errors);
    }
    // On success the backend always returns these fields populated.
    return new Run(
      {
        runId: payload.runId!,
        runUid: payload.runUid!,
        sandboxUrl: payload.sandboxUrl!,
        capabilityToken: payload.capabilityToken!,
        tokenExpiresAt: payload.tokenExpiresAt,
        fetch: this.config.fetch,
      },
      () => this.refreshSandboxToken(payload.runId!),
    );
  }

  /**
   * Resumes an existing, non-terminal run — reconnecting to its (possibly
   * paused) sandbox and minting a fresh capability token. Returns a {@link Run}
   * handle you can stream, wait on, cancel, or respond to, exactly as if you had
   * just started it.
   *
   * Use this to pick a run back up across process boundaries: a Next.js server
   * action starts the run and hands the `runId` to a client component, which
   * wakes it to stream progress. Pass the `runId` alone and the SDK resolves the
   * `runUid` and `status` for you; supply them inline to skip that lookup.
   *
   * @throws {MidsphereUserError} when the run is terminal, not found, or has no
   *   resumable sandbox.
   */
  async wakeForRun(run: WakeForRunInput, options: RequestOptions = {}): Promise<Run> {
    const target = typeof run === 'string' ? { runId: run } : run;
    const identity = await this.resolveRunIdentity(target, options);

    const res = await this.gql.request<{ wakeForRun: WakeForRunPayload }>(
      WAKE_FOR_RUN,
      { runId: target.runId },
      options,
    );
    const payload = res.wakeForRun;
    if (!payload.success) {
      throw new MidsphereUserError(payload.errors);
    }

    return new Run(
      {
        runId: target.runId,
        runUid: identity.runUid,
        // On success the backend always populates the sandbox fields.
        sandboxUrl: payload.sandboxUrl!,
        capabilityToken: payload.capabilityToken!,
        tokenExpiresAt: payload.tokenExpiresAt,
        fetch: this.config.fetch,
        status: identity.status,
      },
      () => this.refreshSandboxToken(target.runId),
    );
  }

  /**
   * Rebuilds a {@link Run} handle from a {@link RunSnapshot} produced by
   * `run.toSnapshot()`. No network call — the snapshot already carries the
   * capability token. This is the client side of the server-action pattern: the
   * server starts the run and serializes it; the browser rehydrates and streams.
   */
  runFromSnapshot(snapshot: RunSnapshot): Run {
    return new Run(
      {
        runId: snapshot.runId,
        runUid: snapshot.runUid,
        sandboxUrl: snapshot.sandboxUrl,
        capabilityToken: snapshot.capabilityToken,
        tokenExpiresAt: snapshot.tokenExpiresAt,
        fetch: this.config.fetch,
        status: snapshot.status,
      },
      () => this.refreshSandboxToken(snapshot.runId),
    );
  }

  /** A lightweight handle bound to one agent — sugar over {@link Midsphere.run} and `agents.get`. */
  agent(agentId: string): AgentRef {
    return new AgentRef(this, agentId);
  }

  /**
   * Resolves the `runUid` (and current `status`) needed to build a {@link Run}
   * handle. Returns the caller-supplied values when present, otherwise looks
   * them up. A woken run is mid-flight, so the status defaults to `'RUNNING'`.
   */
  private async resolveRunIdentity(
    target: { runId: string; runUid?: string; status?: RunStatus },
    options: RequestOptions,
  ): Promise<{ runUid: string; status: RunStatus }> {
    if (target.runUid !== undefined) {
      return { runUid: target.runUid, status: target.status ?? 'RUNNING' };
    }
    const res = await this.gql.request<{
      run: { runUid: string; status: RunStatus } | null;
    }>(RUN_IDENTITY, { id: target.runId }, options);
    if (res.run === null) {
      throw new MidsphereUserError([
        { code: 'NOT_FOUND', field: 'runId', message: 'Run not found.' },
      ]);
    }
    return { runUid: res.run.runUid, status: target.status ?? res.run.status };
  }

  private async refreshSandboxToken(
    runId: string,
  ): Promise<{ capabilityToken: string; tokenExpiresAt: string | null }> {
    const res = await this.gql.request<{ refreshSandboxToken: RefreshTokenPayload }>(
      REFRESH_TOKEN,
      {
        runId,
      },
    );
    const payload = res.refreshSandboxToken;
    if (!payload.success) {
      throw new MidsphereUserError(payload.errors);
    }
    return { capabilityToken: payload.capabilityToken!, tokenExpiresAt: payload.tokenExpiresAt };
  }
}

/** Bound-agent convenience handle returned by {@link Midsphere.agent}. */
export class AgentRef {
  constructor(
    private readonly client: Midsphere,
    readonly id: string,
  ) {}

  /** Start a run for this agent. */
  run(input: Omit<StartRunInput, 'agentId'>, options?: RequestOptions): Promise<Run> {
    return this.client.run({ ...input, agentId: this.id }, options ?? {});
  }

  /** Fetch this agent's configuration. */
  get(options?: { signal?: AbortSignal }): Promise<Agent | null> {
    return this.client.agents.get(this.id, options ?? {});
  }
}

/** Drop optional run fields the caller didn't set, so the backend applies its defaults. */
function buildStartRunInput(input: StartRunInput): Record<string, unknown> {
  const out: Record<string, unknown> = {
    agentId: input.agentId,
    endUserId: input.endUserId,
    prompt: input.prompt,
  };
  if (input.conversationUid !== undefined) out.conversationUid = input.conversationUid;
  if (input.toolIds !== undefined) out.toolIds = input.toolIds;
  if (input.knowledgeIds !== undefined) out.knowledgeIds = input.knowledgeIds;
  return out;
}
