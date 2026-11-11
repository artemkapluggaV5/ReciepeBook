from email.utils import parseaddr
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from core.models import LegalPage
from products.models import Product
from orders.services import can_sell

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
                issues.append('Checkout unavailable: SALES_ENABLED, provider credentials, currency or real product.')
        if not settings.LEGAL_READY or not settings.FISCALIZATION_READY or settings.MERCHANT_COUNTRY != 'RU':
            issues.append('Complete legal/fiscalization review and merchant country configuration.')
        if LegalPage.objects.filter(is_draft=True).exists() or LegalPage.objects.filter(slug__in=['privacy', 'offer', 'consent', 'refunds', 'contacts']).count() != 5:
            issues.append('Complete the legal documents.')
        if settings.DEBUG or settings.YOOKASSA_TEST_MODE:
            issues.append('Disable DEBUG and YOOKASSA_TEST_MODE for real sales.')
        for name in ['CONTACT_EMAIL']:
            if parseaddr(getattr(settings, name))[1].endswith('.invalid'):
                issues.append(f'Replace {name}.')
        if '[' in settings.MERCHANT_NAME or '[' in settings.MERCHANT_DETAILS:
            issues.append('Replace merchant placeholders.')
        if issues:
            raise CommandError('\n'.join(issues))
        self.stdout.write(self.style.SUCCESS('Configuration prerequisites passed; run real sandbox and live acceptance checks separately.'))
