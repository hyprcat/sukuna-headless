from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.billing.factories import BillingHoldFactory
from apps.billing.models.hold import HoldStatus
from apps.runs.factories import RunFactory
from apps.runs.tasks.reconcile_holds import reconcile_billing_holds

pytestmark = pytest.mark.django_db(transaction=True)


class TestReconcileBillingHolds:
    def test_expired_hold_settled_when_cost_present(self):
        now = timezone.now()
        run = RunFactory(running=True, total_cost_usd=Decimal("3.50"), last_callback_at=None)
        hold = BillingHoldFactory(
            run=run,
            wallet__workspace=run.workspace,
            expires_at=now - timedelta(hours=1),
        )

        count = reconcile_billing_holds()

        assert count == 1
        hold.refresh_from_db()
        assert hold.status == HoldStatus.SETTLED
        assert hold.amount_consumed_usd == Decimal("3.50")

    def test_expired_hold_released_when_no_cost(self):
        now = timezone.now()
        run = RunFactory(running=True, total_cost_usd=Decimal("0"), last_callback_at=None)
        hold = BillingHoldFactory(
            run=run,
            wallet__workspace=run.workspace,
            expires_at=now - timedelta(hours=1),
        )

        count = reconcile_billing_holds()

        assert count == 1
        hold.refresh_from_db()
        assert hold.status == HoldStatus.RELEASED

    def test_recent_activity_skipped(self):
        now = timezone.now()
        expires = now - timedelta(hours=1)
        run = RunFactory(
            running=True,
            total_cost_usd=Decimal("1.00"),
            last_callback_at=now,
        )
        hold = BillingHoldFactory(
            run=run,
            wallet__workspace=run.workspace,
            expires_at=expires,
        )

        count = reconcile_billing_holds()

        assert count == 0
        hold.refresh_from_db()
        assert hold.status == HoldStatus.ACTIVE

    def test_future_expiry_untouched(self):
        run = RunFactory(running=True, total_cost_usd=Decimal("1.00"), last_callback_at=None)
        hold = BillingHoldFactory(
            run=run,
            wallet__workspace=run.workspace,
            expires_at=timezone.now() + timedelta(hours=1),
        )

        count = reconcile_billing_holds()

        assert count == 0
        hold.refresh_from_db()
        assert hold.status == HoldStatus.ACTIVE

    def test_already_settled_hold_skipped(self):
        now = timezone.now()
        run = RunFactory(running=True, total_cost_usd=Decimal("2.00"), last_callback_at=None)
        hold = BillingHoldFactory(
            settled=True,
            run=run,
            wallet__workspace=run.workspace,
            expires_at=now - timedelta(hours=1),
        )

        count = reconcile_billing_holds()

        assert count == 0
        hold.refresh_from_db()
        assert hold.status == HoldStatus.SETTLED

    def test_cost_capped_at_reserved_amount(self):
        now = timezone.now()
        run = RunFactory(running=True, total_cost_usd=Decimal("50.00"), last_callback_at=None)
        hold = BillingHoldFactory(
            run=run,
            wallet__workspace=run.workspace,
            amount_reserved_usd=Decimal("10.00"),
            expires_at=now - timedelta(hours=1),
        )

        reconcile_billing_holds()

        hold.refresh_from_db()
        assert hold.status == HoldStatus.SETTLED
        assert hold.amount_consumed_usd == Decimal("10.00")
