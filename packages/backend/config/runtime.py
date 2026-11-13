from __future__ import annotations

from pathlib import Path
from typing import Literal, Self

from pydantic import Field, PostgresDsn, RedisDsn, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Runtime(BaseSettings):
    """Process-level runtime config. The single source of truth for env-driven values.

    Django settings modules import this and project values onto Django globals;
    nothing else should call ``os.environ`` directly.
    """

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
        case_sensitive=False,
    )

    environment: Literal["dev", "test", "staging", "prod"] = "dev"
    debug: bool = False
    secret_key: str = Field(min_length=16)
    allowed_hosts: list[str] = Field(default_factory=list)
    port: int = Field(default=8000, gt=0, le=65535)

    database_url: PostgresDsn
    redis_url: RedisDsn
    celery_broker_url: RedisDsn | None = None

    sentry_dsn: str | None = None
    posthog_api_key: str | None = None
    posthog_host: str = "https://us.i.posthog.com"
    otel_exporter_otlp_endpoint: str | None = None

    frontend_url: str = "http://localhost:4321"

    secure_ssl_redirect: bool = False
    csrf_trusted_origins: list[str] = Field(default_factory=list)
    cors_allowed_origins: list[str] = Field(default_factory=list)

    # Dodo Payments (Merchant of Record). ``dodo_environment`` mirrors the SDK's
    # ``environment`` kwarg — ``"test_mode"`` or ``"live_mode"``.
    dodo_api_key: str = ""
    dodo_webhook_key: str = ""
    dodo_environment: Literal["test_mode", "live_mode"] = "test_mode"
    dodo_return_url: str = ""
    dodo_cancel_url: str = ""
    dodo_credit_product_ids: dict[str, str] = Field(default_factory=dict)
    dodo_credit_entitlement_id: str = ""

    # E2B sandbox runtime
    e2b_api_key: str = ""
    e2b_template_id: str = ""
    # Static API key the sandbox agent server expects as X-API-Key on /runs.
    sandbox_server_api_key: str = ""

    # Manifest signing (Ed25519)
    midsphere_manifest_key_id: str = ""
    midsphere_manifest_private_key: str = ""
    manifest_expiry_seconds: int = Field(default=300, gt=0)

    # Capability JWT minting (EdDSA / Ed25519)
    midsphere_jwt_key_id: str = ""
    midsphere_jwt_private_key: str = ""
    capability_token_ttl_seconds: int = Field(default=1800, gt=0)

    # Callback ingestion
    backend_public_url: str = ""
    callback_ingestion_path: str = Field(default="/webhooks/sandbox/callbacks", pattern=r"^/")
    callback_hmac_secret_length: int = Field(default=32, ge=32)
    fernet_encryption_key: str = ""

    # Sandbox pool
    sandbox_pool_max_warm: int = Field(default=2, ge=0)
    sandbox_pool_max_per_agent: int = Field(default=5, ge=1)
    sandbox_max_idle_seconds: int = Field(default=600, gt=0)
    sandbox_boot_timeout_seconds: int = Field(default=30, gt=0)
    sandbox_resume_timeout_seconds: int = Field(default=15, gt=0)
    sandbox_grace_period_seconds: int = Field(default=60, gt=0)

    # HITL + housekeeping
    hitl_timeout_seconds: int = Field(default=300, gt=0)
    run_manifest_record_retention_days: int = Field(default=30, ge=1)
    sandbox_domain: str = "run.midsphere.com"

    # DigitalOcean Spaces (S3-compatible). When ``use_object_storage`` is False
    # we fall back to local filesystem storage in dev/test.
    use_object_storage: bool = False
    spaces_bucket: str = ""
    spaces_region: str = ""
    spaces_endpoint: str = ""
    spaces_access_key: str = ""
    spaces_secret_key: str = ""
    spaces_cdn_domain: str | None = None

    @model_validator(mode="after")
    def validate_object_storage(self) -> Self:
        if self.use_object_storage:
            self._require_object_storage_settings()
        return self

    def _require_object_storage_settings(self) -> None:
        missing = [
            name
            for name in (
                "spaces_bucket",
                "spaces_region",
                "spaces_endpoint",
                "spaces_access_key",
                "spaces_secret_key",
            )
            if not getattr(self, name)
        ]
        if missing:
            names = ", ".join(missing)
            raise ValueError(f"Object storage enabled but missing: {names}.")


runtime = Runtime()  # type: ignore[call-arg]
