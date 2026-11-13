from __future__ import annotations

from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.accounts"
    label = "accounts"

    def ready(self) -> None:
        # Custom User models can't carry HistoricalRecords directly (the
        # history_user FK would point to a swapped/abstract model). Register
        # at app-ready instead, excluding fields we never want in audit rows.
        from simple_history import register

        from apps.accounts.models import User

        register(
            User,
            excluded_fields=["password", "last_login", "updated_at"],
        )
