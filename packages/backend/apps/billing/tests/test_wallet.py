from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError

from apps.billing.factories import CreditWalletFactory
from apps.billing.models import CreditWallet, LedgerKind
from apps.core.exceptions import BillingError
from apps.workspaces.factories import WorkspaceFactory
from integrations import dodo_payments as dp

pytestmark = pytest.mark.django_db


def _seed(wallet: CreditWallet, amount: str = "50.00", ref: str = "seed") -> None:
    wallet.record_dodo_credit_grant(Decimal(amount), dodo_payment_id=ref)


def test_debit_decreases_balance_and_records_reason() -> None:
    wallet = CreditWalletFactory()
    _seed(wallet)

    entry = wallet.debit(Decimal("12.34"), reason="run_complete", reference="run_42")

    wallet.refresh_from_db()
    assert wallet.balance_usd == Decimal("37.6600")
    assert entry.kind == LedgerKind.RUN_DEBIT
    assert entry.delta_usd == Decimal("-12.3400")
    assert entry.note == "run_complete"
    assert entry.reference == "run_42"


def test_debit_rejects_when_insufficient_balance() -> None:
    wallet = CreditWalletFactory()
    _seed(wallet, "20.00")

    with pytest.raises(BillingError, match="Insufficient credits"):
        wallet.debit(Decimal("21.00"), reason="run_complete", reference="run_x")

    wallet.refresh_from_db()
    assert wallet.balance_usd == Decimal("20.0000")
    assert not wallet.entries.filter(kind=LedgerKind.RUN_DEBIT).exists()


def test_debit_rejects_non_positive_amount() -> None:
    wallet = CreditWalletFactory()
    _seed(wallet, "20.00")
    with pytest.raises(BillingError, match="positive"):
        wallet.debit(Decimal("0"), reason="r", reference="x")


def test_debit_rejects_blank_reason() -> None:
    wallet = CreditWalletFactory()
    _seed(wallet, "20.00")
    with pytest.raises(BillingError, match="reason"):
        wallet.debit(Decimal("1.00"), reason=" ", reference="x")


def test_post_adjustment_records_signed_delta_and_note() -> None:
    wallet = CreditWalletFactory()
    _seed(wallet, "20.00")

    wallet.post_adjustment(
        Decimal("-3.00"), note="Goodwill clawback per ticket #88", reference="admin_5"
    )

    wallet.refresh_from_db()
    assert wallet.balance_usd == Decimal("17.0000")
    entry = wallet.entries.get(kind=LedgerKind.ADJUSTMENT)
    assert entry.delta_usd == Decimal("-3.0000")
    assert "Goodwill" in entry.note


def test_post_adjustment_requires_non_empty_note() -> None:
    wallet = CreditWalletFactory()
    with pytest.raises(BillingError, match="non-empty note"):
        wallet.post_adjustment(Decimal("5.00"), note="   ", reference="x")


def test_post_adjustment_rejects_zero_delta() -> None:
    wallet = CreditWalletFactory()
    with pytest.raises(BillingError, match="non-zero"):
        wallet.post_adjustment(Decimal("0"), note="ok", reference="x")


def test_post_adjustment_rejects_drive_negative() -> None:
    wallet = CreditWalletFactory()
    _seed(wallet, "20.00")
    with pytest.raises(BillingError, match="negative"):
        wallet.post_adjustment(Decimal("-21.00"), note="oops", reference="admin")


def test_available_returns_decimal_balance() -> None:
    wallet = CreditWalletFactory()
    _seed(wallet)
    assert wallet.available() == Decimal("50.0000")
    assert isinstance(wallet.available(), Decimal)


def test_workspace_reverse_accessor_resolves_to_wallet() -> None:
    workspace = WorkspaceFactory()
    wallet = CreditWalletFactory(workspace=workspace)
    assert workspace.wallet == wallet
    assert workspace.wallet.available() == Decimal("0.0000")


def test_record_dodo_credit_grant_adds_balance_and_ledger() -> None:
    wallet = CreditWalletFactory()

    entry = wallet.record_dodo_credit_grant(Decimal("50.00"), dodo_payment_id="pay_abc123")

    wallet.refresh_from_db()
    assert wallet.balance_usd == Decimal("50.0000")
    assert wallet.last_topup_at is not None
    assert entry.kind == LedgerKind.TOPUP
    assert entry.delta_usd == Decimal("50.0000")
    assert entry.reference == "pay_abc123"


