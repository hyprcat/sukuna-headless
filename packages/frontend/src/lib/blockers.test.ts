import { describe, expect, it } from 'vitest';

import { resolveBlocker, resolveRunError } from './blockers';

describe('resolveBlocker', () => {
  it('maps backend mutation error codes to fix routes', () => {
    expect(resolveBlocker('INSUFFICIENT_CREDITS')).toMatchObject({
      reason: 'Not enough credits to complete this action.',
      fixUrl: '/billing',
      fixLabel: 'Top up credits',
    });
    expect(resolveBlocker('PERMISSION_DENIED')).toMatchObject({
      fixUrl: '/workspace/members',
    });
    expect(resolveBlocker('SCOPE_INSUFFICIENT')).toMatchObject({
      fixUrl: '/keys',
    });
  });

  it('uses end-user context for quota blockers', () => {
    expect(resolveBlocker('RUN_LIMIT_EXCEEDED', { endUserId: 'EndUserType:7' })).toMatchObject({
      fixUrl: '/end-users/EndUserType:7',
      fixLabel: 'Adjust run limits',
    });
  });
});

describe('resolveRunError', () => {
  it('deep-links agent configuration blockers to the run agent', () => {
    expect(resolveRunError('tool_failed: timed out', { agentId: 'AgentType:4' })).toMatchObject({
      reason: 'A tool call failed while running.',
      fixUrl: '/agents/AgentType:4',
      fixLabel: 'Check tools',
    });
    expect(resolveRunError('policy_violation', { agentId: 'AgentType:4' })).toMatchObject({
      fixUrl: '/agents/AgentType:4',
      fixLabel: 'Review policies',
    });
  });

  it('falls back to the raw terminal message when the code is unknown', () => {
    expect(resolveRunError('provider timed out')).toEqual({ reason: 'provider timed out' });
    expect(resolveRunError(null)).toBeNull();
  });
});
