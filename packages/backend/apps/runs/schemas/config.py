from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class SandboxTransitionRules(BaseModel):
    model_config = ConfigDict(frozen=True)

    forward: dict[str, frozenset[str]] = {
        "spawning": frozenset({"booting", "terminated"}),
        "booting": frozenset({"running", "terminated"}),
        "running": frozenset({"paused", "terminated"}),
        "paused": frozenset({"running", "terminated"}),
        "terminated": frozenset(),
    }
