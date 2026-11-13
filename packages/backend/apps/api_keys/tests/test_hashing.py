from __future__ import annotations

from apps.api_keys.hashing import hash_secret, verify_secret


def test_hash_and_verify_roundtrip() -> None:
    secret = "ms_dev_abc123"
    stored = hash_secret(secret)

    assert stored != secret
    assert verify_secret(secret, stored)
    assert not verify_secret(secret + "x", stored)


def test_hash_is_self_describing() -> None:
    stored = hash_secret("ms_dev_xyz")

    assert stored.startswith("scrypt$")
    assert stored.count("$") == 5


def test_hash_uses_random_salt() -> None:
    a = hash_secret("ms_dev_same")
    b = hash_secret("ms_dev_same")

    assert a != b  # salt must differ
    assert verify_secret("ms_dev_same", a)
    assert verify_secret("ms_dev_same", b)


def test_verify_rejects_malformed_stored_hash() -> None:
    assert not verify_secret("anything", "")
    assert not verify_secret("anything", "not$a$valid$hash")
    assert not verify_secret("anything", "bcrypt$1$2$3$4$5")  # wrong algo tag
