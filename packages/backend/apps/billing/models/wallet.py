from __future__ import annotations

from decimal import Decimal
from typing import ClassVar

from django.db import models, transaction
from django.db.models import Sum
from django.db.models.functions import Coalesce
from django.utils import timezone
from simple_history.models import HistoricalRecords

from apps.billing.models.ledger import LedgerEntry, LedgerKind
from apps.billing.schemas import BillingFormat
from apps.core.events import record_event
from apps.core.exceptions import BillingError, NotFound
from apps.core.models import TimestampedModel
from config.runtime import runtime
from integrations import dodo_payments


def _event_suffix(kind: str) -> str:
    return BillingFormat().ledger_event_suffixes.get(kind, "posted")


class CreditWallet(TimestampedModel):
    """Workspace credit pool — `balance_usd` is a cache of the ledger sum.

    Owns the canonical ``topup`` / ``debit`` / ``post_adjustment`` paths.
    Each method writes a :class:`LedgerEntry` and updates the cached
    balance inside one transaction; ``select_for_update`` serialises any
    read-then-write path so concurrent debits cannot oversell.

    Per the topology in ``context/todo.md``: this OneToOneField is the
    declaration that gives every Workspace its ``.wallet`` reverse
    accessor. Workspace itself never reaches into billing — callers go
    ``workspace.wallet.available()`` instead of a Workspace property.
    """

    workspace = models.OneToOneField(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="wallet",
    )
    balance_usd = models.DecimalField(
        max_digits=BillingFormat().max_digits,
        decimal_places=BillingFormat().decimal_places,
        default=Decimal("0"),
    )
    currency = models.CharField(max_length=3, default=BillingFormat().currency)
    last_topup_at = models.DateTimeField(blank=True, null=True)
    history = HistoricalRecords()

    class Meta:
        db_table = "billing_creditwallet"
        ordering = ("-created_at",)
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=models.Q(balance_usd__gte=Decimal("0")),
                name="creditwallet_balance_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(currency=BillingFormat().currency),
                name="creditwallet_currency_usd",
            ),
        ]

    def __str__(self) -> str:
        return f"Wallet[{self.workspace_id}] ${self.balance_usd}"

    @classmethod
    def get_for_workspace(cls, workspace_id: int) -> CreditWallet | None:
        return cls.objects.filter(workspace_id=workspace_id).first()

    @classmethod
    def get_for_workspace_or_raise(cls, workspace_id: int) -> CreditWallet:
        try:
            return cls.objects.get(workspace_id=workspace_id)
        except cls.DoesNotExist as exc:
            raise NotFound("No billing wallet configured.") from exc

    def available(self) -> Decimal:
        """Current balance after active run reservations."""
        return Decimal(self.balance_usd) - self._active_hold_total()

    @transaction.atomic
    def record_dodo_credit_grant(self, amount: Decimal, *, dodo_payment_id: str) -> LedgerEntry:
        if amount <= 0:
            raise BillingError("Credit grant amount must be positive.", field="amount")
        if not dodo_payment_id.strip():
            raise BillingError("Dodo payment ID must be non-empty.", field="dodo_payment_id")
        self._lock()
        return self._post(delta=amount, kind=LedgerKind.TOPUP, reference=dodo_payment_id, note="")

    def sync_balance_from_dodo(self) -> tuple[Decimal, Decimal, bool]:
        local = self.available()
        customer_id = self.workspace.dodo_customer_id
        if not customer_id:
            raise BillingError("Workspace has no Dodo customer ID.")
        balance_resp = dodo_payments.retrieve_credit_balance(
            customer_id=customer_id,
            entitlement_id=runtime.dodo_credit_entitlement_id,
        )
        dodo_balance = Decimal(str(balance_resp.balance)) / Decimal("100")
        matches = abs(local - dodo_balance) <= Decimal("0.01")
        return local, dodo_balance, matches

    @transaction.atomic
    def refund(self, amount: Decimal, *, reference: str, note: str = "") -> LedgerEntry:
        if amount <= 0:
            raise BillingError("Refund amount must be positive.", field="amount")
        locked = self._lock()
        if locked.balance_usd < amount:
            raise BillingError("Insufficient credits for refund.", field="amount")
        return self._post(delta=-amount, kind=LedgerKind.REFUND, reference=reference, note=note)

    @transaction.atomic
    def debit(self, amount: Decimal, *, reason: str, reference: str) -> LedgerEntry:
        if amount <= 0:
            raise BillingError("Debit amount must be positive.", field="amount")
        if not reason.strip():
            raise BillingError("Debit reason must be non-empty.", field="reason")
        locked = self._lock()
        if locked.balance_usd < amount:
            raise BillingError("Insufficient credits.", field="amount")
        return self._post(
            delta=-amount, kind=LedgerKind.RUN_DEBIT, reference=reference, note=reason
        )

    @transaction.atomic
    def post_adjustment(self, delta_usd: Decimal, *, note: str, reference: str) -> LedgerEntry:
        if not note.strip():
            raise BillingError("Adjustments require a non-empty note.", field="note")
        if delta_usd == 0:
            raise BillingError("Adjustment delta must be non-zero.", field="delta_usd")
        locked = self._lock()
        if locked.balance_usd + delta_usd < 0:
            raise BillingError("Adjustment would drive balance negative.", field="delta_usd")
        return self._post(
            delta=delta_usd, kind=LedgerKind.ADJUSTMENT, reference=reference, note=note
        )

    def _lock(self) -> CreditWallet:
        return type(self).objects.select_for_update().get(pk=self.pk)

    def _active_hold_total(self) -> Decimal:
        from apps.billing.models.hold import HoldStatus  # noqa: PLC0415

        fmt = BillingFormat()
        total = self.holds.filter(status=HoldStatus.ACTIVE).aggregate(
            total=Coalesce(
                Sum("amount_reserved_usd"),
                Decimal("0"),
                output_field=models.DecimalField(
                    max_digits=fmt.max_digits,
                    decimal_places=fmt.decimal_places,
                ),
            )
        )["total"]
        return Decimal(total)

    def _post(self, *, delta: Decimal, kind: str, reference: str, note: str) -> LedgerEntry:
        entry = LedgerEntry.objects.create(
            wallet=self,
            delta_usd=delta,
            currency=self.currency,
            kind=kind,
            reference=reference,
            note=note,
        )
        self._sync_after_post(mark_topup=(kind == LedgerKind.TOPUP))
        record_event(
            f"wallet_{_event_suffix(kind)}",
            distinct_id=str(self.workspace_id),
            properties=self._event_properties(kind, delta, reference),
        )
        return entry

    def _event_properties(self, kind: str, delta: Decimal, reference: str) -> dict[str, str]:
        return {
            "kind": kind,
            "delta_usd": str(delta),
            "currency": self.currency,
            "reference": reference,
        }

    def _sync_after_post(self, *, mark_topup: bool) -> None:
        if mark_topup:
            type(self).objects.filter(pk=self.pk).update(last_topup_at=timezone.now())
        self.refresh_from_db(fields=("balance_usd", "last_topup_at"))
