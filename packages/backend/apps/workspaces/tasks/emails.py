from __future__ import annotations

from django.core.mail import send_mail
from django.tasks import task
from pydantic import BaseModel, ConfigDict

from config.runtime import runtime


class InvitationEmailSubjects(BaseModel):
    model_config = ConfigDict(frozen=True)

    invite: str = "You're invited to a workspace — midsphere"


@task
def send_invitation_email(invitation_id: int) -> None:
    from apps.workspaces.models.invitation import Invitation  # noqa: PLC0415

    invitation = Invitation.objects.select_related("workspace").filter(pk=invitation_id).first()
    if invitation is None or not invitation.is_pending:
        return
    link = f"{runtime.frontend_url}/accept-invite/{invitation.token}"
    body = (
        f"You've been invited to join {invitation.workspace.name} on midsphere.\n\n"
        f"{link}\n\n"
        "This invitation expires in 7 days."
    )
    send_mail(
        subject=InvitationEmailSubjects().invite,
        message=body,
        from_email=None,
        recipient_list=[invitation.email],
    )
