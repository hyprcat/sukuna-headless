from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.contrib import admin
from django.contrib.auth.models import Permission
from django.test import Client, RequestFactory, override_settings
from django.urls import reverse

from apps.billing.admin.topup import TopupAdmin
from apps.billing.admin.wallet import CreditWalletAdmin
from apps.billing.factories import CreditWalletFactory, TopupFactory
from apps.billing.models import CreditWallet, LedgerKind, Topup, TopupStatus
from apps.billing.services.dodo import refund_topup
from apps.core.exceptions import BillingError, Conflict
from apps.workspaces.factories import UserFactory

_PATCH_EVENT = "apps.billing.services.dodo.record_event"
_PATCH_REFUND = "apps.billing.services.dodo.dodo_payments.refund_full_payment"
_PATCH_ADMIN_REFUND = "apps.billing.admin.topup.refund_topup"

pytestmark = pytest.mark.django_db


def _staff_user():
    return UserFactory(is_staff=True)


def _grant_wallet_change(user) -> None:
    perm = Permission.objects.get(content_type__app_label="billing", codename="change_creditwallet")
    user.user_permissions.add(perm)


class TestRefundTopup:
    def test_happy_path_marks_refund_requested_no_ledger_entry(self) -> None:
        wallet = CreditWalletFactory()
        wallet.record_dodo_credit_grant(Decimal("50.00"), dodo_payment_id="seed")
        topup = TopupFactory(
            wallet=wallet,
            amount_usd=Decimal("50.00"),
            status=TopupStatus.SUCCEEDED,
            dodo_payment_id="pay_abc",
        )
        with (
            patch(_PATCH_REFUND, return_value=_refund_response("ref_abc")) as mock_refund,
            patch(_PATCH_EVENT),
        ):
            result = refund_topup(topup, reason="customer request")

        assert result.status == TopupStatus.REFUND_REQUESTED
        assert result.refund_reason == "customer request"
        assert not wallet.entries.filter(kind=LedgerKind.REFUND).exists()
        wallet.refresh_from_db()
        assert wallet.balance_usd == Decimal("50.0000")
        mock_refund.assert_called_once_with(
            payment_id="pay_abc",
            amount=Decimal("50.00"),
            reason="customer request",
            idempotency_key=f"topup-refund-{topup.pk}",
            metadata={"topup_id": str(topup.pk), "idempotency_key": f"topup-refund-{topup.pk}"},
        )

    def test_rejects_pending_topup(self) -> None:
        topup = TopupFactory(status=TopupStatus.PENDING)
        with pytest.raises(Conflict, match="Only succeeded"):
            refund_topup(topup, reason="test")

    def test_rejects_failed_topup(self) -> None:
        topup = TopupFactory(status=TopupStatus.FAILED)
        with pytest.raises(Conflict, match="Only succeeded"):
            refund_topup(topup, reason="test")

    def test_rejects_missing_payment_id(self) -> None:
        topup = TopupFactory(status=TopupStatus.SUCCEEDED, dodo_payment_id="")
        with pytest.raises(Conflict, match="no Dodo payment ID"):
            refund_topup(topup, reason="test")

    def test_rejects_already_refund_requested(self) -> None:
        wallet = CreditWalletFactory()
        wallet.record_dodo_credit_grant(Decimal("50.00"), dodo_payment_id="seed")
        topup = TopupFactory(
            wallet=wallet,
            amount_usd=Decimal("50.00"),
            status=TopupStatus.SUCCEEDED,
            dodo_payment_id="pay_dup",
        )
        with patch(_PATCH_REFUND, return_value=_refund_response("ref_1")), patch(_PATCH_EVENT):
            refund_topup(topup, reason="first")
        with pytest.raises(Conflict, match="already requested"):
            refund_topup(topup, reason="second")

    def test_rejects_already_refunded(self) -> None:
        topup = TopupFactory(status=TopupStatus.REFUNDED, dodo_payment_id="pay_done")
        with pytest.raises(Conflict, match="already been refunded"):
            refund_topup(topup, reason="again")

    def test_dodo_failure_does_not_change_topup_status(self) -> None:
        wallet = CreditWalletFactory()
        wallet.record_dodo_credit_grant(Decimal("20.00"), dodo_payment_id="seed")
        topup = TopupFactory(
            wallet=wallet,
            amount_usd=Decimal("20.00"),
            status=TopupStatus.SUCCEEDED,
            dodo_payment_id="pay_fail",
        )
        with (
            patch(_PATCH_REFUND, side_effect=BillingError("Dodo refund error")),
            pytest.raises(BillingError, match="Dodo refund error"),
        ):
            refund_topup(topup, reason="test")
        topup.refresh_from_db()
        assert topup.status == TopupStatus.SUCCEEDED

    def test_dodo_failed_status_rejected_without_status_change(self) -> None:
        wallet = CreditWalletFactory()
        wallet.record_dodo_credit_grant(Decimal("50.00"), dodo_payment_id="seed")
        topup = TopupFactory(
            wallet=wallet,
            amount_usd=Decimal("50.00"),
            status=TopupStatus.SUCCEEDED,
            dodo_payment_id="pay_status_failed",
        )
        with (
            patch(_PATCH_REFUND, return_value=SimpleNamespace(status="failed")),
            pytest.raises(BillingError, match="Dodo refund failed"),
        ):
            refund_topup(topup, reason="provider failed")
        topup.refresh_from_db()
        assert topup.status == TopupStatus.SUCCEEDED
        wallet.refresh_from_db()
        assert wallet.balance_usd == Decimal("50.0000")

    def test_emits_refund_requested_event(self) -> None:
        wallet = CreditWalletFactory()
        wallet.record_dodo_credit_grant(Decimal("100.00"), dodo_payment_id="seed")
        topup = TopupFactory(
            wallet=wallet,
            amount_usd=Decimal("100.00"),
            status=TopupStatus.SUCCEEDED,
            dodo_payment_id="pay_evt",
        )
        with patch(_PATCH_REFUND), patch(_PATCH_EVENT) as mock_event:
            refund_topup(topup, reason="customer request")
        calls = [c for c in mock_event.call_args_list if c.args[0] == "topup_refund_requested"]
        assert len(calls) == 1
        assert calls[0].kwargs["properties"]["reason"] == "customer request"

    def test_balance_unchanged_after_request(self) -> None:
        wallet = CreditWalletFactory()
        wallet.record_dodo_credit_grant(Decimal("100.00"), dodo_payment_id="seed")
        wallet.debit(Decimal("30.00"), reason="run", reference="run_1")
        topup = TopupFactory(
            wallet=wallet,
            amount_usd=Decimal("100.00"),
            status=TopupStatus.SUCCEEDED,
            dodo_payment_id="pay_nochange",
        )
        with patch(_PATCH_REFUND, return_value=_refund_response("ref_1")), patch(_PATCH_EVENT):
            refund_topup(topup, reason="refund despite partial spend")
        wallet.refresh_from_db()
        assert wallet.balance_usd == Decimal("70.0000")


