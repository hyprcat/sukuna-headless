from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

from apps.core.exceptions import BillingError
from integrations import dodo_payments

if TYPE_CHECKING:
    from integrations.tests.conftest import DodoClientStub


# ---------------------------------------------------------------------------
# Checkout / payment link
# ---------------------------------------------------------------------------


def test_create_payment_link_uses_decimal_amount_key(
    monkeypatch: pytest.MonkeyPatch,
    dodo_client: DodoClientStub,
) -> None:
    monkeypatch.setattr(dodo_payments.runtime, "dodo_credit_product_ids", {"20.00": "prod_20"})
    url = dodo_payments.create_payment_link(
        Decimal("20.0000"),
        "USD",
        "topup_1",
        "idem_1",
    )
    assert url == "https://checkout.dodopayments.com/s"
    call = dodo_client.checkout_sessions.calls[0]
    assert call["product_cart"] == [{"product_id": "prod_20", "quantity": 1}]
    assert call["billing_currency"] == "USD"
    assert call["metadata"]["reference"] == "topup_1"
    assert call["metadata"]["idempotency_key"] == "idem_1"
    assert call["extra_headers"] == {"Idempotency-Key": "idem_1"}


def test_create_payment_link_integer_amount_keys(
    monkeypatch: pytest.MonkeyPatch,
    dodo_client: DodoClientStub,
) -> None:
    monkeypatch.setattr(dodo_payments.runtime, "dodo_credit_product_ids", {"50": "prod_50"})
    dodo_payments.create_payment_link(Decimal("50.00"), "USD", "t", "i")
    assert dodo_client.checkout_sessions.calls[0]["product_cart"][0]["product_id"] == "prod_50"


def test_create_payment_link_missing_product(
    monkeypatch: pytest.MonkeyPatch,
    dodo_client: DodoClientStub,
) -> None:
    monkeypatch.setattr(dodo_payments.runtime, "dodo_credit_product_ids", {})
    with pytest.raises(BillingError, match="No Dodo product configured"):
        dodo_payments.create_payment_link(Decimal("20.00"), "USD", "t", "i")
    assert dodo_client.checkout_sessions.calls == []


def test_create_payment_link_sdk_error(
    monkeypatch: pytest.MonkeyPatch,
    dodo_client: DodoClientStub,
) -> None:
    monkeypatch.setattr(dodo_payments.runtime, "dodo_credit_product_ids", {"20.00": "prod_20"})
    dodo_client.checkout_sessions.error = RuntimeError("timeout")
    with pytest.raises(BillingError, match="Dodo Payments request failed") as exc:
        dodo_payments.create_payment_link(Decimal("20.00"), "USD", "t", "i")
    assert isinstance(exc.value.__cause__, RuntimeError)


def test_create_payment_link_missing_url(
    monkeypatch: pytest.MonkeyPatch,
    dodo_client: DodoClientStub,
) -> None:
    monkeypatch.setattr(dodo_payments.runtime, "dodo_credit_product_ids", {"20.00": "prod_20"})
    dodo_client.checkout_sessions.response = SimpleNamespace(checkout_url=None)
    with pytest.raises(BillingError, match="did not return a checkout URL"):
        dodo_payments.create_payment_link(Decimal("20.00"), "USD", "t", "i")


def test_create_payment_link_customer_id(
    monkeypatch: pytest.MonkeyPatch,
    dodo_client: DodoClientStub,
) -> None:
    monkeypatch.setattr(dodo_payments.runtime, "dodo_credit_product_ids", {"20.00": "prod_20"})
    dodo_payments.create_payment_link(
        Decimal("20.00"),
        "USD",
        "t",
        "i",
        customer_id="cust_abc",
    )
    assert dodo_client.checkout_sessions.calls[0]["customer"] == {"customer_id": "cust_abc"}


# ---------------------------------------------------------------------------
# Refunds
# ---------------------------------------------------------------------------


def test_create_refund_partial_payload(dodo_client: DodoClientStub) -> None:
    refund = dodo_payments.create_refund("pay_1", "prod_20", amount_cents=2000, reason="request")
    assert refund.refund_id == "ref_1"
    call = dodo_client.refunds.calls[0]
    assert call["items"] == [{"item_id": "prod_20", "amount": 2000}]


