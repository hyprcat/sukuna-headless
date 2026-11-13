from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ToolFormat(BaseModel):
    model_config = ConfigDict(frozen=True)

    max_description_length: int = 4000
    max_parameters_keys: int = 64
    max_parameter_schema_bytes: int = 32_000
