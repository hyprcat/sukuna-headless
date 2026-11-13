from __future__ import annotations

from datetime import datetime

import strawberry
import strawberry_django
from strawberry import relay

from apps.core.api.types import MutationResult
from apps.tools.models import Tool


@strawberry_django.type(Tool)
class ToolType(relay.Node):
    name: str
    description: str
    parameters_schema: strawberry.scalars.JSON
    execution_endpoint: str
    is_sensitive: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime
    deactivated_at: datetime | None


@strawberry.type
class CreateToolPayload(MutationResult):
    tool: ToolType | None = None


@strawberry.type
class DeactivateToolPayload(MutationResult):
    tool: ToolType | None = None


@strawberry.type
class ActivateToolPayload(MutationResult):
    tool: ToolType | None = None


@strawberry.type
class UpdateToolPayload(MutationResult):
    tool: ToolType | None = None
