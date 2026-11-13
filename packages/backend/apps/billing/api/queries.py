from __future__ import annotations

import strawberry
import strawberry_django
from strawberry.types import Info
from strawberry_django.relay import DjangoListConnection

from apps.accounts.permissions import Action
from apps.billing.api.types import BillingHoldType, CreditWalletType, LedgerEntryType, TopupType
from apps.billing.models import BillingHold, CreditWallet, LedgerEntry, Topup
from apps.core.decorators import requires_role, workspace_scoped


@strawberry.type
class BillingQuery:
    @strawberry.field
    @workspace_scoped
    @requires_role(Action.BILLING_READ)
    def wallet(self, info: Info) -> CreditWalletType | None:
        return CreditWallet.get_for_workspace(info.context.workspace.pk)  # type: ignore[return-value]

    @strawberry_django.connection(DjangoListConnection[TopupType])
    @workspace_scoped
    @requires_role(Action.BILLING_READ)
    def topups(self, info: Info, status: str | None = None) -> list[Topup]:
        return Topup.for_workspace(info.context.workspace.pk, status=status)  # type: ignore[return-value]

    @strawberry_django.connection(DjangoListConnection[LedgerEntryType])
    @workspace_scoped
    @requires_role(Action.BILLING_READ)
    def ledger_entries(self, info: Info, kind: str | None = None) -> list[LedgerEntry]:
        return LedgerEntry.for_workspace(info.context.workspace.pk, kind=kind)  # type: ignore[return-value]

    @strawberry_django.connection(DjangoListConnection[BillingHoldType])
    @workspace_scoped
    @requires_role(Action.BILLING_READ)
    def billing_holds(
        self,
        info: Info,
        status: str | None = None,
    ) -> list[BillingHold]:
        return BillingHold.list_for_workspace(  # type: ignore[return-value]
            info.context.workspace.pk,
            status=status,
        )
