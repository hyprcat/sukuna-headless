from __future__ import annotations

from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.billing.factories import BillingRateFactory
from apps.billing.models import BillingRate
from apps.core.exceptions import NotFound

pytestmark = pytest.mark.django_db


class TestBillingRateModel:
    def test_create_default(self) -> None:
        rate = BillingRateFactory()
        assert rate.model_tier == "free"
        assert rate.is_active is True
        assert rate.pk is not None

    def test_str_active(self) -> None:
        rate = BillingRateFactory()
        assert "active" in str(rate)
        assert "free" in str(rate)

    def test_str_inactive(self) -> None:
        rate = BillingRateFactory(is_active=False)
        assert "inactive" in str(rate)

    def test_pro_trait(self) -> None:
        rate = BillingRateFactory(pro=True)
        assert rate.model_tier == "pro"
        assert rate.token_input_rate == Decimal("0.0100")

    def test_enterprise_trait(self) -> None:
        rate = BillingRateFactory(enterprise=True)
        assert rate.model_tier == "enterprise"
        assert rate.token_output_rate == Decimal("0.1500")


class TestComputeCost:
    def test_zero_usage(self) -> None:
        rate = BillingRateFactory()
        assert rate.compute_cost(0, 0, 0) == Decimal("0")

    def test_input_tokens_only(self) -> None:
        rate = BillingRateFactory(token_input_rate=Decimal("0.01"))
        cost = rate.compute_cost(input_tokens=1000, output_tokens=0, tool_calls=0)
        assert cost == Decimal("0.01") * Decimal("1000") / Decimal("1000")

    def test_output_tokens_only(self) -> None:
        rate = BillingRateFactory(token_output_rate=Decimal("0.03"))
        cost = rate.compute_cost(input_tokens=0, output_tokens=2000, tool_calls=0)
        assert cost == Decimal("0.03") * Decimal("2000") / Decimal("1000")

    def test_tool_calls_only(self) -> None:
        rate = BillingRateFactory(tool_call_rate=Decimal("0.005"))
        cost = rate.compute_cost(input_tokens=0, output_tokens=0, tool_calls=5)
        assert cost == Decimal("0.005") * Decimal("5")

    def test_combined(self) -> None:
        rate = BillingRateFactory(
            token_input_rate=Decimal("0.01"),
            token_output_rate=Decimal("0.03"),
            tool_call_rate=Decimal("0.005"),
        )
        cost = rate.compute_cost(input_tokens=500, output_tokens=1000, tool_calls=3)
        expected = (
            Decimal("0.01") * Decimal("500") / Decimal("1000")
            + Decimal("0.03") * Decimal("1000") / Decimal("1000")
            + Decimal("0.005") * Decimal("3")
        )
        assert cost == expected


class TestActiveForTier:
    def test_found(self) -> None:
        BillingRateFactory(model_tier="pro", pro=True)
        rate = BillingRate.active_for_tier("pro")
        assert rate.model_tier == "pro"

    def test_not_found_raises(self) -> None:
        with pytest.raises(NotFound, match="No active billing rate"):
            BillingRate.active_for_tier("nonexistent")

    def test_inactive_not_returned(self) -> None:
        BillingRateFactory(model_tier="pro", is_active=False)
        with pytest.raises(NotFound):
            BillingRate.active_for_tier("pro")


class TestUniqueness:
    def test_one_active_per_tier(self) -> None:
        BillingRateFactory(model_tier="free")
        with pytest.raises(ValidationError, match="billingrate_one_active_per_tier"):
            BillingRateFactory(model_tier="free")

    def test_multiple_inactive_same_tier(self) -> None:
        BillingRateFactory(model_tier="free", is_active=False)
        BillingRateFactory(model_tier="free", is_active=False)

    def test_active_plus_inactive_same_tier(self) -> None:
        BillingRateFactory(model_tier="free", is_active=True)
        BillingRateFactory(model_tier="free", is_active=False)

    def test_different_tiers_active(self) -> None:
        BillingRateFactory(model_tier="free")
        BillingRateFactory(model_tier="pro", pro=True)
        assert BillingRate.objects.active().count() == 2


class TestValidation:
    def test_blank_model_tier_rejected(self) -> None:
        with pytest.raises(ValidationError, match="model_tier"):
            BillingRateFactory(model_tier="")

    def test_whitespace_model_tier_rejected(self) -> None:
        with pytest.raises(ValidationError, match="model_tier"):
            BillingRateFactory(model_tier="   ")

    def test_negative_input_rate_rejected(self) -> None:
        with pytest.raises(ValidationError, match="token_input_rate"):
            BillingRateFactory(token_input_rate=Decimal("-0.01"))

    def test_negative_output_rate_rejected(self) -> None:
        with pytest.raises(ValidationError, match="token_output_rate"):
            BillingRateFactory(token_output_rate=Decimal("-0.01"))

    def test_negative_tool_call_rate_rejected(self) -> None:
        with pytest.raises(ValidationError, match="tool_call_rate"):
            BillingRateFactory(tool_call_rate=Decimal("-0.01"))

    def test_zero_rates_allowed(self) -> None:
        rate = BillingRateFactory(
            token_input_rate=Decimal("0"),
            token_output_rate=Decimal("0"),
            tool_call_rate=Decimal("0"),
        )
        assert rate.pk is not None


class TestQuerySet:
    def test_active_filter(self) -> None:
        BillingRateFactory(model_tier="free")
        BillingRateFactory(model_tier="pro", is_active=False)
        assert BillingRate.objects.active().count() == 1
        assert BillingRate.objects.active().first().model_tier == "free"
