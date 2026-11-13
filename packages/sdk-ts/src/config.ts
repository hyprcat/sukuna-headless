/** A `fetch` implementation. Defaults to the global `fetch` (Node 18+, browsers, edge runtimes). */
export type FetchLike = typeof fetch;

/** Options for constructing a {@link Midsphere} client. */
export interface MidsphereConfig {
  /** Workspace API key, e.g. `ms_prod_…`. Required. */
  apiKey: string;
  /**
   * Backend origin the GraphQL surface is served from. GraphQL is reached at
   * `${baseUrl}/graphql/`. Defaults to `https://api.midsphere.com`; point at
   * `http://localhost:8000` for local development.
   */
  baseUrl?: string;
  /** Custom `fetch` (e.g. for tests, proxies, or non-standard runtimes). */
  fetch?: FetchLike;
  /** Extra headers sent with every GraphQL request. */
  headers?: Record<string, string>;
  /** Per-request timeout in milliseconds. Defaults to 30000. Set to 0 to disable. */
  timeoutMs?: number;
}

/** Fully-resolved config with defaults applied. Internal. */
export interface ResolvedConfig {
  apiKey: string;
  graphqlUrl: string;
  fetch: FetchLike;
  headers: Record<string, string>;
  timeoutMs: number;
}

const DEFAULT_BASE_URL = 'https://api.midsphere.com';
const DEFAULT_TIMEOUT_MS = 30_000;

export function resolveConfig(config: MidsphereConfig): ResolvedConfig {
  if (!config.apiKey) {
    throw new Error('midsphere: `apiKey` is required.');
  }
  const fetchImpl = config.fetch ?? globalThis.fetch;
  if (typeof fetchImpl !== 'function') {
    throw new Error(
      'midsphere: no global `fetch` found. Pass `fetch` in the client config (Node <18 or a custom runtime).',
    );
  }
  const baseUrl = (config.baseUrl ?? DEFAULT_BASE_URL).replace(/\/+$/, '');
  return {
    apiKey: config.apiKey,
    graphqlUrl: `${baseUrl}/graphql/`,
    fetch: fetchImpl,
    headers: config.headers ?? {},
    timeoutMs: config.timeoutMs ?? DEFAULT_TIMEOUT_MS,
  };
}
