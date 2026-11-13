from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from apps.agents.factories import AgentFactory
from apps.agents.models import Agent
from apps.agents.models.agent import ModelTier
from apps.agents.schemas import AgentFormat
from apps.core.exceptions import Conflict
from apps.policies.factories import PolicyFactory
from apps.workspaces.factories import WorkspaceFactory, WorkspaceMemberFactory
from apps.workspaces.models.member import WorkspaceRole

pytestmark = pytest.mark.django_db


# -- __str__ -------------------------------------------------------------------


def test_str_returns_name() -> None:
    agent = AgentFactory()
    assert str(agent) == agent.name


# -- activate / deactivate ----------------------------------------------------


def test_activate_sets_active_and_clears_deactivated_at() -> None:
    agent = AgentFactory(inactive=True)
    agent.deactivated_at = agent.updated_at
    agent.save(update_fields=("deactivated_at",))

    agent.activate()
    agent.refresh_from_db()

    assert agent.is_active is True
    assert agent.deactivated_at is None


def test_activate_is_idempotent() -> None:
    agent = AgentFactory()
    agent.activate()
    agent.refresh_from_db()
    assert agent.is_active is True


def test_deactivate_sets_inactive_and_stamps_time() -> None:
    agent = AgentFactory()

    agent.deactivate()
    agent.refresh_from_db()

    assert agent.is_active is False
    assert agent.deactivated_at is not None


def test_deactivate_is_idempotent() -> None:
    agent = AgentFactory(inactive=True)
    agent.deactivate()
    agent.refresh_from_db()
    assert agent.is_active is False


# -- rename --------------------------------------------------------------------


def test_rename_updates_name() -> None:
    agent = AgentFactory()
    agent.rename("new-name")
    agent.refresh_from_db()
    assert agent.name == "new-name"


def test_rename_rejects_blank() -> None:
    agent = AgentFactory()
    with pytest.raises(Conflict, match="blank"):
        agent.rename("  ")


def test_rename_rejects_duplicate_in_workspace() -> None:
    agent_a = AgentFactory(name="alpha")
    AgentFactory(workspace=agent_a.workspace, name="beta")

    with pytest.raises(Conflict, match="already exists"):
        agent_a.rename("beta")


# -- uniqueness ----------------------------------------------------------------


def test_unique_name_per_workspace_constraint() -> None:
    agent = AgentFactory(name="dup")
    with pytest.raises(IntegrityError, match="agents_agent_workspace_name_uniq"):
        AgentFactory(workspace=agent.workspace, name="dup")


def test_same_name_different_workspaces() -> None:
    a = AgentFactory(name="shared-name")
    b = AgentFactory(name="shared-name")
    assert a.workspace_id != b.workspace_id


# -- can_be_edited_by / can_be_deleted_by -------------------------------------


def test_can_be_edited_by_admin() -> None:
    ws = WorkspaceFactory()
    member = WorkspaceMemberFactory(workspace=ws, role=WorkspaceRole.ADMIN)
    agent = AgentFactory(workspace=ws)
    assert agent.can_be_edited_by(member) is True


def test_can_be_edited_by_editor() -> None:
    ws = WorkspaceFactory()
    member = WorkspaceMemberFactory(workspace=ws, role=WorkspaceRole.EDITOR)
    agent = AgentFactory(workspace=ws)
    assert agent.can_be_edited_by(member) is True


def test_cannot_be_edited_by_viewer() -> None:
    ws = WorkspaceFactory()
    member = WorkspaceMemberFactory(workspace=ws, role=WorkspaceRole.VIEWER)
    agent = AgentFactory(workspace=ws)
    assert agent.can_be_edited_by(member) is False


def test_cannot_be_edited_by_member_of_different_workspace() -> None:
    agent = AgentFactory()
    other_ws = WorkspaceFactory()
    member = WorkspaceMemberFactory(workspace=other_ws, role=WorkspaceRole.ADMIN)
    assert agent.can_be_edited_by(member) is False


def test_can_be_deleted_by_admin() -> None:
    ws = WorkspaceFactory()
    member = WorkspaceMemberFactory(workspace=ws, role=WorkspaceRole.ADMIN)
    agent = AgentFactory(workspace=ws)
    assert agent.can_be_deleted_by(member) is True


def test_cannot_be_deleted_by_editor() -> None:
    ws = WorkspaceFactory()
    member = WorkspaceMemberFactory(workspace=ws, role=WorkspaceRole.EDITOR)
    agent = AgentFactory(workspace=ws)
    assert agent.can_be_deleted_by(member) is False


# -- clean validation ---------------------------------------------------------


def test_validation_rejects_oversized_description() -> None:
    fmt = AgentFormat()
    agent = AgentFactory.build(description="x" * (fmt.max_description_length + 1))
    with pytest.raises(ValidationError, match="characters"):
        agent.full_clean()


def test_validation_rejects_oversized_system_prompt() -> None:
    fmt = AgentFormat()
    agent = AgentFactory.build(system_prompt="x" * (fmt.max_system_prompt_length + 1))
    with pytest.raises(ValidationError, match="characters"):
        agent.full_clean()


def test_validation_rejects_policy_from_different_workspace() -> None:
    agent_ws = WorkspaceFactory()
    other_ws = WorkspaceFactory()
    policy = PolicyFactory(workspace=other_ws)
    agent = AgentFactory.build(workspace=agent_ws, policy_override=policy)

    with pytest.raises(ValidationError, match="same workspace"):
        agent.full_clean()


def test_save_runs_model_validation_for_oversized_description() -> None:
    fmt = AgentFormat()
    agent = Agent(
        workspace=WorkspaceFactory(),
        name="invalid-agent",
        description="x" * (fmt.max_description_length + 1),
    )

    with pytest.raises(ValidationError, match="characters"):
        agent.save()


def test_save_runs_model_validation_for_policy_workspace() -> None:
    agent_ws = WorkspaceFactory()
    other_ws = WorkspaceFactory()
    agent = Agent(
        workspace=agent_ws,
        name="invalid-agent",
        policy_override=PolicyFactory(workspace=other_ws),
    )

    with pytest.raises(ValidationError, match="same workspace"):
        agent.save()


def test_valid_agent_passes_clean() -> None:
    agent = AgentFactory.build()
    agent.full_clean(exclude=["workspace"])


def test_model_tier_choices() -> None:
    assert set(ModelTier.values) == {"free", "pro", "enterprise"}
