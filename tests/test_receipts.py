import tempfile
import uuid
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from django.test import TestCase, override_settings
from orders.services import create_checkout
from orders.models import Order
from payments.models import YooKassaInvoice
from payments.providers import YooKassa, PaymentError
from products.models import Product


@override_settings(DEBUG=True, SALES_ENABLED=True, YOOKASSA_TEST_MODE=False,
                   YOOKASSA_SHOP_ID='123', YOOKASSA_SECRET_KEY='live_unit_only',
                   YOOKASSA_RECEIPTS_ENABLED=False, YOOKASSA_VAT_CODE=1)
class ReceiptTests(TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        override = override_settings(PRIVATE_ROOT=Path(directory.name))
        override.enable()
        self.addCleanup(override.disable)
        (Path(directory.name) / 'book.pdf').write_bytes(b'%PDF-1.4 test')
        self.product = Product.objects.create(title='Book', price='1990.00',
                                             pdf_name='book.pdf', is_demo=False)

    def pending(self, method, resource, payload=None, idempotence_key=None):
        return {'id': str(uuid.uuid4()), 'status': 'pending', 'paid': False, 'test': False,
                'recipient': {'account_id': '123'}, 'amount': payload['amount'],
                'metadata': payload['metadata'], 'confirmation': {'type': 'redirect',
                'confirmation_url': 'https://yoomoney.ru/checkout/test'}}

    def test_live_checkout_requires_valid_receipt_email_before_api(self):
        page = self.client.get('/')
        self.assertContains(page, 'name="receipt_email"')
        for email in ['', 'invalid', 'x\nBcc:secret@example.test']:
            with patch.object(YooKassa, 'request') as api:
                response = self.client.post('/checkout/', {'consent': 'on',
                    'request_key': self.client.session['checkout_key'], 'receipt_email': email})
            self.assertEqual(response.status_code, 400)
            api.assert_not_called()
        self.assertFalse(Order.objects.exists())

    def test_live_checkout_sends_owner_vat_and_server_price_with_receipt(self):
        self.client.get('/')
        with patch.object(YooKassa, 'request', side_effect=self.pending) as api:
            response = self.client.post('/checkout/', {'consent': 'on',
                'request_key': self.client.session['checkout_key'],
                'receipt_email': 'buyer@example.test', 'price': '1', 'vat_code': '2'})
        self.assertEqual(response.status_code, 302)
        payload = api.call_args.args[2]
        receipt = payload['receipt']
        self.assertEqual(receipt['customer'], {'email': 'buyer@example.test'})
        item = receipt['items'][0]
        self.assertEqual(item['amount'], payload['amount'])
        self.assertEqual(item['amount']['value'], '1990.00')
        self.assertEqual(item['quantity'], '1.000')
        self.assertEqual(item['vat_code'], 1)
        self.assertEqual(item['payment_mode'], 'full_payment')
        self.assertEqual(item['payment_subject'], 'intellectual_activity')
        self.assertTrue(receipt['internet'])
        self.assertEqual(receipt, YooKassaInvoice.objects.get().receipt)
        self.assertNotIn('buyer@example.test', response.headers['Location'])

    def test_timeout_retry_preserves_receipt_email_tax_price_and_idempotency(self):
        key = uuid.uuid4()
        with patch.object(YooKassa, 'request', side_effect=PaymentError('yookassa_unavailable')) as api:
            with self.assertRaises(PaymentError):
                create_checkout(self.product, key, receipt_email='first@example.test')
            original = api.call_args.args
            self.product.price = Decimal('5.00')
            self.product.save()
            with override_settings(YOOKASSA_VAT_CODE=7), self.assertRaises(PaymentError):
                create_checkout(self.product, key, receipt_email='second@example.test')
            self.assertEqual(api.call_args.args, original)
        self.assertEqual(Order.objects.count(), 1)

    def test_upgrade_rotates_form_nonce_without_changing_old_attempt(self):
        self.client.get('/')
        old = self.client.session['checkout_key']
        with patch.object(YooKassa, 'request', side_effect=PaymentError('yookassa_unavailable')):
            with self.assertRaises(PaymentError):
                create_checkout(self.product, uuid.UUID(old), receipt_email='buyer@example.test')
        invoice = YooKassaInvoice.objects.get()
        # Emulate a pre-upgrade ambiguous attempt with no receipt or session marker.
        invoice.receipt = {}
        invoice.save(update_fields=['receipt'])
        session = self.client.session
        del session['checkout_receipts']
        session.save()
        self.client.get('/')
        self.assertNotEqual(old, self.client.session['checkout_key'])
        invoice.refresh_from_db()
        self.assertEqual(str(invoice.idempotence_key), old)
        self.assertEqual(invoice.receipt, {})
        current = self.client.session['checkout_key']
        self.client.get('/')
        self.assertEqual(self.client.session['checkout_key'], current)
        with patch.object(YooKassa, 'request') as api, self.assertRaisesMessage(
                PaymentError, 'checkout_receipt_upgrade_required'):
            create_checkout(self.product, uuid.UUID(old), receipt_email='buyer@example.test')
        api.assert_not_called()

    def test_test_receipts_can_be_explicitly_enabled(self):
        with override_settings(YOOKASSA_TEST_MODE=True, YOOKASSA_SECRET_KEY='test_only',
                               YOOKASSA_RECEIPTS_ENABLED=True):
            self.assertContains(self.client.get('/'), 'name="receipt_email"')
