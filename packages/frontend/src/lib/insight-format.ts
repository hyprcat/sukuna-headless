export interface InsightRelationCounts {
  agentCount: number;
  runCount: number;
  endUserCount: number;
}

export function formatInsightContext(counts: InsightRelationCounts): string {
  const parts = [
    countLabel(counts.agentCount, 'agent'),
    countLabel(counts.runCount, 'run'),
    countLabel(counts.endUserCount, 'end user'),
  ].filter((part): part is string => Boolean(part));
  return parts.length > 0 ? `Related to ${parts.join(', ')}` : 'Workspace-wide pattern';
}

export function formatInsightTime(iso: string): string {
  const date = new Date(iso);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffH = Math.floor(diffMs / 3_600_000);
  const diffD = Math.floor(diffMs / 86_400_000);
  if (diffH < 1) return 'Just now';
  if (diffH < 24) return `${diffH}h ago`;
  if (diffD < 7) return `${diffD}d ago`;
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

function countLabel(count: number, label: string): string | null {
  if (count === 0) return null;
  return `${count} ${label}${count === 1 ? '' : 's'}`;
}
