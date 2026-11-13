"""Wire-stable error codes emitted by the sandbox run boundary."""

from __future__ import annotations

from enum import StrEnum


class LeaseErrorCode(StrEnum):
    """Error codes emitted when a run crosses its lease."""

    LEASE_RUNTIME_EXCEEDED = "lease_runtime_exceeded"
    LEASE_TOKENS_EXCEEDED = "lease_tokens_exceeded"
    LEASE_COST_EXCEEDED = "lease_cost_exceeded"


class DomainErrorCode(StrEnum):
    """Non-lease failure codes from the sandbox."""

    TOOL_FAILED = "tool_failed"
    MODEL_UNAVAILABLE = "model_unavailable"
    KNOWLEDGE_INACCESSIBLE = "knowledge_inaccessible"
    SANDBOX_INTERNAL = "sandbox_internal"
    POLICY_VIOLATION = "policy_violation"
    APPROVAL_DENIED = "approval_denied"
    GUARDRAIL_BLOCKED = "guardrail_blocked"
    RUN_TASK_CRASHED = "run_task_crashed"
    UPSTREAM_MODEL_ERROR = "upstream_model_error"
