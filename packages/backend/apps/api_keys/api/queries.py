from __future__ import annotations

from typing import cast

import strawberry
import strawberry_django
from strawberry.types import Info
from strawberry_django.relay import DjangoListConnection

from apps.accounts.permissions import Action
from apps.api_keys.api.types import APIKeyType
from apps.api_keys.models import APIKey
from apps.core.decorators import requires_role, workspace_scoped


@strawberry.type
class APIKeyQuery:
    @strawberry_django.connection(DjangoListConnection[APIKeyType])
    @workspace_scoped
    @requires_role(Action.API_KEYS_READ)
    def api_keys(
        self,
        info: Info,
        show_revoked: bool = False,
    ) -> list[APIKey]:
        return APIKey.list_for_workspace(info.context.workspace.pk, show_revoked=show_revoked)  # type: ignore[return-value]

    @strawberry.field
    @workspace_scoped
    @requires_role(Action.API_KEYS_READ)
    def api_key(self, info: Info, id: strawberry.ID) -> APIKeyType | None:
        return cast("APIKeyType | None", APIKey.get_for_workspace(info.context.workspace.pk, id))
