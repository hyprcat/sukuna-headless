"""Phase 8L — end-to-end integration tests.

Drive the whole stack for a single run: GraphQL ``startRun`` -> orchestration
service -> DB records -> a signed callback batch POSTed to
``/webhooks/sandbox/callbacks`` -> event projection + billing settlement ->
GraphQL ``submitRating``. The only things mocked are the E2B SDK boundary and
the signing keys (via ``patched_e2b_env``); every layer in between runs for real
against the database.
"""

from __future__ import annotations

import os
from decimal import Decimal

import pytest
import strawberry
from asgiref.sync import sync_to_async
from django.test import AsyncClient
from strawberry import relay
from strawberry_django.optimizer import DjangoOptimizerExtension

from apps.billing.models.hold import BillingHold, HoldStatus
from apps.runs.api.mutations import RatingMutation, RunMutation
from apps.runs.api.queries import RunQuery
from apps.runs.factories import RunFactory
from apps.runs.models import Run, RunManifestRecord
from apps.runs.models.records import RunEvent
from apps.runs.models.sandbox_instance import SandboxInstance, SandboxState
from apps.runs.schemas.events import RunStatus
from apps.runs.tests.conftest import api_key_ctx, patched_e2b_env, setup_run_env
from apps.runs.tests.service.conftest import (
    final_usage,
    make_batch,
    make_event,
    started_payload,
    usage_payload,
)
from apps.tools.factories import ToolFactory

os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"

pytestmark = pytest.mark.django_db(transaction=True)

_CALLBACK_PATH = "/webhooks/sandbox/callbacks"
_API_SCOPES = frozenset({"runs:write", "runs:read"})


@strawberry.type
class _Q(RunQuery):
    pass


@strawberry.type
class _M(RunMutation, RatingMutation):
    pass


_schema = strawberry.Schema(query=_Q, mutation=_M, extensions=[DjangoOptimizerExtension])


START_RUN_MUT = """
mutation($input: StartRunInput!) {
    startRun(input: $input) {
        success
        errors { code message field }
        runId
        runUid
        sandboxUrl
        capabilityToken
        tokenExpiresAt
    }
}
"""

SUBMIT_RATING_MUT = """
mutation($input: SubmitRatingInput!) {
    submitRating(input: $input) {
        success
        errors { code message }
        rating { score comment }
    }
}
"""


def _gid(type_name: str, pk: int) -> str:
    return relay.to_base64(type_name, pk)


async def _start_run_mutation(ws, agent, eu, *, tool=None):
    tool_ids = [_gid("ToolType", tool.pk)] if tool else None
    variables = {
        "input": {
            "agentId": _gid("AgentType", agent.pk),
            "endUserId": _gid("EndUserType", eu.pk),
            "prompt": "Summarize the renewal history.",
            "toolIds": tool_ids,
        },
    }
    # Drive via execute_sync (in a thread) to mirror the production sync
    # GraphQL view: start_run is a sync resolver bridging to the async
    # orchestrator, so it must run outside a live event loop.
    return await sync_to_async(_schema.execute_sync)(
        START_RUN_MUT,
        variable_values=variables,
        context_value=api_key_ctx(ws, _API_SCOPES),
    )


async def _started_run_records(run_uid):
    """Fetch run + manifest record + sandbox; mark the booted sandbox running.

    In production the sandbox advances BOOTING -> RUNNING as it boots and picks
    up the run before emitting events; the callback path only pauses RUNNING
    instances, so the test reproduces that boot transition explicitly.
    """

    def _load():
        run = Run.objects.get(run_uid=run_uid)
        record = RunManifestRecord.objects.get(run=run)
        instance = SandboxInstance.objects.get(current_run=run)
        instance.mark_running(run)
        return run, record, instance

    return await sync_to_async(_load)()


async def _deliver(run, record, raw_key, events):
    body = make_batch(run, record, events, raw_key)
    return await AsyncClient().post(
        _CALLBACK_PATH,
        data=body,
        content_type="application/json",
    )


def _completed_events(record, tool):
    return [
        make_event(1, "run_started", started_payload(record.sandbox_id)),
        make_event(2, "tool_call", {"call_id": "c1", "tool_name": tool.name, "arguments": {}}),
        make_event(
            3,
            "tool_result",
            {"call_id": "c1", "tool_name": tool.name, "result": "ok", "duration_ms": 12},
        ),
        make_event(4, "usage_checkpoint", usage_payload(300, "0.30")),
        make_event(
            5,
            "run_completed",
            {"final_usage": final_usage(400, "0.40"), "summary": "Done"},
        ),
    ]


def _failed_events(record):
    return [
        make_event(1, "run_started", started_payload(record.sandbox_id)),
        make_event(
            2,
            "run_failed",
            {
                "error_code": "tool_failed",
                "message": "Tool crashed",
                "final_usage": final_usage(50, "0.00"),
            },
        ),
    ]


