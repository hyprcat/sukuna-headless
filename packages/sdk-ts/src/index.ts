/**
 * `@midsphere/sdk` — the official TypeScript SDK for midsphere.
 *
 * Run agents, stream their progress, and manage end users and ratings against
 * the same GraphQL surface the dashboard uses. See the README for a quick start.
 */
export { Midsphere, AgentRef } from './client.js';
export type { MidsphereConfig, FetchLike } from './config.js';

export { Run, runOutcomeFromEvent } from './run/run.js';
export type { RunInit, RunOutcome, RunSnapshot, RefreshTokenFn } from './run/run.js';
export { SandboxConnection } from './run/sandbox.js';
export type { SandboxConnectionInit } from './run/sandbox.js';

export {
  isTerminalEvent,
  isTerminalType,
  parseStreamEvent,
  TERMINAL_EVENT_TYPES,
} from './run/events.js';
export type {
  StreamEvent,
  StreamEventType,
  LeaseUsage,
  RunStartedPayload,
  StepPayload,
  ToolCallPayload,
  ToolResultPayload,
  HitlRequestedPayload,
  HitlRespondedPayload,
  ArtifactCreatedPayload,
  UsageCheckpointPayload,
  RunCompletedPayload,
  RunFailedPayload,
  RunCancelledPayload,
} from './run/events.js';

export { Agents } from './resources/agents.js';
export { Tools } from './resources/tools.js';
export { KnowledgeBases } from './resources/knowledge.js';
export { EndUsers } from './resources/end-users.js';
export { Ratings } from './resources/ratings.js';

export {
  MidsphereError,
  MidsphereApiError,
  MidsphereUserError,
  MidsphereStreamError,
} from './errors.js';
export type { GraphQLFormattedError } from './errors.js';

export type {
  Agent,
  Tool,
  CreateToolInput,
  UpdateToolInput,
  Knowledge,
  KnowledgeKind,
  KnowledgeKindInput,
  CreateKnowledgeInput,
  UpdateKnowledgeInput,
  EndUser,
  EndUserControls,
  ModelTier,
  RunStatus,
  StartRunInput,
  WakeForRunInput,
  UserError,
  UserErrorCode,
} from './types.js';
