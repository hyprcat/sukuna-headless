from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from dodopayments import DodoPayments
from pydantic import BaseModel, ConfigDict

from config.runtime import runtime
from integrations import dodo_payments


class DodoRecordingConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    amounts: tuple[Decimal, ...] = (
        Decimal("20.00"),
        Decimal("50.00"),
        Decimal("100.00"),
        Decimal("500.00"),
    )
    cancel_url: str = "http://localhost:4321/billing/cancel"
    return_url: str = "http://localhost:4321/billing/return"
    webhook_url: str = "https://example.com/midsphere/dodo-webhook-recording"


def record_dodo_sandbox() -> dict[str, Any]:
    config = DodoRecordingConfig()
    api_key = _api_key()
    client = DodoPayments(bearer_token=api_key, environment="test_mode")
    product_ids = _ensure_products(client, config)
    _configure_runtime(api_key, product_ids, config)
    recording = _base_recording(product_ids)
    recording["checkout_session"] = _record_checkout()
    recording["payment_list_scan"] = _record_payment_list_scan(product_ids)
    recording["webhook"] = _record_webhook(client, config)
    _recording_path().write_text(json.dumps(recording, indent=2, sort_keys=True) + "\n")
    return recording


def _api_key() -> str:
    if api_key := os.environ.get("DODO_API_KEY"):
        return api_key
    return _api_key_from_cli()


def _api_key_from_cli() -> str:
    path = Path.home() / ".dodopayments" / "api-key"
    data = json.loads(path.read_text())
    value = data.get("test_mode", "")
    if isinstance(value, dict):
        value = value.get("apiKey") or value.get("api_key") or ""
    if not isinstance(value, str) or not value:
        raise RuntimeError("Dodo test-mode API key was not found.")
    return value


def _ensure_products(
    client: DodoPayments,
    config: DodoRecordingConfig,
) -> dict[str, str]:
    products = _products_by_amount(client)
    for amount in config.amounts:
        key = _amount_key(amount)
        if key not in products:
            products[key] = _create_product(client, amount)
    return products


def _products_by_amount(client: DodoPayments) -> dict[str, str]:
    page = client.products.list(page_size=100)
    products: dict[str, str] = {}
    for product in getattr(page, "items", []):
        metadata = getattr(product, "metadata", {}) or {}
        if metadata.get("purpose") == "midsphere_test_topup":
            products[metadata.get("amount_usd", "")] = product.product_id
    return products


def _create_product(client: DodoPayments, amount: Decimal) -> str:
    amount_key = _amount_key(amount)
    product = client.products.create(
        name=f"Midsphere test top-up USD {amount.quantize(Decimal('1'))}",
        description=f"Test-mode Midsphere prepaid credit top-up for USD {amount_key}.",
        tax_category="saas",
        metadata={"purpose": "midsphere_test_topup", "amount_usd": amount_key},
        price=_product_price(amount),
    )
    return product.product_id


def _product_price(amount: Decimal) -> dict[str, object]:
    return {
        "type": "one_time_price",
        "currency": "USD",
        "price": int(amount * Decimal("100")),
        "discount": 0,
        "purchasing_power_parity": False,
    }


def _configure_runtime(
    api_key: str,
    product_ids: dict[str, str],
    config: DodoRecordingConfig,
) -> None:
    runtime.dodo_api_key = api_key
    runtime.dodo_webhook_key = "retrieved-during-recording"
    runtime.dodo_environment = "test_mode"
    runtime.dodo_return_url = config.return_url
    runtime.dodo_cancel_url = config.cancel_url
    runtime.dodo_credit_product_ids = product_ids
    dodo_payments._client.cache_clear()


def _base_recording(product_ids: dict[str, str]) -> dict[str, Any]:
    return {
        "recorded_at": datetime.now(UTC).isoformat(),
        "environment": "test_mode",
        "topup_product_ids": product_ids,
    }


def _record_checkout() -> dict[str, Any]:
    url = dodo_payments.create_payment_link(
        Decimal("20.00"),
        "USD",
        f"recording-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}",
        f"dodo-recording-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}",
    )
    parsed = urlparse(url)
    return {"host": parsed.netloc, "scheme": parsed.scheme, "url_length": len(url)}


def _record_payment_list_scan(product_ids: dict[str, str]) -> dict[str, Any]:
    statuses = ("succeeded", "failed")
    return {
        "product_ids": sorted(set(product_ids.values())),
        "statuses": list(statuses),
        "payments": _record_payment_lists(statuses),
    }


def _record_payment_lists(statuses: tuple[str, ...]) -> list[dict[str, Any]]:
    end = datetime.now(UTC)
    start = end - timedelta(days=1)
    results: list[dict[str, Any]] = []
    for product_id in dict.fromkeys(runtime.dodo_credit_product_ids.values()):
        for status in statuses:
            for payment in dodo_payments.list_payments(
                created_at_gte=start,
                created_at_lte=end,
                status=status,
                product_id=product_id,
            ):
                results.append(_payment_summary(payment))
    return results


def _payment_summary(payment: object) -> dict[str, str | int]:
    return {
        "payment_id": str(getattr(payment, "payment_id", "")),
        "status": str(getattr(payment, "status", "")),
        "currency": str(getattr(payment, "currency", "")),
        "total_amount": int(getattr(payment, "total_amount", 0)),
    }


def _record_webhook(
    client: DodoPayments,
    config: DodoRecordingConfig,
) -> dict[str, Any]:
    webhook = _ensure_webhook(client, config)
    secret = client.webhooks.retrieve_secret(webhook.id)
    return {
        "id": webhook.id,
        "url": webhook.url,
        "filter_types": sorted(webhook.filter_types),
        "secret_retrieved": bool(secret.secret),
    }


def _ensure_webhook(client: DodoPayments, config: DodoRecordingConfig) -> Any:
    page = client.webhooks.list(limit=100)
    for webhook in getattr(page, "data", []):
        if webhook.url == config.webhook_url:
            return webhook
    return client.webhooks.create(
        url=config.webhook_url,
        description="Midsphere test recording webhook",
        filter_types=["payment.succeeded", "payment.failed", "refund.succeeded"],
    )


def _recording_path() -> Path:
    path = Path(__file__).resolve().parent / "recordings" / "dodo_sandbox.json"
    path.parent.mkdir(exist_ok=True)
    return path


def _amount_key(amount: Decimal) -> str:
    return format(amount.quantize(Decimal("0.01")), "f")


if __name__ == "__main__":
    record_dodo_sandbox()
