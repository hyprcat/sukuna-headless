"""Single-file wrapper around the Dodo Payments SDK.

Resolvers, models, and tasks import this module — never the Dodo SDK
directly. Swapping payment providers is a one-file change.

Client construction uses ``lru_cache(maxsize=1)`` per
BACKEND_CODING_STANDARDS §2 — no module-level mutable globals.
"""

from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from typing import TYPE_CHECKING, Literal, cast

from dodopayments import DodoPayments

from apps.core.exceptions import BillingError
from config.runtime import runtime

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable
    from datetime import datetime

    from dodopayments.types import (
        CheckoutSessionResponse,
        Customer,
        PaymentListResponse,
        Refund,
        UnwrapWebhookEvent,
    )
    from dodopayments.types.credit_entitlements import (
        BalanceCreateLedgerEntryResponse,
        CustomerCreditBalance,
    )
    from dodopayments.types.currency import Currency


@lru_cache(maxsize=1)
def _client() -> DodoPayments:
    return DodoPayments(
        bearer_token=runtime.dodo_api_key,
        webhook_key=runtime.dodo_webhook_key,
        environment=runtime.dodo_environment,
    )


def _product_id_for_amount(amount: Decimal) -> str:
    for key in _amount_config_keys(amount):
        product_id = runtime.dodo_credit_product_ids.get(key)
        if product_id:
            return product_id
    raise BillingError(f"No Dodo product configured for amount ${amount}")


def _amount_config_keys(amount: Decimal) -> tuple[str, ...]:
    cents = amount.quantize(Decimal("0.01"))
    normalized = cents.normalize()
    keys = (format(cents, "f"), format(normalized, "f"), str(normalized))
    return tuple(dict.fromkeys(keys))


def _dodo_request[T](operation: Callable[[], T]) -> T:
    try:
        return operation()
    except BillingError:
        raise
    except Exception as exc:
        raise BillingError("Dodo Payments request failed.") from exc


# ---------------------------------------------------------------------------
# Customer management
# ---------------------------------------------------------------------------


def create_customer(name: str, email: str) -> Customer:
    return _dodo_request(lambda: _client().customers.create(name=name, email=email))


def update_customer(customer_id: str, *, name: str | None = None, email: str | None = None) -> None:
    if name is None and email is None:
        return
    if name is not None and email is not None:
        _dodo_request(lambda: _client().customers.update(customer_id, name=name, email=email))
    elif name is not None:
        _dodo_request(lambda: _client().customers.update(customer_id, name=name))
    else:
        _dodo_request(lambda: _client().customers.update(customer_id, email=email))


# ---------------------------------------------------------------------------
# Credit entitlements (balance queries + ledger entries)
# ---------------------------------------------------------------------------


def retrieve_credit_balance(customer_id: str, entitlement_id: str) -> CustomerCreditBalance:
    return _dodo_request(
        lambda: _client().credit_entitlements.balances.retrieve(
            customer_id=customer_id,
            credit_entitlement_id=entitlement_id,
        )
    )


def create_credit_addition(
    customer_id: str,
    entitlement_id: str,
    amount: int,
    description: str,
) -> BalanceCreateLedgerEntryResponse:
    return _create_credit_ledger_entry(
        customer_id,
        entitlement_id,
        amount=amount,
        entry_type="credit",
        description=description,
    )


def create_credit_deduction(
    customer_id: str,
    entitlement_id: str,
    amount: int,
    description: str,
) -> BalanceCreateLedgerEntryResponse:
    return _create_credit_ledger_entry(
        customer_id,
        entitlement_id,
        amount=amount,
        entry_type="debit",
        description=description,
    )


def _create_credit_ledger_entry(
    customer_id: str,
    entitlement_id: str,
    *,
    amount: int,
    entry_type: Literal["credit", "debit"],
    description: str,
) -> BalanceCreateLedgerEntryResponse:
    return _dodo_request(
        lambda: _client().credit_entitlements.balances.create_ledger_entry(
            customer_id=customer_id,
            credit_entitlement_id=entitlement_id,
            amount=str(amount),
            entry_type=entry_type,
            reason=description,
        )
    )


