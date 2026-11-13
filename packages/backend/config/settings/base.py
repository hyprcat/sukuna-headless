from __future__ import annotations

from urllib.parse import urlsplit

import structlog
from celery.schedules import crontab
from django.templatetags.static import static

from apps.core.observability.logging import stdlib_pre_chain
from apps.core.observability.sentry import setup_sentry
from config.runtime import BASE_DIR, runtime

SECRET_KEY = runtime.secret_key
DEBUG = runtime.debug
ALLOWED_HOSTS = runtime.allowed_hosts
ENVIRONMENT = runtime.environment

INSTALLED_APPS = [
    "unfold",
    "unfold.contrib.filters",
    "unfold.contrib.forms",
    "unfold.contrib.inlines",
    "unfold.contrib.simple_history",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.postgres",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "simple_history",
    "storages",
    "strawberry_django",
    "django_tasks_db",
    "apps.core",
    "apps.accounts",
    "apps.workspaces",
    "apps.api_keys",
    "apps.billing",
    "apps.policies",
    "apps.tools",
    "apps.knowledge",
    "apps.agents",
    "apps.end_users",
    "apps.runs",
    "apps.schedules",
    "apps.insights",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "simple_history.middleware.HistoryRequestMiddleware",
    "apps.api_keys.auth.WorkspacePrincipalMiddleware",
    "apps.core.observability.middleware.StructlogContextMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

_db = urlsplit(str(runtime.database_url))
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": _db.path.lstrip("/"),
        "USER": _db.username or "",
        "PASSWORD": _db.password or "",
        "HOST": _db.hostname or "",
        "PORT": _db.port or 5432,
        "OPTIONS": {
            "pool": {"min_size": 2, "max_size": 10, "timeout": 10},
        },
        "CONN_MAX_AGE": 0,
    },
}

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": str(runtime.redis_url),
        "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
    },
}

TASKS = {
    "default": {"BACKEND": "django.tasks.backends.immediate.ImmediateBackend"},
}

AUTH_USER_MODEL = "accounts.User"

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = 60 * 60 * 24 * 14  # 2 weeks
SESSION_ENGINE = "django.contrib.sessions.backends.cache"
SESSION_CACHE_ALIAS = "default"

PASSWORD_RESET_TIMEOUT = 60 * 60  # 1 hour
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Storage — DigitalOcean Spaces in non-dev environments. Two backends share the
# same bucket via location prefixes: media is private + signed, static is public.
if runtime.use_object_storage:
    _spaces = {
        "bucket_name": runtime.spaces_bucket,
        "region_name": runtime.spaces_region,
        "endpoint_url": runtime.spaces_endpoint,
        "access_key": runtime.spaces_access_key,
        "secret_key": runtime.spaces_secret_key,
    }
    STORAGES = {
        "default": {
            "BACKEND": "storages.backends.s3.S3Storage",
            "OPTIONS": {
                **_spaces,
                "location": "media",
                "default_acl": None,
                "querystring_auth": True,
                "querystring_expire": 3600,
                "file_overwrite": False,
                "object_parameters": {"CacheControl": "private, max-age=3600"},
            },
        },
        "staticfiles": {
            "BACKEND": "storages.backends.s3.S3Storage",
            "OPTIONS": {
                **_spaces,
                "location": "static",
                "default_acl": "public-read",
                "querystring_auth": False,
                "file_overwrite": True,
                "custom_domain": runtime.spaces_cdn_domain,
                "object_parameters": {"CacheControl": "public, max-age=31536000, immutable"},
            },
        },
    }
    _static_host = (
        runtime.spaces_cdn_domain
        or f"{runtime.spaces_bucket}.{urlsplit(runtime.spaces_endpoint).netloc}"
    )
    STATIC_URL = f"https://{_static_host}/static/"
else:
    STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }

