import type { APIRoute } from 'astro';
import { gql } from '../../../lib/graphql';

/**
 * Lightweight projected-state endpoint polled by the run detail page while a
 * run is queued/running. Re-runs the workspace-scoped query server-side so the
 * browser never needs the workspace header. Returns just the fields the live
 * refresh compares against — the page reloads to re-render the timeline when
 * the event count or status changes.
 */
interface RunLiveState {
  status: string;
  lastCallbackAt: string | null;
  totalCost: number;
  totalTokens: number;
  events: { totalCount: number };
}

export const GET: APIRoute = async ({ params, request, locals }) => {
  if (!locals.user) {
    return new Response('Not authenticated', { status: 401 });
  }

  const cookie = request.headers.get('cookie') ?? '';
  const wsSlug = locals.workspaceSlug ?? undefined;

  const { data } = await gql<{ run: RunLiveState | null }>(
    `query RunState($runUid: UUID!) {
      run(runUid: $runUid) {
        status lastCallbackAt totalCost totalTokens
        events { totalCount }
      }
    }`,
    { runUid: params.id },
    cookie,
    wsSlug,
  );

  const run = data?.run;
  if (!run) {
    return new Response('Not found', { status: 404 });
  }

  return new Response(
    JSON.stringify({
      status: run.status,
      lastCallbackAt: run.lastCallbackAt,
      totalCost: run.totalCost,
      totalTokens: run.totalTokens,
      eventCount: run.events.totalCount,
    }),
    { headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' } },
  );
};
