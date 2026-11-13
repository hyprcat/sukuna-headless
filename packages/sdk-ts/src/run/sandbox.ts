/**
 * Direct HTTP client for a single running sandbox.
 *
 * Sandboxes are reached via the Caddy reverse proxy at
 * `https://{sandbox_id}.run.midsphere.com`. Auth is a short-lived capability
 * JWT sent as `Authorization: Bearer <token>`. This module is intentionally
 * low-level — see {@link ./run} for the higher-level lifecycle handle.
 */

import { EventSourceParserStream } from 'eventsource-parser/stream';
import type { FetchLike } from '../config.js';
import { MidsphereStreamError } from '../errors.js';
import { parseStreamEvent, isTerminalEvent } from './events.js';
import type { StreamEvent } from './events.js';

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

export interface SandboxConnectionInit {
  sandboxUrl: string;
  runUid: string;
  token: string;
  fetch: FetchLike;
}

/** Low-level HTTP client bound to a single sandbox run. */
export class SandboxConnection {
  private readonly runUid: string;
  private readonly fetch: FetchLike;
  private readonly base: string;
  private token: string;

  constructor(init: SandboxConnectionInit) {
    this.runUid = init.runUid;
    this.fetch = init.fetch;
    this.base = init.sandboxUrl.replace(/\/+$/, '');
    this.token = init.token;
  }

  /** Update the capability token (called after a token refresh). */
  setToken(token: string): void {
    this.token = token;
  }

  /** The capability token currently in use — read by {@link Run.toSnapshot}. */
  currentToken(): string {
    return this.token;
  }

  // -------------------------------------------------------------------------
  // Private helpers
  // -------------------------------------------------------------------------

  /** Returns the auth + accept headers shared by all requests. */
  private headers(): Record<string, string> {
    return {
      authorization: `Bearer ${this.token}`,
    };
  }

  // -------------------------------------------------------------------------
  // Methods
  // -------------------------------------------------------------------------

  /**
   * Opens the sandbox SSE stream for this run.
   *
   * Yields {@link StreamEvent}s in order, terminating naturally after the
   * terminal event (`run_completed`, `run_failed`, `run_cancelled`). Cancelling
   * the `signal` or breaking out of the `for await` loop releases the upstream
   * connection.
   */
  async *stream(
    opts: { after?: number; signal?: AbortSignal } = {},
  ): AsyncGenerator<StreamEvent, void, void> {
    const url = new URL(`${this.base}/runs/${this.runUid}/stream`);
    if (opts.after != null) {
      url.searchParams.set('after', String(opts.after));
    }

    let res: Response;
    try {
      res = await this.fetch(url.toString(), {
        method: 'GET',
        headers: { ...this.headers(), accept: 'text/event-stream' },
        ...(opts.signal !== undefined ? { signal: opts.signal } : {}),
      });
    } catch (cause) {
      // Let abort errors (DOMException name AbortError) propagate as-is.
      if (
        cause instanceof Error &&
        (cause.name === 'AbortError' || cause.name === 'TimeoutError')
      ) {
        throw cause;
      }
      throw new MidsphereStreamError('Sandbox stream request failed.', { cause });
    }

    if (!res.ok) {
      throw new MidsphereStreamError(`Sandbox stream failed (HTTP ${res.status}).`, {
        status: res.status,
      });
    }
    if (!res.body) {
      throw new MidsphereStreamError('Sandbox stream returned no body.');
    }

    const reader = res.body
      .pipeThrough(new TextDecoderStream())
      .pipeThrough(new EventSourceParserStream())
      .getReader();

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) return;

        const event = parseStreamEvent(value);
        if (event === null) continue;

        yield event;
        if (isTerminalEvent(event)) return;
      }
    } finally {
      await reader.cancel().catch(() => {});
    }
  }

  /**
   * Requests cancellation of the run.
   *
   * Sends `DELETE /runs/{runUid}`. Throws {@link MidsphereStreamError} on a
   * non-2xx response.
   */
  async cancel(opts: { signal?: AbortSignal } = {}): Promise<void> {
    let res: Response;
    try {
      res = await this.fetch(`${this.base}/runs/${this.runUid}`, {
        method: 'DELETE',
        headers: this.headers(),
        ...(opts.signal !== undefined ? { signal: opts.signal } : {}),
      });
    } catch (cause) {
      throw new MidsphereStreamError('Sandbox cancel request failed.', { cause });
    }

    if (!res.ok) {
      throw new MidsphereStreamError(`Sandbox cancel failed (HTTP ${res.status}).`, {
        status: res.status,
      });
    }
  }

  /**
   * Submits a human-in-the-loop decision for the given `requestId`.
   *
   * Sends `POST /runs/{runUid}/hitl/{requestId}` with `{ response: decision }`.
   * Throws {@link MidsphereStreamError} on a non-2xx response.
   */
  async respondToHitl(
    requestId: string,
    decision: 'approve' | 'deny',
    opts: { signal?: AbortSignal } = {},
  ): Promise<void> {
    let res: Response;
    try {
      res = await this.fetch(`${this.base}/runs/${this.runUid}/hitl/${requestId}`, {
        method: 'POST',
        headers: {
          ...this.headers(),
          'content-type': 'application/json',
        },
        body: JSON.stringify({ response: decision }),
        ...(opts.signal !== undefined ? { signal: opts.signal } : {}),
      });
    } catch (cause) {
      throw new MidsphereStreamError('Sandbox HITL request failed.', { cause });
    }

    if (!res.ok) {
      throw new MidsphereStreamError(`Sandbox HITL response failed (HTTP ${res.status}).`, {
        status: res.status,
      });
    }
  }
}
