/**
 * Blocker routing map — maps UserError codes and run error codes
 * to plain-language reasons and deep links to the fix surface.
 *
 * Consumed by: ErrorBanner, RunSidebar, mutation failure handlers.
 */

export interface BlockerInfo {
  reason: string;
  fixUrl?: string;
  fixLabel?: string;
}

type ErrorCodeMap = Record<string, (ctx?: BlockerContext) => BlockerInfo>;

export interface BlockerContext {
  agentId?: string;
  endUserId?: string;
  runId?: string;
}

const MUTATION_ERRORS: ErrorCodeMap = {
  INSUFFICIENT_CREDITS: () => ({
    reason: 'Not enough credits to complete this action.',
    fixUrl: '/billing',
    fixLabel: 'Top up credits',
  }),
  RUN_LIMIT_EXCEEDED: (ctx) => ({
    reason: 'This end user has reached their run limit for the current period.',
    fixUrl: ctx?.endUserId ? `/end-users/${ctx.endUserId}` : '/end-users',
    fixLabel: 'Adjust run limits',
  }),
  CONCURRENCY_CAP: (ctx) => ({
    reason: 'Too many runs are active at once for this end user.',
    fixUrl: ctx?.endUserId ? `/end-users/${ctx.endUserId}` : '/end-users',
    fixLabel: 'Adjust concurrency cap',
  }),
  MODEL_TIER_RESTRICTED: (ctx) => ({
    reason: "This model tier isn't available for this end user's plan.",
    fixUrl: ctx?.endUserId ? `/end-users/${ctx.endUserId}` : '/end-users',
    fixLabel: 'Update model tier',
  }),
  TOOL_NOT_ALLOWED: (ctx) => ({
    reason: "A required tool isn't in this end user's allowed list.",
    fixUrl: ctx?.endUserId ? `/end-users/${ctx.endUserId}` : '/end-users',
    fixLabel: 'Update allowed tools',
  }),
  KNOWLEDGE_NOT_ALLOWED: (ctx) => ({
    reason: "A required knowledge source isn't in this end user's allowed list.",
    fixUrl: ctx?.endUserId ? `/end-users/${ctx.endUserId}` : '/end-users',
    fixLabel: 'Update allowed knowledge',
  }),
  INVALID_INPUT: () => ({
    reason: 'One or more fields have invalid values.',
  }),
  NOT_FOUND: () => ({
    reason: "The requested resource doesn't exist or was removed.",
  }),
  PERMISSION_DENIED: () => ({
    reason: "You don't have permission for this action. Ask a workspace admin.",
    fixUrl: '/workspace/members',
    fixLabel: 'View members',
  }),
  CONFLICT: () => ({
    reason: 'This conflicts with an existing resource (e.g. duplicate name).',
  }),
  BILLING_ERROR: () => ({
    reason: 'A billing system error occurred. Try again shortly.',
    fixUrl: '/billing',
    fixLabel: 'View billing',
  }),
  INVALID_API_KEY: () => ({
    reason: 'The API key is invalid or has been revoked.',
    fixUrl: '/keys',
    fixLabel: 'Manage API keys',
  }),
  SCOPE_INSUFFICIENT: () => ({
    reason: "The API key doesn't have the required scope for this action.",
    fixUrl: '/keys',
    fixLabel: 'Manage API keys',
  }),
};

const RUN_ERRORS: ErrorCodeMap = {
  lease_runtime_exceeded: () => ({
    reason: 'The run hit its time limit.',
  }),
  lease_tokens_exceeded: () => ({
    reason: 'The run used more tokens than allowed.',
  }),
  lease_cost_exceeded: () => ({
    reason: 'The run exceeded its cost cap.',
    fixUrl: '/billing',
    fixLabel: 'View billing',
  }),
  tool_failed: (ctx) => ({
    reason: 'A tool call failed while running.',
    fixUrl: ctx?.agentId ? `/agents/${ctx.agentId}` : '/tools',
    fixLabel: 'Check tools',
  }),
  model_unavailable: () => ({
    reason: 'The model was temporarily unavailable.',
  }),
  knowledge_inaccessible: (ctx) => ({
    reason: 'A knowledge source could not be reached.',
    fixUrl: ctx?.agentId ? `/agents/${ctx.agentId}` : '/knowledge',
    fixLabel: 'Check knowledge',
  }),
  sandbox_internal: () => ({
    reason: 'An internal error occurred while running the agent.',
  }),
  policy_violation: (ctx) => ({
    reason: 'The agent action was blocked by a policy rule.',
    fixUrl: ctx?.agentId ? `/agents/${ctx.agentId}` : '/policies',
    fixLabel: 'Review policies',
  }),
  approval_denied: () => ({
    reason: 'A required human approval was denied.',
  }),
  guardrail_blocked: () => ({
    reason: 'A safety guardrail blocked the agent action.',
  }),
  run_task_crashed: () => ({
    reason: 'The agent executor process crashed unexpectedly.',
  }),
  upstream_model_error: () => ({
    reason: 'The AI model returned an error.',
  }),
};

export function resolveBlocker(code: string, ctx?: BlockerContext): BlockerInfo {
  const factory = MUTATION_ERRORS[code] ?? RUN_ERRORS[code];
  if (factory) return factory(ctx);
  return { reason: code.replace(/_/g, ' ') };
}

export function resolveRunError(
  errorMessage: string | null | undefined,
  ctx?: BlockerContext,
): BlockerInfo | null {
  if (!errorMessage) return null;

  for (const code of Object.keys(RUN_ERRORS)) {
    if (errorMessage.toLowerCase().includes(code)) {
      return RUN_ERRORS[code]!(ctx);
    }
  }

  return { reason: errorMessage };
}
