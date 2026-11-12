import hashlib
import tempfile
import uuid
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from django.core import signing
from django.core.management import call_command, CommandError
from django.test import TestCase, override_settings, Client
from django.urls import reverse
from django.utils import timezone
from delivery.services import download_token, prepare_download, TOKEN_SALT
from orders.models import Order
from products.models import Product


@override_settings(DEBUG=True)
class BonusTests(TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        override = override_settings(PRIVATE_ROOT=self.root)
        override.enable()
        self.addCleanup(override.disable)
        (self.root / 'book.pdf').write_bytes(b'%PDF-1.4 main')
        (self.root / 'gift.pdf').write_bytes(b'%PDF-1.4 gift')
        self.product = Product.objects.create(title='Book', price='1590.00',
            pdf_name='book.pdf', bonus_pdf_name='gift.pdf', bonus_title='Gift')
        self.order = Order.objects.create(request_key=uuid.uuid4(), product=self.product,
            product_title='Book', amount='1590.00', currency='RUB', provider='yookassa',
            status='paid', token_issued_at=timezone.now(), consent_at=timezone.now(), legal_version='test')
        session = self.client.session
        session['orders'] = [str(self.order.pk)]
        session.save()

    def gift_url(self):
        return reverse('download', args=[download_token(self.order, asset='bonus')])

    def test_owner_downloads_distinct_main_and_gift_with_private_headers(self):
        for asset, expected in [('main', b'%PDF-1.4 main'), ('bonus', b'%PDF-1.4 gift')]:
            response = self.client.get(reverse('download', args=[download_token(self.order, asset=asset)]))
            self.assertEqual(response.status_code, 200)
            self.assertIn('no-store', response.headers['Cache-Control'])
            self.assertIn('attachment', response.headers['Content-Disposition'])
            self.assertEqual(b''.join(response.streaming_content), expected)
            response.close()
        self.order.refresh_from_db()
        self.assertEqual(self.order.download_count, 2)
        self.assertContains(self.client.get(reverse('order-status', args=[self.order.pk])), 'Скачать подарок')

    def test_gift_requires_own_paid_order_for_get_and_head(self):
        stranger = Client()
        for method in ('get', 'head'):
            self.assertEqual(getattr(stranger, method)(self.gift_url()).status_code, 403)
        for status in ('pending', 'refunded'):
            Order.objects.filter(pk=self.order.pk).update(status=status)
            self.assertEqual(self.client.get(self.gift_url()).status_code, 404)

    def test_gift_obeys_expiry_limit_and_revocation(self):
        for values, expected in [
            ({'download_count': 20}, 410),
            ({'download_count': 0, 'token_issued_at': timezone.now()-timedelta(days=31)}, 410),
            ({'token_issued_at': timezone.now(), 'token_version': uuid.uuid4()}, 404),
        ]:
            Order.objects.filter(pk=self.order.pk).update(**values)
            self.assertEqual(self.client.get(self.gift_url()).status_code, expected)

    def test_missing_bonus_does_not_break_primary_download(self):
        (self.root / 'gift.pdf').unlink()
        token, issue = prepare_download(self.order.pk)
        self.assertTrue(token)
        self.assertEqual(issue, '')
        token, issue = prepare_download(self.order.pk, asset='bonus')
        self.assertIsNone(token)
        self.assertEqual(issue, 'pdf_missing')
        self.assertEqual(self.client.get(self.gift_url()).status_code, 503)

    def test_asset_is_signed_and_cannot_be_a_path(self):
        payload = {'order': str(self.order.pk), 'version': str(self.order.token_version), 'asset': '../gift.pdf'}
        token = signing.dumps(payload, salt=TOKEN_SALT)
        self.assertEqual(self.client.get(reverse('download', args=[token])).status_code, 404)
        self.product.bonus_pdf_name = '../gift.pdf'
        self.product.save(update_fields=['bonus_pdf_name'])
        with self.assertRaises(ValueError):
            self.product.private_path(asset='bonus')

    def test_connect_verifies_file_and_changes_only_offer(self):
        release = {'filename': 'gift.pdf', 'title': 'Gift',
            'sha256': hashlib.sha256((self.root/'gift.pdf').read_bytes()).hexdigest()}
        with patch('products.management.commands.connect_bonus.json.loads', return_value=release):
            call_command('connect_bonus', price='1590')
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'paid')
        self.assertEqual(self.order.amount, Decimal('1590'))
        (self.root/'gift.pdf').write_bytes(b'%PDF-1.4 wrong')
        with patch('products.management.commands.connect_bonus.json.loads', return_value=release):
            with self.assertRaisesMessage(CommandError, 'checksum mismatch'):
                call_command('connect_bonus', price='1')
        self.product.refresh_from_db()
        self.assertEqual(self.product.price, Decimal('1590'))

    def test_landing_has_new_intro_and_gift_offer(self):
        response = self.client.get('/')
        self.assertContains(response, 'более 90 любимых рецептов')
        self.assertContains(response, 'Более 90 рецептов уже ждут вас.')
        self.assertContains(response, 'Второй сборник — в подарок')
        self.assertNotContains(response, 'Добро пожаловать')
