"""Async Dodo credit sync tasks — propagate local debits/adjustments to Dodo."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

import sentry_sdk
import structlog
from django.tasks import task
from django.utils import timezone

from apps.billing.schemas.config import DodoSyncConfig
from apps.core.events import record_event
from apps.core.exceptions import BillingError
from config.runtime import runtime
from integrations import dodo_payments

if TYPE_CHECKING:
    from django.tasks.base import Task

_log = structlog.get_logger(__name__)


def _backoff_delay(attempt: int) -> timedelta:
    cfg = DodoSyncConfig()
    index = min(attempt - 1, len(cfg.backoff_seconds) - 1)
    return timedelta(seconds=cfg.backoff_seconds[index])


def _workspace_customer_id(wallet_id: int) -> str:
    from apps.billing.models.wallet import CreditWallet  # noqa: PLC0415

    wallet = CreditWallet.objects.select_related("workspace").get(pk=wallet_id)
    customer_id = wallet.workspace.dodo_customer_id
    if not customer_id:
        raise BillingError("Workspace has no Dodo customer ID.")
    return customer_id


def _to_cents(amount: Decimal) -> int:
    return int((amount * Decimal("100")).quantize(Decimal("1")))


def _deduct_credits(wallet_id: int, amount_usd: str, reason: str, reference: str) -> None:
    customer_id = _workspace_customer_id(wallet_id)
    dodo_payments.create_credit_deduction(
        customer_id=customer_id,
        entitlement_id=runtime.dodo_credit_entitlement_id,
        amount=_to_cents(Decimal(amount_usd)),
        description=f"{reason} [{reference}]",
    )


@task
def sync_credit_deduction(
    wallet_id: int,
    amount_usd: str,
    reference: str,
    reason: str,
    attempt: int = 1,
) -> None:
    try:
        _deduct_credits(wallet_id, amount_usd, reason, reference)
    except Exception as exc:
        _handle_failure(
            task_ref=sync_credit_deduction,
            attempt=attempt,
            exc=exc,
            event_name="billing_dodo_sync_failed",
            wallet_id=wallet_id,
            amount_usd=amount_usd,
            reference=reference,
            reason=reason,
        )
        return
    _log.info("dodo_credit_deduction_synced", wallet_id=wallet_id, reference=reference)


@task
def sync_admin_adjustment(
    wallet_id: int,
    delta_usd: str,
    note: str,
    reference: str,
    attempt: int = 1,
) -> None:
    """Propagate a local admin adjustment to Dodo as a credit addition or deduction."""
    try:
        customer_id = _workspace_customer_id(wallet_id)
        _sync_adjustment_to_dodo(customer_id, Decimal(delta_usd), note)
    except Exception as exc:
        _handle_failure(
            task_ref=sync_admin_adjustment,
            attempt=attempt,
            exc=exc,
            event_name="billing_dodo_adjustment_sync_failed",
            wallet_id=wallet_id,
            delta_usd=delta_usd,
            note=note,
            reference=reference,
        )
        return
    _log.info("dodo_admin_adjustment_synced", wallet_id=wallet_id, reference=reference)


def _sync_adjustment_to_dodo(customer_id: str, delta: Decimal, note: str) -> None:
    amount_cents = _to_cents(abs(delta))
    if delta > 0:
        dodo_payments.create_credit_addition(
            customer_id=customer_id,
            entitlement_id=runtime.dodo_credit_entitlement_id,
            amount=amount_cents,
            description=note,
        )
    else:
        dodo_payments.create_credit_deduction(
            customer_id=customer_id,
            entitlement_id=runtime.dodo_credit_entitlement_id,
            amount=amount_cents,
            description=note,
        )


def _schedule_retry(task_ref: Task, delay: timedelta, **kwargs: str | int) -> None:
    task_ref.using(run_after=timezone.now() + delay).enqueue(**kwargs)


def _handle_failure(
    *,
    task_ref: Task,
    attempt: int,
    exc: Exception,
    event_name: str,
    **kwargs: str | int,
) -> None:
    cfg = DodoSyncConfig()
    if attempt < cfg.max_attempts:
        _retry(task_ref, attempt, exc, **kwargs)
        return
    _alert_final_failure(event_name, attempt, exc, **kwargs)


def _retry(task_ref: Task, attempt: int, exc: Exception, **kwargs: str | int) -> None:
    delay = _backoff_delay(attempt)
    _log.warning(
        "dodo_sync_retry",
        attempt=attempt,
        next_attempt=attempt + 1,
        delay_seconds=delay.total_seconds(),
        error=str(exc),
    )
    _schedule_retry(task_ref, delay, **kwargs, attempt=attempt + 1)


def _alert_final_failure(
    event_name: str,
    attempt: int,
    exc: Exception,
    **kwargs: str | int,
) -> None:
    _log.error(event_name, attempt=attempt, error=str(exc))
    sentry_sdk.capture_exception(exc)
    props = {"attempt": attempt, "error": str(exc), **{k: str(v) for k, v in kwargs.items()}}
    record_event(
        event_name,
        distinct_id=str(kwargs.get("wallet_id", "unknown")),
        properties=props,
    )
