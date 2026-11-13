from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from django.db import models
from simple_history.models import HistoricalRecords

if TYPE_CHECKING:
    from django.db.models import QuerySet

from apps.billing.schemas import BillingFormat
from apps.core.exceptions import Conflict
from apps.core.models import TimestampedModel


class TopupStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    SUCCEEDED = "succeeded", "Succeeded"
    FAILED = "failed", "Failed"
    REFUND_REQUESTED = "refund_requested", "Refund requested"
    REFUNDED = "refunded", "Refunded"


class Topup(TimestampedModel):
    """Mirror of the Dodo Payments payment row we care about.

    Created in ``pending`` state by the ``create_topup`` service before
    the user is sent to hosted checkout.  The Dodo webhook receiver flips
    status to ``succeeded`` (or ``failed``) and triggers the credit grant
    via :meth:`CreditWallet.record_dodo_credit_grant`.
    """

    wallet = models.ForeignKey(
        "billing.CreditWallet",
        on_delete=models.PROTECT,
        related_name="topups",
    )
    dodo_payment_id = models.CharField(max_length=128, blank=True, default="", db_index=True)
    amount_usd = models.DecimalField(
        max_digits=BillingFormat().max_digits,
        decimal_places=BillingFormat().decimal_places,
    )
    currency = models.CharField(max_length=3, default=BillingFormat().currency)
    idempotency_key = models.CharField(max_length=128, unique=True)
    status = models.CharField(max_length=20, choices=TopupStatus, default=TopupStatus.PENDING)
    refund_reason = models.CharField(max_length=512, blank=True, default="")
    history = HistoricalRecords()

    class Meta:
        db_table = "billing_topup"
        ordering = ("-created_at",)
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=models.Q(amount_usd__in=BillingFormat().allowed_topup_amounts),
                name="topup_amount_supported",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=TopupStatus.values),
                name="topup_status_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(currency=BillingFormat().currency),
                name="topup_currency_usd",
            ),
            models.CheckConstraint(
                condition=~models.Q(idempotency_key=""),
                name="topup_idempotency_key_non_empty",
            ),
            models.UniqueConstraint(
                fields=("dodo_payment_id",),
                condition=models.Q(dodo_payment_id__gt=""),
                name="unique_dodo_payment_id_when_set",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=("wallet", "-created_at")),
            models.Index(fields=("status",)),
        ]

    def __str__(self) -> str:
        return f"Topup {self.idempotency_key} {self.status} ${self.amount_usd}"

    @classmethod
    def for_workspace(
        cls,
        workspace_id: int,
        *,
        status: str | None = None,
    ) -> QuerySet[Topup]:
        qs = cls.objects.filter(wallet__workspace_id=workspace_id)
        if status is not None:
            qs = qs.filter(status=status)
        return qs.order_by("-created_at")

    def confirm(self, dodo_payment_id: str) -> None:
        if self.status != TopupStatus.PENDING:
            raise Conflict("Only pending top-ups can be confirmed.")
        if not dodo_payment_id.strip():
            raise Conflict("Dodo payment ID must be non-empty.")
        self.dodo_payment_id = dodo_payment_id
        self.status = TopupStatus.SUCCEEDED
        self.save(update_fields=("dodo_payment_id", "status", "updated_at"))

    def fail(self) -> None:
        if self.status != TopupStatus.PENDING:
            raise Conflict("Only pending top-ups can be marked failed.")
        self.status = TopupStatus.FAILED
        self.save(update_fields=("status", "updated_at"))

    def request_refund(self, reason: str) -> None:
        if self.status != TopupStatus.SUCCEEDED:
            raise Conflict("Only succeeded top-ups can be refunded.")
        if not self.dodo_payment_id.strip():
            raise Conflict("Top-up has no Dodo payment ID.")
        self.status = TopupStatus.REFUND_REQUESTED
        self.refund_reason = reason
        self.save(update_fields=("status", "refund_reason", "updated_at"))

    def complete_refund(self) -> None:
        if self.status != TopupStatus.REFUND_REQUESTED:
            raise Conflict("Only refund-requested top-ups can be marked refunded.")
        self.status = TopupStatus.REFUNDED
        self.save(update_fields=("status", "updated_at"))

    def save(self, *args: Any, **kwargs: Any) -> None:
        self._validate_record()
        super().save(*args, **kwargs)

    def _validate_record(self) -> None:
        fmt = BillingFormat()
        if self.amount_usd <= 0:
            raise Conflict("Top-up amount must be positive.")
        if self.amount_usd not in fmt.allowed_topup_amounts:
            allowed = ", ".join(f"${value:.2f}" for value in fmt.allowed_topup_amounts)
            raise Conflict(f"Top-up amount must be one of {allowed}.")
        if self.currency != fmt.currency:
            raise Conflict("Top-up currency must be USD.")
        if not self.idempotency_key.strip():
            raise Conflict("Top-up idempotency key must be non-empty.")
        if self.status not in TopupStatus.values:
            raise Conflict("Unknown top-up status.")
