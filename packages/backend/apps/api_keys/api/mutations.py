from __future__ import annotations

from datetime import datetime

import strawberry
from strawberry.types import Info

from apps.accounts.permissions import Action
from apps.api_keys.api.types import CreateAPIKeyPayload, RevokeAPIKeyPayload
from apps.api_keys.models import APIKey
from apps.core.api.ids import parse_int_id
from apps.core.api.mappers import catch_domain_errors
from apps.core.decorators import requires_role, workspace_scoped


def _get_api_key(workspace_pk: int, api_key_id: str) -> APIKey:
    pk = parse_int_id(api_key_id, expected_type="APIKeyType")
    return APIKey.get_for_workspace_or_raise(workspace_pk, pk)


@strawberry.input
class CreateAPIKeyInput:
    name: str
    scopes: list[str]
    expires_at: datetime | None = None


@strawberry.input
class RevokeAPIKeyInput:
    id: strawberry.ID
    reason: str = ""


@strawberry.type
class APIKeyMutation:
    @strawberry.mutation
    @workspace_scoped
    @requires_role(Action.API_KEYS_CREATE)
    @catch_domain_errors(CreateAPIKeyPayload)
    def create_api_key(self, info: Info, input: CreateAPIKeyInput) -> CreateAPIKeyPayload:
        api_key, plain_secret = APIKey.create_for_workspace(
            info.context.workspace,
            name=input.name,
            scopes=input.scopes,
            created_by=info.context.principal.member.user,
            expires_at=input.expires_at,
        )
        return CreateAPIKeyPayload(
            success=True,
            errors=[],
            api_key=api_key,  # type: ignore[arg-type]
            plaintext_secret=plain_secret,
        )

    @strawberry.mutation
    @workspace_scoped
    @requires_role(Action.API_KEYS_REVOKE)
    @catch_domain_errors(RevokeAPIKeyPayload)
    def revoke_api_key(self, info: Info, input: RevokeAPIKeyInput) -> RevokeAPIKeyPayload:
        api_key = _get_api_key(info.context.workspace.pk, input.id)
        api_key.revoke(reason=input.reason)
        return RevokeAPIKeyPayload(
            success=True,
            errors=[],
            api_key=api_key,  # type: ignore[arg-type]
        )
