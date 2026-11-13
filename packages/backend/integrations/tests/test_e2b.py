from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from apps.core.exceptions import SandboxError
from integrations import e2b as e2b_wrapper


class FakeAsyncSandbox:
    def __init__(self, sandbox_id: str = "sbx_test123") -> None:
        self.sandbox_id = sandbox_id
        self._host = f"8000-{sandbox_id}.e2b.app"

    def get_host(self, port: int) -> str:
        return f"{port}-{self.sandbox_id}.e2b.app"

    async def pause(self) -> None:
        pass

    async def kill(self) -> bool:
        return True


@pytest.fixture(autouse=True)
def _set_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(e2b_wrapper.runtime, "e2b_api_key", "test_key")
    monkeypatch.setattr(e2b_wrapper.runtime, "e2b_template_id", "tpl_default")


# ---------------------------------------------------------------------------
# spawn_sandbox
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_spawn_sandbox_returns_handle() -> None:
    fake = FakeAsyncSandbox("sbx_new")
    create_mock = AsyncMock(return_value=fake)
    with patch.object(e2b_wrapper.AsyncSandbox, "create", create_mock):
        handle = await e2b_wrapper.spawn_sandbox()

    assert handle.sandbox_id == "sbx_new"
    assert handle.sandbox_url == "https://8000-sbx_new.e2b.app"


@pytest.mark.asyncio
async def test_spawn_sandbox_passes_template_and_env() -> None:
    fake = FakeAsyncSandbox()
    with patch.object(
        e2b_wrapper.AsyncSandbox, "create", new_callable=AsyncMock, return_value=fake
    ) as mock_create:
        await e2b_wrapper.spawn_sandbox(template="custom_tpl", env={"FOO": "bar"}, ttl_seconds=120)

    mock_create.assert_awaited_once_with(
        template="custom_tpl",
        timeout=120,
        envs={"FOO": "bar"},
        api_key="test_key",
    )


@pytest.mark.asyncio
async def test_spawn_sandbox_uses_runtime_template_when_none() -> None:
    fake = FakeAsyncSandbox()
    with patch.object(
        e2b_wrapper.AsyncSandbox, "create", new_callable=AsyncMock, return_value=fake
    ) as mock_create:
        await e2b_wrapper.spawn_sandbox()

    mock_create.assert_awaited_once_with(
        template="tpl_default",
        timeout=None,
        envs=None,
        api_key="test_key",
    )


@pytest.mark.asyncio
async def test_spawn_sandbox_wraps_sdk_error() -> None:
    with (
        patch.object(
            e2b_wrapper.AsyncSandbox,
            "create",
            new_callable=AsyncMock,
            side_effect=RuntimeError("E2B API down"),
        ),
        pytest.raises(SandboxError, match="E2B spawn failed"),
    ):
        await e2b_wrapper.spawn_sandbox()


# ---------------------------------------------------------------------------
# pause_sandbox
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pause_sandbox_calls_pause() -> None:
    fake = FakeAsyncSandbox("sbx_pause")
    fake.pause = AsyncMock()  # type: ignore[method-assign]
    with patch.object(
        e2b_wrapper.AsyncSandbox, "connect", new_callable=AsyncMock, return_value=fake
    ):
        await e2b_wrapper.pause_sandbox("sbx_pause")

    fake.pause.assert_awaited_once()


@pytest.mark.asyncio
async def test_pause_sandbox_wraps_error() -> None:
    fake = FakeAsyncSandbox()
    fake.pause = AsyncMock(side_effect=RuntimeError("pause failed"))  # type: ignore[method-assign]
    with (
        patch.object(
            e2b_wrapper.AsyncSandbox, "connect", new_callable=AsyncMock, return_value=fake
        ),
        pytest.raises(SandboxError, match="E2B pause failed"),
    ):
        await e2b_wrapper.pause_sandbox("sbx_x")


# ---------------------------------------------------------------------------
# resume_sandbox
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resume_sandbox_returns_handle() -> None:
    fake = FakeAsyncSandbox("sbx_resumed")
    with patch.object(
        e2b_wrapper.AsyncSandbox, "connect", new_callable=AsyncMock, return_value=fake
    ):
        handle = await e2b_wrapper.resume_sandbox("sbx_resumed")

    assert handle.sandbox_id == "sbx_resumed"
    assert handle.sandbox_url == "https://8000-sbx_resumed.e2b.app"


