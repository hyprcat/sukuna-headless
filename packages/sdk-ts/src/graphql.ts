import type { ResolvedConfig } from './config.js';
import { MidsphereApiError, type GraphQLFormattedError } from './errors.js';
import { withTimeout } from './internal/signal.js';

interface GraphQLResponse<T> {
  data?: T | null;
  errors?: GraphQLFormattedError[];
}

/** Per-request options for {@link GraphQLClient.request}. */
export interface RequestOptions {
  signal?: AbortSignal;
}

/**
 * Thin GraphQL-over-HTTP transport. The single place network access to the
 * control plane happens — every resource delegates here. Wrapping the protocol
 * in one file keeps swapping it (batching, persisted queries) a one-file change.
 */
export class GraphQLClient {
  constructor(private readonly config: ResolvedConfig) {}

  async request<T>(
    query: string,
    variables: Record<string, unknown> = {},
    options: RequestOptions = {},
  ): Promise<T> {
    const { signal, clear } = withTimeout(options.signal, this.config.timeoutMs);
    let response: Response;
    try {
      response = await this.config.fetch(this.config.graphqlUrl, {
        method: 'POST',
        headers: {
          'content-type': 'application/json',
          accept: 'application/json',
          authorization: `Bearer ${this.config.apiKey}`,
          ...this.config.headers,
        },
        body: JSON.stringify({ query, variables }),
        ...(signal ? { signal } : {}),
      });
    } catch (cause) {
      throw new MidsphereApiError('Network request to midsphere failed.', { cause });
    } finally {
      clear();
    }

    const body = await this.parseBody<T>(response);
    if (!response.ok) {
      const message =
        body?.errors?.[0]?.message ?? `midsphere request failed (HTTP ${response.status}).`;
      throw new MidsphereApiError(message, {
        status: response.status,
        graphQLErrors: body?.errors ?? [],
      });
    }
    if (body?.errors?.length) {
      throw new MidsphereApiError(body.errors[0]!.message, { graphQLErrors: body.errors });
    }
    if (body?.data == null) {
      throw new MidsphereApiError('midsphere returned an empty response.', {
        status: response.status,
      });
    }
    return body.data;
  }

  private async parseBody<T>(response: Response): Promise<GraphQLResponse<T> | null> {
    const text = await response.text();
    if (!text) return null;
    try {
      return JSON.parse(text) as GraphQLResponse<T>;
    } catch (cause) {
      throw new MidsphereApiError('midsphere returned a non-JSON response.', {
        status: response.status,
        cause,
      });
    }
  }
}

/** Asserts a mutation payload succeeded, throwing its domain errors otherwise. */
export { ensureSuccess } from './internal/mutation.js';
