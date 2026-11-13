from __future__ import annotations

from decimal import Decimal

import pytest

from apps.billing.factories import CreditWalletFactory, TopupFactory
from apps.billing.models import TopupStatus, WebhookDelivery
from apps.billing.tests.webhook.helpers import make_payment_event, process_test_event

pytestmark = pytest.mark.django_db


class TestWebhookOutOfOrder:
    def test_failed_after_succeeded_does_not_revert(self) -> None:
        wallet = CreditWalletFactory()
        topup = TopupFactory(wallet=wallet, amount_usd=Decimal("50.00"))
        succeeded = make_payment_event(payment_id="pay_race", metadata={"reference": str(topup.pk)})
        process_test_event(succeeded, '{"seq": 1}')
        topup.refresh_from_db()
        assert topup.status == TopupStatus.SUCCEEDED
        wallet.refresh_from_db()

        failed = make_payment_event(
            payment_id="pay_race",
            event_type="payment.failed",
            metadata={"reference": str(topup.pk)},
        )
        process_test_event(failed, '{"seq": 2}')
        topup.refresh_from_db()
        assert topup.status == TopupStatus.SUCCEEDED
        assert wallet.balance_usd == Decimal("50.0000")

    def test_succeeded_after_failed_does_not_credit(self) -> None:
        wallet = CreditWalletFactory()
        topup = TopupFactory(wallet=wallet, amount_usd=Decimal("20.00"))
        failed = make_payment_event(
            payment_id="pay_late",
            event_type="payment.failed",
            metadata={"reference": str(topup.pk)},
        )
        process_test_event(failed, '{"seq": 1}')
        topup.refresh_from_db()
        assert topup.status == TopupStatus.FAILED
        wallet.refresh_from_db()
        succeeded = make_payment_event(payment_id="pay_late", metadata={"reference": str(topup.pk)})
        process_test_event(succeeded, '{"seq": 2}')
        topup.refresh_from_db()
        assert topup.status == TopupStatus.FAILED
        assert wallet.balance_usd == Decimal("0")

    def test_stale_failed_event_with_latest_succeeded_status_credits(self) -> None:
        wallet = CreditWalletFactory()
        topup = TopupFactory(wallet=wallet, amount_usd=Decimal("50.00"))
        event = make_payment_event(
            payment_id="pay_latest_success",
            event_type="payment.failed",
            metadata={"reference": str(topup.pk)},
            status="succeeded",
        )

        process_test_event(event, "{}")

        topup.refresh_from_db()
        assert topup.status == TopupStatus.SUCCEEDED
        wallet.refresh_from_db()
        assert wallet.balance_usd == Decimal("50.0000")

    def test_stale_succeeded_event_with_latest_failed_status_does_not_credit(self) -> None:
        wallet = CreditWalletFactory()
        topup = TopupFactory(wallet=wallet, amount_usd=Decimal("20.00"))
        event = make_payment_event(
            payment_id="pay_latest_failed",
            metadata={"reference": str(topup.pk)},
            status="failed",
        )

        process_test_event(event, "{}")

        topup.refresh_from_db()
        assert topup.status == TopupStatus.FAILED
        wallet.refresh_from_db()
        assert wallet.balance_usd == Decimal("0")

    def test_processing_event_with_latest_succeeded_status_credits(self) -> None:
        wallet = CreditWalletFactory()
        topup = TopupFactory(wallet=wallet, amount_usd=Decimal("100.00"))
        event = make_payment_event(
            payment_id="pay_processing_latest",
            event_type="payment.processing",
            metadata={"reference": str(topup.pk)},
            status="succeeded",
        )

        process_test_event(event, "{}")

        topup.refresh_from_db()
        assert topup.status == TopupStatus.SUCCEEDED
        wallet.refresh_from_db()
        assert wallet.balance_usd == Decimal("100.0000")

    def test_duplicate_succeeded_does_not_double_credit(self) -> None:
        wallet = CreditWalletFactory()
        topup = TopupFactory(wallet=wallet, amount_usd=Decimal("100.00"))

        event = make_payment_event(payment_id="pay_dup_succ", metadata={"reference": str(topup.pk)})
        assert process_test_event(event, '{"attempt": 1}', event_id="whmsg_same") is True
        assert process_test_event(event, '{"attempt": 2}', event_id="whmsg_same") is False

        wallet.refresh_from_db()
        assert wallet.balance_usd == Decimal("100.0000")
        assert wallet.entries.count() == 1

    def test_same_payment_id_new_webhook_id_records_delivery_once_more(self) -> None:
        wallet = CreditWalletFactory()
        topup = TopupFactory(wallet=wallet, amount_usd=Decimal("50.00"))
        event = make_payment_event(payment_id="pay_same", metadata={"reference": str(topup.pk)})
        process_test_event(event, "{}", event_id="whmsg_first")

        result = process_test_event(event, "{}", event_id="whmsg_second")

        assert result is True
        assert WebhookDelivery.objects.filter(provider="dodo").count() == 2
        assert wallet.entries.count() == 1

    def test_different_payment_ids_same_topup_second_is_noop(self) -> None:
        wallet = CreditWalletFactory()
        topup = TopupFactory(wallet=wallet, amount_usd=Decimal("20.00"))

        event1 = make_payment_event(payment_id="pay_first", metadata={"reference": str(topup.pk)})
        process_test_event(event1, "{}")

        event2 = make_payment_event(payment_id="pay_second", metadata={"reference": str(topup.pk)})
        process_test_event(event2, "{}")

        topup.refresh_from_db()
        assert topup.dodo_payment_id == "pay_first"
        wallet.refresh_from_db()
        assert wallet.balance_usd == Decimal("20.0000")

    def test_dedup_same_event_id_different_providers(self) -> None:
        wallet = CreditWalletFactory()
        topup = TopupFactory(wallet=wallet, amount_usd=Decimal("20.00"))

        event = make_payment_event(payment_id="pay_multi", metadata={"reference": str(topup.pk)})
        process_test_event(event, "{}")

        dodo_delivery = WebhookDelivery.objects.get(provider="dodo")
        sandbox_delivery = WebhookDelivery.objects.create(
            provider="sandbox", event_id=dodo_delivery.event_id
        )
        assert sandbox_delivery.pk != dodo_delivery.pk
