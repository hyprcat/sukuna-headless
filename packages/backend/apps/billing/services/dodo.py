"""Dodo Payments orchestration — top-up creation and refund requests."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.db import IntegrityError, transaction

from apps.billing.models import CreditWallet, Topup, TopupStatus
from apps.billing.schemas import BillingFormat
from apps.billing.services.sync import ensure_dodo_customer
from apps.core.events import record_event
from apps.core.exceptions import BillingError, Conflict
from integrations import dodo_payments

if TYPE_CHECKING:
    from decimal import Decimal

    from dodopayments.types import Refund


def create_topup(
    wallet: CreditWallet,
    amount: Decimal,
    idempotency_key: str,
) -> tuple[Topup, str]:
    topup = _get_or_create_pending_topup(wallet, amount, idempotency_key)
    if topup.status != TopupStatus.PENDING:
        raise Conflict("Top-up is already settled.")
    customer_id = ensure_dodo_customer(wallet.workspace)
    url = dodo_payments.create_payment_link(
        amount=amount,
        currency=BillingFormat().currency,
        reference=str(topup.pk),
        idempotency_key=idempotency_key,
        customer_id=customer_id,
    )
    _record_topup_initiated(wallet, amount, idempotency_key)
    return topup, url


@transaction.atomic
def _get_or_create_pending_topup(
    wallet: CreditWallet,
    amount: Decimal,
    idempotency_key: str,
) -> Topup:
    existing = _topup_for_update(idempotency_key)
    if existing is not None:
        if existing.wallet_id != wallet.pk or existing.amount_usd != amount:
            raise Conflict("Idempotency key already belongs to a different top-up.")
        return existing
    try:
        with transaction.atomic():
            return Topup.objects.create(
                wallet=wallet,
                amount_usd=amount,
                currency=wallet.currency,
                idempotency_key=idempotency_key,
            )
    except IntegrityError as exc:
        raced = _topup_for_update(idempotency_key)
        if raced is None:
            raise
        if raced.wallet_id != wallet.pk or raced.amount_usd != amount:
            raise Conflict("Idempotency key already belongs to a different top-up.") from exc
        return raced


def _topup_for_update(idempotency_key: str) -> Topup | None:
    return Topup.objects.select_for_update().filter(idempotency_key=idempotency_key).first()


def _record_topup_initiated(wallet: CreditWallet, amount: Decimal, key: str) -> None:
    record_event(
        "topup_initiated",
        distinct_id=str(wallet.workspace_id),
        properties={
            "amount_usd": str(amount),
            "currency": BillingFormat().currency,
            "idempotency_key": key,
        },
    )


def refund_topup(topup: Topup, *, reason: str) -> Topup:
    with transaction.atomic():
        locked = Topup.objects.select_for_update().get(pk=topup.pk)
        _guard_refundable_topup(locked)
        refund = _request_dodo_refund(locked, reason)
        locked.request_refund(reason)
    _record_refund_requested(locked, reason, refund_id=str(getattr(refund, "refund_id", "")))
    return locked


def _guard_refundable_topup(topup: Topup) -> None:
    if topup.status == TopupStatus.REFUND_REQUESTED:
        raise Conflict("Refund already requested for this top-up.")
    if topup.status == TopupStatus.REFUNDED:
        raise Conflict("Top-up has already been refunded.")
    if topup.status != TopupStatus.SUCCEEDED:
        raise Conflict("Only succeeded top-ups can be refunded.")
    if not topup.dodo_payment_id:
        raise Conflict("Top-up has no Dodo payment ID.")


def _request_dodo_refund(topup: Topup, reason: str) -> Refund:
    idempotency_key = f"topup-refund-{topup.pk}"
    refund = dodo_payments.refund_full_payment(
        payment_id=topup.dodo_payment_id,
        amount=topup.amount_usd,
        reason=reason,
        idempotency_key=idempotency_key,
        metadata={"topup_id": str(topup.pk), "idempotency_key": idempotency_key},
    )
    if str(getattr(refund, "status", "")).lower() == "failed":
        raise BillingError("Dodo refund failed.", field="topup")
    return refund


def _record_refund_requested(topup: Topup, reason: str, *, refund_id: str) -> None:
    record_event(
        "topup_refund_requested",
        distinct_id=str(topup.wallet.workspace_id),
        properties={
            "amount_usd": str(topup.amount_usd),
            "currency": topup.currency,
            "topup_id": str(topup.pk),
            "dodo_payment_id": topup.dodo_payment_id,
            "dodo_refund_id": refund_id,
            "reason": reason,
        },
    )
