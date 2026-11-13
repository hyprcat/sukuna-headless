export interface Workspace {
  slug: string;
  name: string;
  role: string;
}

export interface RunNode {
  id: string;
  runUid: string;
  status: string;
  agentName: string;
  endUserIdExternal: string;
  promptPreview: string;
  totalCost: number;
  totalTokens: number;
  startedAt: string | null;
  finishedAt: string | null;
  createdAt: string;
  rating: { score: number } | null;
}