def _refund_response(refund_id: str) -> SimpleNamespace:
    return SimpleNamespace(status="succeeded", refund_id=refund_id)


# ---------------------------------------------------------------------------
# Admin views — wallet adjustment + topup refund action
# ---------------------------------------------------------------------------


def test_wallet_admin_keeps_wallet_fields_read_only() -> None:
    wallet = CreditWalletFactory()
    request = RequestFactory().get("/admin/billing/creditwallet/")
    request.user = _staff_user()
    model_admin = CreditWalletAdmin(CreditWallet, admin.site)
    readonly = model_admin.get_readonly_fields(request, wallet)
    assert "workspace" in readonly
    assert not model_admin.has_add_permission(request)
    assert not model_admin.has_delete_permission(request, wallet)


@override_settings(ROOT_URLCONF="apps.billing.tests.webhook.urls")
def test_manual_adjustment_view_requires_change_permission(client: Client) -> None:
    wallet = CreditWalletFactory()
    client.force_login(_staff_user())
    response = client.get(reverse("admin:billing_creditwallet_adjust", args=[wallet.pk]))
    assert response.status_code == 403


@override_settings(ROOT_URLCONF="apps.billing.tests.webhook.urls")
def test_manual_adjustment_writes_ledger_entry(client: Client) -> None:
    wallet = CreditWalletFactory()
    wallet.record_dodo_credit_grant(Decimal("20.00"), dodo_payment_id="seed")
    user = _staff_user()
    _grant_wallet_change(user)
    client.force_login(user)
    response = client.post(
        reverse("admin:billing_creditwallet_adjust", args=[wallet.pk]),
        {
            "delta_usd": "-3.00",
            "note": "Billing correction for ticket 88",
            "reference": f"admin_{user.pk}",
        },
    )
    assert response.status_code == 302
    wallet.refresh_from_db()
    assert wallet.balance_usd == Decimal("17.0000")
    adjustment = wallet.entries.get(kind=LedgerKind.ADJUSTMENT)
    assert adjustment.reference == f"admin_{user.pk}"


@override_settings(ROOT_URLCONF="apps.billing.tests.webhook.urls")
def test_manual_adjustment_rejects_blank_reference(client: Client) -> None:
    wallet = CreditWalletFactory()
    user = _staff_user()
    _grant_wallet_change(user)
    client.force_login(user)
    response = client.post(
        reverse("admin:billing_creditwallet_adjust", args=[wallet.pk]),
        {"delta_usd": "3.00", "note": "Billing correction", "reference": " "},
    )
    assert response.status_code == 200
    assert response.context["form"].errors["reference"] == ["Reference is required."]
    assert not wallet.entries.filter(kind=LedgerKind.ADJUSTMENT).exists()


def test_topup_admin_is_read_only() -> None:
    request = RequestFactory().get("/admin/billing/topup/")
    request.user = _staff_user()
    model_admin = TopupAdmin(Topup, admin.site)
    assert not model_admin.has_add_permission(request)
    assert not model_admin.has_change_permission(request)
    assert not model_admin.has_delete_permission(request)


@override_settings(ROOT_URLCONF="apps.billing.tests.webhook.urls")
def test_topup_refund_view_requires_wallet_change_permission(client: Client) -> None:
    topup = TopupFactory(status=TopupStatus.SUCCEEDED, dodo_payment_id="pay_admin")
    client.force_login(_staff_user())
    response = client.get(reverse("admin:billing_topup_refund", args=[topup.pk]))
    assert response.status_code == 403


@override_settings(ROOT_URLCONF="apps.billing.tests.webhook.urls")
def test_topup_refund_view_calls_service(client: Client) -> None:
    topup = TopupFactory(status=TopupStatus.SUCCEEDED, dodo_payment_id="pay_admin")
    user = _staff_user()
    _grant_wallet_change(user)
    client.force_login(user)
    with patch(_PATCH_ADMIN_REFUND) as mock_refund:
        response = client.post(
            reverse("admin:billing_topup_refund", args=[topup.pk]),
            {"reason": "Customer support ticket 99"},
        )
    assert response.status_code == 302
    mock_refund.assert_called_once_with(topup, reason="Customer support ticket 99")