# ---------------------------------------------------------------------------
# Checkout + payments
# ---------------------------------------------------------------------------


def create_payment_link(
    amount: Decimal,
    currency: str,
    reference: str,
    idempotency_key: str,
    *,
    customer_id: str | None = None,
) -> str:
    product_id = _product_id_for_amount(amount)
    session = _create_checkout_session(
        product_id,
        currency,
        reference,
        idempotency_key,
        customer_id=customer_id,
    )
    if session.checkout_url is None:
        raise BillingError("Dodo checkout session did not return a checkout URL.")
    return session.checkout_url


def _create_checkout_session(
    product_id: str,
    currency: str,
    reference: str,
    idempotency_key: str,
    *,
    customer_id: str | None = None,
) -> CheckoutSessionResponse:
    kwargs: dict[str, object] = {
        "product_cart": [{"product_id": product_id, "quantity": 1}],
        "billing_currency": cast("Currency", currency),
        "return_url": runtime.dodo_return_url,
        "cancel_url": runtime.dodo_cancel_url,
        "metadata": _checkout_metadata(reference, idempotency_key, currency),
        "extra_headers": {"Idempotency-Key": idempotency_key},
    }
    if customer_id is not None:
        kwargs["customer"] = {"customer_id": customer_id}
    return _dodo_request(lambda: _client().checkout_sessions.create(**kwargs))  # type: ignore[arg-type]


def _checkout_metadata(reference: str, idempotency_key: str, currency: str) -> dict[str, str]:
    return {"reference": reference, "idempotency_key": idempotency_key, "currency": currency}


def create_refund(
    payment_id: str,
    product_id: str,
    amount_cents: int | None = None,
    reason: str | None = None,
    idempotency_key: str | None = None,
    metadata: dict[str, str] | None = None,
) -> Refund:
    item: dict[str, str | int] = {"item_id": product_id}
    if amount_cents is not None:
        item["amount"] = amount_cents
    kwargs: dict[str, object] = {"payment_id": payment_id, "items": [item], "reason": reason}
    if metadata is not None:
        kwargs["metadata"] = metadata
    if idempotency_key is not None:
        kwargs["extra_headers"] = {"Idempotency-Key": idempotency_key}
    return _dodo_request(
        lambda: _client().refunds.create(**kwargs)  # type: ignore[arg-type]  # SDK kwargs.
    )


def refund_full_payment(
    payment_id: str,
    amount: Decimal,
    reason: str | None = None,
    idempotency_key: str | None = None,
    metadata: dict[str, str] | None = None,
) -> Refund:
    product_id = _product_id_for_amount(amount)
    return create_refund(
        payment_id=payment_id,
        product_id=product_id,
        reason=reason,
        idempotency_key=idempotency_key,
        metadata=metadata,
    )


def list_payments(
    *,
    created_at_gte: datetime,
    created_at_lte: datetime,
    status: str | None = None,
    product_id: str | None = None,
) -> Iterable[PaymentListResponse]:
    kwargs: dict[str, object] = {
        "created_at_gte": created_at_gte,
        "created_at_lte": created_at_lte,
        "page_size": 100,
    }
    if status is not None:
        kwargs["status"] = status
    if product_id is not None:
        kwargs["product_id"] = product_id
    return _dodo_request(lambda: _client().payments.list(**kwargs))  # type: ignore[arg-type]  # SDK kwargs.


# ---------------------------------------------------------------------------
# Webhooks
# ---------------------------------------------------------------------------


def verify_webhook(
    headers: dict[str, str],
    raw_body: str,
) -> UnwrapWebhookEvent:
    return _dodo_request(lambda: _client().webhooks.unwrap(raw_body, headers=headers))