# Celery — permitted only for beat schedules per coding standards.
CELERY_BROKER_URL = str(runtime.celery_broker_url or runtime.redis_url)
CELERY_RESULT_BACKEND = None
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_TIMEZONE = "UTC"
CELERY_BEAT_SCHEDULE = {
    "refresh-end-user-credits": {
        "task": "apps.end_users.tasks.refresh_credits.refresh_due_credits",
        "schedule": 60.0,
    },
    "reconcile-dodo-payments": {
        "task": "apps.billing.tasks.reconcile.reconcile_dodo_payments",
        "schedule": crontab(hour=3, minute=0),
    },
    "tick-due-schedules": {
        "task": "apps.schedules.tasks.tick.tick_due_schedules",
        "schedule": 60.0,
    },
    "reap-orphan-runs": {
        "task": "apps.runs.tasks.reap_orphans.reap_orphan_runs",
        "schedule": 60.0,
    },
    "sweep-idle-sandboxes": {
        "task": "apps.runs.tasks.sweep_idle.sweep_idle_sandboxes",
        "schedule": 300.0,
    },
    "reap-orphan-hitl": {
        "task": "apps.runs.tasks.reap_hitl.reap_orphan_hitl",
        "schedule": 300.0,
    },
    "detect-callback-gaps": {
        "task": "apps.runs.tasks.detect_gaps.detect_callback_gaps",
        "schedule": 300.0,
    },
    "pre-warm-pools": {
        "task": "apps.runs.tasks.pre_warm.pre_warm_pools",
        "schedule": 300.0,
    },
    "reconcile-sandbox-state": {
        "task": "apps.runs.tasks.reconcile_sandbox.reconcile_sandbox_state",
        "schedule": 600.0,
    },
    "reconcile-billing-holds": {
        "task": "apps.runs.tasks.reconcile_holds.reconcile_billing_holds",
        "schedule": 600.0,
    },
    "nightly-integration-reconciliation": {
        "task": "apps.runs.tasks.nightly_reconcile.nightly_reconciliation",
        "schedule": crontab(hour=4, minute=0),
    },
}

STRAWBERRY_DJANGO = {
    "FIELD_DESCRIPTION_FROM_HELP_TEXT": True,
    "TYPE_DESCRIPTION_FROM_MODEL_DOCSTRING": True,
    "MUTATIONS_DEFAULT_ARGUMENT_NAME": "input",
    "MUTATIONS_DEFAULT_HANDLE_ERRORS": True,
    "MAP_AUTO_ID_AS_GLOBAL_ID": True,
    "PAGINATION_DEFAULT_LIMIT": 50,
}

# Unfold theme — adheres to docs/DESIGN.md.
# Single accent: lime #D7F25C ≈ oklch(91% .174 120). Neutral base = grayscale.
# Brand fonts and focus-ring overrides are injected via STYLES (see
# apps/core/static/sukuna/admin.css).
UNFOLD = {
    "SITE_TITLE": "Sukuna Admin",
    "SITE_HEADER": "Sukuna",
    "SITE_SUBHEADER": "Operations",
    "SHOW_HISTORY": True,
    "SHOW_VIEW_ON_SITE": False,
    "BORDER_RADIUS": "6px",
    "STYLES": [lambda request: static("sukuna/admin.css")],
    "COLORS": {
        "base": {
            "50": "oklch(98% 0 0)",
            "100": "oklch(96% 0 0)",
            "200": "oklch(92% 0 0)",
            "300": "oklch(86% 0 0)",
            "400": "oklch(67% 0 0)",
            "500": "oklch(53% 0 0)",
            "600": "oklch(43% 0 0)",
            "700": "oklch(35% 0 0)",
            "800": "oklch(25% 0 0)",
            "900": "oklch(15% 0 0)",
            "950": "oklch(8% 0 0)",
        },
        "primary": {
            "50": "oklch(98% .025 120)",
            "100": "oklch(96% .05 120)",
            "200": "oklch(94% .09 120)",
            "300": "oklch(92% .13 120)",
            "400": "oklch(91.5% .16 120)",
            "500": "oklch(91% .174 120)",
            "600": "oklch(80% .17 120)",
            "700": "oklch(65% .14 120)",
            "800": "oklch(50% .11 120)",
            "900": "oklch(38% .08 120)",
            "950": "oklch(25% .05 120)",
        },
    },
}

# CORS — strict allowlist; no wildcards. Override per-env in dev/prod.
CORS_ALLOWED_ORIGINS: list[str] = []
CORS_ALLOW_CREDENTIALS = True

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            "()": structlog.stdlib.ProcessorFormatter,
            "processors": [
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.processors.JSONRenderer(),
            ],
            "foreign_pre_chain": stdlib_pre_chain(),
        },
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "json"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
}

try:
    setup_sentry(dsn=runtime.sentry_dsn, environment=ENVIRONMENT)
except Exception:
    structlog.get_logger(__name__).exception("sentry_setup_failed")
