"""RunRequest — the payload the backend sends into the sandbox at run start.

Built once per run by `apps/runs/services/sandbox_client.py::start_run`
(Phase Blocked — depends on the sandbox refactor). All gating — credits,
run-count, concurrency, model tier, allowed tools/knowledge — has already
fired by the time a `RunRequest` exists; this struct simply tells the
sandbox what the lease and resource scope are.

`policy_block` is a pre-rendered system-prompt fragment from
`apps/policies/Policy.as_system_prompt_block()`; the sandbox does not
re-parse it. `allowed_tools` / `allowed_knowledge` are *post-gating* lists,
i.e. the intersection of (agent assignment ∩ end-user `allowed_*`).
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from apps.runs.schemas.lease import Lease


class RunRequest(BaseModel):
    """Wire payload for `agent_server`'s start-run entrypoint."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    agent_id: UUID
    end_user_id: UUID
    prompt: str = Field(min_length=1, max_length=64_000)
    conversation_id: UUID
    lease: Lease
    policy_block: str = Field(default="", max_length=32_000)
    allowed_tools: tuple[UUID, ...] = Field(default_factory=tuple)
    allowed_knowledge: tuple[UUID, ...] = Field(default_factory=tuple)
