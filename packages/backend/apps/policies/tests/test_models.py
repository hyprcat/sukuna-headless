from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError

from apps.policies.factories import PolicyFactory
from apps.policies.schemas import PolicyFormat

pytestmark = pytest.mark.django_db


def test_empty_policy_produces_empty_prompt_block() -> None:
    policy = PolicyFactory()

    assert policy.as_system_prompt_block() == ""


def test_prompt_block_renders_all_sections() -> None:
    policy = PolicyFactory(with_restrictions=True)
    fmt = PolicyFormat()
    block = policy.as_system_prompt_block()

    assert f"## {fmt.action_header}" in block
    assert f"## {fmt.domain_header}" in block
    assert f"## {fmt.output_header}" in block
    assert "- Never delete user data" in block
    assert "- Only use approved APIs" in block
    assert "- Max 4000 tokens per response" in block


def test_prompt_block_omits_empty_sections() -> None:
    policy = PolicyFactory(action_restrictions=["No deletions"])
    block = policy.as_system_prompt_block()
    fmt = PolicyFormat()

    assert f"## {fmt.action_header}" in block
    assert f"## {fmt.domain_header}" not in block
    assert f"## {fmt.output_header}" not in block


def test_validation_rejects_non_list() -> None:
    policy = PolicyFactory.build(action_restrictions="not a list")

    with pytest.raises(ValidationError, match="Must be a list"):
        policy.full_clean()


def test_validation_rejects_empty_string_entry() -> None:
    policy = PolicyFactory.build(action_restrictions=["valid", ""])

    with pytest.raises(ValidationError, match="non-empty string"):
        policy.full_clean()


def test_validation_rejects_too_many_entries() -> None:
    fmt = PolicyFormat()
    policy = PolicyFactory.build(
        action_restrictions=["rule"] * (fmt.max_restrictions_per_list + 1),
    )

    with pytest.raises(ValidationError, match="At most"):
        policy.full_clean()


def test_validation_rejects_oversized_entry() -> None:
    fmt = PolicyFormat()
    policy = PolicyFactory.build(
        domain_restrictions=["x" * (fmt.max_restriction_length + 1)],
    )

    with pytest.raises(ValidationError, match="exceeds"):
        policy.full_clean()


def test_validation_rejects_oversized_assembled_block() -> None:
    fmt = PolicyFormat()
    long_entry = "x" * fmt.max_restriction_length
    count = (fmt.max_prompt_block_length // fmt.max_restriction_length) + 1
    policy = PolicyFactory.build(action_restrictions=[long_entry] * count)

    with pytest.raises(ValidationError, match="Assembled policy block"):
        policy.full_clean(exclude=["workspace"])


def test_valid_policy_passes_clean() -> None:
    policy = PolicyFactory.build(with_restrictions=True)

    policy.full_clean(exclude=["workspace"])
