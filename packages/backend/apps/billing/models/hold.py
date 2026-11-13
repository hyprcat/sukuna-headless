from __future__ import annotations

from decimal import Decimal
from typing import Any, ClassVar

from django.db import models, transaction
from django.utils import timezone
from simple_history.models import HistoricalRecords

from apps.billing.schemas import BillingFormat
from apps.core.exceptions import BillingError, Conflict
from apps.core.models import TimestampedModel


class HoldStatus(models.TextChoices):
    ACTIVE = "active"
    SETTLED = "settled"
    RELEASED = "released"
    EXPIRED = "expired"


class BillingHold(TimestampedModel):
    """Reserves wallet balance before a run starts; settled or released on termination."""

    run = models.OneToOneField(
        "runs.Run",
        on_delete=models.CASCADE,
        related_name="billing_hold",
    )
    wallet = models.ForeignKey(
        "billing.CreditWallet",
        on_delete=models.PROTECT,
        related_name="holds",
    )
    amount_reserved_usd = models.DecimalField(
        max_digits=BillingFormat().max_digits,
        decimal_places=BillingFormat().decimal_places,
    )
    amount_consumed_usd = models.DecimalField(
        max_digits=BillingFormat().max_digits,
        decimal_places=BillingFormat().decimal_places,
        default=Decimal("0"),
    )
    status = models.CharField(
        max_length=10,
        choices=HoldStatus.choices,
        default=HoldStatus.ACTIVE,
        db_index=True,
    )
    settled_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField()
    metadata = models.JSONField(default=dict, blank=True)
    history = HistoricalRecords()

    class Meta:
        db_table = "billing_billinghold"
        ordering = ("-created_at",)
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=models.Q(status__in=HoldStatus.values),
                name="billinghold_status_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(amount_reserved_usd__gt=Decimal("0")),
                name="billinghold_reserved_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(amount_consumed_usd__gte=Decimal("0")),
                name="billinghold_consumed_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(amount_consumed_usd__lte=models.F("amount_reserved_usd")),
                name="billinghold_consumed_lte_reserved",
            ),
        ]

    def __str__(self) -> str:
        return f"Hold[{self.run_id}] ${self.amount_reserved_usd} ({self.status})"

    @classmethod
    def list_for_workspace(
        cls,
        workspace_id: int,
        *,
        status: str | None = None,
    ) -> models.QuerySet[BillingHold]:
        qs = cls.objects.filter(
            wallet__workspace_id=workspace_id,
        ).select_related("run", "wallet")
        if status is not None:
            qs = qs.filter(status=status)
        return qs

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self.pk is None and self.status == HoldStatus.ACTIVE:
            with transaction.atomic():
                self._guard_new_active_reservation()
                super().save(*args, **kwargs)
            return
        super().save(*args, **kwargs)

    def is_expired(self) -> bool:
        return self.status == HoldStatus.ACTIVE and timezone.now() >= self.expires_at

    @transaction.atomic
    def settle(self, actual_cost: Decimal) -> None:
        locked = self._lock()
        locked._guard_active("settle")
        locked._guard_settle_cost(actual_cost)
        if actual_cost > 0:
            locked.wallet.debit(actual_cost, reason="run_debit", reference=str(locked.run.run_uid))
        locked.amount_consumed_usd = actual_cost
        locked.status = HoldStatus.SETTLED
        locked.settled_at = timezone.now()
        locked.save(update_fields=("amount_consumed_usd", "status", "settled_at", "updated_at"))
        self.refresh_from_db()

    @transaction.atomic
    def release(self) -> None:
        locked = self._lock()
        locked._guard_active("release")
        locked.status = HoldStatus.RELEASED
        locked.save(update_fields=("status", "updated_at"))
        self.refresh_from_db()

    @transaction.atomic
    def expire(self) -> None:
        locked = self._lock()
        locked._guard_active("expire")
        locked.status = HoldStatus.EXPIRED
        locked.save(update_fields=("status", "updated_at"))
        self.refresh_from_db()

    def _lock(self) -> BillingHold:
        return type(self).objects.select_for_update().get(pk=self.pk)

    def _guard_active(self, operation: str) -> None:
        if self.status != HoldStatus.ACTIVE:
            raise Conflict(f"Cannot {operation} a {self.status} hold.")

    def _guard_settle_cost(self, cost: Decimal) -> None:
        if cost < 0:
            raise BillingError("Settlement cost cannot be negative.", field="actual_cost")
        if cost > self.amount_reserved_usd:
            raise BillingError("Settlement cost exceeds reserved amount.", field="actual_cost")

    def _guard_new_active_reservation(self) -> None:
        locked_wallet = self.wallet._lock()
        if self.run.workspace_id != locked_wallet.workspace_id:
            raise BillingError("Hold wallet must belong to the run workspace.", field="wallet")
        if self.amount_reserved_usd > locked_wallet.available():
            raise BillingError(
                "Insufficient available credits for hold.",
                field="amount_reserved_usd",
            )
