from __future__ import annotations

import factory
from django.utils import timezone

from apps.end_users.models import ControlProfile, EndUser
from apps.workspaces.factories import WorkspaceFactory


class EndUserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = EndUser
        skip_postgeneration_save = True

    workspace = factory.SubFactory(WorkspaceFactory)
    external_user_id = factory.Sequence(lambda n: f"ext-user-{n}")
    display_name = factory.Faker("name")

    profile = factory.RelatedFactory(
        "apps.end_users.factories.ControlProfileFactory",
        factory_related_name="end_user",
    )

    class Params:
        inactive = factory.Trait(
            is_active=False,
            deactivated_at=factory.LazyFunction(timezone.now),
        )
        free_tier = factory.Trait(
            tier_label="free",
            profile=factory.RelatedFactory(
                "apps.end_users.factories.ControlProfileFactory",
                factory_related_name="end_user",
                model_tier="free",
                credits=100,
                credit_grant_per_period=100,
            ),
        )
        pro_tier = factory.Trait(
            tier_label="pro",
            profile=factory.RelatedFactory(
                "apps.end_users.factories.ControlProfileFactory",
                factory_related_name="end_user",
                model_tier="pro",
                credits=500,
                credit_grant_per_period=500,
                concurrency_max=5,
            ),
        )
        enterprise_tier = factory.Trait(
            tier_label="enterprise",
            profile=factory.RelatedFactory(
                "apps.end_users.factories.ControlProfileFactory",
                factory_related_name="end_user",
                model_tier="enterprise",
                credits=2000,
                credit_grant_per_period=2000,
                concurrency_max=20,
            ),
        )


class ControlProfileFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ControlProfile

    end_user = factory.SubFactory(EndUserFactory, profile=None)
    credits = 100
    model_tier = "free"
    credit_grant_per_period = 100
