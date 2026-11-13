import type { APIContext } from 'astro';
import { describe, expect, it } from 'vitest';

import { POST } from '../pages/api/set-workspace';

const USER = { id: 1, email: 'ada@example.com', full_name: 'Ada', email_verified: true };
const WORKSPACES = [
  { slug: 'acme', name: 'Acme', role: 'admin' },
  { slug: 'orbit', name: 'Orbit', role: 'editor' },
];

function contextFor(body: Record<string, string>, locals: Partial<App.Locals> = {}): APIContext {
  const request = new Request('http://localhost/api/set-workspace', {
    method: 'POST',
    body: new URLSearchParams(body),
  });

  return {
    request,
    locals: {
      user: USER,
      workspaces: WORKSPACES,
      workspaceSlug: 'acme',
      ...locals,
    },
  } as APIContext;
}

describe('set workspace endpoint', () => {
  it('sets the workspace cookie for a workspace the user can access', async () => {
    const response = await POST(contextFor({ slug: 'orbit', returnTo: '/runs?state=failed' }));

    expect(response.status).toBe(302);
    expect(response.headers.get('Location')).toBe('/runs?state=failed');
    expect(response.headers.get('Set-Cookie')).toContain('ms-workspace=orbit');
    expect(response.headers.get('Set-Cookie')).toContain('HttpOnly');
    expect(response.headers.get('Set-Cookie')).toContain('SameSite=Lax');
  });

  it('rejects anonymous requests before setting a cookie', async () => {
    const response = await POST(contextFor({ slug: 'orbit' }, { user: null }));

    expect(response.status).toBe(401);
    expect(response.headers.has('Set-Cookie')).toBe(false);
  });

  it('rejects workspaces outside the authenticated workspace list', async () => {
    const response = await POST(contextFor({ slug: 'outside' }));

    expect(response.status).toBe(404);
    expect(response.headers.has('Set-Cookie')).toBe(false);
  });

  it('falls back to the dashboard for unsafe return targets', async () => {
    const response = await POST(contextFor({ slug: 'orbit', returnTo: 'https://evil.test' }));

    expect(response.status).toBe(302);
    expect(response.headers.get('Location')).toBe('/dashboard');
  });
});
