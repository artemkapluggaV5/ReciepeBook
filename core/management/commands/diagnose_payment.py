import uuid
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.urls import reverse
from orders.models import Order
from payments.models import PaymentEvent
from payments.providers import configured

class Command(BaseCommand):
    help = 'Read-only payment diagnosis; no secrets or signed URLs.'
    def add_arguments(self, parser):
        parser.add_argument('order_id', type=uuid.UUID)
    def handle(self, *args, **options):
        try:
            order = Order.objects.select_related('product', 'yookassa_invoice').get(pk=options['order_id'])
        except Order.DoesNotExist:
            raise CommandError('Order not found.') from None
        self.stdout.write(f'Provider: {order.provider}; status: {order.status}; amount: {order.amount} {order.currency}')
        self.stdout.write(f'Authenticated events: {PaymentEvent.objects.filter(order=order).count()}')
        invoice = getattr(order, 'yookassa_invoice', None)
        if invoice:
            self.stdout.write(f'Shop: {invoice.shop_id}; test: {invoice.test_mode}; payment ID: {order.provider_payment_id or "not created"}')
        self.stdout.write(f'YooKassa configured: {configured()}')
        try:
            order.product.private_path()
            self.stdout.write('Private PDF: available')
        except (OSError, ValueError):
            self.stdout.write('Private PDF: unavailable')
        self.stdout.write('Webhook: ' + settings.SITE_URL + reverse('yookassa-webhook'))
        self.stdout.write('No status changed. Pending orders verify directly through API on the owned status page.')