async def _assert_finished_and_settled(run, wallet, instance):
    def _check():
        seqs = list(
            RunEvent.objects.filter(run=run)
            .order_by("sequence_no")
            .values_list("sequence_no", flat=True),
        )
        run.refresh_from_db()
        wallet.refresh_from_db()
        instance.refresh_from_db()
        hold = BillingHold.objects.get(run=run)
        assert seqs == [1, 2, 3, 4, 5]
        assert run.status == RunStatus.FINISHED
        assert run.total_cost_usd == Decimal("0.40")
        assert hold.status == HoldStatus.SETTLED
        assert hold.amount_consumed_usd == Decimal("0.40")
        assert wallet.balance_usd == Decimal("99.60")
        assert instance.sandbox_state == SandboxState.PAUSED

    await sync_to_async(_check)()


async def _assert_failed_and_released(run, wallet, instance):
    def _check():
        run.refresh_from_db()
        wallet.refresh_from_db()
        instance.refresh_from_db()
        hold = BillingHold.objects.get(run=run)
        assert run.status == RunStatus.FAILED
        assert run.error_message == "Tool crashed"
        assert hold.status == HoldStatus.RELEASED
        assert wallet.balance_usd == Decimal("100.00")
        assert instance.sandbox_state == SandboxState.PAUSED

    await sync_to_async(_check)()


async def _submit_rating(ws, run_uid):
    return await _schema.execute(
        SUBMIT_RATING_MUT,
        variable_values={"input": {"runId": run_uid, "score": 5, "comment": "Great"}},
        context_value=api_key_ctx(ws, _API_SCOPES),
    )


def _set_concurrency_cap(ws, agent, eu):
    RunFactory(workspace=ws, agent=agent, end_user=eu, running=True)
    eu.profile.concurrency_max = 1
    eu.profile.save(update_fields=("concurrency_max",))


# =====================================================================
# Happy path — full stack, run completes, billing settles, rated.
# =====================================================================


async def test_happy_path_full_stack() -> None:
    ws, agent, eu, wallet = await sync_to_async(setup_run_env)()
    tool = await sync_to_async(ToolFactory)(workspace=ws)
    with patched_e2b_env() as mocks:
        result = await _start_run_mutation(ws, agent, eu, tool=tool)
    payload = result.data["startRun"]
    assert result.errors is None, result.errors
    assert payload["success"] is True
    assert payload["capabilityToken"]
    mocks["post_manifest"].assert_awaited_once()
    run, record, instance = await _started_run_records(payload["runUid"])
    raw_key = await sync_to_async(record.decrypt_callback_auth)()
    response = await _deliver(run, record, raw_key, _completed_events(record, tool))
    assert response.status_code == 200
    assert response.json()["acked_through"] == 5
    await _assert_finished_and_settled(run, wallet, instance)
    rating = await _submit_rating(ws, payload["runUid"])
    assert rating.data["submitRating"]["rating"] == {"score": 5, "comment": "Great"}


# =====================================================================
# Failure path — run fails, hold released (no charge), sandbox paused.
# =====================================================================


async def test_failure_path_releases_hold() -> None:
    ws, agent, eu, wallet = await sync_to_async(setup_run_env)()
    with patched_e2b_env():
        result = await _start_run_mutation(ws, agent, eu)
    payload = result.data["startRun"]
    assert payload["success"] is True
    run, record, instance = await _started_run_records(payload["runUid"])
    raw_key = await sync_to_async(record.decrypt_callback_auth)()
    response = await _deliver(run, record, raw_key, _failed_events(record))
    assert response.status_code == 200
    await _assert_failed_and_released(run, wallet, instance)


# =====================================================================
# Denial paths — control checks reject before any sandbox is acquired.
# =====================================================================


async def test_denial_insufficient_credits() -> None:
    ws, agent, eu, _ = await sync_to_async(setup_run_env)(credits=0)
    with patched_e2b_env() as mocks:
        result = await _start_run_mutation(ws, agent, eu)
    payload = result.data["startRun"]
    assert result.errors is None, result.errors
    assert payload["success"] is False
    assert payload["errors"][0]["code"] == "INSUFFICIENT_CREDITS"
    assert payload["runUid"] is None
    mocks["spawn"].assert_not_awaited()
    assert await sync_to_async(Run.objects.count)() == 0


async def test_denial_concurrency_cap() -> None:
    ws, agent, eu, _ = await sync_to_async(setup_run_env)()
    await sync_to_async(_set_concurrency_cap)(ws, agent, eu)
    with patched_e2b_env() as mocks:
        result = await _start_run_mutation(ws, agent, eu)
    payload = result.data["startRun"]
    assert payload["success"] is False
    assert payload["errors"][0]["code"] == "CONCURRENCY_CAP"
    mocks["spawn"].assert_not_awaited()
