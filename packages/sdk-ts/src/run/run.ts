/**
 * High-level handle to a started run.
 *
 * Wraps a {@link SandboxConnection} and exposes a clean lifecycle API:
 * streaming events, waiting for the terminal outcome, cancelling, responding
 * to HITL prompts, and refreshing the short-lived capability token.
 */

import type { RunStatus } from '../types.js';
import type { FetchLike } from '../config.js';
import { MidsphereStreamError } from '../errors.js';
import { SandboxConnection } from './sandbox.js';
import { isTerminalEvent } from './events.js';
import type { StreamEvent, LeaseUsage } from './events.js';

// ---------------------------------------------------------------------------
// Public types
// ---------------------------------------------------------------------------

export interface RunInit {
  runId: string;
  runUid: string;
  sandboxUrl: string;
  capabilityToken: string;
  tokenExpiresAt: string | null;
  fetch: FetchLike;
  /** Initial lifecycle status. Defaults to `'QUEUED'`; a woken run starts `'RUNNING'`. */
  status?: RunStatus;
}

/**
 * Supplied by the {@link Midsphere} client so `Run` can refresh its capability
 * token via GraphQL without importing the transport (avoids a cycle).
 */
export type RefreshTokenFn = () => Promise<{
  capabilityToken: string;
  tokenExpiresAt: string | null;
}>;

/**
 * A plain, JSON-serializable view of a {@link Run} — everything needed to
 * reconstruct the handle elsewhere. Safe to return from a server action / RSC
 * boundary so a client component can resume streaming without a round-trip.
 *
 * Note it carries the short-lived `capabilityToken`; treat it like a bearer
 * credential. It only grants stream/cancel/HITL access to this one run.
 */
export interface RunSnapshot {
  runId: string;
  runUid: string;
  sandboxUrl: string;
  capabilityToken: string;
  tokenExpiresAt: string | null;
  status: RunStatus;
}

/** Outcome returned by {@link Run.wait} once the run has reached a terminal state. */
export interface RunOutcome {
  status: Extract<RunStatus, 'FINISHED' | 'FAILED' | 'CANCELLED'>;
  summary?: string;
  errorCode?: string;
  errorMessage?: string;
  usage?: LeaseUsage;
  lastEvent: StreamEvent;
}

// ---------------------------------------------------------------------------
// Run class
// ---------------------------------------------------------------------------

/** A handle to a started agent run. */
export class Run {
  /** Relay global ID (control-plane identifier). */
  readonly id: string;
  /** Internal UID used by the sandbox. */
  readonly uid: string;
  /** URL base of the sandbox proxy. */
  readonly sandboxUrl: string;
  /** Current lifecycle status. Updated as events arrive. */
  status: RunStatus;

  private readonly connection: SandboxConnection;
  private readonly refresh: RefreshTokenFn | undefined;
  private rawTokenExpiresAt: string | null;

  constructor(init: RunInit, refresh?: RefreshTokenFn) {
    this.id = init.runId;
    this.uid = init.runUid;
    this.sandboxUrl = init.sandboxUrl;
    this.status = init.status ?? 'QUEUED';
    this.rawTokenExpiresAt = init.tokenExpiresAt;
    this.refresh = refresh;
    this.connection = new SandboxConnection({
      sandboxUrl: init.sandboxUrl,
      runUid: init.runUid,
      token: init.capabilityToken,
      fetch: init.fetch,
    });
  }

  /** Expiry of the current capability token, or `null` if unknown. */
  get tokenExpiresAt(): Date | null {
    return this.rawTokenExpiresAt !== null ? new Date(this.rawTokenExpiresAt) : null;
  }

  /**
   * Serializes this handle into a {@link RunSnapshot} you can pass across a
   * server→client boundary (Next.js server action, RSC props) and rebuild with
   * `client.runFromSnapshot(...)`. Captures the live capability token, so the
   * resumed handle streams immediately with no network round-trip.
   */
  toSnapshot(): RunSnapshot {
    return {
      runId: this.id,
      runUid: this.uid,
      sandboxUrl: this.sandboxUrl,
      capabilityToken: this.connection.currentToken(),
      tokenExpiresAt: this.rawTokenExpiresAt,
      status: this.status,
    };
  }

