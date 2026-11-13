from __future__ import annotations

from decimal import Decimal

import pytest
from django.db import IntegrityError
from django.utils import timezone

from apps.billing.factories import BillingHoldFactory, CreditWalletFactory
from apps.billing.models import BillingHold, HoldStatus
from apps.core.exceptions import BillingError, Conflict
from apps.runs.factories import RunFactory

pytestmark = pytest.mark.django_db


def _funded_wallet(balance: Decimal = Decimal("100.00")):
    wallet = CreditWalletFactory()
    wallet.record_dodo_credit_grant(balance, dodo_payment_id="seed-fund")
    return wallet


class TestBillingHoldCreation:
    def test_create_active_hold(self):
        wallet = _funded_wallet()
        run = RunFactory(workspace=wallet.workspace)
        hold = BillingHold.objects.create(
            run=run,
            wallet=wallet,
            amount_reserved_usd=Decimal("25.00"),
            expires_at=timezone.now() + timezone.timedelta(hours=1),
        )
        assert hold.status == HoldStatus.ACTIVE
        assert hold.amount_consumed_usd == Decimal("0")
        assert hold.settled_at is None

    def test_one_hold_per_run(self):
        wallet = _funded_wallet()
        run = RunFactory(workspace=wallet.workspace)
        BillingHold.objects.create(
            run=run,
            wallet=wallet,
            amount_reserved_usd=Decimal("10.00"),
            expires_at=timezone.now() + timezone.timedelta(hours=1),
        )
        with pytest.raises(IntegrityError):
            BillingHold.objects.create(
                run=run,
                wallet=wallet,
                amount_reserved_usd=Decimal("5.00"),
                expires_at=timezone.now() + timezone.timedelta(hours=1),
            )

    def test_create_active_hold_reduces_available_balance(self):
        wallet = _funded_wallet(Decimal("50.00"))
        run = RunFactory(workspace=wallet.workspace)
        BillingHold.objects.create(
            run=run,
            wallet=wallet,
            amount_reserved_usd=Decimal("30.00"),
            expires_at=timezone.now() + timezone.timedelta(hours=1),
        )
        wallet.refresh_from_db()
        assert wallet.available() == Decimal("20.00")

    def test_create_active_hold_rejects_over_reservation(self):
        wallet = _funded_wallet(Decimal("50.00"))
        BillingHold.objects.create(
            run=RunFactory(workspace=wallet.workspace),
            wallet=wallet,
            amount_reserved_usd=Decimal("30.00"),
            expires_at=timezone.now() + timezone.timedelta(hours=1),
        )
        with pytest.raises(BillingError, match="Insufficient available credits"):
            BillingHold.objects.create(
                run=RunFactory(workspace=wallet.workspace),
                wallet=wallet,
                amount_reserved_usd=Decimal("25.00"),
                expires_at=timezone.now() + timezone.timedelta(hours=1),
            )

    def test_create_active_hold_rejects_cross_workspace_wallet(self):
        wallet = _funded_wallet(Decimal("50.00"))
        run = RunFactory()
        with pytest.raises(BillingError, match="run workspace"):
            BillingHold.objects.create(
                run=run,
                wallet=wallet,
                amount_reserved_usd=Decimal("10.00"),
                expires_at=timezone.now() + timezone.timedelta(hours=1),
            )


class TestSettle:
    def test_settle_debits_wallet(self):
        wallet = _funded_wallet(Decimal("50.00"))
        run = RunFactory(workspace=wallet.workspace)
        hold = BillingHold.objects.create(
            run=run,
            wallet=wallet,
            amount_reserved_usd=Decimal("30.00"),
            expires_at=timezone.now() + timezone.timedelta(hours=1),
        )
        hold.settle(Decimal("20.00"))
        assert hold.status == HoldStatus.SETTLED
        assert hold.amount_consumed_usd == Decimal("20.00")
        assert hold.settled_at is not None
        assert hold.history.filter(status=HoldStatus.SETTLED).exists()
        wallet.refresh_from_db()
        assert wallet.balance_usd == Decimal("30.00")

    def test_settle_zero_cost(self):
        wallet = _funded_wallet(Decimal("50.00"))
        run = RunFactory(workspace=wallet.workspace)
        hold = BillingHold.objects.create(
            run=run,
            wallet=wallet,
            amount_reserved_usd=Decimal("10.00"),
            expires_at=timezone.now() + timezone.timedelta(hours=1),
        )
        hold.settle(Decimal("0"))
        assert hold.status == HoldStatus.SETTLED
        assert hold.amount_consumed_usd == Decimal("0")
        wallet.refresh_from_db()
        assert wallet.balance_usd == Decimal("50.00")

    def test_settle_full_reserved_amount(self):
        wallet = _funded_wallet(Decimal("50.00"))
        run = RunFactory(workspace=wallet.workspace)
        hold = BillingHold.objects.create(
            run=run,
            wallet=wallet,
            amount_reserved_usd=Decimal("50.00"),
            expires_at=timezone.now() + timezone.timedelta(hours=1),
        )
        hold.settle(Decimal("50.00"))
        assert hold.status == HoldStatus.SETTLED
        wallet.refresh_from_db()
        assert wallet.balance_usd == Decimal("0")

    def test_settle_rejects_negative_cost(self):
        wallet = _funded_wallet()
        run = RunFactory(workspace=wallet.workspace)
        hold = BillingHold.objects.create(
            run=run,
            wallet=wallet,
            amount_reserved_usd=Decimal("10.00"),
            expires_at=timezone.now() + timezone.timedelta(hours=1),
        )
        with pytest.raises(BillingError, match="negative"):
            hold.settle(Decimal("-1.00"))

    def test_settle_rejects_cost_exceeding_reserved(self):
        wallet = _funded_wallet()
        run = RunFactory(workspace=wallet.workspace)
        hold = BillingHold.objects.create(
            run=run,
            wallet=wallet,
            amount_reserved_usd=Decimal("10.00"),
            expires_at=timezone.now() + timezone.timedelta(hours=1),
        )
        with pytest.raises(BillingError, match="exceeds"):
            hold.settle(Decimal("11.00"))

    def test_double_settle_rejected(self):
        wallet = _funded_wallet(Decimal("50.00"))
        run = RunFactory(workspace=wallet.workspace)
        hold = BillingHold.objects.create(
            run=run,
            wallet=wallet,
            amount_reserved_usd=Decimal("20.00"),
            expires_at=timezone.now() + timezone.timedelta(hours=1),
        )
        hold.settle(Decimal("10.00"))
        with pytest.raises(Conflict, match="settled"):
            hold.settle(Decimal("5.00"))


