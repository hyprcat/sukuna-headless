import type { UserError, UserErrorCode } from './types.js';

/** Base class for every error the SDK throws. `instanceof MidsphereError` catches all of them. */
export class MidsphereError extends Error {
  constructor(message: string, options?: { cause?: unknown }) {
    super(message, options);
    this.name = new.target.name;
  }
}

/** A single formatted GraphQL error from the response `errors` array. */
export interface GraphQLFormattedError {
  message: string;
  path?: ReadonlyArray<string | number>;
  extensions?: Record<string, unknown>;
}

/**
 * Transport- or system-level failure talking to the GraphQL surface: a non-2xx
 * response, a network error, or top-level GraphQL `errors` (auth, rate limit,
 * internal). Domain failures are {@link MidsphereUserError}, not this.
 */
export class MidsphereApiError extends MidsphereError {
  readonly status: number | null;
  readonly graphQLErrors: ReadonlyArray<GraphQLFormattedError>;

  constructor(
    message: string,
    opts: {
      status?: number | null;
      graphQLErrors?: ReadonlyArray<GraphQLFormattedError>;
      cause?: unknown;
    } = {},
  ) {
    super(message, opts.cause !== undefined ? { cause: opts.cause } : undefined);
    this.status = opts.status ?? null;
    this.graphQLErrors = opts.graphQLErrors ?? [];
  }
}

/**
 * A domain failure surfaced through a mutation's `MutationResult.errors`
 * (insufficient credits, concurrency cap, permission denied, …). Carries the
 * full list; `code`/`field`/`message` reflect the first error for convenience.
 */
export class MidsphereUserError extends MidsphereError {
  readonly code: UserErrorCode | (string & {});
  readonly field: string | null;
  readonly errors: ReadonlyArray<UserError>;

  constructor(errors: ReadonlyArray<UserError>) {
    const first = errors[0];
    super(first?.message ?? 'The request was rejected.');
    this.code = first?.code ?? 'INVALID_INPUT';
    this.field = first?.field ?? null;
    this.errors = errors;
  }

  /** True when any error in the list carries `code`. */
  has(code: UserErrorCode): boolean {
    return this.errors.some((e) => e.code === code);
  }
}

/** A failure talking directly to the sandbox over HTTP (stream, cancel, HITL). */
export class MidsphereStreamError extends MidsphereError {
  readonly status: number | null;

  constructor(message: string, opts: { status?: number | null; cause?: unknown } = {}) {
    super(message, opts.cause !== undefined ? { cause: opts.cause } : undefined);
    this.status = opts.status ?? null;
  }
}
