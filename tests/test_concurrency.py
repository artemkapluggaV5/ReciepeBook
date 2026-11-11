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
from payments.models import PaymentEvent, RobokassaInvoice
from payments.services import process_result
from payments.providers import digest, signed_fields, user_fields
from orders.services import create_checkout
from products.models import Product

@override_settings(ROBOKASSA_MERCHANT_LOGIN='concurrency-test-shop', ROBOKASSA_TEST_MODE=True,
                   ROBOKASSA_TEST_PASSWORD1='concurrency-unit-password1', ROBOKASSA_TEST_PASSWORD2='concurrency-unit-test-only',
                   EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
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
            product_title='Test', amount=Decimal('890'), currency='RUB', provider='robokassa',
            status='paid', consent_at=timezone.now(), legal_version='test')
        self.invoice = RobokassaInvoice.objects.create(order=self.order, merchant_login='test-only', test_mode=True)
        self.order.provider_payment_id = str(self.invoice.pk)
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
        fields = user_fields(self.invoice)
        event = {'InvId':str(self.invoice.pk), 'OutSum':'890.000000', **fields}
        event['SignatureValue'] = digest([event['OutSum'],event['InvId'],'concurrency-unit-test-only',*signed_fields(fields)], 'SHA256')
        self.run_parallel(lambda: process_result(event))
        self.assertEqual(PaymentEvent.objects.count(), 1)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'paid')

    @skipUnlessDBFeature('has_select_for_update')
    def test_parallel_checkout_creates_one_order_and_numeric_invoice(self):
        key = uuid.uuid4()
        with patch('orders.services.can_sell', return_value=True):
            results = self.run_parallel(lambda: create_checkout(self.order.product, key))
        self.assertEqual(results[0][0].pk, results[1][0].pk)
        self.assertEqual(results[0][1], results[1][1])
        self.assertEqual(Order.objects.filter(request_key=key).count(), 1)
        self.assertEqual(RobokassaInvoice.objects.filter(order__request_key=key).count(), 1)
