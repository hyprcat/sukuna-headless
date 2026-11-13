from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("insights", "0002_insight_category_valid"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="insight",
            constraint=models.CheckConstraint(
                condition=models.Q(status__in=["active", "dismissed", "pinned"]),
                name="insight_status_valid",
            ),
        ),
    ]
