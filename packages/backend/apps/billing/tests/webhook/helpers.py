from __future__ import annotations

from types import SimpleNamespace

from apps.billing.services.webhooks import _process_event


def make_payment_event(
    payment_id: str = "pay_123",
    event_type: str = "payment.succeeded",
    metadata: dict | None = None,
    status: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        type=event_type,
        business_id="biz_1",
        data=SimpleNamespace(
            payment_id=payment_id,
            metadata=metadata or {},
            status=status,
        ),
    )


def process_test_event(
    event: SimpleNamespace,
    raw_body: str = "{}",
    *,
    event_id: str | None = None,
) -> bool:
    return _process_event(event, raw_body, event_id=event_id or webhook_id(event))


def webhook_id(event: SimpleNamespace) -> str:
    data = event.data
    resource_id = getattr(data, "refund_id", None) or getattr(data, "payment_id", "ignored")
    return f"evt_{event.type}_{resource_id}"
