import { defineMiddleware } from 'astro:middleware';
import { apiGet } from './lib/api';
import { isPublicPath } from './lib/route-access';

interface MeData {
  user: { id: number; email: string; full_name: string; email_verified: boolean };
  workspace_slug: string | null;
  workspaces: { slug: string; name: string; role: string }[];
}

function parseCookie(header: string, name: string): string | null {
  const match = header.match(new RegExp(`(?:^|;)\\s*${name}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : null;
}

function loginUrl(pathname: string, search: string): string {
  const returnTo = `${pathname}${search}`;
  if (returnTo === '/' || returnTo === '/dashboard') return '/login';
  return `/login?return_to=${encodeURIComponent(returnTo)}`;
}

export const onRequest = defineMiddleware(async (context, next) => {
  context.locals.user = null;
  context.locals.workspaceSlug = null;
  context.locals.workspaces = [];
  context.locals.layout = 'classic';

  const cookie = context.request.headers.get('cookie') ?? '';
  const { pathname, search } = context.url;

  // New layout is the default; classic is opt-out via the account-menu toggle.
  context.locals.layout = parseCookie(cookie, 'ms-layout') === 'classic' ? 'classic' : 'new';

  if (!cookie) {
    if (!isPublicPath(pathname)) return context.redirect(loginUrl(pathname, search));
    return next();
  }

  const me = await apiGet<MeData>('/auth/me/', cookie);

  if (!me.ok || !me.data?.user) {
    if (!isPublicPath(pathname)) return context.redirect(loginUrl(pathname, search));
    return next();
  }

  context.locals.user = me.data.user;
  context.locals.workspaces = me.data.workspaces ?? [];

  const preferred = parseCookie(cookie, 'ms-workspace');
  const validSlugs = context.locals.workspaces.map((w) => w.slug);

  if (preferred && validSlugs.includes(preferred)) {
    context.locals.workspaceSlug = preferred;
  } else {
    context.locals.workspaceSlug = me.data.workspace_slug ?? null;
  }

  if (pathname === '/login' || pathname === '/signup') {
    return context.redirect('/dashboard');
  }

  return next();
});
