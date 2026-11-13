/**
 * Projection of sandbox callback events into timeline display content.
 *
 * Event types + payload shapes mirror the sandbox contract
 * (`agent_server/schemas/sandbox_contracts.py`): run_started, step,
 * tool_call, tool_result, hitl_requested, hitl_responded,
 * artifact_created, usage_checkpoint, run_completed, run_failed,
 * run_cancelled. RunEvent rows store the raw (snake_case) callback payload.
 */
import { formatSize } from './format';

export interface RunEvent {
  sequenceNo: number;
  eventType: string;
  payload: Record<string, unknown>;
}

/**
 * Dot category — a functional event-type indicator, not a brand accent.
 * The timeline maps each to a muted hue so events are scannable by kind.
 */
export type EventTone = 'ok' | 'info' | 'tool' | 'hitl' | 'artifact' | 'usage' | 'err' | 'muted';

export interface EventContent {
  /** Primary body text (reasoning, summary, prompt, error). */
  text?: string;
  /** JSON payload rendered in a code block (tool arguments / object results). */
  code?: string;
  /** Label shown on the code block (usually the tool name). */
  codeLabel?: string;
  /** Small muted secondary line (model tier, duration, size, token snapshot). */
  meta?: string;
  /** Renders text in the error tone. */
  isError?: boolean;
}

const EVENT_LABELS: Record<string, string> = {
  run_started: 'Run started',
  step: 'Step',
  tool_call: 'Tool call',
  tool_result: 'Tool result',
  hitl_requested: 'Approval requested',
  hitl_responded: 'Approval responded',
  artifact_created: 'Artifact created',
  usage_checkpoint: 'Usage checkpoint',
  run_completed: 'Run completed',
  run_failed: 'Run failed',
  run_cancelled: 'Run cancelled',
};

const EVENT_TONES: Record<string, EventTone> = {
  run_started: 'ok',
  step: 'info',
  tool_call: 'tool',
  tool_result: 'tool',
  hitl_requested: 'hitl',
  hitl_responded: 'hitl',
  artifact_created: 'artifact',
  usage_checkpoint: 'usage',
  run_completed: 'ok',
  run_failed: 'err',
  run_cancelled: 'muted',
};

export function eventLabel(event: RunEvent): string {
  const base = EVENT_LABELS[event.eventType] ?? event.eventType.replace(/_/g, ' ');
  const name = str(event.payload.tool_name);
  if ((event.eventType === 'tool_call' || event.eventType === 'tool_result') && name) {
    return `${base}: ${name}`;
  }
  return base;
}

export function eventDotTone(eventType: string): EventTone {
  return EVENT_TONES[eventType] ?? 'muted';
}

const TERMINAL_TONES = ['run_completed', 'run_failed', 'run_cancelled'];

export function isTerminalEvent(eventType: string): boolean {
  return TERMINAL_TONES.includes(eventType);
}

export function eventContent(event: RunEvent): EventContent {
  const p = event.payload;
  switch (event.eventType) {
    case 'run_started':
      return { meta: `${str(p.model_tier)} tier · sandbox ${str(p.sandbox_id)}` };
    case 'step':
      return { text: [str(p.reasoning), str(p.output)].filter(Boolean).join('\n\n') };
    case 'tool_call':
      return { code: pretty(p.arguments), codeLabel: str(p.tool_name) || 'tool' };
    case 'tool_result':
      return toolResult(p);
    case 'hitl_requested':
      return { text: str(p.prompt), meta: 'Waiting for approval' };
    case 'hitl_responded':
      return { text: str(p.response) === 'approve' ? 'Approved' : 'Denied' };
    case 'artifact_created':
      return {
        text: str(p.name),
        meta: [str(p.content_type), formatSize(num(p.size_bytes))].filter(Boolean).join(' · '),
      };
    case 'usage_checkpoint':
      return { meta: usageLine(p) };
    case 'run_completed':
      return { text: str(p.summary) || 'Run completed.' };
    case 'run_failed':
      return { text: str(p.message) || str(p.error_code), meta: str(p.error_code), isError: true };
    case 'run_cancelled':
      return { text: str(p.reason) === 'timeout' ? 'Timed out.' : 'Cancelled by user.' };
    default:
      return {};
  }
}

function toolResult(p: Record<string, unknown>): EventContent {
  const meta = num(p.duration_ms) > 0 ? `${num(p.duration_ms)} ms` : undefined;
  if (p.error) return { text: str(p.error), meta, isError: true };
  if (typeof p.result === 'string') return { text: p.result, meta };
  if (p.result != null) return { code: pretty(p.result), codeLabel: 'result', meta };
  return { meta };
}

function usageLine(p: Record<string, unknown>): string {
  const parts = [
    `${num(p.total_tokens).toLocaleString()} tokens`,
    `$${num(p.cost_usd).toFixed(2)}`,
  ];
  if (p.tool_calls_count != null) parts.push(`${num(p.tool_calls_count)} tool calls`);
  return parts.join(' · ');
}

function str(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

function num(value: unknown): number {
  const n = typeof value === 'string' ? Number(value) : (value as number);
  return Number.isFinite(n) ? n : 0;
}

function pretty(value: unknown): string {
  return JSON.stringify(value ?? {}, null, 2);
}
