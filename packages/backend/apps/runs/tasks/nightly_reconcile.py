from __future__ import annotations

from datetime import timedelta

import sentry_sdk
import structlog
from asgiref.sync import async_to_sync
from celery import shared_task
from django.db.models import Count, Max
from django.utils import timezone

from apps.billing.models.hold import BillingHold, HoldStatus
from apps.billing.models.ledger import LedgerEntry, LedgerKind
from apps.core.events import record_event
from apps.runs.models.records import RunEvent
from apps.runs.models.run import Run
from apps.runs.models.sandbox_instance import SandboxInstance, SandboxState
from integrations import e2b

_log = structlog.get_logger(__name__)


def _check_ledger(since: timezone.datetime) -> int:
    settled = BillingHold.objects.filter(
        status=HoldStatus.SETTLED,
        settled_at__gte=since,
        amount_consumed_usd__gt=0,
    ).select_related("run")
    drift = 0
    for hold in settled:
        has_entry = LedgerEntry.objects.filter(
            kind=LedgerKind.RUN_DEBIT,
            reference=str(hold.run.run_uid),
        ).exists()
        if not has_entry:
            drift += 1
    return drift


def _check_hold_states(since: timezone.datetime) -> int:
    return (
        Run.objects.terminal()
        .filter(finished_at__gte=since)
        .filter(billing_hold__status=HoldStatus.ACTIVE)
        .count()
    )


def _check_sandbox_count() -> int:
    our_live = SandboxInstance.objects.exclude(
        sandbox_state=SandboxState.TERMINATED,
    ).count()
    e2b_live = len(async_to_sync(e2b.list_sandbox_states)())
    return abs(our_live - e2b_live)


def _check_callback_gaps(since: timezone.datetime) -> int:
    run_ids = list(
        Run.objects.filter(
            finished_at__gte=since,
            last_projected_sequence__gt=0,
        ).values_list("pk", flat=True)
    )
    if not run_ids:
        return 0
    agg = (
        RunEvent.objects.filter(run_id__in=run_ids)
        .values("run_id")
        .annotate(cnt=Count("sequence_no"), mx=Max("sequence_no"))
    )
    return sum(1 for row in agg if row["cnt"] < row["mx"])


@shared_task
def nightly_reconciliation() -> dict[str, int]:
    since = timezone.now() - timedelta(hours=24)
    summary = {
        "ledger_drift": _check_ledger(since),
        "hold_state_drift": _check_hold_states(since),
        "sandbox_drift": _check_sandbox_count(),
        "callback_drift": _check_callback_gaps(since),
    }
    if any(v > 0 for v in summary.values()):
        sentry_sdk.capture_message("nightly_reconciliation drift detected", level="warning")
        record_event(
            "nightly_reconciliation_drift",
            distinct_id="system",
            properties=summary,
        )
    _log.info("nightly_reconciliation_completed", **summary)
    return summary
