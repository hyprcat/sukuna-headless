from __future__ import annotations

import factory

from apps.policies.models import Policy
from apps.workspaces.factories import WorkspaceFactory


class PolicyFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Policy

    workspace = factory.SubFactory(WorkspaceFactory)
    name = factory.Sequence(lambda n: f"Policy {n}")
    action_restrictions = factory.LazyFunction(list)
    domain_restrictions = factory.LazyFunction(list)
    output_restrictions = factory.LazyFunction(list)

    class Params:
        with_restrictions = factory.Trait(
            action_restrictions=["Never delete user data", "Never send external emails"],
            domain_restrictions=["Only use approved APIs"],
            output_restrictions=["Max 4000 tokens per response"],
        )
