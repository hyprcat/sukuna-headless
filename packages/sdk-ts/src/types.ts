/**
 * Shared public types for the midsphere SDK.
 *
 * These mirror the backend GraphQL surface (camelCase) and the sandbox
 * streaming contract (snake_case payloads — see {@link ./run/events}).
 */

/** Closed set of domain error codes the backend projects into `MutationResult.errors`. */
export type UserErrorCode =
  | 'INSUFFICIENT_CREDITS'
  | 'RUN_LIMIT_EXCEEDED'
  | 'CONCURRENCY_CAP'
  | 'MODEL_TIER_RESTRICTED'
  | 'TOOL_NOT_ALLOWED'
  | 'KNOWLEDGE_NOT_ALLOWED'
  | 'INVALID_INPUT'
  | 'NOT_FOUND'
  | 'PERMISSION_DENIED'
  | 'CONFLICT'
  | 'BILLING_ERROR'
  | 'INVALID_API_KEY'
  | 'SCOPE_INSUFFICIENT'
  | 'SANDBOX_ERROR';

/** A single domain failure from a mutation's `errors` list. */
export interface UserError {
  /** Machine-readable code. Widened to `string` so a new backend code never breaks parsing. */
  code: UserErrorCode | (string & {});
  /** The input field the error applies to, when the failure is input-scoped. */
  field: string | null;
  /** Human-readable, end-of-line message. */
  message: string;
}

/** Lifecycle status of a run, as reported by the control plane. */
export type RunStatus = 'QUEUED' | 'RUNNING' | 'FINISHED' | 'FAILED' | 'CANCELLED';

/** Model tier an agent or end user is allowed to use. */
export type ModelTier = 'free' | 'pro' | 'enterprise';

/** A configured agent (control-plane view). */
export interface Agent {
  id: string;
  name: string;
  description: string;
  defaultModelTier: ModelTier | (string & {});
  isActive: boolean;
}

/** A configured tool (control-plane view). */
export interface Tool {
  id: string;
  name: string;
  description: string;
  /** JSON Schema (Draft 2020-12) describing the tool's parameters. */
  parametersSchema: Record<string, unknown>;
  executionEndpoint: string;
  isSensitive: boolean;
  isActive: boolean;
  createdAt: string;
  updatedAt: string;
  deactivatedAt: string | null;
}

/** Fields accepted when creating a tool. */
export interface CreateToolInput {
  name: string;
  description?: string;
  parametersSchema?: Record<string, unknown>;
  executionEndpoint?: string;
  isSensitive?: boolean;
}

/** Fields accepted when updating a tool — omit any you don't want to change. */
export interface UpdateToolInput {
  name?: string;
  description?: string;
  parametersSchema?: Record<string, unknown>;
  executionEndpoint?: string;
  isSensitive?: boolean;
}

/** The kind of a knowledge base, as returned by the control plane. */
export type KnowledgeKind = 'DOCUMENT' | 'DATASET' | 'CONNECTED_SOURCE';

/** The kind value accepted when creating a knowledge base. */
export type KnowledgeKindInput = 'document' | 'dataset' | 'connected_source';

/** A configured knowledge base (control-plane view). */
export interface Knowledge {
  id: string;
  name: string;
  description: string;
  kind: KnowledgeKind | (string & {});
  fileName: string;
  fileSizeBytes: number | null;
  contentType: string;
  sourceEndpoint: string;
  isActive: boolean;
  createdAt: string;
  updatedAt: string;
  lastIndexedAt: string | null;
  deactivatedAt: string | null;
}

/** Fields accepted when creating a knowledge base. */
export interface CreateKnowledgeInput {
  name: string;
  kind: KnowledgeKindInput;
  description?: string;
  sourceEndpoint?: string;
  sourceConfig?: Record<string, unknown>;
}

/** Fields accepted when updating a knowledge base — omit any you don't want to change. */
export interface UpdateKnowledgeInput {
  name?: string;
  description?: string;
  sourceEndpoint?: string;
  sourceConfig?: Record<string, unknown>;
}

/** A developer's end user (the person the agent acts on behalf of). */
export interface EndUser {
  id: string;
  externalUserId: string;
  displayName: string;
  tierLabel: string;
  metadata: Record<string, unknown>;
  isActive: boolean;
}

/** Per-end-user control levers (credits, caps, allowed tools/knowledge). */
export interface EndUserControls {
  credits?: number;
  creditGrantPerPeriod?: number;
  runCountLimit?: number | null;
  runCountPeriod?: string;
  sandboxTimeSeconds?: number | null;
  concurrencyMax?: number | null;
  modelTier?: ModelTier | (string & {});
  creditRefreshSchedule?: string;
  allowedToolIds?: string[];
  allowedKnowledgeIds?: string[];
}

/**
 * Identifies an existing run to resume via {@link Midsphere.wakeForRun}.
 *
 * Pass the run's global `id` on its own and the SDK looks up the `runUid` and
 * current `status` for you; supply them inline to skip that round-trip (useful
 * in a Next.js server action that already has them from `startRun`).
 */
export type WakeForRunInput = string | { runId: string; runUid?: string; status?: RunStatus };

/** Input for {@link Midsphere.run} — maps 1:1 to the `startRun` mutation. */
export interface StartRunInput {
  /** Global ID of the agent to run. */
  agentId: string;
  /** Global ID of the end user the run acts on behalf of. */
  endUserId: string;
  /** The user's prompt. */
  prompt: string;
  /** Existing conversation to continue (multi-turn). Omit to start fresh. */
  conversationUid?: string;
  /** Restrict the run to a subset of the agent's tools, by global ID. */
  toolIds?: string[];
  /** Restrict the run to a subset of the agent's knowledge, by global ID. */
  knowledgeIds?: string[];
}
