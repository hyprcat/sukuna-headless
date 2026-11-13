/**
 * `useAgent` — React state for running an agent and streaming its progress.
 *
 * The hook owns the run lifecycle: it starts (or resumes) a run, accumulates
 * streamed events into reactive state, and exposes imperative controls
 * (`cancel`, `respond`). It surfaces failures through `error`/`phase` rather
 * than rejecting `start`/`resume`, so a component never needs a try/catch.
 *
 * React is a peer dependency; this entry point lives at `@midsphere/sdk/react`
 * so non-React consumers never pull it in.
 */

import { useCallback, useEffect, useReducer, useRef } from 'react';
import type { Midsphere } from '../client.js';
import { runOutcomeFromEvent } from '../run/run.js';
import type { Run, RunSnapshot } from '../run/run.js';
import type { StartRunInput } from '../types.js';
import { agentReducer, initialAgentState, type AgentState } from './state.js';

/** Everything {@link useAgent} returns: reactive state plus imperative controls. */
export interface UseAgentResult extends AgentState {
  /** `true` while the run is being created or actively streaming. */
  isActive: boolean;
  /** Start a fresh run for this agent and stream it. Never rejects. */
  start: (input: Omit<StartRunInput, 'agentId'>) => Promise<void>;
  /** Resume a run from a {@link RunSnapshot} (e.g. handed over by a server action). Never rejects. */
  resume: (snapshot: RunSnapshot) => Promise<void>;
  /** Drive an existing {@link Run} handle (e.g. from `client.wakeForRun`). Never rejects. */
  attach: (run: Run) => void;
  /** Request cancellation of the active run. */
  cancel: () => Promise<void>;
  /** Submit a human-in-the-loop decision for the active run. */
  respond: (requestId: string, decision: 'approve' | 'deny') => Promise<void>;
  /** Abort streaming and clear all state back to idle. */
  reset: () => void;
}

interface ActiveRun {
  run: Run;
  controller: AbortController;
}

/**
 * @param client a configured {@link Midsphere} instance
 * @param agentId the agent to run (the agent's global ID)
 */
export function useAgent(client: Midsphere, agentId: string): UseAgentResult {
  const [state, dispatch] = useReducer(agentReducer, initialAgentState);
  const active = useRef<ActiveRun | null>(null);

  const drive = useCallback(async (run: Run, signal: AbortSignal): Promise<void> => {
    try {
      for await (const event of run.stream({ signal })) {
        dispatch({ type: 'event', event, status: run.status });
        const outcome = runOutcomeFromEvent(event);
        if (outcome) dispatch({ type: 'outcome', outcome });
      }
    } catch (err) {
      if (signal.aborted) return; // unmounted or reset — not a real failure
      dispatch({ type: 'error', error: asError(err) });
    }
  }, []);

  const begin = useCallback(
    (run: Run): void => {
      active.current?.controller.abort();
      const controller = new AbortController();
      active.current = { run, controller };
      dispatch({ type: 'start', status: run.status });
      void drive(run, controller.signal);
    },
    [drive],
  );

  const start = useCallback(
    async (input: Omit<StartRunInput, 'agentId'>): Promise<void> => {
      try {
        begin(await client.agent(agentId).run(input));
      } catch (err) {
        dispatch({ type: 'error', error: asError(err) });
      }
    },
    [client, agentId, begin],
  );

  const resume = useCallback(
    async (snapshot: RunSnapshot): Promise<void> => {
      try {
        begin(client.runFromSnapshot(snapshot));
      } catch (err) {
        dispatch({ type: 'error', error: asError(err) });
      }
    },
    [client, begin],
  );

  const cancel = useCallback(async (): Promise<void> => {
    // Don't abort the stream — let the sandbox's run_cancelled event flow through.
    await active.current?.run.cancel();
  }, []);

  const respond = useCallback(
    async (requestId: string, decision: 'approve' | 'deny'): Promise<void> => {
      await active.current?.run.respond(requestId, decision);
    },
    [],
  );

  const reset = useCallback((): void => {
    active.current?.controller.abort();
    active.current = null;
    dispatch({ type: 'reset' });
  }, []);

  // Release the upstream stream connection when the component unmounts.
  useEffect(() => () => active.current?.controller.abort(), []);

  const isActive = state.phase === 'starting' || state.phase === 'streaming';
  return { ...state, isActive, start, resume, attach: begin, cancel, respond, reset };
}

function asError(err: unknown): Error {
  return err instanceof Error ? err : new Error(String(err));
}
