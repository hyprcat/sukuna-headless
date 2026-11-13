from __future__ import annotations

from datetime import datetime

import strawberry
import strawberry_django
from django.db.models import Count
from strawberry import relay

from apps.core.api.types import MutationResult
from apps.end_users.models import EndUser


@strawberry.type
class ControlProfileType:
    credits: int
    credit_grant_per_period: int
    run_count_limit: int | None
    run_count_period: str
    runs_used_in_period: int
    sandbox_time_seconds: int | None
    concurrency_max: int | None
    model_tier: str
    credit_refresh_schedule: str


@strawberry_django.type(EndUser)
class EndUserType(relay.Node):
    external_user_id: str
    display_name: str
    tier_label: str
    metadata: strawberry.scalars.JSON
    is_active: bool
    created_at: datetime
    updated_at: datetime
    deactivated_at: datetime | None

    run_count: int = strawberry_django.field(annotate=Count("runs"))

    @strawberry_django.field(select_related=["profile"])
    def controls(self) -> ControlProfileType | None:
        from apps.end_users.models.profile import ControlProfile  # noqa: PLC0415

        try:
            p: ControlProfile = self.profile  # type: ignore[attr-defined]
        except ControlProfile.DoesNotExist:
            return None
        return ControlProfileType(
            credits=p.credits,
            credit_grant_per_period=p.credit_grant_per_period,
            run_count_limit=p.run_count_limit,
            run_count_period=p.run_count_period,
            runs_used_in_period=p.runs_used_in_period,
            sandbox_time_seconds=p.sandbox_time_seconds,
            concurrency_max=p.concurrency_max,
            model_tier=p.model_tier,
            credit_refresh_schedule=p.credit_refresh_schedule,
        )


@strawberry.type
class DeactivateEndUserPayload(MutationResult):
    end_user: EndUserType | None = None


@strawberry.type
class ActivateEndUserPayload(MutationResult):
    end_user: EndUserType | None = None


@strawberry.type
class CreateEndUserPayload(MutationResult):
    end_user: EndUserType | None = None


@strawberry.type
class UpdateEndUserPayload(MutationResult):
    end_user: EndUserType | None = None


@strawberry.type
class UpdateEndUserControlsPayload(MutationResult):
    end_user: EndUserType | None = None
