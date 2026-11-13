from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class AgentFormat(BaseModel):
    model_config = ConfigDict(frozen=True)

    max_description_length: int = 4000
    max_system_prompt_length: int = 32_000
    max_tools_per_agent: int = 64
    max_knowledge_per_agent: int = 32
