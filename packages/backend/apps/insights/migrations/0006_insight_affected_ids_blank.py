from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("insights", "0005_insight_body_non_empty"),
    ]

    operations = [
        migrations.AlterField(
            model_name="historicalinsight",
            name="affected_agent_ids",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="Agent PKs referenced by this insight.",
            ),
        ),
        migrations.AlterField(
            model_name="historicalinsight",
            name="affected_end_user_ids",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="EndUser PKs referenced by this insight.",
            ),
        ),
        migrations.AlterField(
            model_name="historicalinsight",
            name="affected_run_ids",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="Run UUIDs referenced by this insight.",
            ),
        ),
        migrations.AlterField(
            model_name="insight",
            name="affected_agent_ids",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="Agent PKs referenced by this insight.",
            ),
        ),
        migrations.AlterField(
            model_name="insight",
            name="affected_end_user_ids",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="EndUser PKs referenced by this insight.",
            ),
        ),
        migrations.AlterField(
            model_name="insight",
            name="affected_run_ids",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="Run UUIDs referenced by this insight.",
            ),
        ),
    ]
