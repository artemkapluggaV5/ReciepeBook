from django.db import migrations
from django.utils import timezone


def update_seller_email(apps, schema_editor):
    LegalPage = apps.get_model('core', 'LegalPage')
    pages = LegalPage.objects.using(schema_editor.connection.alias)
    for page in pages.all().iterator():
        body = page.body
        for previous in ('marina.novikova-1976@mail.ru', 'marishkinirecepri@mail.ru'):
            body = body.replace(previous, 'marishkinirecepti@mail.ru')
        if body != page.body:
            pages.filter(pk=page.pk).update(body=body, updated_at=timezone.now())


class Migration(migrations.Migration):
    dependencies = [('core', '0003_update_contacts')]
    operations = [migrations.RunPython(update_seller_email, migrations.RunPython.noop)]