  // -------------------------------------------------------------------------
  // Streaming
  // -------------------------------------------------------------------------

  /**
   * Streams sandbox events for this run.
   *
   * Sets `status` to `'RUNNING'` on the first event, and updates it to the
   * appropriate terminal value on the last event. The terminal event is yielded
   * before the generator returns.
   */
  async *stream(
    opts: { after?: number; signal?: AbortSignal } = {},
  ): AsyncGenerator<StreamEvent, void, void> {
    let started = false;
    for await (const event of this.connection.stream(opts)) {
      if (!started) {
        started = true;
        this.status = 'RUNNING';
      }

      if (isTerminalEvent(event)) {
        this.status = terminalStatus(event);
        yield event;
        return;
      }

      yield event;
    }
  }

  // -------------------------------------------------------------------------
  // Wait for outcome
  // -------------------------------------------------------------------------

  /**
   * Consumes the stream and resolves with a structured {@link RunOutcome} once
   * the run reaches a terminal state.
   *
   * @throws {MidsphereStreamError} when the stream ends without a terminal event.
   */
  async wait(opts: { signal?: AbortSignal } = {}): Promise<RunOutcome> {
    let last: StreamEvent | undefined;

    for await (const event of this.stream(opts)) {
      last = event;
    }

    if (last === undefined || !isTerminalEvent(last)) {
      throw new MidsphereStreamError('Run stream ended before a terminal event.');
    }

    return buildOutcome(last);
  }

  // -------------------------------------------------------------------------
  // Control operations
  // -------------------------------------------------------------------------

  /**
   * Requests cancellation of the run. Optimistically sets `status` to
   * `'CANCELLED'` before the sandbox acknowledges.
   */
  async cancel(opts: { signal?: AbortSignal } = {}): Promise<void> {
    await this.connection.cancel(opts);
    this.status = 'CANCELLED';
  }

  /**
   * Submits a human-in-the-loop decision.
   */
  async respond(
    requestId: string,
    decision: 'approve' | 'deny',
    opts: { signal?: AbortSignal } = {},
  ): Promise<void> {
    await this.connection.respondToHitl(requestId, decision, opts);
  }

  /**
   * Refreshes the capability token using the client-supplied `RefreshTokenFn`.
   *
   * @throws {MidsphereStreamError} when no refresh function was provided.
   */
  async refreshToken(): Promise<void> {
    if (this.refresh === undefined) {
      throw new MidsphereStreamError('This run cannot refresh its token (no client context).');
    }
    const result = await this.refresh();
    this.connection.setToken(result.capabilityToken);
    this.rawTokenExpiresAt = result.tokenExpiresAt;
  }
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

function terminalStatus(
  event: StreamEvent,
): Extract<RunStatus, 'FINISHED' | 'FAILED' | 'CANCELLED'> {
  if (event.type === 'run_completed') return 'FINISHED';
  if (event.type === 'run_failed') return 'FAILED';
  return 'CANCELLED';
}

/**
 * Builds a {@link RunOutcome} from a terminal event, or returns `null` for a
 * non-terminal one. Lets consumers that drive `stream()` themselves (e.g. the
 * `useAgent` hook) derive the outcome from the last event without re-waiting.
 */
export function runOutcomeFromEvent(event: StreamEvent): RunOutcome | null {
  return isTerminalEvent(event) ? buildOutcome(event) : null;
}

function buildOutcome(event: StreamEvent): RunOutcome {
  if (event.type === 'run_completed') {
    return {
      status: 'FINISHED',
      summary: event.payload.summary,
      usage: event.payload.final_usage,
      lastEvent: event,
    };
  }

  if (event.type === 'run_failed') {
    return {
      status: 'FAILED',
      errorCode: event.payload.error_code,
      errorMessage: event.payload.message,
      usage: event.payload.final_usage,
      lastEvent: event,
    };
  }

  if (event.type === 'run_cancelled') {
    return {
      status: 'CANCELLED',
      usage: event.payload.final_usage,
      lastEvent: event,
    };
  }

  // buildOutcome is only ever called with a terminal event; guard the contract.
  throw new MidsphereStreamError(`Expected a terminal event, got "${event.type}".`);
}
