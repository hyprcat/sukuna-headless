import { describe, expect, it } from 'vitest';

import { Action, canAction, currentRole } from './permissions';

describe('canAction', () => {
  it('matches the backend role matrix for viewer read actions', () => {
    expect(canAction('viewer', Action.WORKSPACE_READ)).toBe(true);
    expect(canAction('viewer', Action.MEMBERS_READ)).toBe(true);
    expect(canAction('viewer', Action.BILLING_READ)).toBe(true);
    expect(canAction('viewer', Action.API_KEYS_READ)).toBe(true);
    expect(canAction('viewer', Action.AGENTS_READ)).toBe(true);
    expect(canAction('viewer', Action.TOOLS_READ)).toBe(true);
    expect(canAction('viewer', Action.KNOWLEDGE_READ)).toBe(true);
    expect(canAction('viewer', Action.END_USERS_READ)).toBe(true);
    expect(canAction('viewer', Action.RUNS_READ)).toBe(true);
    expect(canAction('viewer', Action.SCHEDULES_READ)).toBe(true);
    expect(canAction('viewer', Action.POLICIES_READ)).toBe(true);
    expect(canAction('viewer', Action.RATINGS_READ)).toBe(true);
    expect(canAction('viewer', Action.INSIGHTS_READ)).toBe(true);
  });

  it('keeps viewer and editor admin-only settings unavailable', () => {
    expect(canAction('viewer', Action.WORKSPACE_WRITE)).toBe(false);
    expect(canAction('viewer', Action.API_KEYS_CREATE)).toBe(false);
    expect(canAction('viewer', Action.BILLING_TOPUP)).toBe(false);
    expect(canAction('editor', Action.MEMBERS_INVITE)).toBe(false);
    expect(canAction('editor', Action.API_KEYS_REVOKE)).toBe(false);
    expect(canAction('editor', Action.WORKSPACE_SUSPEND)).toBe(false);
  });

  it('allows editor configuration work but not agent deletion', () => {
    expect(canAction('editor', Action.AGENTS_WRITE)).toBe(true);
    expect(canAction('editor', Action.AGENTS_DELETE)).toBe(false);
    expect(canAction('editor', Action.TOOLS_DELETE)).toBe(true);
    expect(canAction('editor', Action.KNOWLEDGE_DELETE)).toBe(true);
    expect(canAction('editor', Action.SCHEDULES_PAUSE)).toBe(true);
    expect(canAction('editor', Action.INSIGHTS_PIN)).toBe(true);
  });

  it('allows admins to perform the full action vocabulary', () => {
    for (const action of Object.values(Action)) {
      expect(canAction('admin', action)).toBe(true);
    }
  });

  it('fails closed for missing or unknown roles', () => {
    expect(canAction(null, Action.AGENTS_READ)).toBe(false);
    expect(canAction('owner', Action.AGENTS_READ)).toBe(false);
  });
});

describe('currentRole', () => {
  it('returns the role for the active workspace slug', () => {
    expect(
      currentRole(
        [
          { slug: 'acme', role: 'viewer' },
          { slug: 'beta', role: 'admin' },
        ],
        'beta',
      ),
    ).toBe('admin');
  });

  it('returns null when there is no active workspace match', () => {
    expect(currentRole([{ slug: 'acme', role: 'viewer' }], 'beta')).toBeNull();
    expect(currentRole([{ slug: 'acme', role: 'viewer' }], null)).toBeNull();
  });
});
