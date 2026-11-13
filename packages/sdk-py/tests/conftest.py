"""Shared pytest fixtures for the midsphere SDK test suite."""

from __future__ import annotations

import pytest
from helpers import API_KEY

from midsphere import Midsphere


@pytest.fixture
async def client() -> Midsphere:  # type: ignore[misc]
    """A Midsphere client wired with the test API key.

    Closed after the test via an async finaliser.
    """
    c = Midsphere(api_key=API_KEY)
    yield c
    await c.aclose()