def test_record_dodo_credit_grant_accumulates() -> None:
    wallet = CreditWalletFactory()
    wallet.record_dodo_credit_grant(Decimal("20.00"), dodo_payment_id="pay_1")
    wallet.record_dodo_credit_grant(Decimal("50.00"), dodo_payment_id="pay_2")

    wallet.refresh_from_db()
    assert wallet.balance_usd == Decimal("70.0000")
    assert wallet.entries.count() == 2


def test_record_dodo_credit_grant_rejects_non_positive() -> None:
    wallet = CreditWalletFactory()
    with pytest.raises(BillingError, match="positive"):
        wallet.record_dodo_credit_grant(Decimal("0"), dodo_payment_id="pay_x")
    with pytest.raises(BillingError, match="positive"):
        wallet.record_dodo_credit_grant(Decimal("-5"), dodo_payment_id="pay_x")


def test_record_dodo_credit_grant_rejects_empty_payment_id() -> None:
    wallet = CreditWalletFactory()
    with pytest.raises(BillingError, match="non-empty"):
        wallet.record_dodo_credit_grant(Decimal("20.00"), dodo_payment_id="")
    with pytest.raises(BillingError, match="non-empty"):
        wallet.record_dodo_credit_grant(Decimal("20.00"), dodo_payment_id="  ")


def test_record_dodo_credit_grant_accepts_any_positive_amount() -> None:
    wallet = CreditWalletFactory()
    entry = wallet.record_dodo_credit_grant(Decimal("33.33"), dodo_payment_id="pay_odd")
    wallet.refresh_from_db()
    assert wallet.balance_usd == Decimal("33.3300")
    assert entry.delta_usd == Decimal("33.3300")


def test_sync_balance_from_dodo_returns_matching(monkeypatch: pytest.MonkeyPatch) -> None:
    wallet = CreditWalletFactory()
    wallet.record_dodo_credit_grant(Decimal("100.00"), dodo_payment_id="pay_seed")
    wallet.workspace.dodo_customer_id = "cust_1"
    wallet.workspace.save(update_fields=("dodo_customer_id",))

    monkeypatch.setattr(
        dp,
        "retrieve_credit_balance",
        lambda customer_id, entitlement_id: SimpleNamespace(balance=10000),
    )

    local, dodo, matches = wallet.sync_balance_from_dodo()

    assert local == Decimal("100.0000")
    assert dodo == Decimal("100.00")
    assert matches is True


def test_sync_balance_from_dodo_detects_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    wallet = CreditWalletFactory()
    wallet.record_dodo_credit_grant(Decimal("100.00"), dodo_payment_id="pay_seed")
    wallet.workspace.dodo_customer_id = "cust_2"
    wallet.workspace.save(update_fields=("dodo_customer_id",))

    monkeypatch.setattr(
        dp,
        "retrieve_credit_balance",
        lambda customer_id, entitlement_id: SimpleNamespace(balance=9000),
    )

    local, dodo, matches = wallet.sync_balance_from_dodo()

    assert local == Decimal("100.0000")
    assert dodo == Decimal("90.00")
    assert matches is False


def test_sync_balance_from_dodo_raises_without_customer_id() -> None:
    wallet = CreditWalletFactory()
    with pytest.raises(BillingError, match="Dodo customer ID"):
        wallet.sync_balance_from_dodo()


def test_balance_constraint_blocks_direct_negative_writes() -> None:
    wallet = CreditWalletFactory()
    wallet.balance_usd = Decimal("-1.00")
    with pytest.raises(IntegrityError):
        wallet.save(update_fields=("balance_usd", "updated_at"))


def test_workspace_cascade_deletes_wallet_but_protect_blocks_with_ledger() -> None:
    wallet = CreditWalletFactory()
    _seed(wallet, "20.00")
    workspace = wallet.workspace

    with pytest.raises((ProtectedError, IntegrityError)), transaction.atomic():
        workspace.delete()
    assert CreditWallet.objects.filter(pk=wallet.pk).exists()
