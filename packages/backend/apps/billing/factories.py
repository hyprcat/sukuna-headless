"""Factories for billing rows.

Wallet factories deliberately don't seed a balance — let tests call
:meth:`CreditWallet.record_dodo_credit_grant` so the ledger and balance
stay in lockstep (seeding ``balance_usd`` directly would diverge them).
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import factory
from django.utils import timezone

from apps.billing.models import (
    BillingHold,
    BillingRate,
    CreditWallet,
    HoldStatus,
    LedgerEntry,
    LedgerKind,
    Topup,
    TopupStatus,
    WebhookDelivery,
)
from apps.workspaces.factories import WorkspaceFactory


class CreditWalletFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = CreditWallet
        django_get_or_create = ("workspace",)

    workspace = factory.SubFactory(WorkspaceFactory)


class LedgerEntryFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = LedgerEntry

    wallet = factory.SubFactory(CreditWalletFactory)
    delta_usd = Decimal("10.00")
    kind = LedgerKind.TOPUP
    reference = factory.Sequence(lambda n: f"ref-{n}")
    note = ""


class TopupFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Topup

    wallet = factory.SubFactory(CreditWalletFactory)
    amount_usd = Decimal("20.00")
    idempotency_key = factory.Sequence(lambda n: f"idem-{n:06d}")
    status = TopupStatus.PENDING


class WebhookDeliveryFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = WebhookDelivery

    provider = "dodo"
    event_id = factory.Sequence(lambda n: f"evt_{n:08d}")


class BillingRateFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = BillingRate

    model_tier = "free"
    token_input_rate = Decimal("0.0010")
    token_output_rate = Decimal("0.0030")
    tool_call_rate = Decimal("0.0050")
    is_active = True

    class Params:
        free = factory.Trait(model_tier="free")
        pro = factory.Trait(
            model_tier="pro",
            token_input_rate=Decimal("0.0100"),
            token_output_rate=Decimal("0.0300"),
            tool_call_rate=Decimal("0.0100"),
        )
        enterprise = factory.Trait(
            model_tier="enterprise",
            token_input_rate=Decimal("0.0500"),
            token_output_rate=Decimal("0.1500"),
            tool_call_rate=Decimal("0.0200"),
        )


class BillingHoldFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = BillingHold

    run = factory.SubFactory("apps.runs.factories.RunFactory")
    wallet = factory.LazyAttribute(lambda o: _funded_wallet_for_hold(o.run))
    amount_reserved_usd = Decimal("10.00")
    status = HoldStatus.ACTIVE
    expires_at = factory.LazyFunction(lambda: timezone.now() + timezone.timedelta(hours=1))

    class Params:
        settled = factory.Trait(
            status=HoldStatus.SETTLED,
            amount_consumed_usd=Decimal("5.00"),
            settled_at=factory.LazyFunction(timezone.now),
        )
        released = factory.Trait(status=HoldStatus.RELEASED)
        expired = factory.Trait(status=HoldStatus.EXPIRED)


def _funded_wallet_for_hold(run):
    wallet = CreditWalletFactory(workspace=run.workspace)
    if wallet.available() < Decimal("100.00"):
        wallet.record_dodo_credit_grant(
            Decimal("100.00"),
            dodo_payment_id=f"hold-factory-{uuid.uuid4().hex}",
        )
    return wallet
