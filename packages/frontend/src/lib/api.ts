/**
 * Server-side API client for Django auth endpoints.
 * Single-file swap surface per FRONTEND_CODING_STANDARDS.
 *
 * Astro SSR calls these from page frontmatter; cookies are
 * forwarded both ways (browser → Django, Django → browser).
 */

const API_BASE = import.meta.env.API_URL ?? 'http://localhost:8000';

export const clientApiUrl: string = import.meta.env.CLIENT_API_URL ?? API_BASE;

export interface ApiResult<T = Record<string, unknown>> {
  ok: boolean;
  error?: string;
  field?: string | null;
  setCookie?: string[];
  data: T;
}

export async function apiPost<T = Record<string, unknown>>(
  path: string,
  body: Record<string, unknown>,
  cookie?: string,
): Promise<ApiResult<T>> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (cookie) headers['Cookie'] = cookie;

  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
    credentials: 'include',
  });

  const setCookie = res.headers.getSetCookie?.() ?? [];
  const data = (await res.json()) as T & { ok: boolean; error?: string; field?: string | null };

  return {
    ok: data.ok,
    error: data.error,
    field: data.field,
    setCookie,
    data,
  };
}

export async function apiGet<T = Record<string, unknown>>(
  path: string,
  cookie?: string,
): Promise<ApiResult<T>> {
  const headers: Record<string, string> = {};
  if (cookie) headers['Cookie'] = cookie;

  const res = await fetch(`${API_BASE}${path}`, {
    method: 'GET',
    headers,
    credentials: 'include',
  });

  if (res.status === 401) {
    return { ok: false, error: 'Not authenticated.', data: {} as T };
  }

  const data = (await res.json()) as T & { ok: boolean; error?: string; field?: string | null };

  return {
    ok: data.ok,
    error: data.error,
    field: data.field,
    data,
  };
}
