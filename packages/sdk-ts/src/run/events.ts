/**
 * Sandbox streaming event contract.
 *
 * The sandbox emits Server-Sent Events; each message's `data` field is a JSON
 * envelope with camelCase keys wrapping a snake_case payload that mirrors the
 * runtime wire contract exactly — do not rename payload fields.
 */

import type { EventSourceMessage } from 'eventsource-parser';

// ---------------------------------------------------------------------------
// Shared
// ---------------------------------------------------------------------------

/** Cumulative lease usage figures, shared across terminal event payloads. */
export interface LeaseUsage {
  runtime_seconds: number;
  total_tokens: number;
  /** Stringified decimal, e.g. "0.0142". */
  cost_usd: string;
}

// ---------------------------------------------------------------------------
// Per-type payload interfaces (snake_case, faithful to runtime contract)
// ---------------------------------------------------------------------------

export interface RunStartedPayload {
  model_tier: string;
  sandbox_id: string;
}

export interface StepPayload {
  step_index: number;
  reasoning: string;
  output: string;
}

export interface ToolCallPayload {
  call_id: string;
  tool_name: string;
  arguments: Record<string, unknown>;
  is_mcp: boolean;
}

export interface ToolResultPayload {
  call_id: string;
  tool_name: string;
  result: string | Record<string, unknown>;
  error?: string;
  duration_ms: number;
}

export interface HitlRequestedPayload {
  request_id: string;
  prompt: string;
  choices: string[];
}

export interface HitlRespondedPayload {
  request_id: string;
  response: 'approve' | 'deny';
  responded_at: string;
}

export interface ArtifactCreatedPayload {
  artifact_id: string;
  name: string;
  content_type: string;
  size_bytes: number;
  storage_ref: string;
}

export interface UsageCheckpointPayload {
  runtime_seconds: number;
  total_tokens: number;
  cost_usd: string;
  tool_calls_count: number;
}

export interface RunCompletedPayload {
  final_usage: LeaseUsage;
  summary: string;
}

export interface RunFailedPayload {
  error_code: string;
  message: string;
  final_usage: LeaseUsage;
}

export interface RunCancelledPayload {
  reason: string;
  final_usage: LeaseUsage;
}

// ---------------------------------------------------------------------------
// Discriminant union
// ---------------------------------------------------------------------------

export type StreamEventType =
  | 'run_started'
  | 'step'
  | 'tool_call'
  | 'tool_result'
  | 'hitl_requested'
  | 'hitl_responded'
  | 'artifact_created'
  | 'usage_checkpoint'
  | 'run_completed'
  | 'run_failed'
  | 'run_cancelled';

/** CamelCase envelope wrapping a snake_case payload per the sandbox contract. */
interface StreamEventBase<T extends StreamEventType, P> {
  /** Unique event id (UUID) from the sandbox. */
  eventId: string;
  /** Monotonic per-run sequence number. Use as the `after` cursor to resume. */
  sequenceNo: number;
  /** Discriminant. */
  type: T;
  /** Type-specific payload (snake_case, faithful to the runtime contract). */
  payload: P;
  /** ISO-8601 timestamp. */
  emittedAt: string;
}

export type StreamEvent =
  | StreamEventBase<'run_started', RunStartedPayload>
  | StreamEventBase<'step', StepPayload>
  | StreamEventBase<'tool_call', ToolCallPayload>
  | StreamEventBase<'tool_result', ToolResultPayload>
  | StreamEventBase<'hitl_requested', HitlRequestedPayload>
  | StreamEventBase<'hitl_responded', HitlRespondedPayload>
  | StreamEventBase<'artifact_created', ArtifactCreatedPayload>
  | StreamEventBase<'usage_checkpoint', UsageCheckpointPayload>
  | StreamEventBase<'run_completed', RunCompletedPayload>
  | StreamEventBase<'run_failed', RunFailedPayload>
  | StreamEventBase<'run_cancelled', RunCancelledPayload>;

// ---------------------------------------------------------------------------
// Terminal-event helpers
// ---------------------------------------------------------------------------

const TERMINAL_EVENT_TYPES = [
  'run_completed',
  'run_failed',
  'run_cancelled',
] as const satisfies ReadonlyArray<StreamEventType>;
export { TERMINAL_EVENT_TYPES };

/** Returns true when the event is one of the three terminal types. */
export function isTerminalEvent(event: StreamEvent): boolean {
  return isTerminalType(event.type);
}

/** Returns true when `type` is one of the three terminal type strings. */
export function isTerminalType(type: string): boolean {
  return (TERMINAL_EVENT_TYPES as ReadonlyArray<string>).includes(type);
}

// ---------------------------------------------------------------------------
// Parser
// ---------------------------------------------------------------------------

const KNOWN_EVENT_TYPES = new Set<string>([
  'run_started',
  'step',
  'tool_call',
  'tool_result',
  'hitl_requested',
  'hitl_responded',
  'artifact_created',
  'usage_checkpoint',
  'run_completed',
  'run_failed',
  'run_cancelled',
]);

/**
 * Parses a raw SSE message into a typed {@link StreamEvent}.
 *
 * Returns `null` for empty data, parse errors, or unrecognised event types
 * (forward-compatible: new event types are silently skipped).
 */
export function parseStreamEvent(message: EventSourceMessage): StreamEvent | null {
  if (!message.data) return null;

  let raw: unknown;
  try {
    raw = JSON.parse(message.data);
  } catch {
    return null;
  }

  if (
    raw === null ||
    typeof raw !== 'object' ||
    !('event_type' in raw) ||
    typeof (raw as Record<string, unknown>)['event_type'] !== 'string'
  ) {
    return null;
  }

  const r = raw as Record<string, unknown>;
  const event_type = r['event_type'] as string;

  if (!KNOWN_EVENT_TYPES.has(event_type)) {
    return null;
  }

  if (typeof r['sequence_no'] !== 'number') return null;
  if (typeof r['event_id'] !== 'string') return null;
  if (typeof r['emitted_at'] !== 'string') return null;

  const event_id = r['event_id'];
  const sequence_no = r['sequence_no'];
  const emitted_at = r['emitted_at'];
  const payload = r['payload'] ?? {};

  // Cast is acceptable here: the runtime guarantees payload shape per event_type.
  // We validate the envelope fields above; deep payload validation is not done
  // to avoid brittleness when the runtime adds optional fields.
  return {
    eventId: event_id,
    sequenceNo: sequence_no,
    type: event_type as StreamEventType,
    payload,
    emittedAt: emitted_at,
  } as StreamEvent;
}
