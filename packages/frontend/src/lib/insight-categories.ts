export const CATEGORY_LABELS: Record<string, string> = {
  capability_gap: 'Capability gaps',
  tier_optimization: 'Tier optimization',
  quality_issue: 'Quality issues',
  scheduled_task_health: 'Scheduled health',
};

export const CATEGORY_ACTIONS: Record<string, { href: string; label: string }> = {
  capability_gap: { href: '/tools', label: 'Review tools' },
  tier_optimization: { href: '/end-users', label: 'Adjust limits' },
  quality_issue: { href: '/runs', label: 'View runs' },
  scheduled_task_health: { href: '/schedules', label: 'View schedules' },
};

export const CATEGORY_CSS_COLORS: Record<string, string> = {
  capability_gap: 'var(--ms-cat-capability-gap)',
  tier_optimization: 'var(--ms-cat-tier-optimization)',
  quality_issue: 'var(--ms-cat-quality-issue)',
  scheduled_task_health: 'var(--ms-cat-scheduled-health)',
};
