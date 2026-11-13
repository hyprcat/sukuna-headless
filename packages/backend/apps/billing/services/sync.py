"""Dodo ↔ local synchronisation services.

Two concerns, one module:

- **Customer lifecycle** — ``ensure_dodo_customer`` lazily provisions
  a Dodo customer when a workspace first enters the billing flow,
  and ``sync_customer_email`` keeps the email in sync afterwards.
- **Nightly reconciliation** — ``run_nightly_reconciliation`` compares
  local wallet balances against Dodo credit balances for every wallet
  that had ledger activity in the last 24 h. Reports drift via
  Sentry + PostHog; automates nothing about resolution per
  BACKEND_CODING_STANDARDS §5.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

import sentry_sdk
import structlog
from django.db import transaction
from django.db.models import Exists, OuterRef, QuerySet
from django.utils import timezone
from pydantic import BaseModel, ConfigDict

from apps.billing.models.ledger import LedgerEntry
from apps.billing.models.wallet import CreditWallet
from apps.core.events import record_event
from integrations import dodo_payments

if TYPE_CHECKING:
    from decimal import Decimal

    from apps.workspaces.models.workspace import Workspace

_log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Workspace ↔ Dodo customer lifecycle
# ---------------------------------------------------------------------------


def ensure_dodo_customer(workspace: Workspace) -> str:
    if workspace.dodo_customer_id:
        return workspace.dodo_customer_id
    customer_id = _create_customer_atomically(workspace)
    workspace.dodo_customer_id = customer_id
    _record_customer_created(workspace.pk, customer_id)
    return customer_id


def _create_customer_atomically(workspace: Workspace) -> str:
    with transaction.atomic():
        locked = type(workspace).objects.select_for_update().get(pk=workspace.pk)
        if locked.dodo_customer_id:
            workspace.dodo_customer_id = locked.dodo_customer_id
            return locked.dodo_customer_id
        customer = dodo_payments.create_customer(
            name=locked.name,
            email=locked.billing_email or locked.owner.email,
        )
        locked.dodo_customer_id = customer.customer_id
        locked.save(update_fields=("dodo_customer_id", "updated_at"))
        return customer.customer_id


def _record_customer_created(workspace_id: int, customer_id: str) -> None:
    _log.info("dodo_customer_created", workspace_id=workspace_id, customer_id=customer_id)
    record_event(
        "dodo_customer_created",
        distinct_id=str(workspace_id),
        properties={"customer_id": customer_id, "workspace_id": workspace_id},
    )


def sync_customer_email(workspace_id: int) -> None:
    from apps.workspaces.models.workspace import Workspace  # noqa: PLC0415

    workspace = Workspace.objects.select_related("owner").get(pk=workspace_id)
    if not workspace.dodo_customer_id:
        return
    email = workspace.billing_email or workspace.owner.email
    dodo_payments.update_customer(workspace.dodo_customer_id, email=email)
    _log.info("dodo_customer_email_synced", workspace_id=workspace_id)
    record_event(
        "dodo_customer_email_synced",
        distinct_id=str(workspace_id),
        properties={"customer_id": workspace.dodo_customer_id},
    )


# ---------------------------------------------------------------------------
# Nightly balance reconciliation
# ---------------------------------------------------------------------------


class ReconciliationConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    window_hours: int = 24


def run_nightly_reconciliation() -> dict[str, int]:
    config = ReconciliationConfig()
    wallets = _wallets_with_recent_activity(config)
    checked = 0
    drifted = 0
    for wallet in wallets.iterator(chunk_size=200):
        checked += 1
        local, remote, matches = wallet.sync_balance_from_dodo()
        if not matches:
            drifted += 1
            _report_drift(wallet, local=local, remote=remote)
    if drifted == 0:
        _log.info("billing_reconciliation_clean", checked=checked)
    return {"checked": checked, "drifted": drifted}


def _wallets_with_recent_activity(
    config: ReconciliationConfig,
) -> QuerySet[CreditWallet]:
    cutoff = timezone.now() - timedelta(hours=config.window_hours)
    recent_entries = LedgerEntry.objects.filter(
        wallet_id=OuterRef("pk"),
        created_at__gte=cutoff,
    )
    return (
        CreditWallet.objects.filter(workspace__dodo_customer_id__isnull=False)
        .exclude(workspace__dodo_customer_id="")
        .annotate(has_recent_activity=Exists(recent_entries))
        .filter(has_recent_activity=True)
        .select_related("workspace")
    )


def _drift_properties(wallet: CreditWallet, local: Decimal, remote: Decimal) -> dict[str, str]:
    return {
        "local": str(local),
        "remote": str(remote),
        "delta": str(local - remote),
        "workspace_id": str(wallet.workspace_id),
    }


def _report_drift(wallet: CreditWallet, *, local: Decimal, remote: Decimal) -> None:
    props = _drift_properties(wallet, local, remote)
    _log.warning("billing_reconciliation_drift", **props)
    sentry_sdk.capture_message(
        f"Billing reconciliation drift: workspace {props['workspace_id']} "
        f"local=${local} vs Dodo=${remote} (delta=${props['delta']})",
        level="error",
    )
    record_event(
        "billing_reconciliation_drift",
        distinct_id=props["workspace_id"],
        properties=props,
    )
