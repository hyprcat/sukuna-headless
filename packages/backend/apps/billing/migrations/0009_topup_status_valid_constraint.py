from __future__ import annotations

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("billing", "0008_topup_amount_supported_constraint"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="topup",
            constraint=models.CheckConstraint(
                condition=models.Q(("status__in", ["pending", "succeeded", "failed"])),
                name="topup_status_valid",
            ),
        ),
    ]
