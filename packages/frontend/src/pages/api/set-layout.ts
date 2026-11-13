import type { APIRoute } from 'astro';
import { safeReturnTo } from '../../lib/url';

const LAYOUT_COOKIE_MAX_AGE_SECONDS = 31_536_000;
const VALID_LAYOUTS = new Set(['classic', 'new']);

export const POST: APIRoute = async ({ locals, request }) => {
  const form = await request.formData();
  const layout = (form.get('layout') as string) ?? '';
  const returnTo = safeReturnTo((form.get('returnTo') as string) || '');

  if (!locals.user) {
    return new Response('Not authenticated', { status: 401 });
  }

  if (!VALID_LAYOUTS.has(layout)) {
    return new Response('Invalid layout', { status: 400 });
  }

  return new Response(null, {
    status: 302,
    headers: {
      Location: returnTo,
      'Set-Cookie': `ms-layout=${layout}; Path=/; HttpOnly; SameSite=Lax; Max-Age=${LAYOUT_COOKIE_MAX_AGE_SECONDS}`,
    },
  });
};
