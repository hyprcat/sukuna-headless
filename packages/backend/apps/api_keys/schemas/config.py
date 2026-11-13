"""Pydantic configuration models for the api_keys app.

Per BACKEND_CODING_STANDARDS §2 — no module-level globals; every grouped
collection of values lives on a frozen `BaseModel` and is instantiated at
the use site (or passed in via DI). Each model below is the single source
of truth for the constants its consumers need.
"""

from __future__ import annotations

import string

from pydantic import BaseModel, ConfigDict


class APIKeyFormat(BaseModel):
    """Wire-stable secret string shape: ``ms_<env>_<base62-random>``.

    Consumed by `apps.api_keys.models.api_key` (mints secrets, computes
    prefixes) and `apps.api_keys.auth` (parses them back from the
    Authorization header). Changing any field here is a wire break.
    """

    model_config = ConfigDict(frozen=True)

    namespace: str = "ms"
    prefix_length: int = 8
    random_length: int = 43  # ~256 bits of entropy in base62
    base62_alphabet: str = string.digits + string.ascii_letters
    record_use_throttle_seconds: int = 60


class ScryptParams(BaseModel):
    """Cost parameters for the API-key secret hasher.

    Tuned for ~25-50ms verify on commodity hardware. API key auth runs on
    every request, so the floor matters; tune via env if hot-path pressure
    ever forces a re-evaluation.
    """

    model_config = ConfigDict(frozen=True)

    n: int = 2**14
    r: int = 8
    p: int = 1
    salt_bytes: int = 16
    hash_bytes: int = 64
    algo_tag: str = "scrypt"
    hash_parts: int = 6  # ``algo$N$r$p$salt$hash``


class AuthMiddlewareConfig(BaseModel):
    """Header parsing + audit rate-limiting for `WorkspacePrincipalMiddleware`.

    The bucketed audit cache is the atomic dedup primitive for the
    ``api_key_lookup_failed`` event — `cache.add` returns False when the key
    already exists, so only the first failure per bucket is recorded.
    """

    model_config = ConfigDict(frozen=True)

    bearer_prefix: str = "Bearer "
    workspace_slug_header: str = "X-Workspace-Slug"
    audit_cache_key_prefix: str = "api_key_audit"
    audit_bucket_seconds: int = 60
    audit_ttl_seconds: int = 120  # covers a 60s bucket with overlap
