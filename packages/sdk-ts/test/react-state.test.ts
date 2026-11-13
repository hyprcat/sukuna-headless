import { describe, expect, it } from 'vitest';
import { agentReducer, initialAgentState } from '../src/react/state.js';
import type { AgentState } from '../src/react/state.js';
import type { StreamEvent } from '../src/index.js';
import type { RunOutcome } from '../src/run/run.js';

const startedEvent: StreamEvent = {
  eventId: 'e1',
  sequenceNo: 1,
  emittedAt: '2026-06-21T00:00:00Z',
  type: 'run_started',
  payload: { model_tier: 'pro', sandbox_id: 'sb1' },
};

const completedOutcome: RunOutcome = {
  status: 'FINISHED',
  summary: 'done',
  usage: { runtime_seconds: 1, total_tokens: 10, cost_usd: '0.10' },
  lastEvent: startedEvent,
};

describe('agentReducer', () => {
  it("'start' clears prior events/outcome/error and sets the phase", () => {
    const dirty: AgentState = {
      phase: 'done',
      status: 'FINISHED',
      events: [startedEvent],
      outcome: completedOutcome,
      error: new Error('old'),
    };
    const next = agentReducer(dirty, { type: 'start', status: 'QUEUED' });
    expect(next).toEqual({
      phase: 'starting',
      status: 'QUEUED',
      events: [],
      outcome: null,
      error: null,
    });
  });

  it("'event' appends and moves to the streaming phase", () => {
    const next = agentReducer(initialAgentState, {
      type: 'event',
      event: startedEvent,
      status: 'RUNNING',
    });
    expect(next.phase).toBe('streaming');
    expect(next.status).toBe('RUNNING');
    expect(next.events).toEqual([startedEvent]);
  });

  it("'outcome' records the terminal result and status", () => {
    const streaming = agentReducer(initialAgentState, {
      type: 'event',
      event: startedEvent,
      status: 'RUNNING',
    });
    const next = agentReducer(streaming, { type: 'outcome', outcome: completedOutcome });
    expect(next.phase).toBe('done');
    expect(next.status).toBe('FINISHED');
    expect(next.outcome).toBe(completedOutcome);
    expect(next.events).toEqual([startedEvent]); // events preserved
  });

  it("'error' surfaces the failure without losing events", () => {
    const streaming = agentReducer(initialAgentState, {
      type: 'event',
      event: startedEvent,
      status: 'RUNNING',
    });
    const err = new Error('boom');
    const next = agentReducer(streaming, { type: 'error', error: err });
    expect(next.phase).toBe('error');
    expect(next.error).toBe(err);
    expect(next.events).toEqual([startedEvent]);
  });

  it("'reset' returns to the initial state", () => {
    const next = agentReducer(
      {
        phase: 'error',
        status: 'FAILED',
        events: [startedEvent],
        outcome: null,
        error: new Error(),
      },
      { type: 'reset' },
    );
    expect(next).toEqual(initialAgentState);
  });
});
