from __future__ import annotations

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("billing", "0009_topup_status_valid_constraint"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="topup",
            constraint=models.CheckConstraint(
                condition=models.Q(("idempotency_key", ""), _negated=True),
                name="topup_idempotency_key_non_empty",
            ),
        ),
    ]
