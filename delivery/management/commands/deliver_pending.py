import time
from pathlib import Path
from django.core.management.base import BaseCommand
from django.db import close_old_connections
from delivery.services import deliver_order, due_orders

class Command(BaseCommand):
    help = 'Deliver paid orders. --loop runs a lightweight database-backed worker.'
    def add_arguments(self, parser):
        parser.add_argument('--loop', action='store_true')
    def handle(self, *args, **options):
        while True:
            close_old_connections()
            for order_id in due_orders():
                deliver_order(order_id)
            Path('/tmp/delivery-heartbeat').touch() if Path('/tmp').exists() else None
            if not options['loop']:
                break
            time.sleep(15)
