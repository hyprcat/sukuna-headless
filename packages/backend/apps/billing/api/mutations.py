from __future__ import annotations

from decimal import Decimal
from typing import cast

import strawberry
from strawberry.types import Info

from apps.accounts.permissions import Action
from apps.billing.api.types import CreateTopupPayload, TopupType
from apps.billing.models import CreditWallet
from apps.billing.services.dodo import create_topup
from apps.core.api.mappers import catch_domain_errors
from apps.core.decorators import requires_role, workspace_scoped


@strawberry.input
class CreateTopupInput:
    amount: Decimal
    idempotency_key: str


@strawberry.type
class BillingMutation:
    @strawberry.mutation
    @catch_domain_errors(CreateTopupPayload)
    @workspace_scoped
    @requires_role(Action.BILLING_TOPUP)
    def create_topup(self, info: Info, input: CreateTopupInput) -> CreateTopupPayload:
        wallet = CreditWallet.get_for_workspace_or_raise(info.context.workspace.pk)
        topup, url = create_topup(wallet, input.amount, input.idempotency_key)
        return CreateTopupPayload(
            success=True,
            errors=[],
            topup=cast("TopupType", topup),
            hosted_checkout_url=url,
        )
