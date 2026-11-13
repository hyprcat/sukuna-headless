"""Billing background tasks — beat schedules (Celery) and one-shot work (Django tasks)."""

from __future__ import annotations

from celery import shared_task
from django.tasks import task

from apps.billing.services.sync import run_nightly_reconciliation, sync_customer_email


@shared_task
def reconcile_dodo_payments() -> dict[str, int]:
    return run_nightly_reconciliation()


@task
def sync_dodo_customer_email(workspace_id: int) -> None:
    sync_customer_email(workspace_id)
