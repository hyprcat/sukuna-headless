from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
import strawberry

from apps.core.exceptions import Conflict, NotFound
from apps.runs.api.mutations import RatingMutation
from apps.runs.api.queries import RatingQuery
from apps.runs.factories import RatingFactory, RunFactory
from apps.runs.models import Rating

pytestmark = pytest.mark.django_db


# -- GraphQL schema setup --


@strawberry.type
class _Q(RatingQuery):
    pass


@strawberry.type
class _M(RatingMutation):
    pass


_schema = strawberry.Schema(query=_Q, mutation=_M)


def _api_ctx(*, workspace_pk: int, scopes: frozenset[str] | None = None) -> SimpleNamespace:
    ws = SimpleNamespace(pk=workspace_pk)
    principal = SimpleNamespace(
        workspace_id=workspace_pk,
        member=None,
        scopes=scopes or frozenset({"runs:read", "runs:write"}),
    )
    return SimpleNamespace(workspace=ws, principal=principal)


def _session_ctx(*, workspace_pk: int, allowed: str) -> SimpleNamespace:
    ws = SimpleNamespace(pk=workspace_pk)
    member = SimpleNamespace(workspace_id=workspace_pk, can=lambda a: a == allowed)
    principal = SimpleNamespace(workspace_id=workspace_pk, member=member, scopes=frozenset())
    return SimpleNamespace(workspace=ws, principal=principal)


SUBMIT_MUTATION = """
mutation Submit($input: SubmitRatingInput!) {
    submitRating(input: $input) {
        success
        errors { code message field }
        rating { score comment }
    }
}
"""

RATING_FOR_RUN_QUERY = """
query RatingForRun($runUid: UUID!) {
    ratingForRun(runUid: $runUid) { score comment }
}
"""

STATS_QUERY = """
query Stats {
    ratingStats { average totalCount distribution { score count } }
}
"""


# -- Mutation tests --


def test_submit_rating_via_api_key() -> None:
    run = RunFactory(finished=True)
    ctx = _api_ctx(workspace_pk=run.workspace_id)
    result = _schema.execute_sync(
        SUBMIT_MUTATION,
        variable_values={"input": {"runId": str(run.run_uid), "score": 5, "comment": "Great"}},
        context_value=ctx,
    )
    assert result.errors is None
    data = result.data["submitRating"]
    assert data["success"] is True
    assert data["rating"]["score"] == 5
    assert data["rating"]["comment"] == "Great"


def test_submit_rating_conflict_duplicate() -> None:
    run = RunFactory(finished=True)
    ctx = _api_ctx(workspace_pk=run.workspace_id)
    _schema.execute_sync(
        SUBMIT_MUTATION,
        variable_values={"input": {"runId": str(run.run_uid), "score": 5}},
        context_value=ctx,
    )
    result = _schema.execute_sync(
        SUBMIT_MUTATION,
        variable_values={"input": {"runId": str(run.run_uid), "score": 3}},
        context_value=ctx,
    )
    assert result.errors is None
    data = result.data["submitRating"]
    assert data["success"] is False
    assert data["errors"][0]["code"] == "CONFLICT"


# -- Query tests --


def test_rating_for_run_returns_rating() -> None:
    rating = RatingFactory(score=4, comment="Good")
    run = rating.run
    ctx = _session_ctx(workspace_pk=run.workspace_id, allowed="ratings:read")
    result = _schema.execute_sync(
        RATING_FOR_RUN_QUERY,
        variable_values={"runUid": str(run.run_uid)},
        context_value=ctx,
    )
    assert result.errors is None
    data = result.data["ratingForRun"]
    assert data["score"] == 4
    assert data["comment"] == "Good"


def test_rating_for_run_returns_null_when_unrated() -> None:
    run = RunFactory(finished=True)
    ctx = _session_ctx(workspace_pk=run.workspace_id, allowed="ratings:read")
    result = _schema.execute_sync(
        RATING_FOR_RUN_QUERY,
        variable_values={"runUid": str(run.run_uid)},
        context_value=ctx,
    )
    assert result.errors is None
    assert result.data["ratingForRun"] is None


