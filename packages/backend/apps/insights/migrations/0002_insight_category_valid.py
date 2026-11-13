from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("insights", "0001_initial"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="insight",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    category__in=[
                        "capability_gap",
                        "tier_optimization",
                        "quality_issue",
                        "scheduled_task_health",
                    ],
                ),
                name="insight_category_valid",
            ),
        ),
    ]
