from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import cast

import strawberry
import strawberry_django
from strawberry import relay
from strawberry_django.relay import DjangoListConnection

from apps.billing.models import BillingHold, CreditWallet, LedgerEntry, Topup
from apps.core.api.types import MutationResult


@strawberry.enum
class TopupStatusEnum(Enum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REFUND_REQUESTED = "refund_requested"
    REFUNDED = "refunded"


@strawberry.enum
class LedgerKindEnum(Enum):
    TOPUP = "topup"
    RUN_DEBIT = "run_debit"
    REFUND = "refund"
    ADJUSTMENT = "adjustment"


@strawberry_django.type(LedgerEntry)
class LedgerEntryType(relay.Node):
    delta_usd: Decimal
    currency: str
    kind: LedgerKindEnum
    reference: str
    note: str
    created_at: datetime


@strawberry_django.type(CreditWallet)
class CreditWalletType(relay.Node):
    balance_usd: Decimal
    currency: str
    last_topup_at: datetime | None
    created_at: datetime
    updated_at: datetime

    entries: DjangoListConnection[LedgerEntryType] = strawberry_django.connection()

    @strawberry_django.field
    def available(self) -> Decimal:
        return CreditWallet.available(cast("CreditWallet", self))

    @strawberry_django.connection(DjangoListConnection[LedgerEntryType])
    def ledger(self) -> list[LedgerEntry]:
        wallet = cast("CreditWallet", self)
        return LedgerEntry.for_wallet(wallet.pk)  # type: ignore[return-value]


@strawberry.enum
class HoldStatusEnum(Enum):
    ACTIVE = "active"
    SETTLED = "settled"
    RELEASED = "released"
    EXPIRED = "expired"


@strawberry_django.type(BillingHold)
class BillingHoldType(relay.Node):
    amount_reserved_usd: Decimal
    amount_consumed_usd: Decimal
    status: HoldStatusEnum
    settled_at: datetime | None
    expires_at: datetime
    created_at: datetime
    updated_at: datetime

    @strawberry_django.field
    def is_expired(self) -> bool:
        return cast("BillingHold", self).is_expired()

    @strawberry_django.field(select_related=["run"])
    def run_uid(self) -> uuid.UUID:
        return cast("BillingHold", self).run.run_uid


@strawberry_django.type(Topup)
class TopupType(relay.Node):
    amount_usd: Decimal
    currency: str
    idempotency_key: str
    status: TopupStatusEnum
    dodo_payment_id: str
    created_at: datetime
    updated_at: datetime


@strawberry.type
class CreateTopupPayload(MutationResult):
    topup: TopupType | None = None
    hosted_checkout_url: str | None = None
