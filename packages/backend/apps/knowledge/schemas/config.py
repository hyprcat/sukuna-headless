from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class KnowledgeFormat(BaseModel):
    model_config = ConfigDict(frozen=True)

    max_description_length: int = 4000
    max_file_size_bytes: int = 50_000_000
    max_source_config_bytes: int = 32_000
    allowed_content_types: tuple[str, ...] = (
        "application/pdf",
        "text/plain",
        "text/csv",
        "text/markdown",
        "application/json",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
