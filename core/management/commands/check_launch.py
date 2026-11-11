from email.utils import parseaddr
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from core.models import LegalPage
from products.models import Product
from orders.services import can_sell
from delivery.backends import production_email_ready

class Command(BaseCommand):
    help = 'Fail until production sales prerequisites have been supplied.'
    def handle(self, *args, **options):
        issues = []
        product = Product.objects.filter(active=True).first()
        if not product:
            issues.append('No active product.')
        else:
            try:
                product.private_path()
            except (OSError, ValueError):
                issues.append('Private PDF is missing or invalid.')
            if not can_sell(product):
                issues.append('Sales prerequisites incomplete: SALES_ENABLED, legal pages, fiscalization, RU merchant, provider credentials, real product.')
        if settings.DEBUG or settings.ROBOKASSA_TEST_MODE:
            issues.append('Disable DEBUG and ROBOKASSA_TEST_MODE for real sales.')
        if not production_email_ready():
            issues.append('Configure production SMTP or Unisender API with a sender on SITE_URL domain.')
        for name in ['CONTACT_EMAIL', 'DEFAULT_FROM_EMAIL']:
            if parseaddr(getattr(settings, name))[1].endswith('.invalid'):
                issues.append(f'Replace {name}.')
        if '[' in settings.MERCHANT_NAME or '[' in settings.MERCHANT_DETAILS:
            issues.append('Replace merchant placeholders.')
        if settings.EMAIL_BACKEND == 'django.core.mail.backends.smtp.EmailBackend' and settings.EMAIL_USE_TLS == settings.EMAIL_USE_SSL:
            issues.append('Enable exactly one SMTP transport protection: TLS or SSL.')
        if issues:
            raise CommandError('\n'.join(issues))
        self.stdout.write(self.style.SUCCESS('Configuration prerequisites passed; run real sandbox and live acceptance checks separately.'))
