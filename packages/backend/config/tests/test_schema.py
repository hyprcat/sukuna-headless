from __future__ import annotations

from config.schema import schema


def test_schema_excludes_blocked_runtime_fields() -> None:
    sdl = str(schema)

    assert "cancelRun" not in sdl
    assert "streamToken" not in sdl


def test_schema_keeps_phase_five_mutations() -> None:
    sdl = str(schema)

    assert "submitRating" in sdl
    assert "createTopup" in sdl
    assert "createApiKey" in sdl


def test_schema_includes_run_orchestration_mutations() -> None:
    sdl = str(schema)

    assert "startRun" in sdl
    assert "wakeForRun" in sdl
    assert "refreshSandboxToken" in sdl
