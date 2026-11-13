from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest
import strawberry
from strawberry_django.optimizer import DjangoOptimizerExtension

from apps.billing.api.queries import BillingQuery
from apps.billing.factories import BillingHoldFactory, CreditWalletFactory
from apps.billing.models import HoldStatus
from apps.runs.factories import RunFactory
from apps.workspaces.factories import WorkspaceFactory

pytestmark = pytest.mark.django_db


@strawberry.type
class _Q(BillingQuery):
    pass


_schema = strawberry.Schema(query=_Q, extensions=[DjangoOptimizerExtension])


def _session_ctx(workspace: object) -> SimpleNamespace:
    member = SimpleNamespace(workspace_id=workspace.pk, can=lambda _action: True)
    principal = SimpleNamespace(workspace_id=workspace.pk, member=member, scopes=frozenset())
    return SimpleNamespace(workspace=workspace, principal=principal)


HOLDS_QUERY = """
query($status: String) {
    billingHolds(status: $status, first: 10) {
        totalCount
        edges {
            node {
                amountReservedUsd
                amountConsumedUsd
                status
                isExpired
                runUid
            }
        }
    }
}
"""


def _funded_wallet(workspace=None) -> object:
    wallet = CreditWalletFactory(workspace=workspace or WorkspaceFactory())
    wallet.record_dodo_credit_grant(Decimal("500.00"), dodo_payment_id="seed")
    return wallet


def test_billing_holds_list() -> None:
    wallet = _funded_wallet()
    run = RunFactory(workspace=wallet.workspace)
    BillingHoldFactory(run=run, wallet=wallet, amount_reserved_usd=Decimal("25.00"))

    result = _schema.execute_sync(
        HOLDS_QUERY,
        variable_values={},
        context_value=_session_ctx(wallet.workspace),
    )

    assert result.errors is None
    assert result.data["billingHolds"]["totalCount"] == 1
    node = result.data["billingHolds"]["edges"][0]["node"]
    assert Decimal(node["amountReservedUsd"]) == Decimal("25.00")
    assert Decimal(node["amountConsumedUsd"]) == Decimal("0")
    assert node["status"] == "ACTIVE"
    assert node["isExpired"] is False
    assert node["runUid"] == str(run.run_uid)


def test_billing_holds_filter_by_status() -> None:
    wallet = _funded_wallet()
    run1 = RunFactory(workspace=wallet.workspace)
    run2 = RunFactory(workspace=wallet.workspace)
    BillingHoldFactory(run=run1, wallet=wallet, amount_reserved_usd=Decimal("10.00"))
    BillingHoldFactory(
        run=run2,
        wallet=wallet,
        amount_reserved_usd=Decimal("15.00"),
        settled=True,
    )

    result = _schema.execute_sync(
        HOLDS_QUERY,
        variable_values={"status": HoldStatus.ACTIVE},
        context_value=_session_ctx(wallet.workspace),
    )

    assert result.errors is None
    assert result.data["billingHolds"]["totalCount"] == 1
    assert result.data["billingHolds"]["edges"][0]["node"]["status"] == "ACTIVE"


def test_billing_holds_scoped_to_workspace() -> None:
    wallet = _funded_wallet()
    run = RunFactory(workspace=wallet.workspace)
    BillingHoldFactory(run=run, wallet=wallet)

    other_ws = WorkspaceFactory()
    result = _schema.execute_sync(
        HOLDS_QUERY,
        variable_values={},
        context_value=_session_ctx(other_ws),
    )

    assert result.errors is None
    assert result.data["billingHolds"]["totalCount"] == 0
