from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("insights", "0004_insight_title_non_empty"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="insight",
            constraint=models.CheckConstraint(
                condition=~models.Q(body=""),
                name="insight_body_non_empty",
            ),
        ),
    ]
