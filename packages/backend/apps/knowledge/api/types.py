from __future__ import annotations

from datetime import datetime
from enum import Enum

import strawberry
import strawberry_django
from strawberry import relay

from apps.core.api.types import MutationResult
from apps.knowledge.models import Knowledge


@strawberry.enum
class KnowledgeKindEnum(Enum):
    DOCUMENT = "document"
    DATASET = "dataset"
    CONNECTED_SOURCE = "connected_source"


@strawberry_django.type(Knowledge)
class KnowledgeType(relay.Node):
    name: str
    description: str
    kind: KnowledgeKindEnum
    file_name: str
    file_size_bytes: int | None
    content_type: str
    source_endpoint: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
    last_indexed_at: datetime | None
    deactivated_at: datetime | None


@strawberry.type
class DeactivateKnowledgePayload(MutationResult):
    knowledge: KnowledgeType | None = None


@strawberry.type
class ActivateKnowledgePayload(MutationResult):
    knowledge: KnowledgeType | None = None


@strawberry.type
class ReindexKnowledgePayload(MutationResult):
    knowledge: KnowledgeType | None = None


@strawberry.type
class CreateKnowledgePayload(MutationResult):
    knowledge: KnowledgeType | None = None


@strawberry.type
class UpdateKnowledgePayload(MutationResult):
    knowledge: KnowledgeType | None = None
