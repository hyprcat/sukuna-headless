import { MidsphereUserError } from '../errors.js';
import type { UserError } from '../types.js';

/** The common envelope every mutation payload shares. */
export interface MutationPayload {
  success: boolean;
  errors: UserError[];
}

/**
 * Assert a mutation payload succeeded. Returns it narrowed on success; throws a
 * {@link MidsphereUserError} carrying the domain errors otherwise.
 */
export function ensureSuccess<P extends MutationPayload>(payload: P): P {
  if (!payload.success) {
    throw new MidsphereUserError(payload.errors);
  }
  return payload;
}
