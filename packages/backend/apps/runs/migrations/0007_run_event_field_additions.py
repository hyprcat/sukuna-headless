import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("runs", "0006_manifest_record"),
    ]

    operations = [
        # --- Run: replace conversation_id UUID with conversation FK ---
        migrations.RemoveIndex(
            model_name="run",
            name="runs_run_convers_1382a4_idx",
        ),
        migrations.RemoveField(
            model_name="run",
            name="conversation_id",
        ),
        migrations.RemoveField(
            model_name="historicalrun",
            name="conversation_id",
        ),
        migrations.AddField(
            model_name="run",
            name="conversation",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="runs",
                to="runs.conversation",
            ),
        ),
        migrations.AddField(
            model_name="historicalrun",
            name="conversation",
            field=models.ForeignKey(
                blank=True,
                db_constraint=False,
                null=True,
                on_delete=django.db.models.deletion.DO_NOTHING,
                related_name="+",
                to="runs.conversation",
            ),
        ),
        # --- Run: new integration fields ---
        migrations.AddField(
            model_name="run",
            name="manifest_id",
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="historicalrun",
            name="manifest_id",
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="run",
            name="last_callback_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="historicalrun",
            name="last_callback_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="run",
            name="last_projected_sequence",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="historicalrun",
            name="last_projected_sequence",
            field=models.PositiveIntegerField(default=0),
        ),
        # --- RunEvent: callback dedup + batch tracking ---
        migrations.AddField(
            model_name="runevent",
            name="callback_event_id",
            field=models.UUIDField(blank=True, null=True, unique=True),
        ),
        migrations.AddField(
            model_name="runevent",
            name="batch_id",
            field=models.UUIDField(blank=True, null=True),
        ),
    ]