def test_rating_stats_returns_aggregates() -> None:
    ws = RunFactory(finished=True).workspace
    for score in (3, 4, 5, 5):
        RatingFactory(run=RunFactory(finished=True, workspace=ws), score=score)
    ctx = _session_ctx(workspace_pk=ws.pk, allowed="ratings:read")
    result = _schema.execute_sync(STATS_QUERY, context_value=ctx)
    assert result.errors is None
    stats = result.data["ratingStats"]
    assert stats["totalCount"] == 4
    assert stats["average"] == pytest.approx(4.25)
    assert len(stats["distribution"]) == 5
    scores_in_dist = {b["score"]: b["count"] for b in stats["distribution"]}
    assert scores_in_dist == {1: 0, 2: 0, 3: 1, 4: 1, 5: 2}


def test_rating_stats_empty_workspace() -> None:
    ws = RunFactory(finished=True).workspace
    ctx = _session_ctx(workspace_pk=ws.pk, allowed="ratings:read")
    result = _schema.execute_sync(STATS_QUERY, context_value=ctx)
    assert result.errors is None
    stats = result.data["ratingStats"]
    assert stats["totalCount"] == 0
    assert stats["average"] is None
    assert len(stats["distribution"]) == 5
    assert all(b["count"] == 0 for b in stats["distribution"])


# -- QuerySet / model tests --


def test_for_workspace_filters_by_run_workspace() -> None:
    r1 = RatingFactory()
    r2 = RatingFactory()
    qs = Rating.objects.for_workspace(r1.run.workspace_id)
    assert list(qs.values_list("pk", flat=True)) == [r1.pk]
    assert r2.pk not in qs.values_list("pk", flat=True)


def test_for_agent_filters_by_run_agent() -> None:
    r1 = RatingFactory()
    RatingFactory()
    qs = Rating.objects.for_agent(r1.run.agent_id)
    assert qs.count() == 1
    assert qs.first().pk == r1.pk


def test_for_end_user_filters_by_run_end_user() -> None:
    r1 = RatingFactory()
    RatingFactory()
    qs = Rating.objects.for_end_user(r1.run.end_user_id)
    assert qs.count() == 1


def test_with_run_loads_related_run() -> None:
    RatingFactory()
    rating = Rating.objects.with_run().first()
    assert rating is not None
    assert rating.run is not None


def test_avg_score_returns_decimal() -> None:
    ws = RunFactory(finished=True).workspace
    agent = RunFactory(finished=True, workspace=ws).agent
    RatingFactory(run=RunFactory(finished=True, workspace=ws, agent=agent), score=3)
    RatingFactory(run=RunFactory(finished=True, workspace=ws, agent=agent), score=5)
    avg = Rating.objects.for_workspace(ws.pk).avg_score()
    assert avg == Decimal("4")


def test_avg_score_returns_none_when_empty() -> None:
    assert Rating.objects.avg_score() is None


def test_score_distribution_returns_all_five_buckets() -> None:
    ws = RunFactory(finished=True).workspace
    for score in (3, 3, 5, 5, 5):
        RatingFactory(run=RunFactory(finished=True, workspace=ws), score=score)
    dist = Rating.objects.for_workspace(ws.pk).score_distribution()
    assert len(dist) == 5
    assert dict(dist) == {1: 0, 2: 0, 3: 2, 4: 0, 5: 3}


def test_score_distribution_empty_returns_zero_buckets() -> None:
    dist = Rating.objects.score_distribution()
    assert len(dist) == 5
    assert all(count == 0 for _, count in dist)


def test_submit_by_uid_creates_rating() -> None:
    run = RunFactory(finished=True)
    rating = Rating.submit_by_uid(run.run_uid, score=4, comment="Nice")
    assert rating.score == 4
    assert rating.comment == "Nice"
    assert rating.run_id == run.pk


def test_submit_by_uid_raises_not_found_for_missing_run() -> None:
    with pytest.raises(NotFound, match="not found"):
        Rating.submit_by_uid(uuid.uuid4(), score=4)


def test_submit_by_uid_raises_conflict_for_active_run() -> None:
    run = RunFactory(running=True)
    with pytest.raises(Conflict, match="completed runs"):
        Rating.submit_by_uid(run.run_uid, score=4)


def test_submit_by_uid_raises_conflict_for_duplicate() -> None:
    run = RunFactory(finished=True)
    Rating.submit_by_uid(run.run_uid, score=4)
    with pytest.raises(Conflict, match="already been rated"):
        Rating.submit_by_uid(run.run_uid, score=3)
