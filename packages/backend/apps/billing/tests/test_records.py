from __future__ import annotations

from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.utils import timezone

from apps.billing.factories import (
    CreditWalletFactory,
    LedgerEntryFactory,
    TopupFactory,
    WebhookDeliveryFactory,
)
from apps.billing.models import (
    LedgerEntry,
    LedgerKind,
    Topup,
    TopupStatus,
    WebhookDelivery,
)
from apps.core.exceptions import Conflict

pytestmark = pytest.mark.django_db


def test_ledger_entry_save_blocks_updates() -> None:
    entry = LedgerEntryFactory()
    entry.note = "tampered"
    with pytest.raises(Conflict, match="append-only"):
        entry.save()


def test_ledger_entry_delete_is_blocked() -> None:
    entry = LedgerEntryFactory()
    with pytest.raises(Conflict, match="append-only"):
        entry.delete()


def test_ledger_entry_adjustment_requires_note_at_save() -> None:
    wallet = CreditWalletFactory()
    entry = LedgerEntry(
        wallet=wallet,
        delta_usd=Decimal("1.00"),
        kind=LedgerKind.ADJUSTMENT,
        reference="r",
        note="",
    )
    with pytest.raises(Conflict, match="non-empty note"):
        entry.save()


def test_ledger_entry_requires_reference_at_save() -> None:
    wallet = CreditWalletFactory()
    entry = LedgerEntry(
        wallet=wallet,
        delta_usd=Decimal("1.00"),
        kind=LedgerKind.TOPUP,
        reference=" ",
    )
    with pytest.raises(Conflict, match="reference"):
        entry.save()


def test_ledger_entry_rejects_unknown_kind_at_save() -> None:
    wallet = CreditWalletFactory()
    entry = LedgerEntry(
        wallet=wallet,
        delta_usd=Decimal("1.00"),
        kind="bogus",
        reference="r",
    )
    with pytest.raises(Conflict, match="Unknown ledger kind"):
        entry.save()


def test_ledger_entry_create_recomputes_wallet_balance_from_sum() -> None:
    wallet = CreditWalletFactory()
    wallet.balance_usd = Decimal("99.00")
    wallet.save(update_fields=("balance_usd", "updated_at"))
    LedgerEntry.objects.create(
        wallet=wallet,
        delta_usd=Decimal("5.00"),
        kind=LedgerKind.TOPUP,
        reference="direct",
    )
    wallet.refresh_from_db()
    assert wallet.balance_usd == Decimal("5.0000")


def test_ledger_entry_queryset_update_and_delete_are_blocked() -> None:
    entry = LedgerEntryFactory()
    with pytest.raises(Conflict, match="append-only"):
        LedgerEntry.objects.filter(pk=entry.pk).update(note="tampered")
    with pytest.raises(Conflict, match="append-only"):
        LedgerEntry.objects.filter(pk=entry.pk).delete()


def test_ledger_entry_base_manager_update_and_delete_are_blocked() -> None:
    entry = LedgerEntryFactory()
    with pytest.raises(Conflict, match="append-only"):
        LedgerEntry._base_manager.filter(pk=entry.pk).update(note="tampered")
    with pytest.raises(Conflict, match="append-only"):
        LedgerEntry._base_manager.filter(pk=entry.pk).delete()


def test_ledger_entry_queryset_bulk_create_is_blocked() -> None:
    wallet = CreditWalletFactory()
    entry = LedgerEntry(
        wallet=wallet,
        delta_usd=Decimal("10.00"),
        kind=LedgerKind.TOPUP,
        reference="bulk",
    )
    with pytest.raises(Conflict, match="bulk_create"):
        LedgerEntry.objects.all().bulk_create([entry])


def test_ledger_entry_creation_is_historical() -> None:
    entry = LedgerEntryFactory()
    assert entry.history.count() == 1


def test_topup_idempotency_key_is_unique_at_db_level() -> None:
    wallet = CreditWalletFactory()
    TopupFactory(wallet=wallet, idempotency_key="dup")
    with pytest.raises(IntegrityError):
        TopupFactory(wallet=wallet, idempotency_key="dup")


def test_topup_dodo_payment_id_is_unique_when_set() -> None:
    wallet = CreditWalletFactory()
    TopupFactory(wallet=wallet, dodo_payment_id="pay_123")
    with pytest.raises(IntegrityError):
        TopupFactory(wallet=wallet, dodo_payment_id="pay_123")


def test_topup_blank_dodo_payment_ids_dont_collide() -> None:
    wallet = CreditWalletFactory()
    TopupFactory(wallet=wallet, dodo_payment_id="")
    TopupFactory(wallet=wallet, dodo_payment_id="")


def test_topup_confirm_sets_succeeded_and_payment_id() -> None:
    topup = TopupFactory(status=TopupStatus.PENDING)
    topup.confirm("pay_dodo_123")
    topup.refresh_from_db()
    assert topup.status == TopupStatus.SUCCEEDED
    assert topup.dodo_payment_id == "pay_dodo_123"


