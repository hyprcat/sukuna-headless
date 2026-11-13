from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class EndUserFormat(BaseModel):
    model_config = ConfigDict(frozen=True)

    max_metadata_bytes: int = 16_384
    control_update_fields: tuple[str, ...] = (
        "credits",
        "credit_grant_per_period",
        "run_count_limit",
        "run_count_period",
        "sandbox_time_seconds",
        "concurrency_max",
        "model_tier",
        "credit_refresh_schedule",
    )
    refresh_schedule_presets: frozenset[str] = frozenset(
        {"", "daily", "weekly", "monthly", "never"}
    )
