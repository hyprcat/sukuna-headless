from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class PolicyFormat(BaseModel):
    model_config = ConfigDict(frozen=True)

    max_restrictions_per_list: int = 50
    max_restriction_length: int = 2000
    max_prompt_block_length: int = 32_000
    action_header: str = "ACTION RESTRICTIONS"
    domain_header: str = "DOMAIN RESTRICTIONS"
    output_header: str = "OUTPUT RESTRICTIONS"
