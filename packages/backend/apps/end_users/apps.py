from __future__ import annotations

from django.apps import AppConfig


class EndUsersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.end_users"
    label = "end_users"
