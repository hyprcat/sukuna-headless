import uuid

import django.db.models.deletion
import simple_history.models
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("agents", "0001_initial"),
        ("end_users", "0001_initial"),
        ("runs", "0004_sandbox_instance"),
        ("workspaces", "0004_add_dodo_customer_id"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="HistoricalConversation",
            fields=[
                ("id", models.BigIntegerField(auto_created=True, blank=True, db_index=True, verbose_name="ID")),
                ("created_at", models.DateTimeField(blank=True, db_index=True, editable=False)),
                ("updated_at", models.DateTimeField(blank=True, editable=False)),
                ("conversation_uid", models.UUIDField(db_index=True, default=uuid.uuid4, editable=False)),
                ("title", models.CharField(blank=True, default="", max_length=512)),
                ("history_id", models.AutoField(primary_key=True, serialize=False)),
                ("history_date", models.DateTimeField(db_index=True)),
                ("history_change_reason", models.CharField(max_length=100, null=True)),
                ("history_type", models.CharField(choices=[("+", "Created"), ("~", "Changed"), ("-", "Deleted")], max_length=1)),
                ("agent", models.ForeignKey(blank=True, db_constraint=False, null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name="+", to="agents.agent")),
                ("end_user", models.ForeignKey(blank=True, db_constraint=False, null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name="+", to="end_users.enduser")),
                ("history_user", models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
                ("workspace", models.ForeignKey(blank=True, db_constraint=False, null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name="+", to="workspaces.workspace")),
            ],
            options={
                "verbose_name": "historical conversation",
                "verbose_name_plural": "historical conversations",
                "ordering": ("-history_date", "-history_id"),
                "get_latest_by": ("history_date", "history_id"),
            },
            bases=(simple_history.models.HistoricalChanges, models.Model),
        ),
        migrations.CreateModel(
            name="Conversation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("conversation_uid", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("title", models.CharField(blank=True, default="", max_length=512)),
                ("agent", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="conversations", to="agents.agent")),
                ("end_user", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="conversations", to="end_users.enduser")),
                ("workspace", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="conversations", to="workspaces.workspace")),
            ],
            options={
                "db_table": "runs_conversation",
                "ordering": ("-created_at",),
            },
        ),
    ]