class TestRelease:
    def test_release_frees_hold(self):
        wallet = _funded_wallet(Decimal("50.00"))
        run = RunFactory(workspace=wallet.workspace)
        hold = BillingHold.objects.create(
            run=run,
            wallet=wallet,
            amount_reserved_usd=Decimal("30.00"),
            expires_at=timezone.now() + timezone.timedelta(hours=1),
        )
        hold.release()
        assert hold.status == HoldStatus.RELEASED
        assert hold.history.filter(status=HoldStatus.RELEASED).exists()
        wallet.refresh_from_db()
        assert wallet.balance_usd == Decimal("50.00")
        assert wallet.available() == Decimal("50.00")

    def test_release_on_settled_rejected(self):
        wallet = _funded_wallet(Decimal("50.00"))
        run = RunFactory(workspace=wallet.workspace)
        hold = BillingHold.objects.create(
            run=run,
            wallet=wallet,
            amount_reserved_usd=Decimal("10.00"),
            expires_at=timezone.now() + timezone.timedelta(hours=1),
        )
        hold.settle(Decimal("5.00"))
        with pytest.raises(Conflict, match="settled"):
            hold.release()


class TestExpire:
    def test_expire_sets_status(self):
        wallet = _funded_wallet()
        run = RunFactory(workspace=wallet.workspace)
        hold = BillingHold.objects.create(
            run=run,
            wallet=wallet,
            amount_reserved_usd=Decimal("10.00"),
            expires_at=timezone.now() - timezone.timedelta(minutes=5),
        )
        hold.expire()
        assert hold.status == HoldStatus.EXPIRED
        assert hold.history.filter(status=HoldStatus.EXPIRED).exists()

    def test_expire_on_released_rejected(self):
        wallet = _funded_wallet()
        run = RunFactory(workspace=wallet.workspace)
        hold = BillingHold.objects.create(
            run=run,
            wallet=wallet,
            amount_reserved_usd=Decimal("10.00"),
            expires_at=timezone.now() + timezone.timedelta(hours=1),
        )
        hold.release()
        with pytest.raises(Conflict, match="released"):
            hold.expire()


class TestIsExpired:
    def test_active_hold_past_expiry(self):
        wallet = _funded_wallet()
        run = RunFactory(workspace=wallet.workspace)
        hold = BillingHold.objects.create(
            run=run,
            wallet=wallet,
            amount_reserved_usd=Decimal("10.00"),
            expires_at=timezone.now() - timezone.timedelta(minutes=1),
        )
        assert hold.is_expired() is True

    def test_active_hold_before_expiry(self):
        wallet = _funded_wallet()
        run = RunFactory(workspace=wallet.workspace)
        hold = BillingHold.objects.create(
            run=run,
            wallet=wallet,
            amount_reserved_usd=Decimal("10.00"),
            expires_at=timezone.now() + timezone.timedelta(hours=1),
        )
        assert hold.is_expired() is False

    def test_settled_hold_not_expired(self):
        wallet = _funded_wallet()
        run = RunFactory(workspace=wallet.workspace)
        hold = BillingHold.objects.create(
            run=run,
            wallet=wallet,
            amount_reserved_usd=Decimal("10.00"),
            expires_at=timezone.now() - timezone.timedelta(minutes=1),
        )
        hold.settle(Decimal("5.00"))
        assert hold.is_expired() is False


class TestFactory:
    def test_active_trait(self):
        hold = BillingHoldFactory()
        assert hold.status == HoldStatus.ACTIVE
        assert hold.pk is not None

    def test_settled_trait(self):
        hold = BillingHoldFactory(settled=True)
        assert hold.status == HoldStatus.SETTLED
        assert hold.amount_consumed_usd == Decimal("5.00")
        assert hold.settled_at is not None

    def test_released_trait(self):
        hold = BillingHoldFactory(released=True)
        assert hold.status == HoldStatus.RELEASED

    def test_expired_trait(self):
        hold = BillingHoldFactory(expired=True)
        assert hold.status == HoldStatus.EXPIRED
