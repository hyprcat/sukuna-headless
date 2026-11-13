from __future__ import annotations

import strawberry
import strawberry_django
from strawberry.types import Info
from strawberry_django.relay import DjangoListConnection

from apps.accounts.permissions import Action
from apps.core.api.ids import parse_int_id
from apps.core.decorators import requires_role, requires_scope, workspace_scoped
from apps.knowledge.api.types import KnowledgeType
from apps.knowledge.models import Knowledge


@strawberry.type
class KnowledgeQuery:
    @strawberry_django.connection(DjangoListConnection[KnowledgeType])
    @workspace_scoped
    @requires_role(Action.KNOWLEDGE_READ)
    @requires_scope("knowledge:read")
    def knowledge_bases(
        self,
        info: Info,
        kind: str | None = None,
        is_active: bool | None = None,
    ) -> list[Knowledge]:
        return Knowledge.for_workspace(info.context.workspace.pk, kind=kind, is_active=is_active)  # type: ignore[return-value]

    @strawberry.field
    @workspace_scoped
    @requires_role(Action.KNOWLEDGE_READ)
    @requires_scope("knowledge:read")
    def knowledge_base(self, info: Info, id: strawberry.ID) -> KnowledgeType | None:
        pk = parse_int_id(id, expected_type="KnowledgeType")
        return Knowledge.get_for_workspace(info.context.workspace.pk, pk)  # type: ignore[return-value]
