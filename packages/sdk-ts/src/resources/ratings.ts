/**
 * Submit end-user ratings for completed runs (1–5 stars).
 */

import type { GraphQLClient } from '../graphql.js';
import { ensureSuccess } from '../internal/mutation.js';
import type { UserError } from '../types.js';

// ---------------------------------------------------------------------------
// Mutation
// ---------------------------------------------------------------------------

const SUBMIT_RATING = /* GraphQL */ `
  mutation SubmitRating($input: SubmitRatingInput!) {
    submitRating(input: $input) {
      success
      errors {
        code
        field
        message
      }
    }
  }
`;

// ---------------------------------------------------------------------------
// Resource class
// ---------------------------------------------------------------------------

/** Submit end-user ratings for completed runs. */
export class Ratings {
  constructor(private readonly gql: GraphQLClient) {}

  /**
   * Submits a star rating (1–5) for a completed run. The `comment` defaults to
   * an empty string when omitted.
   *
   * @param input.runUid - The UUID of the run to rate (not the relay global ID).
   * @param input.score - Rating from 1 (worst) to 5 (best).
   * @param input.comment - Optional freeform feedback from the end user.
   * @param opts.signal - Optional abort signal to cancel the request.
   */
  async submit(
    input: { runUid: string; score: number; comment?: string },
    opts: { signal?: AbortSignal } = {},
  ): Promise<void> {
    // GraphQL field is `runId` but it carries the run UUID (not a relay ID)
    const mutationInput = {
      runId: input.runUid,
      score: input.score,
      comment: input.comment ?? '',
    };

    const o = opts.signal ? { signal: opts.signal } : undefined;
    const res = await this.gql.request<{ submitRating: { success: boolean; errors: UserError[] } }>(
      SUBMIT_RATING,
      { input: mutationInput },
      o,
    );
    ensureSuccess(res.submitRating);
  }
}
