from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from django.utils import timezone

from apps.agents.factories import AgentFactory
from apps.billing.factories import CreditWalletFactory
from apps.core.errors import UserError
from apps.end_users.factories import EndUserFactory
from apps.end_users.models import RunCountPeriod
from apps.end_users.schemas import Allowed, Denied
from apps.knowledge.factories import KnowledgeFactory
from apps.tools.factories import ToolFactory

pytestmark = pytest.mark.django_db


def _funded_end_user(**kwargs: Any) -> Any:
    end_user = EndUserFactory(**kwargs)
    wallet = CreditWalletFactory(workspace=end_user.workspace)
    wallet.record_dodo_credit_grant(Decimal("100"), dodo_payment_id="test")
    return end_user


def test_check_can_run_allowed() -> None:
    end_user = _funded_end_user(profile__credits=10)
    agent = AgentFactory(workspace=end_user.workspace)

    result = end_user.check_can_run(agent, [], [])

    assert isinstance(result, Allowed)
    assert result.model_tier == "free"


def test_check_can_run_returns_model_tier() -> None:
    end_user = _funded_end_user(profile__credits=10, profile__model_tier="enterprise")
    agent = AgentFactory(workspace=end_user.workspace)

    result = end_user.check_can_run(agent, [], [])

    assert isinstance(result, Allowed)
    assert result.model_tier == "enterprise"


def test_check_can_run_denied_inactive() -> None:
    end_user = _funded_end_user(inactive=True, profile__credits=10)
    agent = AgentFactory(workspace=end_user.workspace)

    result = end_user.check_can_run(agent, [], [])

    assert isinstance(result, Denied)
    assert result.reason == UserError.PERMISSION_DENIED


def test_check_can_run_denied_cross_workspace_agent() -> None:
    end_user = _funded_end_user(profile__credits=10)
    agent = AgentFactory()

    result = end_user.check_can_run(agent, [], [])

    assert isinstance(result, Denied)
    assert result.reason == UserError.PERMISSION_DENIED


def test_check_can_run_denied_no_wallet() -> None:
    end_user = EndUserFactory(profile__credits=10)
    agent = AgentFactory(workspace=end_user.workspace)

    result = end_user.check_can_run(agent, [], [])

    assert isinstance(result, Denied)
    assert result.reason == UserError.BILLING_ERROR


def test_check_can_run_denied_empty_wallet() -> None:
    end_user = EndUserFactory(profile__credits=10)
    CreditWalletFactory(workspace=end_user.workspace)
    agent = AgentFactory(workspace=end_user.workspace)

    result = end_user.check_can_run(agent, [], [])

    assert isinstance(result, Denied)
    assert result.reason == UserError.BILLING_ERROR


def test_check_can_run_denied_insufficient_credits() -> None:
    end_user = _funded_end_user(profile__credits=0)
    agent = AgentFactory(workspace=end_user.workspace)

    result = end_user.check_can_run(agent, [], [])

    assert isinstance(result, Denied)
    assert result.reason == UserError.INSUFFICIENT_CREDITS


def test_check_can_run_denied_run_limit_exceeded() -> None:
    end_user = _funded_end_user(
        profile__credits=10,
        profile__run_count_limit=5,
        profile__run_count_period=RunCountPeriod.DAY,
        profile__runs_used_in_period=5,
    )
    agent = AgentFactory(workspace=end_user.workspace)

    result = end_user.check_can_run(agent, [], [])

    assert isinstance(result, Denied)
    assert result.reason == UserError.RUN_LIMIT_EXCEEDED


def test_check_can_run_run_count_allows_when_refresh_overdue() -> None:
    past = timezone.now() - timedelta(days=2)
    end_user = _funded_end_user(
        profile__credits=10,
        profile__run_count_limit=5,
        profile__run_count_period=RunCountPeriod.DAY,
        profile__runs_used_in_period=5,
        profile__next_credit_refresh_at=past,
    )
    agent = AgentFactory(workspace=end_user.workspace)

    result = end_user.check_can_run(agent, [], [])

    assert isinstance(result, Allowed)


def test_check_can_run_denied_concurrency_cap() -> None:
    end_user = _funded_end_user(profile__credits=10, profile__concurrency_max=2)
    agent = AgentFactory(workspace=end_user.workspace)

    result = end_user.check_can_run(agent, [], [], active_run_count=2)

    assert isinstance(result, Denied)
    assert result.reason == UserError.CONCURRENCY_CAP


def test_check_can_run_denied_tool_not_allowed() -> None:
    end_user = _funded_end_user(profile__credits=10)
    tool = ToolFactory(workspace=end_user.workspace)
    other_tool = ToolFactory(workspace=end_user.workspace)
    end_user.profile.allowed_tools.add(tool)
    agent = AgentFactory(workspace=end_user.workspace)

    result = end_user.check_can_run(agent, [other_tool], [])

    assert isinstance(result, Denied)
    assert result.reason == UserError.TOOL_NOT_ALLOWED


def test_check_can_run_denied_cross_workspace_tool_when_unrestricted() -> None:
    end_user = _funded_end_user(profile__credits=10)
    tool = ToolFactory()
    agent = AgentFactory(workspace=end_user.workspace)

    result = end_user.check_can_run(agent, [tool], [])

    assert isinstance(result, Denied)
    assert result.reason == UserError.TOOL_NOT_ALLOWED


def test_check_can_run_denied_knowledge_not_allowed() -> None:
    end_user = _funded_end_user(profile__credits=10)
    kb = KnowledgeFactory(workspace=end_user.workspace)
    other_kb = KnowledgeFactory(workspace=end_user.workspace)
    end_user.profile.allowed_knowledge.add(kb)
    agent = AgentFactory(workspace=end_user.workspace)

    result = end_user.check_can_run(agent, [], [other_kb])

    assert isinstance(result, Denied)
    assert result.reason == UserError.KNOWLEDGE_NOT_ALLOWED


def test_check_can_run_denied_cross_workspace_knowledge_when_unrestricted() -> None:
    end_user = _funded_end_user(profile__credits=10)
    kb = KnowledgeFactory()
    agent = AgentFactory(workspace=end_user.workspace)

    result = end_user.check_can_run(agent, [], [kb])

    assert isinstance(result, Denied)
    assert result.reason == UserError.KNOWLEDGE_NOT_ALLOWED


def test_check_can_run_unrestricted_tools() -> None:
    end_user = _funded_end_user(profile__credits=10)
    tool = ToolFactory(workspace=end_user.workspace)
    agent = AgentFactory(workspace=end_user.workspace)

    result = end_user.check_can_run(agent, [tool], [])

    assert isinstance(result, Allowed)


def test_check_can_run_unrestricted_knowledge() -> None:
    end_user = _funded_end_user(profile__credits=10)
    kb = KnowledgeFactory(workspace=end_user.workspace)
    agent = AgentFactory(workspace=end_user.workspace)

    result = end_user.check_can_run(agent, [], [kb])

    assert isinstance(result, Allowed)
