from __future__ import annotations

import posthog


def configure_posthog(*, api_key: str | None, host: str) -> None:
    """Configure the process-wide PostHog client.

    PostHog ships its own module-level singleton; we just point it at the
    project + host. With no key the SDK is flipped to ``disabled``, so every
    ``capture`` / ``identify`` call becomes a cheap no-op.
    """
    if not api_key:
        posthog.disabled = True
        posthog.api_key = None
        posthog.project_api_key = None
        return
    posthog.api_key = api_key
    posthog.project_api_key = api_key
    posthog.host = host
    posthog.disabled = False
