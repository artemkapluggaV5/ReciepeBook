from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('payments', '0003_yookassa')]
    operations = [migrations.AddField(
        model_name='yookassainvoice', name='receipt',
        field=models.JSONField(default=dict, blank=True),
    )]
