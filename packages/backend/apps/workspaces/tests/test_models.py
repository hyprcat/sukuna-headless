from __future__ import annotations

from datetime import timedelta

import pytest
from django.db import IntegrityError, models, transaction
from django.utils import timezone

from apps.core.exceptions import Conflict
from apps.workspaces.factories import (
    InvitationFactory,
    UserFactory,
    WorkspaceFactory,
    WorkspaceMemberFactory,
)
from apps.workspaces.models.member import WorkspaceMember, WorkspaceRole

pytestmark = pytest.mark.django_db


def test_owner_is_workspace_admin() -> None:
    workspace = WorkspaceFactory()

    assert workspace.members.get(user=workspace.owner).role == WorkspaceRole.ADMIN


def test_remove_last_admin_is_blocked() -> None:
    workspace = WorkspaceFactory()
    owner_member = workspace.members.get(user=workspace.owner)

    with pytest.raises(Conflict):
        workspace.remove_member(owner_member)


def test_direct_delete_last_admin_is_blocked() -> None:
    workspace = WorkspaceFactory()
    owner_member = workspace.members.get(user=workspace.owner)

    with pytest.raises(Conflict):
        owner_member.delete()


def test_stale_member_delete_uses_locked_role() -> None:
    workspace = WorkspaceFactory()
    stale_member = WorkspaceMemberFactory(workspace=workspace, role=WorkspaceRole.VIEWER)
    owner_member = workspace.members.get(user=workspace.owner)
    # Test-only bypass so the stale in-memory object no longer matches the DB row.
    models.QuerySet.update(
        owner_member.__class__.objects.filter(pk=owner_member.pk),
        role=WorkspaceRole.VIEWER,
    )
    models.QuerySet.update(
        stale_member.__class__.objects.filter(pk=stale_member.pk),
        role=WorkspaceRole.ADMIN,
    )

    with pytest.raises(Conflict):
        stale_member.delete()


def test_bulk_delete_last_admin_is_blocked() -> None:
    workspace = WorkspaceFactory()
    owner_member = workspace.members.get(user=workspace.owner)

    with pytest.raises(Conflict):
        workspace.members.filter(pk=owner_member.pk).delete()


def test_remove_admin_when_another_admin_exists() -> None:
    workspace = WorkspaceFactory()
    second_admin = WorkspaceMemberFactory(workspace=workspace, role=WorkspaceRole.ADMIN)
    owner_member = workspace.members.get(user=workspace.owner)
    workspace.transfer_ownership(second_admin.user)

    workspace.remove_member(owner_member)

    assert workspace.members.filter(role=WorkspaceRole.ADMIN).count() == 1


def test_transfer_ownership_makes_new_owner_admin() -> None:
    workspace = WorkspaceFactory()
    new_owner = UserFactory()

    workspace.transfer_ownership(new_owner)

    assert workspace.owner == new_owner
    assert workspace.members.get(user=new_owner).role == WorkspaceRole.ADMIN


def test_transfer_ownership_records_locked_previous_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[str, dict[str, object]]] = []
    workspace = WorkspaceFactory()
    stale_workspace = workspace.__class__.objects.get(pk=workspace.pk)
    intermediate = WorkspaceMemberFactory(workspace=workspace, role=WorkspaceRole.ADMIN).user
    workspace.transfer_ownership(intermediate)
    new_owner = UserFactory()
    monkeypatch.setattr("apps.workspaces.models.workspace.record_event", _capture(events))

    stale_workspace.transfer_ownership(new_owner)

    assert stale_workspace.owner == new_owner
    assert events[0][1]["properties"] == {
        "previous_owner_id": intermediate.pk,
        "new_owner_id": new_owner.pk,
    }


def test_partial_save_does_not_add_unpersisted_owner_as_admin() -> None:
    workspace = WorkspaceFactory()
    new_owner = UserFactory()

    workspace.owner = new_owner
    workspace.name = "Renamed workspace"
    workspace.save(update_fields=("name", "updated_at"))

    workspace.refresh_from_db()
    assert workspace.owner != new_owner
    assert not workspace.members.filter(user=new_owner).exists()


def test_owner_role_cannot_be_demoted() -> None:
    workspace = WorkspaceFactory()
    WorkspaceMemberFactory(workspace=workspace, role=WorkspaceRole.ADMIN)
    owner_member = workspace.members.get(user=workspace.owner)
    owner_member.role = WorkspaceRole.VIEWER

    with pytest.raises(Conflict):
        owner_member.save()

    owner_member.refresh_from_db()
    assert owner_member.role == WorkspaceRole.ADMIN


def test_owner_bulk_update_is_blocked() -> None:
    workspace = WorkspaceFactory()
    new_owner = UserFactory()

    with pytest.raises(Conflict):
        workspace.__class__.objects.filter(pk=workspace.pk).update(owner=new_owner)

    workspace.refresh_from_db()
    assert workspace.owner_id != new_owner.id
    assert not workspace.members.filter(user=new_owner).exists()


def test_member_role_queryset_update_is_blocked() -> None:
    workspace = WorkspaceFactory()
    owner_member = workspace.members.get(user=workspace.owner)

    with pytest.raises(Conflict):
        owner_member.__class__.objects.filter(pk=owner_member.pk).update(role=WorkspaceRole.VIEWER)

    owner_member.refresh_from_db()
    assert owner_member.role == WorkspaceRole.ADMIN


