"""Scrypt-backed hashing for API-key secrets.

API keys are high-entropy (256-bit) random strings, but we still hash before
storage so a leaked DB row cannot be replayed against the API. Scrypt keeps
brute-force expensive even with the entropy advantage on our side, and
`hmac.compare_digest` makes verification constant-time.

Self-contained on purpose — touching Django's global ``PASSWORD_HASHERS``
would change how *user* passwords are stored as a side effect, which is a
different concern entirely.

Cost parameters live on `ScryptParams` (a frozen Pydantic model) per
BACKEND_CODING_STANDARDS §2: no module-level constants. Pass `params=` to
override per-call; the default `ScryptParams()` is used otherwise.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import secrets
from typing import TYPE_CHECKING

from apps.api_keys.schemas.config import ScryptParams

if TYPE_CHECKING:
    type ScryptHashParts = tuple[int, int, int, bytes, bytes]


def hash_secret(secret: str, *, params: ScryptParams | None = None) -> str:
    """Return a self-describing scrypt hash: ``scrypt$N$r$p$salt$hash`` (b64)."""
    p = params or ScryptParams()
    salt = secrets.token_bytes(p.salt_bytes)
    derived = hashlib.scrypt(
        secret.encode("utf-8"),
        salt=salt,
        n=p.n,
        r=p.r,
        p=p.p,
        dklen=p.hash_bytes,
    )
    salt_b64 = base64.b64encode(salt).decode("ascii")
    hash_b64 = base64.b64encode(derived).decode("ascii")
    return f"{p.algo_tag}${p.n}${p.r}${p.p}${salt_b64}${hash_b64}"


def verify_secret(presented: str, stored: str, *, params: ScryptParams | None = None) -> bool:
    """Constant-time verify of `presented` against a stored hash."""
    p = params or ScryptParams()
    parsed = _parse_stored_hash(stored, p)
    if parsed is None:
        return False
    n, r, scrypt_p, salt, expected = parsed
    derived = _derive_secret(presented, salt=salt, n=n, r=r, scrypt_p=scrypt_p, dklen=len(expected))
    return hmac.compare_digest(derived, expected)


def _parse_stored_hash(stored: str, p: ScryptParams) -> ScryptHashParts | None:
    parts = stored.split("$")
    if len(parts) != p.hash_parts or parts[0] != p.algo_tag:
        return None
    try:
        n, r, scrypt_p = int(parts[1]), int(parts[2]), int(parts[3])
        salt = base64.b64decode(parts[4])
        expected = base64.b64decode(parts[5])
    except (ValueError, binascii.Error):
        return None
    return n, r, scrypt_p, salt, expected


def _derive_secret(
    presented: str, *, salt: bytes, n: int, r: int, scrypt_p: int, dklen: int
) -> bytes:
    return hashlib.scrypt(
        presented.encode("utf-8"),
        salt=salt,
        n=n,
        r=r,
        p=scrypt_p,
        dklen=dklen,
    )
