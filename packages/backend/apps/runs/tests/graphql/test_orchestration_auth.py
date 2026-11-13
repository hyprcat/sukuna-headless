"""Tests for run orchestration GraphQL mutation auth checks."""

from __future__ import annotations

import pytest
import strawberry
from strawberry import relay
from strawberry_django.optimizer import DjangoOptimizerExtension

from apps.runs.api.mutations import RunMutation
from apps.runs.api.queries import RunQuery
from apps.runs.factories import RunFactory, SandboxInstanceFactory
from apps.runs.tests.conftest import (
    api_key_ctx,
    denied_session_ctx,
    patched_signing,
    session_ctx,
    setup_run_env,
)

pytestmark = pytest.mark.django_db(transaction=True)


@strawberry.type
class _Q(RunQuery):
    pass


@strawberry.type
class _M(RunMutation):
    pass


_schema = strawberry.Schema(
    query=_Q,
    mutation=_M,
    extensions=[DjangoOptimizerExtension],
)


def _run_id(run: object) -> str:
    return relay.to_base64("RunType", run.pk)  # type: ignore[attr-defined]


REFRESH_TOKEN_MUT = """
mutation($runId: ID!) {
    refreshSandboxToken(runId: $runId) {
        success
        errors { code message field }
        capabilityToken
        tokenExpiresAt
    }
}
"""


def test_refresh_token_graphql_session_ok() -> None:
    ws, agent, eu, _ = setup_run_env()
    run = RunFactory(
        workspace=ws,
        agent=agent,
        end_user=eu,
        running=True,
        sandbox_id="sbx-gql",
    )
    SandboxInstanceFactory(
        running=True,
        sandbox_id="sbx-gql",
        workspace=ws,
        agent=agent,
    )
    with patched_signing():
        result = _schema.execute_sync(
            REFRESH_TOKEN_MUT,
            variable_values={"runId": _run_id(run)},
            context_value=session_ctx(ws),
        )
    assert result.errors is None, result.errors
    data = result.data["refreshSandboxToken"]
    assert data["success"] is True
    assert data["capabilityToken"] is not None


def test_refresh_token_graphql_denied_role() -> None:
    ws, agent, eu, _ = setup_run_env()
    run = RunFactory(
        workspace=ws,
        agent=agent,
        end_user=eu,
        running=True,
        sandbox_id="sbx-deny",
    )
    SandboxInstanceFactory(
        running=True,
        sandbox_id="sbx-deny",
        workspace=ws,
        agent=agent,
    )
    result = _schema.execute_sync(
        REFRESH_TOKEN_MUT,
        variable_values={"runId": _run_id(run)},
        context_value=denied_session_ctx(ws),
    )
    assert result.errors is not None
    assert "not permitted" in result.errors[0].message


def test_refresh_token_graphql_api_key_with_scope() -> None:
    ws, agent, eu, _ = setup_run_env()
    run = RunFactory(
        workspace=ws,
        agent=agent,
        end_user=eu,
        running=True,
        sandbox_id="sbx-key",
    )
    SandboxInstanceFactory(
        running=True,
        sandbox_id="sbx-key",
        workspace=ws,
        agent=agent,
    )
    ctx = api_key_ctx(ws, frozenset({"runs:write", "runs:read"}))
    with patched_signing():
        result = _schema.execute_sync(
            REFRESH_TOKEN_MUT,
            variable_values={"runId": _run_id(run)},
            context_value=ctx,
        )
    assert result.errors is None, result.errors
    data = result.data["refreshSandboxToken"]
    assert data["success"] is True
    assert data["capabilityToken"] is not None


def test_refresh_token_graphql_api_key_wrong_scope() -> None:
    ws, agent, eu, _ = setup_run_env()
    run = RunFactory(
        workspace=ws,
        agent=agent,
        end_user=eu,
        running=True,
        sandbox_id="sbx-noscope",
    )
    SandboxInstanceFactory(
        running=True,
        sandbox_id="sbx-noscope",
        workspace=ws,
        agent=agent,
    )
    result = _schema.execute_sync(
        REFRESH_TOKEN_MUT,
        variable_values={"runId": _run_id(run)},
        context_value=api_key_ctx(ws, frozenset({"runs:read"})),
    )
    assert result.errors is not None
    assert "runs:write" in result.errors[0].message
