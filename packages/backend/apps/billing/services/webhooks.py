"""Dodo Payments webhook reception, validation, and event dispatch."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Protocol, cast

import structlog
from django.db import IntegrityError, transaction
from django.http import HttpResponse, HttpResponseBadRequest
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.billing.models import CreditWallet, Topup, TopupStatus, WebhookDelivery
from apps.billing.schemas import DodoWebhookConfig
from apps.core.events import record_event
from integrations import dodo_payments

if TYPE_CHECKING:
    from collections.abc import Mapping

    from django.http import HttpRequest
    from dodopayments.types import (
        Payment,
        RefundSucceededWebhookEvent,
        UnwrapWebhookEvent,
    )

    from apps.workspaces.models.workspace import Workspace

_log = structlog.get_logger(__name__)


class PaymentWebhookEvent(Protocol):
    type: str
    data: Payment


@csrf_exempt
@require_POST
def dodo_webhook_view(request: HttpRequest) -> HttpResponse:
    try:
        raw_body = request.body.decode()
    except UnicodeDecodeError:
        _log.warning("dodo_webhook_body_decode_failed")
        return HttpResponseBadRequest()
    headers = dict(request.headers)
    try:
        event = dodo_payments.verify_webhook(headers, raw_body)
    except Exception:
        _log.warning("dodo_webhook_signature_failed")
        return HttpResponseBadRequest()
    event_id = _extract_webhook_id(headers)
    if not event_id:
        _log.warning("dodo_webhook_id_missing")
        return HttpResponseBadRequest()
    _process_event(event, raw_body, event_id=event_id)
    return HttpResponse(status=200)


def _extract_webhook_id(headers: Mapping[str, str]) -> str:
    normalized = {key.lower(): value for key, value in headers.items()}
    return normalized.get(DodoWebhookConfig().webhook_id_header, "").strip()


def _process_event(event: UnwrapWebhookEvent, raw_body: str, *, event_id: str) -> bool:
    event_type = event.type
    if event_type not in DodoWebhookConfig().handled_events:
        _log.info("dodo_webhook_ignored", event_type=event_type)
        return False
    return _process_handled_event(event, raw_body, event_id=event_id)


def _process_handled_event(event: UnwrapWebhookEvent, raw_body: str, *, event_id: str) -> bool:
    event_id = event_id.strip()
    if not event_id:
        raise ValueError("Dodo webhook event ID must be non-empty.")
    payload_hash = hashlib.sha256(raw_body.encode()).hexdigest()
    try:
        if not _process_delivery(event, event_id, payload_hash):
            return False
    except Exception:
        _log.exception("dodo_webhook_failed", event_id=event_id)
        raise
    _record_webhook_processed(event, event_id)
    return True


def _process_delivery(event: UnwrapWebhookEvent, event_id: str, payload_hash: str) -> bool:
    with transaction.atomic():
        delivery = _insert_delivery(event_id, payload_hash)
        if delivery is None:
            return False
        _dispatch(event.type, event)
        delivery.mark_processed()
        return True


def _record_webhook_processed(event: UnwrapWebhookEvent, event_id: str) -> None:
    record_event(
        "dodo_webhook_processed",
        distinct_id=event.business_id,
        properties={"event_type": event.type, "event_id": event_id},
    )


def _insert_delivery(event_id: str, payload_hash: str) -> WebhookDelivery | None:
    try:
        with transaction.atomic():
            return WebhookDelivery.objects.create(
                provider="dodo",
                event_id=event_id,
                payload_hash=payload_hash,
            )
    except IntegrityError:
        _log.info("dodo_webhook_replay", event_id=event_id)
        return None


def _dispatch(event_type: str, event: UnwrapWebhookEvent) -> None:
    if event_type.startswith(DodoWebhookConfig().payment_event_prefix):
        _handle_payment_event(cast("PaymentWebhookEvent", event))
    elif event_type == "refund.succeeded":
        _handle_refund_succeeded(cast("RefundSucceededWebhookEvent", event))
    elif event_type == "credit.balance_low":
        _handle_credit_balance_low(event)


def _handle_payment_event(event: PaymentWebhookEvent) -> None:
    payment = event.data
    topup = _find_topup(payment.metadata)
    status = _payment_status(event.type, getattr(payment, "status", None))
    if status == DodoWebhookConfig().succeeded_payment_status:
        _settle_payment_succeeded(topup, payment.payment_id)
    elif status in DodoWebhookConfig().failed_payment_statuses:
        _settle_payment_failed(topup)


def _payment_status(event_type: str, payload_status: object) -> str:
    status = str(payload_status or "").strip()
    if status:
        return status
    return event_type.removeprefix(DodoWebhookConfig().payment_event_prefix)


def _settle_payment_succeeded(topup: Topup, payment_id: str) -> None:
    if topup.status != TopupStatus.PENDING:
        _log.info("dodo_topup_already_settled", topup_id=topup.pk)
        return
    topup.confirm(payment_id)
    wallet = CreditWallet.objects.select_for_update().get(pk=topup.wallet_id)
    wallet.record_dodo_credit_grant(amount=topup.amount_usd, dodo_payment_id=payment_id)


def _settle_payment_failed(topup: Topup) -> None:
    if topup.status != TopupStatus.PENDING:
        _log.info("dodo_topup_already_settled", topup_id=topup.pk)
        return
    topup.fail()


def _handle_refund_succeeded(event: RefundSucceededWebhookEvent) -> None:
    payment_id = event.data.payment_id
    try:
        topup = Topup.objects.select_for_update().get(dodo_payment_id=payment_id)
    except Topup.DoesNotExist:
        _log.warning("dodo_refund_unknown_payment", payment_id=payment_id)
        return
    if topup.status == TopupStatus.REFUNDED:
        _log.info("dodo_refund_already_completed", payment_id=payment_id)
        return
    wallet = CreditWallet.objects.select_for_update().get(pk=topup.wallet_id)
    wallet.refund(amount=topup.amount_usd, reference=str(topup.pk), note=topup.refund_reason)
    topup.complete_refund()
    _log.info(
        "dodo_refund_confirmed",
        refund_id=event.data.refund_id,
        payment_id=payment_id,
        amount_usd=str(topup.amount_usd),
    )


def _handle_credit_balance_low(event: UnwrapWebhookEvent) -> None:
    from apps.workspaces.models.workspace import Workspace  # noqa: PLC0415

    data = event.data
    customer_id = getattr(data, "customer_id", "")
    if not customer_id:
        _log.warning("credit_balance_low_missing_customer_id")
        return
    try:
        workspace = Workspace.objects.get(dodo_customer_id=customer_id)
    except Workspace.DoesNotExist:
        _log.warning("credit_balance_low_unknown_customer", customer_id=customer_id)
        return
    _record_credit_balance_low(workspace, data)


def _record_credit_balance_low(workspace: Workspace, data: object) -> None:
    record_event(
        "credit_balance_low",
        distinct_id=str(workspace.owner_id),
        properties={
            "workspace_id": workspace.pk,
            "available": str(getattr(data, "available_balance", "")),
            "threshold": str(getattr(data, "threshold_percent", "")),
        },
    )


def _find_topup(metadata: dict[str, str]) -> Topup:
    reference = metadata.get("reference")
    if not reference:
        raise ValueError("Webhook payment metadata missing 'reference' (topup PK).")
    return Topup.objects.select_for_update().get(pk=reference)
