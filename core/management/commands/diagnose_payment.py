"""Read-only diagnosis. Never print signed URLs, passwords or customer details."""
import uuid
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.urls import reverse
from orders.models import Order
from payments.models import PaymentEvent


class Command(BaseCommand):
    help = 'Read-only payment diagnosis without exposing secrets or changing payment status.'

    def add_arguments(self, parser):
        parser.add_argument('order_id', type=uuid.UUID)

    def handle(self, *args, **options):
        try:
            order = Order.objects.select_related('product', 'robokassa_invoice').get(pk=options['order_id'])
        except Order.DoesNotExist:
            raise CommandError('Order not found.') from None
        invoice = getattr(order, 'robokassa_invoice', None)
        self.stdout.write(f'Order status: {order.status}; amount: {order.amount} {order.currency}')
        self.stdout.write(f'Authenticated payment events: {PaymentEvent.objects.filter(order=order).count()}')
        if invoice:
            self.stdout.write(f'Invoice: {invoice.pk}; test: {invoice.test_mode}; hash: {invoice.hash_algorithm}')
            prefix = 'ROBOKASSA_TEST_' if invoice.test_mode else 'ROBOKASSA_'
            self.stdout.write(f'Callback password configured: {bool(getattr(settings, prefix + "PASSWORD2"))}')
        else:
            self.stdout.write('Local Robokassa invoice: missing')
        try:
            order.product.private_path()
            self.stdout.write('Private PDF: available')
        except (OSError, ValueError):
            self.stdout.write('Private PDF: unavailable')
        for label, name in [('ResultURL (POST)', 'robokassa-result'), ('SuccessURL', 'robokassa-success'), ('FailURL', 'robokassa-fail')]:
            self.stdout.write(f'{label}: {settings.SITE_URL.rstrip("/")}{reverse(name)}')
        self.stdout.write('No payment status was changed. Compare ResultURL with the merchant cabinet.')
