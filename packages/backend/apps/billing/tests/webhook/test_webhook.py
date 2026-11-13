from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from apps.billing.factories import CreditWalletFactory, TopupFactory
from apps.billing.models import LedgerKind, Topup, TopupStatus, WebhookDelivery
from apps.billing.tests.webhook.helpers import make_payment_event, process_test_event

pytestmark = pytest.mark.django_db


class TestProcessEvent:
    def test_payment_succeeded_credits_wallet(self) -> None:
        wallet = CreditWalletFactory()
        topup = TopupFactory(wallet=wallet, amount_usd=Decimal("50.00"))
        event = make_payment_event(
            payment_id="pay_abc",
            metadata={"reference": str(topup.pk)},
        )
        result = process_test_event(event, '{"raw": "body"}')

        assert result is True
        topup.refresh_from_db()
        assert topup.status == TopupStatus.SUCCEEDED
        assert topup.dodo_payment_id == "pay_abc"
        wallet.refresh_from_db()
        assert wallet.balance_usd == Decimal("50.0000")

    def test_payment_succeeded_writes_delivery(self) -> None:
        wallet = CreditWalletFactory()
        topup = TopupFactory(wallet=wallet, amount_usd=Decimal("20.00"))
        event = make_payment_event(metadata={"reference": str(topup.pk)})
        process_test_event(event, "{}", event_id="whmsg_delivery")

        delivery = WebhookDelivery.objects.get(provider="dodo")
        assert delivery.event_id == "whmsg_delivery"
        assert delivery.processed_at is not None

    def test_payment_succeeded_marks_delivery_with_history(self) -> None:
        wallet = CreditWalletFactory()
        topup = TopupFactory(wallet=wallet, amount_usd=Decimal("20.00"))
        event = make_payment_event(metadata={"reference": str(topup.pk)})
        process_test_event(event, "{}")

        delivery = WebhookDelivery.objects.get(provider="dodo")
        assert delivery.history.count() == 2

    def test_payment_succeeded_writes_ledger_entry(self) -> None:
        wallet = CreditWalletFactory()
        topup = TopupFactory(wallet=wallet, amount_usd=Decimal("100.00"))
        event = make_payment_event(
            payment_id="pay_ledger",
            metadata={"reference": str(topup.pk)},
        )
        process_test_event(event, "{}")

        entry = wallet.entries.first()
        assert entry is not None
        assert entry.kind == LedgerKind.TOPUP
        assert entry.delta_usd == Decimal("100.0000")
        assert entry.reference == "pay_ledger"

    def test_payment_failed_marks_topup(self) -> None:
        wallet = CreditWalletFactory()
        topup = TopupFactory(wallet=wallet, amount_usd=Decimal("20.00"))
        event = make_payment_event(
            event_type="payment.failed",
            metadata={"reference": str(topup.pk)},
        )
        result = process_test_event(event, "{}")

        assert result is True
        topup.refresh_from_db()
        assert topup.status == TopupStatus.FAILED
        wallet.refresh_from_db()
        assert wallet.balance_usd == Decimal("0")

    def test_replay_is_idempotent(self) -> None:
        wallet = CreditWalletFactory()
        topup = TopupFactory(wallet=wallet, amount_usd=Decimal("50.00"))
        event = make_payment_event(
            payment_id="pay_dup",
            metadata={"reference": str(topup.pk)},
        )
        process_test_event(event, "{}", event_id="whmsg_dup")
        result = process_test_event(event, "{}", event_id="whmsg_dup")

        assert result is False
        wallet.refresh_from_db()
        assert wallet.balance_usd == Decimal("50.0000")

    def test_already_settled_topup_is_skipped(self) -> None:
        wallet = CreditWalletFactory()
        topup = TopupFactory(
            wallet=wallet,
            amount_usd=Decimal("20.00"),
            status=TopupStatus.SUCCEEDED,
            dodo_payment_id="pay_old",
        )
        event = make_payment_event(
            payment_id="pay_retry",
            metadata={"reference": str(topup.pk)},
        )
        result = process_test_event(event, "{}")

        assert result is True
        topup.refresh_from_db()
        assert topup.dodo_payment_id == "pay_old"

    def test_missing_reference_raises(self) -> None:
        event = make_payment_event(metadata={})
        with pytest.raises(ValueError, match="missing 'reference'"):
            process_test_event(event, "{}")

    def test_unknown_event_type_is_ignored(self) -> None:
        event = SimpleNamespace(
            type="subscription.cancelled",
            business_id="biz_1",
            data=SimpleNamespace(subscription_id="sub_1"),
        )
        result = process_test_event(event, "{}")
        assert result is False
        assert WebhookDelivery.objects.count() == 0

    def test_refund_succeeded_credits_wallet_and_marks_refunded(self) -> None:
        wallet = CreditWalletFactory()
        wallet.record_dodo_credit_grant(Decimal("50.00"), dodo_payment_id="seed")
        topup = TopupFactory(
            wallet=wallet,
            amount_usd=Decimal("50.00"),
            status=TopupStatus.REFUND_REQUESTED,
            dodo_payment_id="pay_ref_ok",
            refund_reason="customer request",
        )
        event = SimpleNamespace(
            type="refund.succeeded",
            business_id="biz_1",
            data=SimpleNamespace(refund_id="ref_456", payment_id="pay_ref_ok"),
        )
        result = process_test_event(event, "{}", event_id="whmsg_refund")

        assert result is True
        topup.refresh_from_db()
        assert topup.status == TopupStatus.REFUNDED
        wallet.refresh_from_db()
        assert wallet.balance_usd == Decimal("0")
        entry = wallet.entries.filter(kind=LedgerKind.REFUND).first()
        assert entry is not None
        assert entry.delta_usd == Decimal("-50.0000")
        assert entry.reference == str(topup.pk)
        assert entry.note == "customer request"

    def test_refund_succeeded_records_delivery(self) -> None:
        wallet = CreditWalletFactory()
        wallet.record_dodo_credit_grant(Decimal("20.00"), dodo_payment_id="seed")
        TopupFactory(
            wallet=wallet,
            amount_usd=Decimal("20.00"),
            status=TopupStatus.REFUND_REQUESTED,
            dodo_payment_id="pay_ref_del",
            refund_reason="test",
        )
        event = SimpleNamespace(
            type="refund.succeeded",
            business_id="biz_1",
            data=SimpleNamespace(refund_id="ref_del", payment_id="pay_ref_del"),
        )
        result = process_test_event(event, "{}", event_id="whmsg_refund_del")

        assert result is True
        delivery = WebhookDelivery.objects.get(provider="dodo")
        assert delivery.event_id == "whmsg_refund_del"
        assert delivery.processed_at is not None

    def test_refund_succeeded_unknown_payment_does_not_crash(self) -> None:
        event = SimpleNamespace(
            type="refund.succeeded",
            business_id="biz_1",
            data=SimpleNamespace(refund_id="ref_unk", payment_id="pay_nonexistent"),
        )
        result = process_test_event(event, "{}", event_id="whmsg_refund_unk")
        assert result is True

    def test_refund_succeeded_already_refunded_is_idempotent(self) -> None:
        wallet = CreditWalletFactory()
        wallet.record_dodo_credit_grant(Decimal("50.00"), dodo_payment_id="seed")
        TopupFactory(
            wallet=wallet,
            amount_usd=Decimal("50.00"),
            status=TopupStatus.REFUNDED,
            dodo_payment_id="pay_ref_done",
            refund_reason="already done",
        )
        event = SimpleNamespace(
            type="refund.succeeded",
            business_id="biz_1",
            data=SimpleNamespace(refund_id="ref_done", payment_id="pay_ref_done"),
        )
        result = process_test_event(event, "{}", event_id="whmsg_refund_done")

        assert result is True
        wallet.refresh_from_db()
        assert wallet.balance_usd == Decimal("50.0000")
        assert not wallet.entries.filter(kind=LedgerKind.REFUND).exists()

    def test_failure_rolls_back_delivery(self) -> None:
        event = make_payment_event(metadata={"reference": "99999999"})
        with pytest.raises(Topup.DoesNotExist):
            process_test_event(event, "{}")
        assert WebhookDelivery.objects.count() == 0
