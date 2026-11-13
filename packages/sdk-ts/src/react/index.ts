/**
 * `@midsphere/sdk/react` — React bindings for the midsphere SDK.
 *
 * Import surface kept separate from the core so non-React consumers never pull
 * in React. Requires `react` as a peer dependency.
 */

export { useAgent } from './use-agent.js';
export type { UseAgentResult } from './use-agent.js';
export {
  agentReducer,
  initialAgentState,
  type AgentState,
  type AgentAction,
  type AgentPhase,
} from './state.js';
