from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, ClassVar, TypedDict

from django.core.exceptions import ValidationError
from django.db import IntegrityError, models, transaction
from pydantic import BaseModel, ConfigDict

from apps.core.events import record_event
from apps.core.exceptions import Conflict, NotFound
from apps.core.models import TimestampedModel
from apps.runs.schemas.events import RunStatus

if TYPE_CHECKING:
    import uuid

    from apps.runs.models.run import Run


class RatingBounds(BaseModel):
    model_config = ConfigDict(frozen=True)

    min_score: int = 1
    max_score: int = 5


class RatingQuerySet(models.QuerySet["Rating"]):
    def for_workspace(self, workspace_id: int) -> RatingQuerySet:
        return self.filter(run__workspace_id=workspace_id)

    def for_agent(self, agent_id: int) -> RatingQuerySet:
        return self.filter(run__agent_id=agent_id)

    def for_end_user(self, end_user_id: int) -> RatingQuerySet:
        return self.filter(run__end_user_id=end_user_id)

    def with_run(self) -> RatingQuerySet:
        return self.select_related("run")

    def avg_score(self) -> Decimal | None:
        result = self.aggregate(avg=models.Avg("score"))["avg"]
        return Decimal(str(result)) if result is not None else None

    def score_distribution(self) -> list[tuple[int, int]]:
        bounds = RatingBounds()
        rows = dict(
            self.values("score").annotate(count=models.Count("id")).values_list("score", "count")
        )
        return [(s, rows.get(s, 0)) for s in range(bounds.min_score, bounds.max_score + 1)]


class RatingStatsData(TypedDict):
    average: float | None
    total_count: int
    distribution: list[tuple[int, int]]


class Rating(TimestampedModel):
    run = models.OneToOneField(
        "runs.Run",
        on_delete=models.CASCADE,
        related_name="rating",
    )
    score = models.PositiveSmallIntegerField()
    comment = models.TextField(blank=True, default="", max_length=2_000)
    objects = RatingQuerySet.as_manager()

    class Meta:
        db_table = "runs_rating"
        ordering = ("-created_at",)
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=models.Q(score__gte=1, score__lte=5),
                name="runs_rating_score_range",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=("score",)),
        ]

    def __str__(self) -> str:
        return f"Rating {self.score}/5 for run {self.run_id}"

    def clean(self) -> None:
        self._validate_score()
        self._validate_run_terminal()

    def _validate_score(self) -> None:
        bounds = RatingBounds()
        if not (bounds.min_score <= self.score <= bounds.max_score):
            raise ValidationError(
                {"score": f"Score must be between {bounds.min_score} and {bounds.max_score}."}
            )

    def _validate_run_terminal(self) -> None:
        if hasattr(self, "run") and self.run_id:
            status = self.run.status
            if status not in (RunStatus.FINISHED, RunStatus.FAILED, RunStatus.CANCELLED):
                raise ValidationError({"run": "Ratings can only be submitted for completed runs."})

    @classmethod
    def get_for_run_uid(cls, workspace_id: int, run_uid: uuid.UUID) -> Rating | None:
        return (
            cls.objects.with_run().for_workspace(workspace_id).filter(run__run_uid=run_uid).first()
        )

    @classmethod
    def list_for_workspace(
        cls,
        workspace_id: int,
        *,
        agent_id: int | None = None,
    ) -> RatingQuerySet:
        qs = cls.objects.with_run().for_workspace(workspace_id)
        if agent_id is not None:
            qs = qs.for_agent(agent_id)
        return qs

    @classmethod
    def stats_for_workspace(
        cls,
        workspace_id: int,
        *,
        agent_id: int | None = None,
    ) -> RatingStatsData:
        qs = cls.objects.for_workspace(workspace_id)
        if agent_id is not None:
            qs = qs.for_agent(agent_id)
        agg = qs.aggregate(avg=models.Avg("score"), total=models.Count("id"))
        avg_val = agg["avg"]
        return {
            "average": float(avg_val) if avg_val is not None else None,
            "total_count": agg["total"],
            "distribution": qs.score_distribution(),
        }

    @classmethod
    @transaction.atomic
    def submit(cls, run_id: int, score: int, comment: str = "") -> Rating:
        from apps.runs.models.run import Run  # noqa: PLC0415

        run = Run.objects.select_for_update().get(pk=run_id)
        return cls._create_for_run(run, score, comment)

    @classmethod
    @transaction.atomic
    def submit_by_uid(cls, run_uid: uuid.UUID, score: int, comment: str = "") -> Rating:
        from apps.runs.models.run import Run  # noqa: PLC0415

        try:
            run = Run.objects.select_for_update().get(run_uid=run_uid)
        except Run.DoesNotExist as exc:
            raise NotFound(f"Run {run_uid} not found.") from exc
        return cls._create_for_run(run, score, comment)

    @classmethod
    def _create_for_run(cls, run: Run, score: int, comment: str) -> Rating:
        if not run.is_terminal:
            raise Conflict("Ratings can only be submitted for completed runs.")
        try:
            rating = cls.objects.create(run=run, score=score, comment=comment)
        except IntegrityError as exc:
            raise Conflict("This run has already been rated.") from exc
        cls._emit_rated_event(run, score)
        return rating

    @staticmethod
    def _emit_rated_event(run: Run, score: int) -> None:
        record_event(
            "run_rated",
            distinct_id=str(run.workspace_id),
            properties={
                "run_id": str(run.run_uid),
                "score": str(score),
                "end_user_id": str(run.end_user_id),
            },
        )
