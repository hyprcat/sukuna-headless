from __future__ import annotations

from datetime import datetime
from typing import cast

import strawberry
import strawberry_django
from django.db.models import Count
from strawberry import relay
from strawberry_django.relay import DjangoListConnection

from apps.agents.api.types import AgentType
from apps.api_keys.api.types import APIKeyType
from apps.api_keys.models import APIKey
from apps.billing.api.types import CreditWalletType
from apps.billing.models.wallet import CreditWallet
from apps.core.api.types import MutationResult
from apps.end_users.api.types import EndUserType
from apps.insights.api.types import InsightType
from apps.knowledge.api.types import KnowledgeType
from apps.policies.api.types import PolicyType
from apps.runs.api.types import ConversationType, RunType
from apps.runs.models import Conversation, Run
from apps.schedules.api.types import ScheduleType
from apps.tools.api.types import ToolType
from apps.workspaces.models import Invitation, Workspace
from apps.workspaces.models.member import WorkspaceMember


@strawberry_django.type(WorkspaceMember)
class WorkspaceMemberType(relay.Node):
    role: str
    joined_at: datetime | None
    created_at: datetime

    @strawberry_django.field(select_related=["user"])
    def user_email(self) -> str:
        member = cast("WorkspaceMember", self)
        return str(member.user.email)

    @strawberry_django.field(select_related=["user"])
    def user_name(self) -> str:
        member = cast("WorkspaceMember", self)
        full = member.user.get_full_name()
        return str(full or member.user.email)

    @strawberry_django.field(select_related=["user"])
    def user_id(self) -> str:
        return str(cast("WorkspaceMember", self).user_id)

    @strawberry_django.field(select_related=["user"])
    def user_last_active_at(self) -> datetime | None:
        return cast("WorkspaceMember", self).user.last_login


@strawberry_django.type(Workspace)
class WorkspaceType(relay.Node):
    name: str
    slug: str
    billing_email: str
    suspended_at: datetime | None
    created_at: datetime

    member_count: int = strawberry_django.field(annotate=Count("members"))

    @strawberry_django.field(select_related=["owner"])
    def owner_email(self) -> str:
        return str(cast("Workspace", self).owner.email)

    @strawberry_django.field(select_related=["owner"])
    def owner_id(self) -> str:
        return str(cast("Workspace", self).owner_id)

    members: DjangoListConnection[WorkspaceMemberType] = strawberry_django.connection()

    agents: DjangoListConnection[AgentType] = strawberry_django.connection()
    tools: DjangoListConnection[ToolType] = strawberry_django.connection()
    knowledge_bases: DjangoListConnection[KnowledgeType] = strawberry_django.connection()
    end_users: DjangoListConnection[EndUserType] = strawberry_django.connection()
    schedules: DjangoListConnection[ScheduleType] = strawberry_django.connection()
    insights: DjangoListConnection[InsightType] = strawberry_django.connection()
    policies: DjangoListConnection[PolicyType] = strawberry_django.connection()

    @strawberry_django.connection(DjangoListConnection[ConversationType])
    def conversations(
        self,
        agent_id: int | None = None,
    ) -> list[Conversation]:
        workspace = cast("Workspace", self)
        return Conversation.list_for_workspace(  # type: ignore[return-value]
            workspace.pk,
            agent_id=agent_id,
        )

    @strawberry_django.connection(DjangoListConnection[RunType])
    def runs(
        self,
        status: str | None = None,
        agent_id: int | None = None,
    ) -> list[Run]:
        workspace = cast("Workspace", self)
        return Run.list_for_workspace(  # type: ignore[return-value]
            workspace.pk,
            status=status,
            agent_id=agent_id,
        )

    @strawberry_django.connection(DjangoListConnection[APIKeyType])
    def api_keys(self, show_revoked: bool = False) -> list[APIKey]:
        workspace = cast("Workspace", self)
        return APIKey.list_for_workspace(  # type: ignore[return-value]
            workspace.pk,
            show_revoked=show_revoked,
        )

    @strawberry_django.field
    def wallet(self) -> CreditWalletType | None:
        workspace = cast("Workspace", self)
        wallet = CreditWallet.get_for_workspace(workspace.pk)
        return cast("CreditWalletType | None", wallet)


@strawberry_django.type(Invitation)
class InvitationType(relay.Node):
    email: str
    role: str
    expires_at: datetime
    accepted_at: datetime | None
    created_at: datetime

    @strawberry_django.field(select_related=["workspace"])
    def workspace_name(self) -> str:
        return str(cast("Invitation", self).workspace.name)

    @strawberry_django.field
    def pending(self) -> bool:
        from django.utils import timezone  # noqa: PLC0415

        invitation = cast("Invitation", self)
        return invitation.accepted_at is None and invitation.expires_at > timezone.now()


@strawberry.type
class CreateWorkspacePayload(MutationResult):
    workspace: WorkspaceType | None = None


@strawberry.type
class UpdateWorkspacePayload(MutationResult):
    workspace: WorkspaceType | None = None


@strawberry.type
class InviteMemberPayload(MutationResult):
    invitation: InvitationType | None = None


@strawberry.type
class AcceptInvitationPayload(MutationResult):
    member: WorkspaceMemberType | None = None


@strawberry.type
class TransferOwnershipPayload(MutationResult):
    workspace: WorkspaceType | None = None


@strawberry.type
class RevokeInvitationPayload(MutationResult):
    pass


@strawberry.type
class RemoveMemberPayload(MutationResult):
    pass


@strawberry.type
class UpdateMemberRolePayload(MutationResult):
    member: WorkspaceMemberType | None = None
