from __future__ import annotations

from decimal import Decimal
from typing import Any, ClassVar

from django.core.exceptions import ValidationError
from django.db import models
from simple_history.models import HistoricalRecords

from apps.billing.schemas import BillingFormat
from apps.core.exceptions import NotFound
from apps.core.models import TimestampedModel


class BillingRateQuerySet(models.QuerySet["BillingRate"]):
    def active(self) -> BillingRateQuerySet:
        return self.filter(is_active=True)


class BillingRate(TimestampedModel):
    """Rate card for usage cost calculation. One active rate per model tier."""

    model_tier = models.CharField(max_length=20, db_index=True)
    token_input_rate = models.DecimalField(
        max_digits=BillingFormat().max_digits,
        decimal_places=BillingFormat().decimal_places,
        help_text="Cost per 1k input tokens",
    )
    token_output_rate = models.DecimalField(
        max_digits=BillingFormat().max_digits,
        decimal_places=BillingFormat().decimal_places,
        help_text="Cost per 1k output tokens",
    )
    tool_call_rate = models.DecimalField(
        max_digits=BillingFormat().max_digits,
        decimal_places=BillingFormat().decimal_places,
        help_text="Cost per tool call",
    )
    is_active = models.BooleanField(default=True, db_index=True)
    history = HistoricalRecords()

    objects = BillingRateQuerySet.as_manager()

    class Meta:
        db_table = "billing_billingrate"
        ordering = ("model_tier",)
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=("model_tier",),
                condition=models.Q(is_active=True),
                name="billingrate_one_active_per_tier",
            ),
            models.CheckConstraint(
                condition=models.Q(token_input_rate__gte=Decimal("0")),
                name="billingrate_input_rate_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(token_output_rate__gte=Decimal("0")),
                name="billingrate_output_rate_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(tool_call_rate__gte=Decimal("0")),
                name="billingrate_tool_call_rate_non_negative",
            ),
        ]

    def __str__(self) -> str:
        status = "active" if self.is_active else "inactive"
        return f"BillingRate[{self.model_tier}] ({status})"

    def clean(self) -> None:
        super().clean()
        if not self.model_tier or not self.model_tier.strip():
            raise ValidationError({"model_tier": "Model tier is required."})
        for field in ("token_input_rate", "token_output_rate", "tool_call_rate"):
            val = getattr(self, field, None)
            if val is not None and val < 0:
                raise ValidationError({field: "Rate cannot be negative."})

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.full_clean()
        super().save(*args, **kwargs)

    def compute_cost(
        self,
        input_tokens: int,
        output_tokens: int,
        tool_calls: int,
    ) -> Decimal:
        input_cost = self.token_input_rate * Decimal(input_tokens) / Decimal("1000")
        output_cost = self.token_output_rate * Decimal(output_tokens) / Decimal("1000")
        tool_cost = self.tool_call_rate * Decimal(tool_calls)
        return input_cost + output_cost + tool_cost

    @classmethod
    def active_for_tier(cls, tier: str) -> BillingRate:
        try:
            return cls.objects.active().get(model_tier=tier)
        except cls.DoesNotExist as exc:
            raise NotFound(f"No active billing rate for tier '{tier}'.") from exc
