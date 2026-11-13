from __future__ import annotations

from typing import Any, cast

import strawberry
from strawberry.types import Info

from apps.accounts.permissions import Action
from apps.core.api.ids import parse_int_id
from apps.core.api.mappers import catch_domain_errors
from apps.core.decorators import requires_role, requires_scope, workspace_scoped
from apps.knowledge.api.types import (
    ActivateKnowledgePayload,
    CreateKnowledgePayload,
    DeactivateKnowledgePayload,
    ReindexKnowledgePayload,
    UpdateKnowledgePayload,
)
from apps.knowledge.models import Knowledge


def _get_knowledge(workspace_pk: int, knowledge_id: str) -> Knowledge:
    pk = parse_int_id(knowledge_id, expected_type="KnowledgeType")
    return Knowledge.get_for_workspace_or_raise(workspace_pk, pk)


@strawberry.input
class CreateKnowledgeInput:
    name: str
    kind: str  # "document", "dataset", "connected_source"
    description: str = ""
    source_endpoint: str = ""
    source_config: strawberry.scalars.JSON | None = strawberry.UNSET


@strawberry.input
class UpdateKnowledgeInput:
    name: str | None = strawberry.UNSET
    description: str | None = strawberry.UNSET
    source_endpoint: str | None = strawberry.UNSET
    source_config: strawberry.scalars.JSON | None = strawberry.UNSET


@strawberry.type
class KnowledgeMutation:
    @strawberry.mutation
    @workspace_scoped
    @requires_role(Action.KNOWLEDGE_WRITE)
    @requires_scope("knowledge:write")
    @catch_domain_errors(CreateKnowledgePayload)
    def create_knowledge(
        self,
        info: Info,
        input: CreateKnowledgeInput,
    ) -> CreateKnowledgePayload:
        config: dict[str, Any] = {}
        if input.source_config is not strawberry.UNSET and input.source_config is not None:
            config = cast("dict[str, Any]", input.source_config)
        kb = Knowledge.create_for_workspace(
            info.context.workspace.pk,
            name=input.name,
            kind=input.kind,
            description=input.description,
            source_endpoint=input.source_endpoint,
            source_config=config,
        )
        return CreateKnowledgePayload(
            success=True,
            errors=[],
            knowledge=kb,  # type: ignore[arg-type]
        )

    @strawberry.mutation
    @workspace_scoped
    @requires_role(Action.KNOWLEDGE_WRITE)
    @requires_scope("knowledge:write")
    @catch_domain_errors(UpdateKnowledgePayload)
    def update_knowledge(
        self,
        info: Info,
        id: strawberry.ID,
        input: UpdateKnowledgeInput,
    ) -> UpdateKnowledgePayload:
        kb = _get_knowledge(info.context.workspace.pk, id)
        fields: dict[str, Any] = {}
        if input.name is not strawberry.UNSET and input.name is not None:
            fields["name"] = input.name
        if input.description is not strawberry.UNSET:
            fields["description"] = input.description or ""
        if input.source_endpoint is not strawberry.UNSET:
            fields["source_endpoint"] = input.source_endpoint or ""
        if input.source_config is not strawberry.UNSET:
            fields["source_config"] = input.source_config or {}
        if fields:
            kb.update(**fields)
        return UpdateKnowledgePayload(
            success=True,
            errors=[],
            knowledge=kb,  # type: ignore[arg-type]
        )

    @strawberry.mutation
    @workspace_scoped
    @requires_role(Action.KNOWLEDGE_DELETE)
    @requires_scope("knowledge:write")
    @catch_domain_errors(DeactivateKnowledgePayload)
    def deactivate_knowledge(self, info: Info, id: strawberry.ID) -> DeactivateKnowledgePayload:
        kb = _get_knowledge(info.context.workspace.pk, id)
        kb.deactivate()
        return DeactivateKnowledgePayload(
            success=True,
            errors=[],
            knowledge=kb,  # type: ignore[arg-type]
        )

    @strawberry.mutation
    @workspace_scoped
    @requires_role(Action.KNOWLEDGE_WRITE)
    @requires_scope("knowledge:write")
    @catch_domain_errors(ActivateKnowledgePayload)
    def activate_knowledge(self, info: Info, id: strawberry.ID) -> ActivateKnowledgePayload:
        kb = _get_knowledge(info.context.workspace.pk, id)
        kb.activate()
        return ActivateKnowledgePayload(
            success=True,
            errors=[],
            knowledge=kb,  # type: ignore[arg-type]
        )

    @strawberry.mutation
    @workspace_scoped
    @requires_role(Action.KNOWLEDGE_WRITE)
    @requires_scope("knowledge:write")
    @catch_domain_errors(ReindexKnowledgePayload)
    def reindex_knowledge(self, info: Info, id: strawberry.ID) -> ReindexKnowledgePayload:
        kb = _get_knowledge(info.context.workspace.pk, id)
        kb.reindex()
        return ReindexKnowledgePayload(
            success=True,
            errors=[],
            knowledge=kb,  # type: ignore[arg-type]
        )
