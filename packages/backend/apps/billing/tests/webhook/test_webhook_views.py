from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.test import RequestFactory

from apps.billing.factories import CreditWalletFactory, TopupFactory, WebhookDeliveryFactory
from apps.billing.services.webhooks import dodo_webhook_view
from apps.billing.tests.webhook.helpers import make_payment_event, process_test_event

pytestmark = pytest.mark.django_db

_PATCH_VERIFY = "apps.billing.services.webhooks.dodo_payments.verify_webhook"


class TestCreditBalanceLow:
    def test_emits_event_for_known_workspace(self) -> None:
        wallet = CreditWalletFactory()
        workspace = wallet.workspace
        workspace.dodo_customer_id = "cust_low"
        workspace.save(update_fields=("dodo_customer_id", "updated_at"))

        event = SimpleNamespace(
            type="credit.balance_low",
            business_id="biz_1",
            data=SimpleNamespace(
                customer_id="cust_low",
                available_balance="500",
                threshold_percent=20,
            ),
        )
        with patch("apps.billing.services.webhooks.record_event") as mock_event:
            result = process_test_event(event, "{}", event_id="whmsg_credit_low")

        assert result is True
        mock_event.assert_any_call(
            "credit_balance_low",
            distinct_id=str(workspace.owner_id),
            properties={
                "workspace_id": workspace.pk,
                "available": "500",
                "threshold": "20",
            },
        )

    def test_unknown_customer_logs_warning(self) -> None:
        event = SimpleNamespace(
            type="credit.balance_low",
            business_id="biz_1",
            data=SimpleNamespace(
                customer_id="cust_unknown",
                available_balance="0",
                threshold_percent=20,
            ),
        )
        with patch("apps.billing.services.webhooks.record_event") as mock_event:
            result = process_test_event(event, "{}", event_id="whmsg_credit_unknown")

        assert result is True
        credit_calls = [c for c in mock_event.call_args_list if c.args[0] == "credit_balance_low"]
        assert credit_calls == []

    def test_missing_customer_id_logs_warning(self) -> None:
        event = SimpleNamespace(
            type="credit.balance_low",
            business_id="biz_1",
            data=SimpleNamespace(
                available_balance="0",
                threshold_percent=20,
            ),
        )
        with patch("apps.billing.services.webhooks.record_event") as mock_event:
            result = process_test_event(event, "{}", event_id="whmsg_credit_no_cust")

        assert result is True
        credit_calls = [c for c in mock_event.call_args_list if c.args[0] == "credit_balance_low"]
        assert credit_calls == []

    def test_no_balance_mutation(self) -> None:
        wallet = CreditWalletFactory()
        wallet.record_dodo_credit_grant(Decimal("100.00"), dodo_payment_id="seed")
        workspace = wallet.workspace
        workspace.dodo_customer_id = "cust_bal"
        workspace.save(update_fields=("dodo_customer_id", "updated_at"))

        event = SimpleNamespace(
            type="credit.balance_low",
            business_id="biz_1",
            data=SimpleNamespace(
                customer_id="cust_bal",
                available_balance="200",
                threshold_percent=20,
            ),
        )
        with patch("apps.billing.services.webhooks.record_event"):
            process_test_event(event, "{}", event_id="whmsg_credit_no_mut")

        wallet.refresh_from_db()
        assert wallet.balance_usd == Decimal("100.0000")


class TestDodoWebhookView:
    rf = RequestFactory()

    def test_valid_webhook_returns_200(self) -> None:
        wallet = CreditWalletFactory()
        topup = TopupFactory(wallet=wallet, amount_usd=Decimal("20.00"))
        event = make_payment_event(metadata={"reference": str(topup.pk)})
        request = self.rf.post(
            "/webhooks/dodo/",
            data=b"{}",
            content_type="application/json",
            HTTP_WEBHOOK_ID="whmsg_view",
        )
        with patch(_PATCH_VERIFY, return_value=event):
            response = dodo_webhook_view(request)
        assert response.status_code == 200

    def test_invalid_signature_returns_400(self) -> None:
        request = self.rf.post(
            "/webhooks/dodo/",
            data=b"{}",
            content_type="application/json",
        )
        with patch(_PATCH_VERIFY, side_effect=ValueError("bad sig")):
            response = dodo_webhook_view(request)
        assert response.status_code == 400

    def test_missing_webhook_id_returns_400(self) -> None:
        wallet = CreditWalletFactory()
        topup = TopupFactory(wallet=wallet, amount_usd=Decimal("20.00"))
        event = make_payment_event(metadata={"reference": str(topup.pk)})
        request = self.rf.post(
            "/webhooks/dodo/",
            data=b"{}",
            content_type="application/json",
        )
        with patch(_PATCH_VERIFY, return_value=event):
            response = dodo_webhook_view(request)
        assert response.status_code == 400

    def test_replay_returns_200(self) -> None:
        wallet = CreditWalletFactory()
        topup = TopupFactory(wallet=wallet, amount_usd=Decimal("20.00"))
        event = make_payment_event(
            payment_id="pay_dup2",
            metadata={"reference": str(topup.pk)},
        )
        WebhookDeliveryFactory(
            provider="dodo",
            event_id="whmsg_replay",
        )
        request = self.rf.post(
            "/webhooks/dodo/",
            data=b"{}",
            content_type="application/json",
            HTTP_WEBHOOK_ID="whmsg_replay",
        )
        with patch(_PATCH_VERIFY, return_value=event):
            response = dodo_webhook_view(request)
        assert response.status_code == 200
