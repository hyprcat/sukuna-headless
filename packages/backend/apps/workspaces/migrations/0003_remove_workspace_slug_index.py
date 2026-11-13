from __future__ import annotations

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("workspaces", "0002_invitation_token_text"),
    ]

    operations = [
        migrations.RemoveIndex(
            model_name="workspace",
            name="workspaces__slug_b5cc60_idx",
        ),
    ]
