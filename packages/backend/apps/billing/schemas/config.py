"""Pydantic configuration models for the billing app.

Per BACKEND_CODING_STANDARDS §2 — no module-level globals; every grouped
collection of values lives on a frozen `BaseModel` and is instantiated at
the use site. Each model below is the single source of truth for the
constants its consumers need.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class BillingFormat(BaseModel):
    """Currency, precision, and fixed top-up amounts for the credit wallet.

    `decimal_places=4` lets us record sub-cent debits (per-token model
    pricing easily falls below a cent). Presentation rounds to 2 places.
    """

    model_config = ConfigDict(frozen=True)

    currency: str = "USD"
    max_digits: int = 14
    decimal_places: int = 4
    allowed_topup_amounts: tuple[Decimal, ...] = (
        Decimal("20.00"),
        Decimal("50.00"),
        Decimal("100.00"),
        Decimal("500.00"),
    )
    ledger_event_suffixes: dict[str, str] = {
        "topup": "topped_up",
        "run_debit": "debited",
        "refund": "refunded",
        "adjustment": "adjusted",
    }


class WebhookProviders(BaseModel):
    """Closed vocabulary of providers `WebhookDelivery` will accept.

    Phase 4 ships ``"dodo"``; the sandbox metering receiver in the blocked
    section uses ``"sandbox"``. Both reuse this dedup table — defined now
    so neither phase needs to retrofit the schema.
    """

    model_config = ConfigDict(frozen=True)

    values: frozenset[str] = frozenset({"dodo", "sandbox"})


class DodoWebhookConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    handled_events: frozenset[str] = frozenset(
        {
            "payment.succeeded",
            "payment.failed",
            "payment.processing",
            "payment.cancelled",
            "refund.succeeded",
            "credit.balance_low",
        }
    )
    payment_event_prefix: str = "payment."
    webhook_id_header: str = "webhook-id"
    succeeded_payment_status: str = "succeeded"
    failed_payment_statuses: frozenset[str] = frozenset({"failed", "cancelled"})


class DodoSyncConfig(BaseModel):
    """Retry and backoff parameters for async Dodo credit sync tasks."""

    model_config = ConfigDict(frozen=True)

    max_attempts: int = 3
    backoff_seconds: tuple[int, ...] = (30, 120, 480)
