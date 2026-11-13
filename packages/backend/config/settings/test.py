from __future__ import annotations

from config.settings.base import *  # noqa: F403

DEBUG = False

# Speed up auth in tests; never use MD5 elsewhere.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# Disable real cache in tests.
CACHES = {
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
}

# Connection pooling is a production concern. In tests it adds a hard
# ``max_size`` cap that async tests exhaust — ORM run through ``sync_to_async``
# opens connections in executor threads the pool can't reclaim, so the suite
# eventually fails with ``PoolTimeout``. Use direct connections instead.
DATABASES["default"]["OPTIONS"].pop("pool", None)  # noqa: F405
