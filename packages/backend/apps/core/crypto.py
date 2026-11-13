"""Ed25519 key loading for manifest signing and JWT minting."""

from __future__ import annotations

import base64

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key


def load_ed25519_private_key(key_text: str) -> Ed25519PrivateKey:
    """Load an Ed25519 private key from PEM or raw base64."""
    text = key_text.strip()
    if text.startswith("-----BEGIN"):
        raw_key = load_pem_private_key(text.encode(), password=None)
    else:
        raw_bytes = base64.b64decode(text)
        raw_key = Ed25519PrivateKey.from_private_bytes(raw_bytes)
    if not isinstance(raw_key, Ed25519PrivateKey):
        raise TypeError("Key is not Ed25519.")
    return raw_key
