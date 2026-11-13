from __future__ import annotations

from types import SimpleNamespace

import pytest
import strawberry
from strawberry import relay
from strawberry_django.optimizer import DjangoOptimizerExtension

from apps.knowledge.api.mutations import KnowledgeMutation
from apps.knowledge.factories import KnowledgeFactory
from apps.knowledge.models import KnowledgeKind
from apps.workspaces.factories import WorkspaceFactory

pytestmark = pytest.mark.django_db


@strawberry.type
class _Q:
    @strawberry.field
    def health(self) -> str:
        return "ok"


@strawberry.type
class _M(KnowledgeMutation):
    pass


_schema = strawberry.Schema(query=_Q, mutation=_M, extensions=[DjangoOptimizerExtension])


def _ctx(workspace: object) -> SimpleNamespace:
    member = SimpleNamespace(workspace_id=workspace.pk, can=lambda _action: True)
    principal = SimpleNamespace(workspace_id=workspace.pk, member=member, scopes=frozenset())
    return SimpleNamespace(workspace=workspace, principal=principal)


CREATE_KNOWLEDGE = """
mutation($input: CreateKnowledgeInput!) {
    createKnowledge(input: $input) {
        success
        errors { code field message }
        knowledge { name }
    }
}
"""


def test_create_knowledge_duplicate_name_returns_mutation_error() -> None:
    ws = WorkspaceFactory()
    KnowledgeFactory(workspace=ws, name="Handbook")

    result = _schema.execute_sync(
        CREATE_KNOWLEDGE,
        variable_values={
            "input": {
                "name": "Handbook",
                "kind": KnowledgeKind.CONNECTED_SOURCE.value,
                "sourceEndpoint": "https://api.example.com/docs",
            }
        },
        context_value=_ctx(ws),
    )

    assert result.errors is None
    data = result.data["createKnowledge"]
    assert data["success"] is False
    assert data["errors"][0]["code"] == "CONFLICT"


UPDATE_KNOWLEDGE = """
mutation($id: ID!, $input: UpdateKnowledgeInput!) {
    updateKnowledge(id: $id, input: $input) {
        success
        errors { code field message }
        knowledge { description }
    }
}
"""


def test_update_knowledge_accepts_relay_global_id() -> None:
    kb = KnowledgeFactory()

    result = _schema.execute_sync(
        UPDATE_KNOWLEDGE,
        variable_values={
            "id": relay.to_base64("KnowledgeType", kb.pk),
            "input": {"description": "Updated"},
        },
        context_value=_ctx(kb.workspace),
    )

    assert result.errors is None
    assert result.data["updateKnowledge"]["success"] is True
    assert result.data["updateKnowledge"]["knowledge"]["description"] == "Updated"
