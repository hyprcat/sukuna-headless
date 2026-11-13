from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from integrations import dodo_payments


class CheckoutSessionsStub:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.response = SimpleNamespace(checkout_url="https://checkout.dodopayments.com/s")
        self.error: Exception | None = None

    def create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.response


class RefundsStub:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.response = SimpleNamespace(refund_id="ref_1")

    def create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        return self.response


class PaymentsStub:
    def __init__(self) -> None:
        self.retrieved: list[str] = []
        self.calls: list[dict[str, Any]] = []
        self.response = [SimpleNamespace(payment_id="pay_1")]

    def retrieve(self, payment_id: str) -> SimpleNamespace:
        self.retrieved.append(payment_id)
        return SimpleNamespace(payment_id=payment_id)

    def list(self, **kwargs: Any) -> list[SimpleNamespace]:
        self.calls.append(kwargs)
        return self.response


class WebhooksStub:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def unwrap(self, payload: str, *, headers: dict[str, str]) -> SimpleNamespace:
        self.calls.append({"payload": payload, "headers": headers})
        return SimpleNamespace(type="payment.succeeded")


class CustomersStub:
    def __init__(self) -> None:
        self.creates: list[dict[str, Any]] = []
        self.updates: list[tuple[str, dict[str, Any]]] = []
        self.create_response = SimpleNamespace(customer_id="cust_1", name="", email="")

    def create(self, **kwargs: Any) -> SimpleNamespace:
        self.creates.append(kwargs)
        return self.create_response

    def update(self, customer_id: str, **kwargs: Any) -> None:
        self.updates.append((customer_id, kwargs))


class BalancesStub:
    def __init__(self) -> None:
        self.retrieves: list[dict[str, str]] = []
        self.ledger_entries: list[dict[str, Any]] = []
        self.retrieve_response = SimpleNamespace(balance=10000, used=5000)
        self.ledger_response = SimpleNamespace(new_balance=15000)

    def retrieve(self, *, customer_id: str, credit_entitlement_id: str) -> SimpleNamespace:
        self.retrieves.append(
            {"customer_id": customer_id, "credit_entitlement_id": credit_entitlement_id}
        )
        return self.retrieve_response

    def create_ledger_entry(
        self, *, customer_id: str, credit_entitlement_id: str, **kwargs: Any
    ) -> SimpleNamespace:
        self.ledger_entries.append(
            {"customer_id": customer_id, "credit_entitlement_id": credit_entitlement_id, **kwargs}
        )
        return self.ledger_response


class CreditEntitlementsStub:
    def __init__(self) -> None:
        self.balances = BalancesStub()


class DodoClientStub:
    def __init__(self) -> None:
        self.checkout_sessions = CheckoutSessionsStub()
        self.refunds = RefundsStub()
        self.payments = PaymentsStub()
        self.webhooks = WebhooksStub()
        self.customers = CustomersStub()
        self.credit_entitlements = CreditEntitlementsStub()


@pytest.fixture
def dodo_client(monkeypatch: pytest.MonkeyPatch) -> DodoClientStub:
    client = DodoClientStub()
    monkeypatch.setattr(dodo_payments, "_client", lambda: client)
    monkeypatch.setattr(dodo_payments.runtime, "dodo_return_url", "https://app.test/return")
    monkeypatch.setattr(dodo_payments.runtime, "dodo_cancel_url", "https://app.test/cancel")
    return client
