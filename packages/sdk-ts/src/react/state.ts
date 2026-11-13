/**
 * The state machine behind {@link useAgent}, extracted as a pure reducer so the
 * interesting transitions are testable without rendering React.
 */

import type { RunStatus } from '../types.js';
import type { RunOutcome } from '../run/run.js';
import type { StreamEvent } from '../run/events.js';

/** Coarse lifecycle phase the UI keys off of. */
export type AgentPhase = 'idle' | 'starting' | 'streaming' | 'done' | 'error';

export interface AgentState {
  /** Coarse phase — drives spinners, disabled states, result panels. */
  phase: AgentPhase;
  /** Control-plane run status, or `null` before a run is attached. */
  status: RunStatus | null;
  /** Events streamed so far, in arrival order. */
  events: StreamEvent[];
  /** Structured terminal outcome, once the run finishes/fails/cancels. */
  outcome: RunOutcome | null;
  /** The error that moved the hook into the `'error'` phase, if any. */
  error: Error | null;
}

export const initialAgentState: AgentState = {
  phase: 'idle',
  status: null,
  events: [],
  outcome: null,
  error: null,
};

export type AgentAction =
  | { type: 'start'; status: RunStatus }
  | { type: 'event'; event: StreamEvent; status: RunStatus }
  | { type: 'outcome'; outcome: RunOutcome }
  | { type: 'error'; error: Error }
  | { type: 'reset' };

/** Pure transition function — see {@link AgentState} for field meaning. */
export function agentReducer(state: AgentState, action: AgentAction): AgentState {
  switch (action.type) {
    case 'start':
      // A new run clears prior events/outcome/error so the UI starts clean.
      return { phase: 'starting', status: action.status, events: [], outcome: null, error: null };
    case 'event':
      return {
        ...state,
        phase: 'streaming',
        status: action.status,
        events: [...state.events, action.event],
      };
    case 'outcome':
      return { ...state, phase: 'done', status: action.outcome.status, outcome: action.outcome };
    case 'error':
      return { ...state, phase: 'error', error: action.error };
    case 'reset':
      return initialAgentState;
  }
}
