from django.core.management.base import BaseCommand, CommandError
from delivery.services import deliver_order
from orders.models import Order

class Command(BaseCommand):
    help = 'Resend only a verified paid order; --renew revokes the old link and resets its policy.'
    def add_arguments(self, parser):
        parser.add_argument('order_id')
        parser.add_argument('--renew', action='store_true')
    def handle(self, *args, **options):
        try:
            if not deliver_order(options['order_id'], force=True, renew=options['renew']):
                raise CommandError('Not sent: unpaid order, missing PDF, or email failure. Inspect Admin.')
        except (Order.DoesNotExist, ValueError) as exc:
            raise CommandError('Order not found') from exc
        self.stdout.write(self.style.SUCCESS('Message accepted by email backend.'))
