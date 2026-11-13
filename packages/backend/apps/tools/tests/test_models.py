from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from apps.core.exceptions import Conflict
from apps.tools.factories import ToolFactory
from apps.tools.models import Tool
from apps.tools.schemas import ToolFormat
from apps.workspaces.factories import WorkspaceFactory, WorkspaceMemberFactory
from apps.workspaces.models.member import WorkspaceRole

pytestmark = pytest.mark.django_db


# -- __str__ -------------------------------------------------------------------


def test_str_returns_name() -> None:
    tool = ToolFactory()
    assert str(tool) == tool.name


# -- activate / deactivate ----------------------------------------------------


def test_activate_sets_active_and_clears_deactivated_at() -> None:
    tool = ToolFactory(inactive=True)
    tool.deactivated_at = tool.updated_at
    tool.save(update_fields=("deactivated_at",))

    tool.activate()
    tool.refresh_from_db()

    assert tool.is_active is True
    assert tool.deactivated_at is None


def test_activate_is_idempotent() -> None:
    tool = ToolFactory()
    tool.activate()
    tool.refresh_from_db()
    assert tool.is_active is True


def test_deactivate_sets_inactive_and_stamps_time() -> None:
    tool = ToolFactory()

    tool.deactivate()
    tool.refresh_from_db()

    assert tool.is_active is False
    assert tool.deactivated_at is not None


def test_deactivate_is_idempotent() -> None:
    tool = ToolFactory(inactive=True)
    tool.deactivate()
    tool.refresh_from_db()
    assert tool.is_active is False


# -- rename --------------------------------------------------------------------


def test_rename_updates_name() -> None:
    tool = ToolFactory()
    tool.rename("new-name")
    tool.refresh_from_db()
    assert tool.name == "new-name"


def test_rename_rejects_blank() -> None:
    tool = ToolFactory()
    with pytest.raises(Conflict, match="blank"):
        tool.rename("  ")


def test_rename_rejects_duplicate_in_workspace() -> None:
    tool_a = ToolFactory(name="alpha")
    ToolFactory(workspace=tool_a.workspace, name="beta")

    with pytest.raises(Conflict, match="already exists"):
        tool_a.rename("beta")


# -- uniqueness ----------------------------------------------------------------


def test_unique_name_per_workspace_constraint() -> None:
    tool = ToolFactory(name="dup")
    with pytest.raises(IntegrityError, match="tools_tool_workspace_name_uniq"):
        ToolFactory(workspace=tool.workspace, name="dup")


def test_same_name_different_workspaces() -> None:
    a = ToolFactory(name="shared-name")
    b = ToolFactory(name="shared-name")
    assert a.workspace_id != b.workspace_id


# -- validate_params -----------------------------------------------------------


def test_validate_params_accepts_valid_payload() -> None:
    tool = ToolFactory.build(
        parameters_schema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    )
    assert tool.validate_params({"query": "hello"}) == []


def test_validate_params_rejects_missing_required_key() -> None:
    tool = ToolFactory.build(
        parameters_schema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    )
    errors = tool.validate_params({})
    assert len(errors) == 1
    assert "query" in errors[0]


def test_validate_params_rejects_wrong_type() -> None:
    tool = ToolFactory.build(
        parameters_schema={
            "type": "object",
            "properties": {"count": {"type": "integer"}},
        },
    )
    errors = tool.validate_params({"count": "not-an-int"})
    assert len(errors) >= 1


def test_validate_params_rejects_additional_properties() -> None:
    tool = ToolFactory.build(
        parameters_schema={
            "type": "object",
            "properties": {"q": {"type": "string"}},
            "additionalProperties": False,
        },
    )
    errors = tool.validate_params({"q": "ok", "extra": 1})
    assert len(errors) >= 1


def test_validate_params_returns_empty_for_empty_schema() -> None:
    tool = ToolFactory.build(parameters_schema={})
    assert tool.validate_params({"anything": True}) == []


# -- can_be_edited_by ---------------------------------------------------------


def test_can_be_edited_by_admin() -> None:
    ws = WorkspaceFactory()
    member = WorkspaceMemberFactory(workspace=ws, role=WorkspaceRole.ADMIN)
    tool = ToolFactory(workspace=ws)
    assert tool.can_be_edited_by(member) is True


def test_can_be_edited_by_editor() -> None:
    ws = WorkspaceFactory()
    member = WorkspaceMemberFactory(workspace=ws, role=WorkspaceRole.EDITOR)
    tool = ToolFactory(workspace=ws)
    assert tool.can_be_edited_by(member) is True


def test_cannot_be_edited_by_viewer() -> None:
    ws = WorkspaceFactory()
    member = WorkspaceMemberFactory(workspace=ws, role=WorkspaceRole.VIEWER)
    tool = ToolFactory(workspace=ws)
    assert tool.can_be_edited_by(member) is False


def test_cannot_be_edited_by_member_of_different_workspace() -> None:
    tool = ToolFactory()
    other_ws = WorkspaceFactory()
    member = WorkspaceMemberFactory(workspace=other_ws, role=WorkspaceRole.ADMIN)
    assert tool.can_be_edited_by(member) is False


# -- clean validation ---------------------------------------------------------


def test_validation_rejects_non_dict_schema() -> None:
    tool = ToolFactory.build(parameters_schema=["not", "a", "dict"])
    with pytest.raises(ValidationError, match="JSON object"):
        tool.full_clean()


def test_validation_rejects_oversized_schema() -> None:
    huge = {"properties": {f"p{i}": {"type": "string"} for i in range(200)}}
    tool = ToolFactory.build(parameters_schema=huge)

    with pytest.raises(ValidationError, match=r"bytes|parameters"):
        tool.full_clean()


def test_validation_rejects_too_many_parameters() -> None:
    fmt = ToolFormat()
    schema = {"properties": {f"k{i}": {} for i in range(fmt.max_parameters_keys + 1)}}
    tool = ToolFactory.build(parameters_schema=schema)

    with pytest.raises(ValidationError, match="parameters"):
        tool.full_clean()


def test_validation_rejects_malformed_json_schema() -> None:
    tool = ToolFactory.build(parameters_schema={"type": "not-a-real-type"})
    with pytest.raises(ValidationError, match="Invalid JSON Schema"):
        tool.full_clean()


def test_validation_rejects_oversized_description() -> None:
    fmt = ToolFormat()
    tool = ToolFactory.build(description="x" * (fmt.max_description_length + 1))
    with pytest.raises(ValidationError, match="characters"):
        tool.full_clean()


def test_validation_rejects_blank_endpoint() -> None:
    tool = ToolFactory.build(execution_endpoint="   ")
    with pytest.raises(ValidationError, match="blank"):
        tool.full_clean()


def test_valid_tool_passes_clean() -> None:
    tool = ToolFactory.build(
        parameters_schema={"properties": {"query": {"type": "string"}}},
    )
    tool.full_clean(exclude=["workspace"])


def test_save_rejects_malformed_json_schema() -> None:
    workspace = WorkspaceFactory()

    with pytest.raises(ValidationError, match="Invalid JSON Schema"):
        Tool.objects.create(
            workspace=workspace,
            name="bad-schema",
            parameters_schema={"type": "not-a-real-type"},
            execution_endpoint="https://tools.example.com/bad-schema",
        )
