from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("workspaces", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="historicalinvitation",
            name="token",
            field=models.TextField(blank=True, db_index=True, default="", editable=False),
        ),
        migrations.AlterField(
            model_name="invitation",
            name="token",
            field=models.TextField(blank=True, default="", editable=False, unique=True),
        ),
    ]
