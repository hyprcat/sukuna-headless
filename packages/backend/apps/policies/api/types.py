from __future__ import annotations

from datetime import datetime

import strawberry
import strawberry_django
from strawberry import relay

from apps.core.api.types import MutationResult
from apps.policies.models import Policy


@strawberry_django.type(Policy)
class PolicyType(relay.Node):
    name: str
    action_restrictions: strawberry.scalars.JSON
    domain_restrictions: strawberry.scalars.JSON
    output_restrictions: strawberry.scalars.JSON
    created_at: datetime
    updated_at: datetime


@strawberry.type
class CreatePolicyPayload(MutationResult):
    policy: PolicyType | None = None


@strawberry.type
class UpdatePolicyPayload(MutationResult):
    policy: PolicyType | None = None
