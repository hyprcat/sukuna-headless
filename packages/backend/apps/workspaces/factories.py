from __future__ import annotations

from datetime import timedelta

import factory
from django.utils import timezone

from apps.accounts.models import User
from apps.workspaces.models import Invitation, Workspace, WorkspaceMember
from apps.workspaces.models.member import WorkspaceRole


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User
        django_get_or_create = ("email",)

    email = factory.Sequence(lambda n: f"user{n}@example.com")
    full_name = factory.Faker("name")


class WorkspaceFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Workspace

    name = factory.Sequence(lambda n: f"Workspace {n}")
    slug = factory.Sequence(lambda n: f"workspace-{n}")
    owner = factory.SubFactory(UserFactory)
    billing_email = factory.LazyAttribute(lambda obj: obj.owner.email)


class WorkspaceMemberFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = WorkspaceMember

    workspace = factory.SubFactory(WorkspaceFactory)
    user = factory.SubFactory(UserFactory)
    role = WorkspaceRole.VIEWER
    joined_at = factory.LazyFunction(timezone.now)


class InvitationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Invitation

    workspace = factory.SubFactory(WorkspaceFactory)
    email = factory.Sequence(lambda n: f"invitee{n}@example.com")
    role = WorkspaceRole.VIEWER
    expires_at = factory.LazyFunction(lambda: timezone.now() + timedelta(days=7))

    @factory.lazy_attribute
    def token(self) -> str:
        return Invitation.build_token(workspace_id=self.workspace.id, email=self.email)
