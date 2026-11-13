from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from apps.core.exceptions import Conflict
from apps.knowledge.factories import KnowledgeFactory
from apps.knowledge.models.knowledge import KnowledgeKind
from apps.knowledge.schemas import KnowledgeFormat
from apps.workspaces.factories import WorkspaceFactory, WorkspaceMemberFactory
from apps.workspaces.models.member import WorkspaceRole

pytestmark = pytest.mark.django_db


# -- __str__ -------------------------------------------------------------------


def test_str_returns_name() -> None:
    kb = KnowledgeFactory()
    assert str(kb) == kb.name


# -- activate / deactivate ----------------------------------------------------


def test_activate_sets_active_and_clears_deactivated_at() -> None:
    kb = KnowledgeFactory(inactive=True)
    kb.deactivated_at = kb.updated_at
    kb.save(update_fields=("deactivated_at",))

    kb.activate()
    kb.refresh_from_db()

    assert kb.is_active is True
    assert kb.deactivated_at is None


def test_activate_is_idempotent() -> None:
    kb = KnowledgeFactory()
    kb.activate()
    kb.refresh_from_db()
    assert kb.is_active is True


def test_deactivate_sets_inactive_and_stamps_time() -> None:
    kb = KnowledgeFactory()

    kb.deactivate()
    kb.refresh_from_db()

    assert kb.is_active is False
    assert kb.deactivated_at is not None


def test_deactivate_is_idempotent() -> None:
    kb = KnowledgeFactory(inactive=True)
    kb.deactivate()
    kb.refresh_from_db()
    assert kb.is_active is False


# -- reindex -------------------------------------------------------------------


def test_reindex_sets_last_indexed_at() -> None:
    kb = KnowledgeFactory()
    assert kb.last_indexed_at is None

    kb.reindex()
    kb.refresh_from_db()

    assert kb.last_indexed_at is not None


def test_reindex_updates_timestamp_on_repeat() -> None:
    kb = KnowledgeFactory()
    kb.reindex()
    kb.refresh_from_db()
    first = kb.last_indexed_at

    kb.reindex()
    kb.refresh_from_db()

    assert kb.last_indexed_at >= first


# -- rename --------------------------------------------------------------------


def test_rename_updates_name() -> None:
    kb = KnowledgeFactory()
    kb.rename("new-name")
    kb.refresh_from_db()
    assert kb.name == "new-name"


def test_rename_rejects_blank() -> None:
    kb = KnowledgeFactory()
    with pytest.raises(Conflict, match="blank"):
        kb.rename("  ")


def test_rename_rejects_duplicate_in_workspace() -> None:
    kb_a = KnowledgeFactory(name="alpha")
    KnowledgeFactory(workspace=kb_a.workspace, name="beta")

    with pytest.raises(Conflict, match="already exists"):
        kb_a.rename("beta")


# -- uniqueness ----------------------------------------------------------------


def test_unique_name_per_workspace_constraint() -> None:
    kb = KnowledgeFactory(name="dup")
    with pytest.raises(IntegrityError, match="knowledge_workspace_name_uniq"):
        KnowledgeFactory(workspace=kb.workspace, name="dup")


def test_same_name_different_workspaces() -> None:
    a = KnowledgeFactory(name="shared-name")
    b = KnowledgeFactory(name="shared-name")
    assert a.workspace_id != b.workspace_id


# -- can_be_edited_by ---------------------------------------------------------


def test_can_be_edited_by_admin() -> None:
    ws = WorkspaceFactory()
    member = WorkspaceMemberFactory(workspace=ws, role=WorkspaceRole.ADMIN)
    kb = KnowledgeFactory(workspace=ws)
    assert kb.can_be_edited_by(member) is True


def test_can_be_edited_by_editor() -> None:
    ws = WorkspaceFactory()
    member = WorkspaceMemberFactory(workspace=ws, role=WorkspaceRole.EDITOR)
    kb = KnowledgeFactory(workspace=ws)
    assert kb.can_be_edited_by(member) is True


def test_cannot_be_edited_by_viewer() -> None:
    ws = WorkspaceFactory()
    member = WorkspaceMemberFactory(workspace=ws, role=WorkspaceRole.VIEWER)
    kb = KnowledgeFactory(workspace=ws)
    assert kb.can_be_edited_by(member) is False


def test_cannot_be_edited_by_member_of_different_workspace() -> None:
    kb = KnowledgeFactory()
    other_ws = WorkspaceFactory()
    member = WorkspaceMemberFactory(workspace=other_ws, role=WorkspaceRole.ADMIN)
    assert kb.can_be_edited_by(member) is False


# -- clean validation ---------------------------------------------------------


def test_document_without_file_fails() -> None:
    kb = KnowledgeFactory.build(kind=KnowledgeKind.DOCUMENT, file="")
    with pytest.raises(ValidationError, match="file"):
        kb.full_clean()


def test_connected_source_without_endpoint_fails() -> None:
    kb = KnowledgeFactory.build(kind=KnowledgeKind.CONNECTED_SOURCE, file="", source_endpoint="")
    with pytest.raises(ValidationError, match="source_endpoint"):
        kb.full_clean()


def test_oversized_description_fails() -> None:
    fmt = KnowledgeFormat()
    kb = KnowledgeFactory.build(description="x" * (fmt.max_description_length + 1))
    with pytest.raises(ValidationError, match="characters"):
        kb.full_clean()


def test_missing_content_type_with_file_fails() -> None:
    kb = KnowledgeFactory.build(content_type="")
    with pytest.raises(ValidationError, match="required"):
        kb.full_clean()


def test_disallowed_content_type_fails() -> None:
    kb = KnowledgeFactory.build(content_type="application/x-executable")
    with pytest.raises(ValidationError, match="not allowed"):
        kb.full_clean()


def test_direct_create_rejects_disallowed_content_type() -> None:
    with pytest.raises(ValidationError, match="not allowed"):
        KnowledgeFactory(content_type="application/x-executable")


def test_oversized_file_fails() -> None:
    fmt = KnowledgeFormat()
    kb = KnowledgeFactory.build(file_size_bytes=fmt.max_file_size_bytes + 1)
    with pytest.raises(ValidationError, match="bytes"):
        kb.full_clean()


def test_non_dict_source_config_fails() -> None:
    kb = KnowledgeFactory.build(source_config=["not", "a", "dict"])
    with pytest.raises(ValidationError, match="JSON object"):
        kb.full_clean()


def test_direct_save_rejects_non_dict_source_config() -> None:
    kb = KnowledgeFactory.build(source_config=["not", "a", "dict"])
    with pytest.raises(ValidationError, match="JSON object"):
        kb.save()


def test_oversized_source_config_fails() -> None:
    huge = {f"k{i}": "v" * 100 for i in range(500)}
    kb = KnowledgeFactory.build(source_config=huge)
    with pytest.raises(ValidationError, match="bytes"):
        kb.full_clean()


def test_valid_document_passes_clean() -> None:
    kb = KnowledgeFactory.build()
    kb.full_clean(exclude=["workspace"])


def test_valid_connected_source_passes_clean() -> None:
    kb = KnowledgeFactory.build(
        kind=KnowledgeKind.CONNECTED_SOURCE,
        file="",
        source_endpoint="https://api.example.com/data",
    )
    kb.full_clean(exclude=["workspace"])
