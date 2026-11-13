"""
Shared public types for the midsphere SDK.

These mirror the backend GraphQL surface (camelCase keys in ``from_node``
class methods) and the sandbox streaming contract. No imports from other
midsphere modules — this module must stay cycle-free.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

# ---------------------------------------------------------------------------
# Closed literal types
# ---------------------------------------------------------------------------

UserErrorCode = Literal[
    "INSUFFICIENT_CREDITS",
    "RUN_LIMIT_EXCEEDED",
    "CONCURRENCY_CAP",
    "MODEL_TIER_RESTRICTED",
    "TOOL_NOT_ALLOWED",
    "KNOWLEDGE_NOT_ALLOWED",
    "INVALID_INPUT",
    "NOT_FOUND",
    "PERMISSION_DENIED",
    "CONFLICT",
    "BILLING_ERROR",
    "INVALID_API_KEY",
    "SCOPE_INSUFFICIENT",
    "SANDBOX_ERROR",
]

RunStatus = Literal["QUEUED", "RUNNING", "FINISHED", "FAILED", "CANCELLED"]

ModelTier = Literal["free", "pro", "enterprise"]

KnowledgeKind = Literal["DOCUMENT", "DATASET", "CONNECTED_SOURCE"]

KnowledgeKindInput = Literal["document", "dataset", "connected_source"]

# ---------------------------------------------------------------------------
# Domain dataclasses
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class UserError:
    """A single domain failure from a mutation's ``errors`` list."""

    code: str
    """Machine-readable code. Widened to ``str`` so a new backend code never breaks parsing."""
    field: str | None
    """The input field the error applies to, when the failure is input-scoped."""
    message: str
    """Human-readable, end-of-line message."""

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> UserError:
        """Construct from a raw dict, ignoring unknown keys."""
        return cls(
            code=d.get("code") or "INVALID_INPUT",
            field=d.get("field"),
            message=d.get("message") or "",
        )


@dataclass(slots=True)
class Agent:
    """A configured agent (control-plane view)."""

    id: str
    name: str
    description: str
    default_model_tier: str
    is_active: bool

    @classmethod
    def from_node(cls, node: dict[str, Any]) -> Agent:
        """Construct from a camelCase GraphQL node, ignoring unknown keys."""
        return cls(
            id=node.get("id") or "",
            name=node.get("name") or "",
            description=node.get("description") or "",
            default_model_tier=node.get("defaultModelTier") or "",
            is_active=bool(node.get("isActive")),
        )


@dataclass(slots=True)
class Tool:
    """A configured tool (control-plane view)."""

    id: str
    name: str
    description: str
    parameters_schema: dict[str, Any]
    """JSON Schema (Draft 2020-12) describing the tool's parameters."""
    execution_endpoint: str
    is_sensitive: bool
    is_active: bool
    created_at: str
    updated_at: str
    deactivated_at: str | None

    @classmethod
    def from_node(cls, node: dict[str, Any]) -> Tool:
        """Construct from a camelCase GraphQL node, ignoring unknown keys."""
        return cls(
            id=node.get("id") or "",
            name=node.get("name") or "",
            description=node.get("description") or "",
            parameters_schema=node.get("parametersSchema") or {},
            execution_endpoint=node.get("executionEndpoint") or "",
            is_sensitive=bool(node.get("isSensitive")),
            is_active=bool(node.get("isActive")),
            created_at=node.get("createdAt") or "",
            updated_at=node.get("updatedAt") or "",
            deactivated_at=node.get("deactivatedAt"),
        )


@dataclass(slots=True)
class Knowledge:
    """A configured knowledge base (control-plane view)."""

    id: str
    name: str
    description: str
    kind: str
    file_name: str
    file_size_bytes: int | None
    content_type: str
    source_endpoint: str
    is_active: bool
    created_at: str
    updated_at: str
    last_indexed_at: str | None
    deactivated_at: str | None

    @classmethod
    def from_node(cls, node: dict[str, Any]) -> Knowledge:
        """Construct from a camelCase GraphQL node, ignoring unknown keys."""
        return cls(
            id=node.get("id") or "",
            name=node.get("name") or "",
            description=node.get("description") or "",
            kind=node.get("kind") or "",
            file_name=node.get("fileName") or "",
            file_size_bytes=node.get("fileSizeBytes"),
            content_type=node.get("contentType") or "",
            source_endpoint=node.get("sourceEndpoint") or "",
            is_active=bool(node.get("isActive")),
            created_at=node.get("createdAt") or "",
            updated_at=node.get("updatedAt") or "",
            last_indexed_at=node.get("lastIndexedAt"),
            deactivated_at=node.get("deactivatedAt"),
        )


@dataclass(slots=True)
class EndUser:
    """A developer's end user — the person the agent acts on behalf of."""

    id: str
    external_user_id: str
    display_name: str
    tier_label: str
    metadata: dict[str, Any]
    is_active: bool

    @classmethod
    def from_node(cls, node: dict[str, Any]) -> EndUser:
        """Construct from a camelCase GraphQL node, ignoring unknown keys."""
        return cls(
            id=node.get("id") or "",
            external_user_id=node.get("externalUserId") or "",
            display_name=node.get("displayName") or "",
            tier_label=node.get("tierLabel") or "",
            metadata=node.get("metadata") or {},
            is_active=bool(node.get("isActive")),
        )
