from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import strawberry

from apps.api_keys.principals import SessionPrincipal
from apps.billing.api.mutations import BillingMutation
from apps.billing.factories import CreditWalletFactory, TopupFactory
from apps.billing.models import LedgerKind, Topup
from apps.billing.models.topup import TopupStatus
from apps.billing.services.dodo import create_topup
from apps.core.exceptions import BillingError, Conflict
from apps.workspaces.factories import WorkspaceMemberFactory
from apps.workspaces.models.member import WorkspaceRole

_PATCH_LINK = "apps.billing.services.dodo.dodo_payments.create_payment_link"
_PATCH_EVENT = "apps.billing.services.dodo.record_event"
_PATCH_ENSURE = "apps.billing.services.dodo.ensure_dodo_customer"

pytestmark = pytest.mark.django_db


class TestCreateTopup:
    def test_happy_path(self) -> None:
        wallet = CreditWalletFactory()
        checkout_url = "https://checkout.dodopayments.com/session-1"
        with (
            patch(_PATCH_LINK, return_value=checkout_url) as mock_link,
            patch(_PATCH_EVENT) as mock_event,
            patch(_PATCH_ENSURE, return_value="cust_abc") as mock_ensure,
        ):
            topup, url = create_topup(wallet, Decimal("20.00"), "key-1")

        assert topup.status == TopupStatus.PENDING
        assert topup.amount_usd == Decimal("20.00")
        assert topup.wallet_id == wallet.pk
        assert url == checkout_url
        mock_ensure.assert_called_once_with(wallet.workspace)
        mock_link.assert_called_once_with(
            amount=Decimal("20.00"),
            currency="USD",
            reference=str(topup.pk),
            idempotency_key="key-1",
            customer_id="cust_abc",
        )
        mock_event.assert_called_once_with(
            "topup_initiated",
            distinct_id=str(wallet.workspace_id),
            properties={
                "amount_usd": "20.00",
                "currency": "USD",
                "idempotency_key": "key-1",
            },
        )

    def test_idempotent_same_key(self) -> None:
        wallet = CreditWalletFactory()
        with (
            patch(_PATCH_LINK, return_value="https://dodo.com/s1"),
            patch(_PATCH_EVENT),
            patch(_PATCH_ENSURE, return_value="cust_1"),
        ):
            topup1, _url1 = create_topup(wallet, Decimal("50.00"), "key-2")

        with (
            patch(_PATCH_LINK, return_value="https://dodo.com/s2"),
            patch(_PATCH_EVENT),
            patch(_PATCH_ENSURE, return_value="cust_1"),
        ):
            topup2, url2 = create_topup(wallet, Decimal("50.00"), "key-2")

        assert topup1.pk == topup2.pk
        assert url2 == "https://dodo.com/s2"

    def test_rejects_settled_topup(self) -> None:
        wallet = CreditWalletFactory()
        TopupFactory(
            wallet=wallet,
            amount_usd=Decimal("20.00"),
            idempotency_key="key-3",
            status=TopupStatus.SUCCEEDED,
        )

        with pytest.raises(Conflict, match="already settled"):
            create_topup(wallet, Decimal("20.00"), "key-3")

    def test_rejects_failed_topup(self) -> None:
        wallet = CreditWalletFactory()
        TopupFactory(
            wallet=wallet,
            amount_usd=Decimal("100.00"),
            idempotency_key="key-4",
            status=TopupStatus.FAILED,
        )

        with pytest.raises(Conflict, match="already settled"):
            create_topup(wallet, Decimal("100.00"), "key-4")

    def test_invalid_amount_rejected(self) -> None:
        wallet = CreditWalletFactory()
        with pytest.raises(Conflict, match="must be one of"):
            create_topup(wallet, Decimal("42.00"), "key-5")

    def test_no_event_on_settled_rejection(self) -> None:
        wallet = CreditWalletFactory()
        TopupFactory(
            wallet=wallet,
            amount_usd=Decimal("20.00"),
            idempotency_key="key-settled",
            status=TopupStatus.SUCCEEDED,
        )
        with patch(_PATCH_EVENT) as mock_event, pytest.raises(Conflict):
            create_topup(wallet, Decimal("20.00"), "key-settled")
        mock_event.assert_not_called()

    def test_dodo_failure_propagates(self) -> None:
        wallet = CreditWalletFactory()
        with (
            patch(_PATCH_LINK, side_effect=BillingError("Dodo API error")),
            patch(_PATCH_ENSURE, return_value="cust_err"),
            pytest.raises(BillingError, match="Dodo API error"),
        ):
            create_topup(wallet, Decimal("20.00"), "key-6")
        assert Topup.objects.filter(idempotency_key="key-6").exists()

    def test_customer_created_before_payment_link(self) -> None:
        wallet = CreditWalletFactory()
        call_order: list[str] = []
        with (
            patch(
                _PATCH_ENSURE,
                side_effect=lambda w: (call_order.append("ensure"), "cust_x")[1],
            ),
            patch(
                _PATCH_LINK,
                side_effect=lambda **kw: (call_order.append("link"), "https://dodo.com/s")[1],
            ),
            patch(_PATCH_EVENT),
        ):
            create_topup(wallet, Decimal("20.00"), "key-order")
        assert call_order == ["ensure", "link"]