def test_topup_confirm_rejects_non_pending() -> None:
    topup = TopupFactory(status=TopupStatus.PENDING)
    topup.confirm("pay_1")
    with pytest.raises(Conflict, match="pending"):
        topup.confirm("pay_2")


def test_topup_confirm_rejects_empty_payment_id() -> None:
    topup = TopupFactory(status=TopupStatus.PENDING)
    with pytest.raises(Conflict, match="non-empty"):
        topup.confirm("")
    with pytest.raises(Conflict, match="non-empty"):
        topup.confirm("   ")


def test_topup_fail_sets_failed_status() -> None:
    topup = TopupFactory(status=TopupStatus.PENDING)
    topup.fail()
    topup.refresh_from_db()
    assert topup.status == TopupStatus.FAILED


def test_topup_fail_rejects_non_pending() -> None:
    topup = TopupFactory(status=TopupStatus.PENDING)
    topup.fail()
    with pytest.raises(Conflict, match="pending"):
        topup.fail()


def test_topup_save_rejects_non_positive_amount() -> None:
    wallet = CreditWalletFactory()
    bad = Topup(wallet=wallet, amount_usd=Decimal("0"), idempotency_key="zero")
    with pytest.raises(Conflict, match="positive"):
        bad.save()


def test_topup_save_rejects_unsupported_amount() -> None:
    wallet = CreditWalletFactory()
    bad = Topup(wallet=wallet, amount_usd=Decimal("25.00"), idempotency_key="bad")
    with pytest.raises(Conflict, match=r"\$20\.00"):
        bad.save()


def test_topup_save_rejects_blank_idempotency_key() -> None:
    wallet = CreditWalletFactory()
    bad = Topup(wallet=wallet, amount_usd=Decimal("20.00"), idempotency_key=" ")
    with pytest.raises(Conflict, match="idempotency key"):
        bad.save()


def test_topup_save_rejects_unknown_status() -> None:
    topup = TopupFactory.build(status="unknown")
    with pytest.raises(Conflict, match="status"):
        topup.save()


def test_topup_amount_constraint_blocks_queryset_update() -> None:
    topup = TopupFactory()
    with pytest.raises(IntegrityError):
        Topup.objects.filter(pk=topup.pk).update(amount_usd=Decimal("25.00"))


def test_topup_status_constraint_blocks_queryset_update() -> None:
    topup = TopupFactory()
    with pytest.raises(IntegrityError):
        Topup.objects.filter(pk=topup.pk).update(status="unknown")


def test_topup_idempotency_key_constraint_blocks_queryset_update() -> None:
    topup = TopupFactory()
    with pytest.raises(IntegrityError):
        Topup.objects.filter(pk=topup.pk).update(idempotency_key="")


def test_webhook_delivery_unique_per_provider_event_id() -> None:
    WebhookDeliveryFactory(provider="dodo", event_id="evt_1")
    with pytest.raises(IntegrityError):
        WebhookDeliveryFactory(provider="dodo", event_id="evt_1")


def test_webhook_delivery_same_event_id_different_provider_ok() -> None:
    WebhookDeliveryFactory(provider="dodo", event_id="evt_1")
    WebhookDeliveryFactory(provider="sandbox", event_id="evt_1")
    assert WebhookDelivery.objects.count() == 2


def test_webhook_delivery_rejects_unknown_provider() -> None:
    delivery = WebhookDelivery(provider="stripe", event_id="evt_x")
    with pytest.raises(ValidationError, match="Unknown provider"):
        delivery.save()


def test_webhook_delivery_rejects_blank_event_id() -> None:
    delivery = WebhookDelivery(provider="dodo", event_id=" ")
    with pytest.raises(ValidationError, match="event ID"):
        delivery.save()


def test_webhook_delivery_provider_constraint_blocks_queryset_update() -> None:
    delivery = WebhookDeliveryFactory()
    with pytest.raises(IntegrityError):
        WebhookDelivery.objects.filter(pk=delivery.pk).update(provider="stripe")


def test_webhook_delivery_event_id_constraint_blocks_queryset_update() -> None:
    delivery = WebhookDeliveryFactory()
    with pytest.raises(IntegrityError):
        WebhookDelivery.objects.filter(pk=delivery.pk).update(event_id="")


def test_webhook_delivery_mark_processed_is_one_shot() -> None:
    delivery = WebhookDeliveryFactory()
    before = timezone.now()
    delivery.mark_processed()
    delivery.refresh_from_db()
    assert delivery.processed_at is not None
    assert delivery.processed_at >= before
    with pytest.raises(Conflict, match="already processed"):
        delivery.mark_processed()


def test_webhook_delivery_mark_processed_checks_database_state() -> None:
    delivery = WebhookDeliveryFactory()
    stale = WebhookDelivery.objects.get(pk=delivery.pk)
    delivery.mark_processed()
    with pytest.raises(Conflict, match="already processed"):
        stale.mark_processed()


def test_webhook_delivery_processing_is_historical() -> None:
    delivery = WebhookDeliveryFactory()
    assert delivery.history.count() == 1
    delivery.mark_processed()
    assert delivery.history.count() == 2
