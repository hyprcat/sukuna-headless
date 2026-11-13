from __future__ import annotations

import structlog
from celery import shared_task
from django.db import transaction
from django.utils import timezone

from apps.billing.models.hold import BillingHold, HoldStatus
from apps.core.events import record_event

_log = structlog.get_logger(__name__)

_BATCH = 500


@shared_task
def reconcile_billing_holds() -> int:
    now = timezone.now()
    expired_pks = list(
        BillingHold.objects.filter(status=HoldStatus.ACTIVE, expires_at__lte=now).values_list(
            "pk", flat=True
        )[:_BATCH]
    )
    count = 0
    for pk in expired_pks:
        if _settle_hold(pk, now):
            count += 1
    _log.info("reconcile_billing_holds_done", reconciled=count, checked=len(expired_pks))
    return count


@transaction.atomic
def _settle_hold(pk: int, now: timezone.datetime) -> bool:
    try:
        hold = BillingHold.objects.select_for_update(skip_locked=True).get(pk=pk)
    except BillingHold.DoesNotExist:
        return False
    if hold.status != HoldStatus.ACTIVE:
        return False
    if _has_recent_activity(hold):
        return False
    run = hold.run
    if run.total_cost_usd > 0:
        hold.settle(min(run.total_cost_usd, hold.amount_reserved_usd))
        outcome = "settled"
    else:
        hold.release()
        outcome = "released"
    record_event(
        "billing_hold_reconciled",
        distinct_id=str(run.workspace_id),
        properties={"run_id": str(run.run_uid), "outcome": outcome},
    )
    return True


def _has_recent_activity(hold: BillingHold) -> bool:
    run = hold.run
    return run.last_callback_at is not None and run.last_callback_at > hold.expires_at
