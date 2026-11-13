/**
 * Server-side GraphQL client for the Strawberry backend.
 * Single-file swap surface per FRONTEND_CODING_STANDARDS §7.
 *
 * Called from Astro page frontmatter (SSR); forwards session
 * cookies so workspace-scoped resolvers authenticate correctly.
 */

const API_BASE = import.meta.env.API_URL ?? 'http://localhost:8000';

export interface GqlError {
  message: string;
  path?: string[];
}

export interface GqlResult<T> {
  data: T | null;
  errors: GqlError[] | null;
}

export async function gql<T = Record<string, unknown>>(
  query: string,
  variables: Record<string, unknown> = {},
  cookie?: string,
  workspaceSlug?: string,
): Promise<GqlResult<T>> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (cookie) headers['Cookie'] = cookie;
  if (workspaceSlug) headers['X-Workspace-Slug'] = workspaceSlug;

  const res = await fetch(`${API_BASE}/graphql/`, {
    method: 'POST',
    headers,
    body: JSON.stringify({ query, variables }),
    credentials: 'include',
  });

  if (!res.ok) {
    return {
      data: null,
      errors: [{ message: `HTTP ${res.status}: ${res.statusText}` }],
    };
  }

  const json = (await res.json()) as GqlResult<T>;
  return { data: json.data ?? null, errors: json.errors ?? null };
}
