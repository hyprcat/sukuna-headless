"""Project-wide pytest fixtures.

Kept intentionally small: only cross-cutting test-harness concerns belong here.
App-specific helpers stay in each app's ``tests/conftest.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from asgiref.sync import SyncToAsync
from django.db import connection, connections

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture(autouse=True)
def _reap_async_orm_connections() -> Iterator[None]:
    """Close DB connections leaked into asgiref's single-thread executor.

    Top-level ``async def`` tests run ORM through ``sync_to_async`` (thread
    sensitive) inside asgiref's persistent ``single_thread_executor``. That
    thread's Django connection is never closed, so it lingers for the whole
    session and shows up as an extra Postgres session. Under random ordering a
    later ``transaction=True`` test then fails its TRUNCATE teardown with
    "database is being accessed by other users". Reaping the executor's
    connection around every test keeps the leak from crossing test boundaries.
    """

    def _reap() -> None:
        SyncToAsync.single_thread_executor.submit(connections.close_all).result()

    _reap()
    yield
    _reap()


@pytest.fixture(scope="session", autouse=True)
def _terminate_stray_connections_before_db_drop(
    django_db_setup: object,
    django_db_blocker: object,
) -> Iterator[None]:
    """Drop stray Postgres sessions before the test database is destroyed.

    Async tests open ORM connections in executor threads (asgiref's thread pool,
    the ASGI test client's handler) that are not closed when the loop ends.
    Those sessions block pytest-django's session-end ``DROP DATABASE`` with
    "database is being accessed by other users". Depending on ``django_db_setup``
    makes this fixture tear down *before* the drop runs, so we terminate the
    leftovers first. Per-test contamination is handled by
    ``_reap_async_orm_connections``; this only guards the final teardown.
    """
    yield
    with django_db_blocker.unblock(), connection.cursor() as cursor:  # type: ignore[attr-defined]
        cursor.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = current_database() AND pid <> pg_backend_pid()"
        )
