from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any, ClassVar

from django.apps import apps
from django.db import models
from django.db.models import Sum
from django.db.models.functions import Coalesce
from django.db.transaction import atomic
from simple_history.models import HistoricalRecords

from apps.billing.schemas import BillingFormat
from apps.core.exceptions import Conflict
from apps.core.models import TimestampedModel

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable

    from django.db.models import QuerySet


class LedgerKind(models.TextChoices):
    TOPUP = "topup", "Top-up"
    RUN_DEBIT = "run_debit", "Run debit"
    REFUND = "refund", "Refund"
    ADJUSTMENT = "adjustment", "Adjustment"


class LedgerEntryQuerySet(models.QuerySet["LedgerEntry"]):
    def bulk_create(
        self,
        objs: Iterable[LedgerEntry],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> list[LedgerEntry]:
        raise Conflict("LedgerEntry bulk_create bypasses wallet balance recomputation.")

    def bulk_update(
        self,
        objs: Iterable[LedgerEntry],
        fields: Iterable[str],
        batch_size: int | None = None,
    ) -> int:
        raise Conflict("LedgerEntry is append-only; create a correcting entry instead.")

    def update(self, **kwargs: Any) -> int:
        raise Conflict("LedgerEntry is append-only; create a correcting entry instead.")

    def delete(self) -> tuple[int, dict[str, int]]:
        raise Conflict("LedgerEntry is append-only; create a correcting entry instead.")


class LedgerEntryManager(models.Manager["LedgerEntry"]):
    def get_queryset(self) -> LedgerEntryQuerySet:
        return LedgerEntryQuerySet(self.model, using=self._db)

    def bulk_create(
        self,
        objs: Iterable[LedgerEntry],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> list[LedgerEntry]:
        raise Conflict("LedgerEntry bulk_create bypasses wallet balance recomputation.")

    def bulk_update(
        self,
        objs: Iterable[LedgerEntry],
        fields: Iterable[str],
        batch_size: int | None = None,
    ) -> int:
        raise Conflict("LedgerEntry is append-only; create a correcting entry instead.")


class LedgerEntry(TimestampedModel):
    """Append-only record of every credit movement on a wallet.

    Never edited or deleted — corrections are new entries with the
    ``adjustment`` kind. The wallet's denormalised ``balance_usd`` is a
    cache of the SUM of ``delta_usd`` here, recomputed inside the same
    transaction as every insert.
    """

    wallet = models.ForeignKey(
        "billing.CreditWallet",
        on_delete=models.PROTECT,
        related_name="entries",
    )
    delta_usd = models.DecimalField(
        max_digits=BillingFormat().max_digits,
        decimal_places=BillingFormat().decimal_places,
    )
    currency = models.CharField(max_length=3, default=BillingFormat().currency)
    kind = models.CharField(max_length=24, choices=LedgerKind)
    reference = models.CharField(max_length=128)
    note = models.TextField(blank=True, default="")
    history = HistoricalRecords()
    objects = LedgerEntryManager()

    class Meta:
        db_table = "billing_ledgerentry"
        ordering = ("-created_at",)
        base_manager_name = "objects"
        default_manager_name = "objects"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=models.Q(kind__in=LedgerKind.values),
                name="ledgerentry_kind_valid",
            ),
            models.CheckConstraint(
                condition=~models.Q(reference=""),
                name="ledgerentry_reference_non_empty",
            ),
            models.CheckConstraint(
                condition=~(models.Q(kind=LedgerKind.ADJUSTMENT) & models.Q(note="")),
                name="ledgerentry_adjustment_note_non_empty",
            ),
            models.CheckConstraint(
                condition=models.Q(currency=BillingFormat().currency),
                name="ledgerentry_currency_usd",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=("wallet", "-created_at")),
            models.Index(fields=("kind",)),
        ]

    @classmethod
    def for_workspace(
        cls,
        workspace_id: int,
        *,
        kind: str | None = None,
    ) -> QuerySet[LedgerEntry]:
        qs = cls.objects.filter(wallet__workspace_id=workspace_id)
        if kind is not None:
            qs = qs.filter(kind=kind)
        return qs.order_by("-created_at")

    @classmethod
    def for_wallet(cls, wallet_id: int) -> QuerySet[LedgerEntry]:
        return cls.objects.filter(wallet_id=wallet_id).order_by("-created_at")

    def __str__(self) -> str:
        sign = "+" if self.delta_usd >= 0 else ""
        return f"{self.kind} {sign}{self.delta_usd}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self.pk is not None:
            raise Conflict("LedgerEntry is append-only; create a correcting entry instead.")
        self._validate_insert()
        with atomic():
            self._lock_wallet()
            super().save(*args, **kwargs)
            self._recompute_wallet_balance()

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        raise Conflict("LedgerEntry is append-only; create a correcting entry instead.")

    def _lock_wallet(self) -> None:
        wallet_model = apps.get_model("billing", "CreditWallet")
        wallet_model.objects.select_for_update().get(pk=self.wallet_id)

    def _validate_insert(self) -> None:
        if self.kind not in LedgerKind.values:
            raise Conflict("Unknown ledger kind.")
        if not self.reference.strip():
            raise Conflict("Ledger entries require a non-empty reference.")
        if self.kind == LedgerKind.ADJUSTMENT and not self.note.strip():
            raise Conflict("Adjustments require a non-empty note.")
        if self.currency != BillingFormat().currency:
            raise Conflict("Ledger entry currency must be USD.")

    def _recompute_wallet_balance(self) -> None:
        total = self._wallet_entry_sum()
        wallet_model = apps.get_model("billing", "CreditWallet")
        wallet_model.objects.filter(pk=self.wallet_id).update(balance_usd=total)

    def _wallet_entry_sum(self) -> Any:
        fmt = BillingFormat()
        return LedgerEntry.objects.filter(wallet_id=self.wallet_id).aggregate(
            total=Coalesce(
                Sum("delta_usd"),
                Decimal("0"),
                output_field=models.DecimalField(
                    max_digits=fmt.max_digits,
                    decimal_places=fmt.decimal_places,
                ),
            )
        )["total"]
