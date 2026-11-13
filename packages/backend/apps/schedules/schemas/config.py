from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ScheduleFormat(BaseModel):
    model_config = ConfigDict(frozen=True)

    max_cron_expression_length: int = 120
    max_prompt_length: int = 64_000
    max_output_routes: int = 4
    max_retry_attempts: int = 5
    max_description_length: int = 2000