def test_create_refund_metadata_and_idempotency(dodo_client: DodoClientStub) -> None:
    dodo_payments.create_refund(
        "pay_2",
        "prod_50",
        reason="request",
        idempotency_key="k1",
        metadata={"topup_id": "1"},
    )
    call = dodo_client.refunds.calls[0]
    assert call["metadata"] == {"topup_id": "1"}
    assert call["extra_headers"] == {"Idempotency-Key": "k1"}


# ---------------------------------------------------------------------------
# Webhooks + generic payments
# ---------------------------------------------------------------------------


def test_verify_webhook(dodo_client: DodoClientStub) -> None:
    event = dodo_payments.verify_webhook({"x": "y"}, '{"ok": true}')
    assert event.type == "payment.succeeded"


def test_list_payments_product_filter(dodo_client: DodoClientStub) -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = datetime(2026, 1, 2, tzinfo=UTC)
    payments = list(
        dodo_payments.list_payments(
            created_at_gte=start,
            created_at_lte=end,
            status="succeeded",
            product_id="prod_20",
        )
    )
    assert payments[0].payment_id == "pay_1"
    assert dodo_client.payments.calls[0]["product_id"] == "prod_20"


# ---------------------------------------------------------------------------
# Customer management
# ---------------------------------------------------------------------------


def test_create_customer(dodo_client: DodoClientStub) -> None:
    customer = dodo_payments.create_customer("Alice", "alice@example.com")
    assert customer.customer_id == "cust_1"
    assert dodo_client.customers.creates == [{"name": "Alice", "email": "alice@example.com"}]


def test_create_customer_sdk_error(dodo_client: DodoClientStub) -> None:
    def _raise(**_: Any) -> None:
        raise RuntimeError("network")

    dodo_client.customers.create = _raise  # type: ignore[assignment]
    with pytest.raises(BillingError, match="Dodo Payments request failed"):
        dodo_payments.create_customer("Bob", "bob@example.com")


def test_update_customer_email(dodo_client: DodoClientStub) -> None:
    dodo_payments.update_customer("cust_1", email="new@example.com")
    assert dodo_client.customers.updates == [("cust_1", {"email": "new@example.com"})]


def test_update_customer_name(dodo_client: DodoClientStub) -> None:
    dodo_payments.update_customer("cust_1", name="New Name")
    assert dodo_client.customers.updates == [("cust_1", {"name": "New Name"})]


def test_update_customer_noop(dodo_client: DodoClientStub) -> None:
    dodo_payments.update_customer("cust_1")
    assert dodo_client.customers.updates == []


# ---------------------------------------------------------------------------
# Credit entitlements
# ---------------------------------------------------------------------------


def test_retrieve_credit_balance(dodo_client: DodoClientStub) -> None:
    balance = dodo_payments.retrieve_credit_balance("cust_1", "ce_abc")
    assert balance.balance == 10000
    assert dodo_client.credit_entitlements.balances.retrieves == [
        {"customer_id": "cust_1", "credit_entitlement_id": "ce_abc"},
    ]


def test_create_credit_addition(dodo_client: DodoClientStub) -> None:
    result = dodo_payments.create_credit_addition("cust_1", "ce_abc", 5000, "Manual top-up")
    assert result.new_balance == 15000
    entry = dodo_client.credit_entitlements.balances.ledger_entries[0]
    assert entry["amount"] == "5000"
    assert entry["entry_type"] == "credit"
    assert entry["reason"] == "Manual top-up"


def test_create_credit_deduction(dodo_client: DodoClientStub) -> None:
    result = dodo_payments.create_credit_deduction("cust_1", "ce_abc", 3000, "run_debit [r42]")
    assert result.new_balance == 15000
    entry = dodo_client.credit_entitlements.balances.ledger_entries[0]
    assert entry["amount"] == "3000"
    assert entry["entry_type"] == "debit"
    assert entry["reason"] == "run_debit [r42]"


def test_credit_operation_sdk_error(dodo_client: DodoClientStub) -> None:
    def _raise(**_: Any) -> None:
        raise RuntimeError("timeout")

    dodo_client.credit_entitlements.balances.retrieve = _raise  # type: ignore[assignment]
    with pytest.raises(BillingError, match="Dodo Payments request failed"):
        dodo_payments.retrieve_credit_balance("cust_1", "ce_abc")
