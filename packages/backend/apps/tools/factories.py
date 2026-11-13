from __future__ import annotations

import factory

from apps.tools.models import Tool
from apps.workspaces.factories import WorkspaceFactory


class ToolFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Tool

    workspace = factory.SubFactory(WorkspaceFactory)
    name = factory.Sequence(lambda n: f"tool-{n}")
    description = factory.Faker("sentence")
    parameters_schema = factory.LazyFunction(dict)
    execution_endpoint = factory.Sequence(lambda n: f"https://tools.example.com/{n}")
    is_sensitive = False
    is_active = True

    class Params:
        sensitive = factory.Trait(is_sensitive=True)
        inactive = factory.Trait(is_active=False)
