import type { APIRoute } from 'astro';
import { safeReturnTo } from '../../lib/url';

const WORKSPACE_COOKIE_MAX_AGE_SECONDS = 31_536_000;

export const POST: APIRoute = async ({ locals, request }) => {
  const form = await request.formData();
  const slug = (form.get('slug') as string) ?? '';
  const returnTo = safeReturnTo((form.get('returnTo') as string) || '');

  if (!locals.user) {
    return new Response('Not authenticated', { status: 401 });
  }

  if (!slug) {
    return new Response('Missing slug', { status: 400 });
  }

  const canSwitch = locals.workspaces.some((workspace) => workspace.slug === slug);
  if (!canSwitch) {
    return new Response('Workspace not found', { status: 404 });
  }

  return new Response(null, {
    status: 302,
    headers: {
      Location: returnTo,
      'Set-Cookie': `ms-workspace=${encodeURIComponent(slug)}; Path=/; HttpOnly; SameSite=Lax; Max-Age=${WORKSPACE_COOKIE_MAX_AGE_SECONDS}`,
    },
  });
};
