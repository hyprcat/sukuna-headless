from __future__ import annotations

from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("billing", "0007_ledgerentry_adjustment_note_constraint"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="topup",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    (
                        "amount_usd__in",
                        [
                            Decimal("20.00"),
                            Decimal("50.00"),
                            Decimal("100.00"),
                            Decimal("500.00"),
                        ],
                    )
                ),
                name="topup_amount_supported",
            ),
        ),
    ]
