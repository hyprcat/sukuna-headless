from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("insights", "0003_insight_status_valid"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="insight",
            constraint=models.CheckConstraint(
                condition=~models.Q(title=""),
                name="insight_title_non_empty",
            ),
        ),
    ]
