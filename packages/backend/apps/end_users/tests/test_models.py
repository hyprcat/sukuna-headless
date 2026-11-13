from __future__ import annotations

from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.end_users.factories import ControlProfileFactory, EndUserFactory
from apps.end_users.models import EndUser
from apps.workspaces.factories import WorkspaceFactory

pytestmark = pytest.mark.django_db


def test_refresh_credits_adds_grant() -> None:
    past = timezone.now() - timedelta(hours=1)
    end_user = EndUserFactory(
        profile__credits=0,
        profile__credit_grant_per_period=50,
        profile__credit_refresh_schedule="daily",
        profile__next_credit_refresh_at=past,
        profile__runs_used_in_period=10,
    )

    end_user.refresh_credits()
    end_user.profile.refresh_from_db()

    assert end_user.profile.credits == 50
    assert end_user.profile.runs_used_in_period == 0
    assert end_user.profile.next_credit_refresh_at > timezone.now()


def test_refresh_credits_idempotent_within_period() -> None:
    future = timezone.now() + timedelta(hours=1)
    end_user = EndUserFactory(
        profile__credits=50,
        profile__credit_grant_per_period=50,
        profile__credit_refresh_schedule="daily",
        profile__next_credit_refresh_at=future,
    )

    end_user.refresh_credits()
    end_user.profile.refresh_from_db()

    assert end_user.profile.credits == 50


def test_refresh_credits_idempotent_for_stale_instances() -> None:
    past = timezone.now() - timedelta(hours=1)
    end_user = EndUserFactory(
        profile__credits=0,
        profile__credit_grant_per_period=50,
        profile__credit_refresh_schedule="daily",
        profile__next_credit_refresh_at=past,
    )
    stale = EndUser.objects.select_related("profile").get(pk=end_user.pk)

    end_user.refresh_credits()
    stale.refresh_credits()
    end_user.profile.refresh_from_db()

    assert end_user.profile.credits == 50


def test_refresh_credits_accepts_cron_schedule() -> None:
    past = timezone.now() - timedelta(days=2)
    end_user = EndUserFactory(
        profile__credits=0,
        profile__credit_grant_per_period=25,
        profile__credit_refresh_schedule="0 0 * * *",
        profile__next_credit_refresh_at=past,
    )

    end_user.refresh_credits()
    end_user.profile.refresh_from_db()

    assert end_user.profile.credits == 25
    assert end_user.profile.next_credit_refresh_at > timezone.now()


def test_refresh_credits_ignores_never_schedule() -> None:
    past = timezone.now() - timedelta(days=1)
    end_user = EndUserFactory(
        profile__credits=10,
        profile__credit_grant_per_period=50,
        profile__credit_refresh_schedule="never",
        profile__next_credit_refresh_at=past,
    )

    end_user.refresh_credits()
    end_user.profile.refresh_from_db()

    assert end_user.profile.credits == 10


def test_activate_deactivate_cycle() -> None:
    end_user = EndUserFactory()
    end_user.deactivate()
    end_user.refresh_from_db()
    assert not end_user.is_active
    assert end_user.deactivated_at is not None

    end_user.activate()
    end_user.refresh_from_db()
    assert end_user.is_active
    assert end_user.deactivated_at is None


def test_unique_external_user_id_per_workspace() -> None:
    end_user = EndUserFactory()
    with pytest.raises(IntegrityError):
        EndUserFactory(workspace=end_user.workspace, external_user_id=end_user.external_user_id)


def test_external_user_id_cannot_be_blank_on_save() -> None:
    with pytest.raises(ValidationError):
        EndUserFactory(external_user_id="")


def test_external_user_id_non_empty_db_constraint() -> None:
    end_user = EndUserFactory()

    with pytest.raises(IntegrityError), transaction.atomic():
        EndUser.objects.filter(pk=end_user.pk).update(external_user_id="")


def test_metadata_must_be_json_object_on_save() -> None:
    with pytest.raises(ValidationError):
        EndUserFactory(metadata=[])


def test_metadata_size_is_validated_on_save() -> None:
    with pytest.raises(ValidationError):
        EndUserFactory(metadata={"blob": "x" * 16_385})


def test_profile_run_count_config_validated_on_save() -> None:
    with pytest.raises(ValidationError):
        ControlProfileFactory(run_count_limit=5, run_count_period="")


def test_profile_refresh_schedule_validated_on_save() -> None:
    with pytest.raises(ValidationError):
        ControlProfileFactory(credit_refresh_schedule="not a cron")


def test_profile_credits_non_negative_db_constraint() -> None:
    profile = ControlProfileFactory()

    with pytest.raises(IntegrityError), transaction.atomic():
        type(profile).objects.filter(pk=profile.pk).update(credits=-1)


def test_profile_run_count_config_db_constraint() -> None:
    profile = ControlProfileFactory()

    with pytest.raises(IntegrityError), transaction.atomic():
        type(profile).objects.filter(pk=profile.pk).update(
            run_count_limit=5,
            run_count_period="",
        )


def test_external_user_id_unique_per_workspace_only() -> None:
    end_user = EndUserFactory(external_user_id="same")

    other = EndUserFactory(workspace=WorkspaceFactory(), external_user_id="same")

    assert other.workspace_id != end_user.workspace_id


def test_str_prefers_display_name() -> None:
    end_user = EndUserFactory(external_user_id="u-123", display_name="Alice")
    assert str(end_user) == "Alice"


def test_str_falls_back_to_external_user_id() -> None:
    end_user = EndUserFactory(external_user_id="u-123", display_name="")
    assert str(end_user) == "u-123"
