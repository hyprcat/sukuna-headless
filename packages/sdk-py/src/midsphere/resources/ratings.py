"""Submit end-user ratings for completed runs (1–5 stars)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from midsphere._graphql import GraphQLClient

# ---------------------------------------------------------------------------
# Mutation
# ---------------------------------------------------------------------------

_SUBMIT_RATING = """
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
"""

# ---------------------------------------------------------------------------
# Resource class
# ---------------------------------------------------------------------------


class Ratings:
    """Submit end-user ratings for completed runs."""

    def __init__(self, gql: GraphQLClient) -> None:
        self._gql = gql

    async def submit(
        self,
        *,
        run_uid: str,
        score: int,
        comment: str | None = None,
    ) -> None:
        """Submit a star rating (1–5) for a completed run.

        The ``comment`` defaults to an empty string when omitted.

        Args:
            run_uid: The UUID of the run to rate (not the relay global ID).
            score: Rating from 1 (worst) to 5 (best).
            comment: Optional freeform feedback from the end user.

        Raises:
            MidsphereUserError: If the backend returns domain errors (e.g.
                run not found, score out of range).
        """
        from midsphere._mutation import ensure_success

        # GraphQL field is `runId` but it carries the run UUID (not a relay ID)
        mutation_input = {
            "runId": run_uid,
            "score": score,
            "comment": comment or "",
        }

        res = await self._gql.request(_SUBMIT_RATING, {"input": mutation_input})
        ensure_success(res["submitRating"])
