from __future__ import annotations

import json
from pathlib import Path


def test_dodo_sandbox_recording_exists() -> None:
    recording = _recording()

    assert recording["environment"] == "test_mode"
    assert set(recording["topup_product_ids"]) == {"20.00", "50.00", "100.00", "500.00"}
    assert all(value.startswith("pdt_") for value in recording["topup_product_ids"].values())
    assert recording["checkout_session"]["host"] == "test.checkout.dodopayments.com"
    assert recording["checkout_session"]["scheme"] == "https"
    assert recording["payment_list_scan"]["statuses"] == ["succeeded", "failed"]
    assert len(recording["payment_list_scan"]["product_ids"]) == 4
    assert recording["webhook"]["id"].startswith("ep_")
    assert recording["webhook"]["secret_retrieved"] is True
    assert recording["webhook"]["filter_types"] == [
        "payment.failed",
        "payment.succeeded",
        "refund.succeeded",
    ]


def _recording() -> dict[str, object]:
    return json.loads(_recording_path().read_text())


def _recording_path() -> Path:
    return Path(__file__).resolve().parent / "recordings" / "dodo_sandbox.json"
