from __future__ import annotations

import factory

from apps.knowledge.models import Knowledge, KnowledgeKind
from apps.workspaces.factories import WorkspaceFactory


class KnowledgeFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Knowledge

    workspace = factory.SubFactory(WorkspaceFactory)
    name = factory.Sequence(lambda n: f"knowledge-{n}")
    description = factory.Faker("sentence")
    kind = KnowledgeKind.DOCUMENT
    file = factory.django.FileField(filename="test.txt")
    file_name = "test.txt"
    file_size_bytes = 256
    content_type = "text/plain"

    class Params:
        dataset = factory.Trait(
            kind=KnowledgeKind.DATASET,
            file=factory.django.FileField(filename="data.csv"),
            file_name="data.csv",
            content_type="text/csv",
        )
        connected = factory.Trait(
            kind=KnowledgeKind.CONNECTED_SOURCE,
            file="",
            file_name="",
            file_size_bytes=None,
            content_type="",
            source_endpoint="https://api.example.com/data",
        )
        inactive = factory.Trait(is_active=False)
