"""Single-file wrapper around the E2B Python SDK.

Resolvers, models, and tasks import this module — never the E2B SDK
directly. Swapping sandbox providers is a one-file change.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx
from e2b import AsyncSandbox

from apps.core.exceptions import SandboxError
from config.runtime import runtime

if TYPE_CHECKING:
    from collections.abc import Awaitable


@dataclass(frozen=True, slots=True)
class SandboxHandle:
    sandbox_id: str
    sandbox_url: str


def _http_client() -> httpx.AsyncClient:
    # Fresh client per call. A cached AsyncClient binds to the event loop it was
    # created on; under the sync GraphQL view (per-request async_to_sync loops)
    # reuse hits a closed loop. One manifest POST per run doesn't need pooling.
    return httpx.AsyncClient(timeout=httpx.Timeout(30.0))


def _api_key() -> str:
    key = runtime.e2b_api_key
    if not key:
        raise SandboxError("E2B API key not configured.")
    return key


async def _e2b_request[T](operation: str, coro: Awaitable[T]) -> T:
    try:
        return await coro
    except SandboxError:
        raise
    except Exception as exc:
        raise SandboxError(f"E2B {operation} failed.") from exc


def _sandbox_handle(sbx: AsyncSandbox) -> SandboxHandle:
    return SandboxHandle(
        sandbox_id=sbx.sandbox_id,
        sandbox_url=f"https://{sbx.get_host(8000)}",
    )


async def spawn_sandbox(
    template: str | None = None,
    env: dict[str, str] | None = None,
    ttl_seconds: int | None = None,
) -> SandboxHandle:
    tpl = template or runtime.e2b_template_id or None
    sbx = await _e2b_request(
        "spawn",
        AsyncSandbox.create(
            template=tpl,
            timeout=ttl_seconds,
            envs=env,
            api_key=_api_key(),
        ),
    )
    return _sandbox_handle(sbx)


async def pause_sandbox(sandbox_id: str) -> None:
    sbx = await _connect(sandbox_id)
    await _e2b_request("pause", sbx.pause())


async def resume_sandbox(
    sandbox_id: str,
    ttl_seconds: int | None = None,
) -> SandboxHandle:
    sbx = await _e2b_request(
        "resume",
        AsyncSandbox.connect(
            sandbox_id,
            timeout=ttl_seconds,
            api_key=_api_key(),
        ),
    )
    return _sandbox_handle(sbx)


async def terminate_sandbox(sandbox_id: str) -> None:
    sbx = await _connect(sandbox_id)
    await _e2b_request("terminate", sbx.kill())


async def post_manifest(
    sandbox_id: str,
    manifest: bytes,
) -> None:
    handle = await resume_sandbox(sandbox_id)
    url = f"{handle.sandbox_url}/runs"
    client = _http_client()
    try:
        await _await_ready(client, handle.sandbox_url)
        resp = await client.post(
            url,
            content=manifest,
            headers={
                "Content-Type": "application/json",
                "X-API-Key": runtime.sandbox_server_api_key,
            },
        )
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise SandboxError(f"Sandbox rejected manifest: {exc.response.status_code}") from exc
    except SandboxError:
        raise
    except Exception as exc:
        raise SandboxError("Failed to post manifest to sandbox.") from exc
    finally:
        await client.aclose()


async def _await_ready(client: httpx.AsyncClient, base_url: str) -> None:
    """Poll the sandbox health endpoint until its agent server is listening.

    A freshly spawned sandbox boots its agent server asynchronously; posting a
    manifest before it listens yields a 502 from the E2B proxy.
    """
    deadline = asyncio.get_running_loop().time() + runtime.sandbox_boot_timeout_seconds
    while True:
        try:
            resp = await client.get(f"{base_url}/health", timeout=httpx.Timeout(5.0))
            if resp.status_code == 200:
                return
        except httpx.HTTPError:
            pass
        if asyncio.get_running_loop().time() >= deadline:
            raise SandboxError("Sandbox agent server did not become ready.")
        await asyncio.sleep(1.0)


async def set_sandbox_timeout(sandbox_id: str, seconds: int) -> None:
    """Extend the sandbox's auto-shutdown timeout to cover the run's lease."""
    sbx = await _connect(sandbox_id)
    await _e2b_request("set_timeout", sbx.set_timeout(seconds))


async def get_sandbox_url(sandbox_id: str) -> str:
    return _sandbox_handle(await _connect(sandbox_id)).sandbox_url


async def list_sandbox_states() -> dict[str, str]:
    """Map ``sandbox_id`` -> E2B state for every live sandbox.

    E2B only reports running/paused sandboxes; a terminated sandbox is simply
    absent from the result. Reconciliation treats "not present" as terminated.
    """
    paginator = AsyncSandbox.list(api_key=_api_key())
    states: dict[str, str] = {}
    while paginator.has_next:
        infos = await _e2b_request("list", paginator.next_items())
        for info in infos:
            states[info.sandbox_id] = info.state
    return states


async def _connect(sandbox_id: str) -> AsyncSandbox:
    return await _e2b_request(
        "connect",
        AsyncSandbox.connect(sandbox_id, api_key=_api_key()),
    )
