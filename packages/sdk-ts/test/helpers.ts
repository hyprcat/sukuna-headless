/** Test utilities: fake `fetch`, JSON responses, and SSE response bodies. */

export interface RecordedCall {
  url: string;
  method: string;
  headers: Record<string, string>;
  body: string | null;
}

export type FetchHandler = (call: RecordedCall) => Response | Promise<Response>;

/** Build a `fetch`-compatible function that records calls and delegates to `handler`. */
export function recordingFetch(handler: FetchHandler): {
  fetch: typeof fetch;
  calls: RecordedCall[];
} {
  const calls: RecordedCall[] = [];
  const impl = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const url = typeof input === 'string' ? input : input.toString();
    const headers: Record<string, string> = {};
    const rawHeaders = init?.headers;
    if (rawHeaders) {
      for (const [k, v] of Object.entries(rawHeaders as Record<string, string>)) {
        headers[k.toLowerCase()] = v;
      }
    }
    const body = typeof init?.body === 'string' ? init.body : null;
    const call: RecordedCall = { url, method: init?.method ?? 'GET', headers, body };
    calls.push(call);
    return handler(call);
  };
  return { fetch: impl as unknown as typeof fetch, calls };
}

/** A JSON Response with the given body and status. */
export function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

/** A `text/event-stream` Response built from a list of sandbox event objects. */
export function sseResponse(events: Array<Record<string, unknown>>): Response {
  const text = events
    .map(
      (e) =>
        `id: ${String(e.sequence_no)}\nevent: ${String(e.event_type)}\ndata: ${JSON.stringify(e)}\n\n`,
    )
    .join('');
  return new Response(text, {
    status: 200,
    headers: { 'content-type': 'text/event-stream' },
  });
}

/** A representative ordered batch of run events ending in `run_completed`. */
export function happyPathEvents(): Array<Record<string, unknown>> {
  return [
    {
      event_id: 'e1',
      sequence_no: 1,
      event_type: 'run_started',
      payload: { model_tier: 'pro', sandbox_id: 'sb1' },
      emitted_at: '2026-06-21T00:00:00Z',
    },
    {
      event_id: 'e2',
      sequence_no: 2,
      event_type: 'tool_call',
      payload: { call_id: 'c1', tool_name: 'search', arguments: { q: 'x' }, is_mcp: false },
      emitted_at: '2026-06-21T00:00:01Z',
    },
    {
      event_id: 'e3',
      sequence_no: 3,
      event_type: 'tool_result',
      payload: { call_id: 'c1', tool_name: 'search', result: 'ok', duration_ms: 12 },
      emitted_at: '2026-06-21T00:00:02Z',
    },
    {
      event_id: 'e4',
      sequence_no: 4,
      event_type: 'usage_checkpoint',
      payload: { runtime_seconds: 5, total_tokens: 50, cost_usd: '0.20', tool_calls_count: 1 },
      emitted_at: '2026-06-21T00:00:03Z',
    },
    {
      event_id: 'e5',
      sequence_no: 5,
      event_type: 'run_completed',
      payload: {
        final_usage: { runtime_seconds: 10, total_tokens: 100, cost_usd: '0.40' },
        summary: 'done',
      },
      emitted_at: '2026-06-21T00:00:04Z',
    },
  ];
}
