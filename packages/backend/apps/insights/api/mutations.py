from __future__ import annotations

import strawberry
from strawberry.types import Info

from apps.accounts.permissions import Action
from apps.core.api.ids import parse_int_id
from apps.core.api.mappers import catch_domain_errors
from apps.core.decorators import requires_role, workspace_scoped
from apps.insights.api.types import DismissInsightPayload, PinInsightPayload, UnpinInsightPayload
from apps.insights.models import Insight


def _get_insight(workspace_pk: int, insight_id: str) -> Insight:
    pk = parse_int_id(insight_id, expected_type="InsightType")
    return Insight.get_for_workspace_or_raise(workspace_pk, pk)


@strawberry.type
class InsightMutation:
    @strawberry.mutation
    @catch_domain_errors(DismissInsightPayload)
    @workspace_scoped
    @requires_role(Action.INSIGHTS_DISMISS)
    def dismiss_insight(self, info: Info, id: strawberry.ID) -> DismissInsightPayload:
        insight = _get_insight(info.context.workspace.pk, id)
        insight.dismiss(user_id=info.context.principal.member.user_id)
        return DismissInsightPayload(success=True, errors=[], insight=insight)  # type: ignore[arg-type]

    @strawberry.mutation
    @catch_domain_errors(PinInsightPayload)
    @workspace_scoped
    @requires_role(Action.INSIGHTS_PIN)
    def pin_insight(self, info: Info, id: strawberry.ID) -> PinInsightPayload:
        insight = _get_insight(info.context.workspace.pk, id)
        insight.pin()
        return PinInsightPayload(success=True, errors=[], insight=insight)  # type: ignore[arg-type]

    @strawberry.mutation
    @catch_domain_errors(UnpinInsightPayload)
    @workspace_scoped
    @requires_role(Action.INSIGHTS_PIN)
    def unpin_insight(self, info: Info, id: strawberry.ID) -> UnpinInsightPayload:
        insight = _get_insight(info.context.workspace.pk, id)
        insight.unpin()
        return UnpinInsightPayload(success=True, errors=[], insight=insight)  # type: ignore[arg-type]