def test_member_role_bulk_update_is_blocked() -> None:
    member = WorkspaceMemberFactory(role=WorkspaceRole.VIEWER)
    member.role = WorkspaceRole.EDITOR

    with pytest.raises(Conflict):
        WorkspaceMember.objects.bulk_update([member], ["role"])

    member.refresh_from_db()
    assert member.role == WorkspaceRole.VIEWER


def test_member_role_change_records_event_and_history(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr("apps.workspaces.models.member.record_event", _capture(events))
    workspace = WorkspaceFactory()
    member = WorkspaceMemberFactory(workspace=workspace, role=WorkspaceRole.VIEWER)
    starting_history_count = member.history.count()

    member.role = WorkspaceRole.EDITOR
    member.save(update_fields=("role", "updated_at"))

    member.refresh_from_db()
    latest_history = member.history.first()
    assert member.role == WorkspaceRole.EDITOR
    assert latest_history is not None
    assert latest_history.role == WorkspaceRole.EDITOR
    assert member.history.count() == starting_history_count + 1
    assert events[0][0] == "workspace_member_role_changed"
    assert events[0][1]["distinct_id"] == str(workspace.pk)
    assert events[0][1]["properties"] == {
        "member_id": member.pk,
        "user_id": member.user_id,
        "previous_role": WorkspaceRole.VIEWER,
        "new_role": WorkspaceRole.EDITOR,
    }


def test_member_workspace_cannot_be_changed() -> None:
    workspace = WorkspaceFactory()
    target_workspace = WorkspaceFactory()
    owner_member = workspace.members.get(user=workspace.owner)
    owner_member.workspace = target_workspace

    with pytest.raises(Conflict):
        owner_member.save()

    owner_member.refresh_from_db()
    assert owner_member.workspace_id == workspace.id


def test_member_user_cannot_be_changed() -> None:
    workspace = WorkspaceFactory()
    WorkspaceMemberFactory(workspace=workspace, role=WorkspaceRole.ADMIN)
    owner_member = workspace.members.get(user=workspace.owner)
    owner_member.user = UserFactory()

    with pytest.raises(Conflict):
        owner_member.save()

    owner_member.refresh_from_db()
    assert owner_member.user_id == workspace.owner_id


def test_invalid_member_role_is_rejected() -> None:
    workspace = WorkspaceFactory()
    user = UserFactory()

    with pytest.raises(Conflict):
        workspace.add_member(user, "billing-admin")


def test_invitation_token_must_match_email() -> None:
    invitation = InvitationFactory(email="first@example.com")
    invitation.email = "second@example.com"
    invitation.save(update_fields=("email", "updated_at"))
    user = UserFactory(email="second@example.com")

    with pytest.raises(Conflict):
        invitation.accept(user)


def test_invitation_accept_does_not_demote_existing_member() -> None:
    workspace = WorkspaceFactory()
    user = UserFactory(email="member@example.com")
    member = workspace.add_member(user, WorkspaceRole.ADMIN)
    invitation = InvitationFactory(workspace=workspace, email=user.email, role=WorkspaceRole.VIEWER)

    accepted_member = invitation.accept(user)

    member.refresh_from_db()
    invitation.refresh_from_db()
    assert accepted_member.pk == member.pk
    assert member.role == WorkspaceRole.ADMIN
    assert invitation.accepted_at is not None


def test_invitation_accept_is_single_use() -> None:
    invitation = InvitationFactory(email="single-use@example.com")
    user = UserFactory(email=invitation.email)

    invitation.accept(user)

    with pytest.raises(Conflict):
        invitation.accept(user)


def test_expired_invitation_cannot_be_accepted() -> None:
    invitation = InvitationFactory(
        email="expired@example.com",
        expires_at=timezone.now() - timedelta(minutes=1),
    )
    user = UserFactory(email=invitation.email)

    with pytest.raises(Conflict):
        invitation.accept(user)


def test_workspace_dodo_customer_id_nullable_and_unique() -> None:
    w1 = WorkspaceFactory()
    assert w1.dodo_customer_id is None

    w1.dodo_customer_id = "cust_abc"
    w1.save(update_fields=("dodo_customer_id",))
    w1.refresh_from_db()
    assert w1.dodo_customer_id == "cust_abc"

    w2 = WorkspaceFactory()
    w2.dodo_customer_id = "cust_abc"
    with pytest.raises(IntegrityError), transaction.atomic():
        w2.save(update_fields=("dodo_customer_id",))


def test_workspace_multiple_null_dodo_customer_ids_allowed() -> None:
    w1 = WorkspaceFactory()
    w2 = WorkspaceFactory()
    assert w1.dodo_customer_id is None
    assert w2.dodo_customer_id is None


def test_invitation_token_supports_max_length_email() -> None:
    email = f"{'a' * 64}@{'b' * 63}.{'c' * 63}.{'d' * 61}"
    invitation = InvitationFactory(email=email)

    assert len(invitation.token) > 255
    assert invitation.email == email


def _capture(
    events: list[tuple[str, dict[str, object]]],
) -> object:
    def fake_record_event(name: str, **kwargs: object) -> None:
        events.append((name, kwargs))

    return fake_record_event
