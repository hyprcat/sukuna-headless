from decimal import Decimal

import django.db.models.deletion
import simple_history.models
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("billing", "0017_remove_topup_hosted_checkout_url"),
        ("runs", "0006_manifest_record"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="BillingHold",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "amount_reserved_usd",
                    models.DecimalField(decimal_places=4, max_digits=14),
                ),
                (
                    "amount_consumed_usd",
                    models.DecimalField(decimal_places=4, default=Decimal("0"), max_digits=14),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("active", "Active"),
                            ("settled", "Settled"),
                            ("released", "Released"),
                            ("expired", "Expired"),
                        ],
                        db_index=True,
                        default="active",
                        max_length=10,
                    ),
                ),
                ("settled_at", models.DateTimeField(blank=True, null=True)),
                ("expires_at", models.DateTimeField()),
                ("metadata", models.JSONField(blank=True, default=dict)),
                (
                    "run",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="billing_hold",
                        to="runs.run",
                    ),
                ),
                (
                    "wallet",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="holds",
                        to="billing.creditwallet",
                    ),
                ),
            ],
            options={
                "db_table": "billing_billinghold",
                "ordering": ("-created_at",),
            },
        ),
        migrations.CreateModel(
            name="HistoricalBillingHold",
            fields=[
                (
                    "id",
                    models.BigIntegerField(
                        auto_created=True, blank=True, db_index=True, verbose_name="ID"
                    ),
                ),
                ("created_at", models.DateTimeField(blank=True, db_index=True, editable=False)),
                ("updated_at", models.DateTimeField(blank=True, editable=False)),
                (
                    "amount_reserved_usd",
                    models.DecimalField(decimal_places=4, max_digits=14),
                ),
                (
                    "amount_consumed_usd",
                    models.DecimalField(decimal_places=4, default=Decimal("0"), max_digits=14),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("active", "Active"),
                            ("settled", "Settled"),
                            ("released", "Released"),
                            ("expired", "Expired"),
                        ],
                        db_index=True,
                        default="active",
                        max_length=10,
                    ),
                ),
                ("settled_at", models.DateTimeField(blank=True, null=True)),
                ("expires_at", models.DateTimeField()),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("history_id", models.AutoField(primary_key=True, serialize=False)),
                ("history_date", models.DateTimeField(db_index=True)),
                ("history_change_reason", models.CharField(max_length=100, null=True)),
                (
                    "history_type",
                    models.CharField(
                        choices=[("+", "Created"), ("~", "Changed"), ("-", "Deleted")],
                        max_length=1,
                    ),
                ),
                (
                    "history_user",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "run",
                    models.ForeignKey(
                        blank=True,
                        db_constraint=False,
                        null=True,
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        related_name="+",
                        to="runs.run",
                    ),
                ),
                (
                    "wallet",
                    models.ForeignKey(
                        blank=True,
                        db_constraint=False,
                        null=True,
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        related_name="+",
                        to="billing.creditwallet",
                    ),
                ),
            ],
            options={
                "verbose_name": "historical billing hold",
                "verbose_name_plural": "historical billing holds",
                "ordering": ("-history_date", "-history_id"),
                "get_latest_by": ("history_date", "history_id"),
            },
            bases=(simple_history.models.HistoricalChanges, models.Model),
        ),
        migrations.AddConstraint(
            model_name="billinghold",
            constraint=models.CheckConstraint(
                condition=models.Q(("status__in", ["active", "settled", "released", "expired"])),
                name="billinghold_status_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="billinghold",
            constraint=models.CheckConstraint(
                condition=models.Q(("amount_reserved_usd__gt", Decimal("0"))),
                name="billinghold_reserved_positive",
            ),
        ),
        migrations.AddConstraint(
            model_name="billinghold",
            constraint=models.CheckConstraint(
                condition=models.Q(("amount_consumed_usd__gte", Decimal("0"))),
                name="billinghold_consumed_non_negative",
            ),
        ),
        migrations.AddConstraint(
            model_name="billinghold",
            constraint=models.CheckConstraint(
                condition=models.Q(("amount_consumed_usd__lte", models.F("amount_reserved_usd"))),
                name="billinghold_consumed_lte_reserved",
            ),
        ),
    ]
