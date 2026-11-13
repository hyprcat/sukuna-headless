/**
 * Frontend mirror of backend apps/accounts/permissions.py.
 * Kept in sync manually — the action vocabulary and role matrix
 * must match the backend's RolePermissions model.
 */

export type Role = 'admin' | 'editor' | 'viewer';

export const Action = {
  WORKSPACE_READ: 'workspace:read',
  WORKSPACE_WRITE: 'workspace:write',
  WORKSPACE_DELETE: 'workspace:delete',
  WORKSPACE_SUSPEND: 'workspace:suspend',

  MEMBERS_READ: 'members:read',
  MEMBERS_INVITE: 'members:invite',
  MEMBERS_UPDATE_ROLE: 'members:update_role',
  MEMBERS_REMOVE: 'members:remove',
  MEMBERS_TRANSFER_OWNERSHIP: 'members:transfer_ownership',

  BILLING_READ: 'billing:read',
  BILLING_TOPUP: 'billing:topup',
  BILLING_REFUND: 'billing:refund',

  API_KEYS_READ: 'api_keys:read',
  API_KEYS_CREATE: 'api_keys:create',
  API_KEYS_REVOKE: 'api_keys:revoke',

  AGENTS_READ: 'agents:read',
  AGENTS_WRITE: 'agents:write',
  AGENTS_DELETE: 'agents:delete',

  TOOLS_READ: 'tools:read',
  TOOLS_WRITE: 'tools:write',
  TOOLS_DELETE: 'tools:delete',

  KNOWLEDGE_READ: 'knowledge:read',
  KNOWLEDGE_WRITE: 'knowledge:write',
  KNOWLEDGE_DELETE: 'knowledge:delete',

  END_USERS_READ: 'end_users:read',
  END_USERS_WRITE: 'end_users:write',
  END_USERS_DELETE: 'end_users:delete',

  RUNS_READ: 'runs:read',
  RUNS_WRITE: 'runs:write',
  RUNS_CANCEL: 'runs:cancel',

  SCHEDULES_READ: 'schedules:read',
  SCHEDULES_WRITE: 'schedules:write',
  SCHEDULES_DELETE: 'schedules:delete',
  SCHEDULES_PAUSE: 'schedules:pause',

  POLICIES_READ: 'policies:read',
  POLICIES_WRITE: 'policies:write',

  RATINGS_READ: 'ratings:read',

  INSIGHTS_READ: 'insights:read',
  INSIGHTS_DISMISS: 'insights:dismiss',
  INSIGHTS_PIN: 'insights:pin',
} as const;

export type ActionValue = (typeof Action)[keyof typeof Action];

const VIEWER_ACTIONS: ReadonlySet<string> = new Set([
  Action.WORKSPACE_READ,
  Action.MEMBERS_READ,
  Action.BILLING_READ,
  Action.API_KEYS_READ,
  Action.AGENTS_READ,
  Action.TOOLS_READ,
  Action.KNOWLEDGE_READ,
  Action.END_USERS_READ,
  Action.RUNS_READ,
  Action.SCHEDULES_READ,
  Action.POLICIES_READ,
  Action.RATINGS_READ,
  Action.INSIGHTS_READ,
]);

const EDITOR_ACTIONS: ReadonlySet<string> = new Set([
  ...VIEWER_ACTIONS,
  Action.AGENTS_WRITE,
  Action.TOOLS_WRITE,
  Action.TOOLS_DELETE,
  Action.KNOWLEDGE_WRITE,
  Action.KNOWLEDGE_DELETE,
  Action.END_USERS_WRITE,
  Action.END_USERS_DELETE,
  Action.RUNS_WRITE,
  Action.RUNS_CANCEL,
  Action.SCHEDULES_WRITE,
  Action.SCHEDULES_DELETE,
  Action.SCHEDULES_PAUSE,
  Action.POLICIES_WRITE,
  Action.INSIGHTS_DISMISS,
  Action.INSIGHTS_PIN,
]);

export function canAction(role: Role | string | null | undefined, action: ActionValue): boolean {
  if (!role) return false;
  if (role === 'admin') return true;
  if (role === 'editor') return EDITOR_ACTIONS.has(action);
  if (role === 'viewer') return VIEWER_ACTIONS.has(action);
  return false;
}

export function currentRole(
  workspaces: { slug: string; role: string }[],
  activeSlug: string | null,
): Role | null {
  if (!activeSlug) return null;
  const ws = workspaces.find((w) => w.slug === activeSlug);
  return (ws?.role as Role) ?? null;
}
