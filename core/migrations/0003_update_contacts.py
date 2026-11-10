from django.db import migrations
from django.utils import timezone


def update_contacts(apps, schema_editor):
    LegalPage = apps.get_model('core', 'LegalPage')
    LegalPage.objects.using(schema_editor.connection.alias).update_or_create(
        slug='contacts', defaults={
            'title': 'Контакты',
            'body': 'По вопросам покупки и скачивания сборника напишите на электронную почту:',
            'is_draft': False,
            'updated_at': timezone.now(),
        })


class Migration(migrations.Migration):
    dependencies = [('core', '0002_import_owner_offer')]
    operations = [migrations.RunPython(update_contacts, migrations.RunPython.noop)]
