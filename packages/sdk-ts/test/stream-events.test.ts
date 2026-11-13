import { describe, expect, it } from 'vitest';
import { parseStreamEvent, isTerminalEvent, isTerminalType } from '../src/run/events.js';
import type { EventSourceMessage } from 'eventsource-parser';

function message(data: unknown): EventSourceMessage {
  return { data: typeof data === 'string' ? data : JSON.stringify(data) };
}

describe('parseStreamEvent', () => {
  it('parses a known event into the camelCase envelope', () => {
    const event = parseStreamEvent(
      message({
        event_id: 'e1',
        sequence_no: 7,
        event_type: 'run_started',
        payload: { model_tier: 'pro', sandbox_id: 'sb1' },
        emitted_at: '2026-06-21T00:00:00Z',
      }),
    );
    expect(event).not.toBeNull();
    expect(event?.type).toBe('run_started');
    expect(event?.eventId).toBe('e1');
    expect(event?.sequenceNo).toBe(7);
    expect(event?.emittedAt).toBe('2026-06-21T00:00:00Z');
    // Payload stays faithful to the snake_case runtime contract.
    if (event?.type === 'run_started') {
      expect(event.payload.sandbox_id).toBe('sb1');
    }
  });

  it('skips unknown event types for forward compatibility', () => {
    const event = parseStreamEvent(
      message({
        event_id: 'e1',
        sequence_no: 1,
        event_type: 'something_new',
        payload: {},
        emitted_at: '2026-06-21T00:00:00Z',
      }),
    );
    expect(event).toBeNull();
  });

  it('skips malformed JSON and empty data', () => {
    expect(parseStreamEvent(message('not json {'))).toBeNull();
    expect(parseStreamEvent({ data: '' })).toBeNull();
  });

  it('detects terminal events', () => {
    expect(isTerminalType('run_completed')).toBe(true);
    expect(isTerminalType('run_failed')).toBe(true);
    expect(isTerminalType('run_cancelled')).toBe(true);
    expect(isTerminalType('tool_call')).toBe(false);

    const completed = parseStreamEvent(
      message({
        event_id: 'e',
        sequence_no: 1,
        event_type: 'run_completed',
        payload: {
          final_usage: { runtime_seconds: 1, total_tokens: 1, cost_usd: '0.01' },
          summary: '',
        },
        emitted_at: '2026-06-21T00:00:00Z',
      }),
    );
    expect(completed && isTerminalEvent(completed)).toBe(true);
  });
});
