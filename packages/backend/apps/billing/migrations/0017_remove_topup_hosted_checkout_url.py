from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("billing", "0016_refund_requested_status"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="topup",
            name="hosted_checkout_url",
        ),
        migrations.RemoveField(
            model_name="historicaltopup",
            name="hosted_checkout_url",
        ),
    ]
