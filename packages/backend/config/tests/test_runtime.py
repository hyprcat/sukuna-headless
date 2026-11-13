from __future__ import annotations

import pytest
from pydantic import ValidationError

from config.runtime import Runtime


def _runtime_kwargs(**overrides: object) -> dict[str, object]:
    kwargs: dict[str, object] = {
        "secret_key": "test-secret-key-value",
        "database_url": "postgresql://user:pass@localhost:5432/sukuna",
        "redis_url": "redis://localhost:6379/0",
    }
    kwargs.update(overrides)
    return kwargs


def test_runtime_rejects_incomplete_object_storage_settings() -> None:
    with pytest.raises(ValidationError, match="spaces_bucket"):
        Runtime(**_runtime_kwargs(use_object_storage=True))


def test_runtime_accepts_complete_object_storage_settings() -> None:
    runtime = Runtime(
        **_runtime_kwargs(
            use_object_storage=True,
            spaces_bucket="sukuna",
            spaces_region="nyc3",
            spaces_endpoint="https://nyc3.digitaloceanspaces.com",
            spaces_access_key="access",
            spaces_secret_key="secret",
        )
    )

    assert runtime.use_object_storage is True


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("manifest_expiry_seconds", 0),
        ("capability_token_ttl_seconds", 0),
        ("callback_hmac_secret_length", 31),
        ("sandbox_pool_max_warm", -1),
        ("sandbox_pool_max_per_agent", 0),
        ("sandbox_max_idle_seconds", 0),
        ("sandbox_boot_timeout_seconds", 0),
        ("sandbox_resume_timeout_seconds", 0),
        ("sandbox_grace_period_seconds", 0),
        ("hitl_timeout_seconds", 0),
        ("run_manifest_record_retention_days", 0),
    ],
)
def test_runtime_rejects_invalid_sandbox_integration_bounds(field: str, value: int) -> None:
    with pytest.raises(ValidationError, match=field):
        Runtime(**_runtime_kwargs(**{field: value}))


def test_runtime_rejects_relative_callback_ingestion_path() -> None:
    with pytest.raises(ValidationError, match="callback_ingestion_path"):
        Runtime(**_runtime_kwargs(callback_ingestion_path="webhooks/sandbox/callbacks"))