class TestIdempotencyKeyCollision:
    def test_same_key_different_wallet_rejected_at_service_level(self) -> None:
        wallet_a = CreditWalletFactory()
        wallet_b = CreditWalletFactory()
        with (
            patch(_PATCH_LINK, return_value="https://dodo.com/s"),
            patch(_PATCH_EVENT),
            patch(_PATCH_ENSURE, return_value="cust_a"),
        ):
            create_topup(wallet_a, Decimal("20.00"), "shared-key")

        with pytest.raises(Conflict, match="different top-up"):
            create_topup(wallet_b, Decimal("20.00"), "shared-key")

    def test_same_key_different_amount_rejected_at_service_level(self) -> None:
        wallet = CreditWalletFactory()
        with (
            patch(_PATCH_LINK, return_value="https://dodo.com/s"),
            patch(_PATCH_EVENT),
            patch(_PATCH_ENSURE, return_value="cust_b"),
        ):
            create_topup(wallet, Decimal("20.00"), "key-amt")

        with pytest.raises(Conflict, match="different top-up"):
            create_topup(wallet, Decimal("50.00"), "key-amt")

    def test_same_key_same_params_returns_same_topup(self) -> None:
        wallet = CreditWalletFactory()
        with (
            patch(_PATCH_LINK, return_value="https://dodo.com/s"),
            patch(_PATCH_EVENT),
            patch(_PATCH_ENSURE, return_value="cust_c"),
        ):
            topup1, _url1 = create_topup(wallet, Decimal("100.00"), "key-idem")
            topup2, _url2 = create_topup(wallet, Decimal("100.00"), "key-idem")

        assert topup1.pk == topup2.pk
        assert Topup.objects.filter(idempotency_key="key-idem").count() == 1


class TestDoubleSpendOnRetry:
    def test_retry_after_dodo_failure_reuses_pending_topup(self) -> None:
        wallet = CreditWalletFactory()
        with (
            patch(_PATCH_LINK, side_effect=BillingError("Dodo timeout")),
            patch(_PATCH_ENSURE, return_value="cust_retry"),
            pytest.raises(BillingError),
        ):
            create_topup(wallet, Decimal("50.00"), "retry-key")

        assert Topup.objects.filter(idempotency_key="retry-key").exists()

        with (
            patch(_PATCH_LINK, return_value="https://dodo.com/s2"),
            patch(_PATCH_EVENT),
            patch(_PATCH_ENSURE, return_value="cust_retry"),
        ):
            topup, url = create_topup(wallet, Decimal("50.00"), "retry-key")

        assert topup.status == TopupStatus.PENDING
        assert url == "https://dodo.com/s2"
        assert Topup.objects.filter(idempotency_key="retry-key").count() == 1

    def test_retry_after_success_does_not_create_duplicate(self) -> None:
        wallet = CreditWalletFactory()
        with (
            patch(_PATCH_LINK, return_value="https://dodo.com/s"),
            patch(_PATCH_EVENT),
            patch(_PATCH_ENSURE, return_value="cust_dup"),
        ):
            topup, _ = create_topup(wallet, Decimal("20.00"), "settled-key")

        topup.confirm("pay_settled")
        wallet.record_dodo_credit_grant(Decimal("20.00"), dodo_payment_id="pay_settled")

        with pytest.raises(Conflict, match="already settled"):
            create_topup(wallet, Decimal("20.00"), "settled-key")

        assert wallet.entries.filter(kind=LedgerKind.TOPUP).count() == 1

    def test_concurrent_debit_cannot_oversell(self) -> None:
        wallet = CreditWalletFactory()
        wallet.record_dodo_credit_grant(Decimal("50.00"), dodo_payment_id="seed")

        wallet.debit(Decimal("30.00"), reason="run_1", reference="run_1")

        with pytest.raises(BillingError, match="Insufficient"):
            wallet.debit(Decimal("30.00"), reason="run_2", reference="run_2")

        wallet.refresh_from_db()
        assert wallet.balance_usd == Decimal("20.0000")

    def test_webhook_succeeded_then_retry_create_topup_raises(self) -> None:
        wallet = CreditWalletFactory()
        TopupFactory(
            wallet=wallet,
            amount_usd=Decimal("20.00"),
            idempotency_key="webhook-first",
            status=TopupStatus.SUCCEEDED,
            dodo_payment_id="pay_wh",
        )
        with pytest.raises(Conflict, match="already settled"):
            create_topup(wallet, Decimal("20.00"), "webhook-first")


