import tempfile
import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path
from threading import Barrier
from unittest.mock import patch
from django.db import close_old_connections
from django.test import TransactionTestCase, override_settings, skipUnlessDBFeature
from django.utils import timezone
from delivery.services import prepare_download
from orders.models import Order
from payments.models import PaymentEvent, YooKassaInvoice
from payments.services import apply_payment
from payments.providers import YooKassa
from django.db import transaction
from orders.services import create_checkout
from products.models import Product

@override_settings(YOOKASSA_SHOP_ID='123', YOOKASSA_SECRET_KEY='test_concurrency', YOOKASSA_TEST_MODE=True)
class PostgreSQLConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.override = override_settings(PRIVATE_ROOT=Path(self.temp.name))
        self.override.enable()
        self.addCleanup(self.override.disable)
        (Path(self.temp.name)/'book.pdf').write_bytes(b'%PDF-1.4\nfixture')
        product = Product.objects.create(title='Test', description='Test', price=Decimal('890'), pdf_name='book.pdf')
        self.order = Order.objects.create(request_key=uuid.uuid4(), product=product,
            product_title='Test', amount=Decimal('890'), currency='RUB', provider='yookassa',
            status='paid', consent_at=timezone.now(), legal_version='test')
        self.invoice = YooKassaInvoice.objects.create(order=self.order, shop_id='123', test_mode=True, idempotence_key=self.order.request_key)
        self.order.provider_payment_id = str(uuid.uuid4())
        self.order.save()

    def run_parallel(self, action):
        barrier = Barrier(2)
        def run(_):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return action()
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(run, range(2)))

    @skipUnlessDBFeature('has_select_for_update')
    def test_parallel_pages_issue_same_download_token(self):
        results = self.run_parallel(lambda: prepare_download(self.order.pk))
        self.assertEqual(results[0], results[1])
        self.assertTrue(results[0][0])

    @skipUnlessDBFeature('has_select_for_update')
    def test_parallel_duplicate_events_are_idempotent(self):
        def settle():
            with transaction.atomic():
                order = Order.objects.select_for_update().get(pk=self.order.pk)
                apply_payment(order, {'id':order.provider_payment_id,'status':'succeeded'})
        self.run_parallel(settle)
        self.assertEqual(PaymentEvent.objects.count(), 1)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'paid')

    @skipUnlessDBFeature('has_select_for_update')
    def test_parallel_checkout_creates_one_remote_payment(self):
        key = uuid.uuid4()
        payment_id = str(uuid.uuid4())
        def create(order, invoice):
            return {'id':payment_id, 'status':'pending', 'paid':False, 'test':True,
                    'recipient':{'account_id':'123'}, 'amount':{'value':'890.00','currency':'RUB'},
                    'metadata':{'order_id':str(order.pk)},
                    'confirmation':{'type':'redirect','confirmation_url':'https://yoomoney.ru/checkout/test'}}
        with patch('orders.services.can_sell', return_value=True), patch.object(YooKassa,'create_payment',side_effect=create) as api:
            results = self.run_parallel(lambda: create_checkout(self.order.product, key))
        api.assert_called_once()
        self.assertEqual(results[0][0].pk, results[1][0].pk)
        self.assertEqual(results[0][1], results[1][1])
        self.assertEqual(Order.objects.filter(request_key=key).count(), 1)
        self.assertEqual(YooKassaInvoice.objects.filter(order__request_key=key).count(), 1)
