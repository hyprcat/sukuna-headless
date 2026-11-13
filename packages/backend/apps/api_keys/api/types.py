from __future__ import annotations

from datetime import datetime

import strawberry
import strawberry_django
from strawberry import relay

from apps.api_keys.models import APIKey
from apps.core.api.types import MutationResult


@strawberry_django.type(APIKey)
class APIKeyType(relay.Node):
    name: str
    key_prefix: str
    scopes: list[str]
    last_used_at: datetime | None
    revoked_at: datetime | None
    expires_at: datetime | None
    created_at: datetime

    @strawberry_django.field
    def is_active(self) -> bool:
        return APIKey.is_active(self)  # type: ignore[arg-type]

    @strawberry_django.field
    def masked_value(self) -> str:
        return APIKey.masked_value(self)  # type: ignore[arg-type]

    @strawberry_django.field(select_related=["created_by"])
    def created_by_email(self) -> str | None:
        created_by = self.created_by  # type: ignore[attr-defined]
        return created_by.email if created_by else None


@strawberry.type
class CreateAPIKeyPayload(MutationResult):
    api_key: APIKeyType | None = None
    plaintext_secret: str | None = strawberry.field(default=None, name="plaintextSecret")


@strawberry.type
class RevokeAPIKeyPayload(MutationResult):
    api_key: APIKeyType | None = None