# --- GraphQL API integration tests (formerly test_api.py) ---


@strawberry.type
class _Q:
    @strawberry.field
    def health(self) -> str:
        return "ok"


@strawberry.type
class _M(BillingMutation):
    pass


_schema = strawberry.Schema(query=_Q, mutation=_M)

_CREATE_TOPUP = """
mutation Create($input: CreateTopupInput!) {
    createTopup(input: $input) {
        success
        errors { code field message }
        hostedCheckoutUrl
        topup { amountUsd currency idempotencyKey status dodoPaymentId }
    }
}
"""


def _ctx(member, *, workspace=None):
    principal = SessionPrincipal(user=member.user, member=member, role=member.role)
    return SimpleNamespace(workspace=workspace or member.workspace, principal=principal)


class TestCreateTopupApi:
    def test_schema_uses_input_contract(self) -> None:
        sdl = str(_schema)
        assert "createTopup(input:" in sdl
        assert "hostedCheckoutUrl" in sdl
        assert "input CreateTopupInput" in sdl

    def test_admin_session_returns_checkout_url(self) -> None:
        member = WorkspaceMemberFactory(role=WorkspaceRole.ADMIN)
        CreditWalletFactory(workspace=member.workspace)
        checkout_url = "https://checkout.dodopayments.com/session-1"

        with (
            patch("apps.billing.services.dodo.ensure_dodo_customer", return_value="cust_1"),
            patch(
                "apps.billing.services.dodo.dodo_payments.create_payment_link",
                return_value=checkout_url,
            ),
            patch("apps.billing.services.dodo.record_event"),
        ):
            result = _schema.execute_sync(
                _CREATE_TOPUP,
                variable_values={"input": {"amount": Decimal("20.00"), "idempotencyKey": "idem-1"}},
                context_value=_ctx(member),
            )

        assert result.errors is None
        data = result.data["createTopup"]
        assert data["success"] is True
        assert data["hostedCheckoutUrl"] == checkout_url
        assert data["topup"]["idempotencyKey"] == "idem-1"
        assert data["topup"]["status"] == "PENDING"

    def test_permission_errors_use_payload(self) -> None:
        member = WorkspaceMemberFactory(role=WorkspaceRole.EDITOR)
        CreditWalletFactory(workspace=member.workspace)

        result = _schema.execute_sync(
            _CREATE_TOPUP,
            variable_values={"input": {"amount": Decimal("20.00"), "idempotencyKey": "blocked"}},
            context_value=_ctx(member),
        )

        assert result.errors is None
        data = result.data["createTopup"]
        assert data["success"] is False
        assert data["errors"][0]["code"] == "PERMISSION_DENIED"
        assert not Topup.objects.filter(idempotency_key="blocked").exists()

    def test_missing_wallet_returns_not_found(self) -> None:
        member = WorkspaceMemberFactory(role=WorkspaceRole.ADMIN)

        result = _schema.execute_sync(
            _CREATE_TOPUP,
            variable_values={"input": {"amount": Decimal("20.00"), "idempotencyKey": "no-wallet"}},
            context_value=_ctx(member),
        )

        assert result.errors is None
        data = result.data["createTopup"]
        assert data["success"] is False
        assert data["errors"][0]["code"] == "NOT_FOUND"

    def test_invalid_amount_returns_payload_error(self) -> None:
        member = WorkspaceMemberFactory(role=WorkspaceRole.ADMIN)
        CreditWalletFactory(workspace=member.workspace)

        result = _schema.execute_sync(
            _CREATE_TOPUP,
            variable_values={"input": {"amount": Decimal("42.00"), "idempotencyKey": "bad-amount"}},
            context_value=_ctx(member),
        )

        assert result.errors is None
        data = result.data["createTopup"]
        assert data["success"] is False
        assert data["errors"][0]["code"] == "CONFLICT"
        assert not Topup.objects.filter(idempotency_key="bad-amount").exists()
