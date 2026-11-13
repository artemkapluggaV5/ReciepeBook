import re
from django.db import migrations
from django.utils import timezone


def update_support_email(apps, schema_editor):
    LegalPage = apps.get_model('core', 'LegalPage')
    pages = LegalPage.objects.using(schema_editor.connection.alias)
    pattern = re.compile('|'.join(re.escape(address) for address in (
        'marina.novikova-1976@mail.ru', 'marishkinirecepri@mail.ru', 'marishkinirecepti@mail.ru',
    )), re.IGNORECASE)
    for page in pages.all().iterator():
        body = pattern.sub('valeron684@mail.ru', page.body)
        if body != page.body:
            pages.filter(pk=page.pk).update(body=body, updated_at=timezone.now())


class Migration(migrations.Migration):
    dependencies = [('core', '0005_direct_download_copy')]
    operations = [migrations.RunPython(update_support_email, migrations.RunPython.noop)]