@pytest.mark.asyncio
async def test_resume_sandbox_passes_timeout() -> None:
    fake = FakeAsyncSandbox()
    with patch.object(
        e2b_wrapper.AsyncSandbox, "connect", new_callable=AsyncMock, return_value=fake
    ) as mock_connect:
        await e2b_wrapper.resume_sandbox("sbx_r", ttl_seconds=60)

    mock_connect.assert_awaited_once_with("sbx_r", timeout=60, api_key="test_key")


@pytest.mark.asyncio
async def test_resume_sandbox_wraps_error() -> None:
    with (
        patch.object(
            e2b_wrapper.AsyncSandbox,
            "connect",
            new_callable=AsyncMock,
            side_effect=RuntimeError("not found"),
        ),
        pytest.raises(SandboxError, match="E2B resume failed"),
    ):
        await e2b_wrapper.resume_sandbox("sbx_gone")


# ---------------------------------------------------------------------------
# terminate_sandbox
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_terminate_sandbox_calls_kill() -> None:
    fake = FakeAsyncSandbox("sbx_kill")
    fake.kill = AsyncMock(return_value=True)  # type: ignore[method-assign]
    with patch.object(
        e2b_wrapper.AsyncSandbox, "connect", new_callable=AsyncMock, return_value=fake
    ):
        await e2b_wrapper.terminate_sandbox("sbx_kill")

    fake.kill.assert_awaited_once()


@pytest.mark.asyncio
async def test_terminate_sandbox_wraps_error() -> None:
    fake = FakeAsyncSandbox()
    fake.kill = AsyncMock(side_effect=RuntimeError("kill failed"))  # type: ignore[method-assign]
    with (
        patch.object(
            e2b_wrapper.AsyncSandbox, "connect", new_callable=AsyncMock, return_value=fake
        ),
        pytest.raises(SandboxError, match="E2B terminate failed"),
    ):
        await e2b_wrapper.terminate_sandbox("sbx_x")


# ---------------------------------------------------------------------------
# post_manifest
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_manifest_sends_to_sandbox() -> None:
    fake = FakeAsyncSandbox("sbx_manifest")
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    health_ok = MagicMock(spec=httpx.Response)
    health_ok.status_code = 200
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.get = AsyncMock(return_value=health_ok)

    with (
        patch.object(
            e2b_wrapper.AsyncSandbox, "connect", new_callable=AsyncMock, return_value=fake
        ),
        patch.object(e2b_wrapper, "_http_client", return_value=mock_client),
    ):
        await e2b_wrapper.post_manifest("sbx_manifest", b'{"run_id":"123"}')

    mock_client.post.assert_awaited_once_with(
        "https://8000-sbx_manifest.e2b.app/runs",
        content=b'{"run_id":"123"}',
        headers={"Content-Type": "application/json"},
    )


@pytest.mark.asyncio
async def test_post_manifest_wraps_http_error() -> None:
    fake = FakeAsyncSandbox("sbx_m")
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 400
    mock_response.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError(
            "Bad request", request=MagicMock(), response=mock_response
        )
    )
    health_ok = MagicMock(spec=httpx.Response)
    health_ok.status_code = 200
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.get = AsyncMock(return_value=health_ok)

    with (
        patch.object(
            e2b_wrapper.AsyncSandbox, "connect", new_callable=AsyncMock, return_value=fake
        ),
        patch.object(e2b_wrapper, "_http_client", return_value=mock_client),
        pytest.raises(SandboxError, match="Sandbox rejected manifest: 400"),
    ):
        await e2b_wrapper.post_manifest("sbx_m", b"{}")


# ---------------------------------------------------------------------------
# get_sandbox_url
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_sandbox_url_returns_https_url() -> None:
    fake = FakeAsyncSandbox("sbx_url")
    with patch.object(
        e2b_wrapper.AsyncSandbox, "connect", new_callable=AsyncMock, return_value=fake
    ):
        url = await e2b_wrapper.get_sandbox_url("sbx_url")

    assert url == "https://8000-sbx_url.e2b.app"


# ---------------------------------------------------------------------------
# fresh http client per call
# ---------------------------------------------------------------------------


def test_http_client_is_fresh_per_call() -> None:
    # A cached async client binds to one event loop and breaks across the
    # per-request loops the sync GraphQL view creates — each call is fresh.
    c1 = e2b_wrapper._http_client()
    c2 = e2b_wrapper._http_client()
    assert c1 is not c2


# ---------------------------------------------------------------------------
# Missing API key
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_spawn_raises_when_no_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(e2b_wrapper.runtime, "e2b_api_key", "")
    with pytest.raises(SandboxError, match="E2B API key not configured"):
        await e2b_wrapper.spawn_sandbox()
