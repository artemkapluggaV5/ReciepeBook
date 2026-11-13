import json
import os
import subprocess
import sys
import tempfile
import uuid
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from delivery.services import download_token
from orders.models import Order
from payments.models import YooKassaInvoice
from products.models import Product


@override_settings(
    ALLOWED_HOSTS=['testserver', 'localhost', 'marishkinirecepti.ru', 'www.marishkinirecepti.ru'],
    SITE_URL='https://www.marishkinirecepti.ru',
    CANONICAL_HOST='www.marishkinirecepti.ru',
    CANONICAL_REDIRECT_HOSTS=('marishkinirecepti.ru',),
)
class CanonicalHostTests(TestCase):
    apex = 'marishkinirecepti.ru'
    www = 'www.marishkinirecepti.ru'

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        private = override_settings(PRIVATE_ROOT=self.root)
        private.enable()
        self.addCleanup(private.disable)
        (self.root / 'book.pdf').write_bytes(b'%PDF-1.4 book')
        self.product = Product.objects.create(title='Book', description='Book', price=Decimal('1.00'), pdf_name='book.pdf')
        self.order = Order.objects.create(product=self.product, product_title='Book', amount=Decimal('1.00'),
            request_key=uuid.uuid4(), status='paid', provider='yookassa', paid_at=timezone.now(),
            token_issued_at=timezone.now(), consent_at=timezone.now(), legal_version='test')

    def test_public_redirect_keeps_path_query_and_head_without_loop(self):
        for method in (self.client.get, self.client.head):
            for path in ('/', '/legal/offer/?from=footer&x=1', '/sitemap.xml', '/missing/?next=//other.example/'):
                response = method(path, HTTP_HOST=self.apex, secure=True)
                self.assertEqual(response.status_code, 308)
                self.assertEqual(response['Location'], 'https://' + self.www + path)
                self.assertIn('no-store', response['Cache-Control'])
        response = self.client.get('/', HTTP_HOST=self.www, secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<link rel="canonical" href="https://www.marishkinirecepti.ru/">')
        self.assertIsNone(response.cookies.get('sessionid')['domain'] or None)

    def test_health_and_payment_callbacks_stay_on_registered_host(self):
        self.assertEqual(self.client.get('/health/', HTTP_HOST=self.apex, secure=True).status_code, 200)
        for host in (self.apex, self.www):
            response = self.client.post('/payments/yookassa/webhook/',
                json.dumps({'type': 'notification', 'event': 'ignored'}), content_type='application/json',
                HTTP_HOST=host, secure=True)
            self.assertEqual(response.status_code, 200)
            self.assertNotIn('Location', response)

    def test_old_form_moves_to_fresh_www_checkout_before_creating_payment(self):
        response = self.client.post('/checkout/', {'consent': 'on'}, HTTP_HOST=self.apex, secure=True)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response['Location'], 'https://' + self.www + '/#purchase')
        self.assertFalse(YooKassaInvoice.objects.exists())

    def test_old_owner_keeps_download_without_sharing_or_transferring_session(self):
        session = self.client.session
        session['orders'] = [str(self.order.pk)]
        session.save()
        path = '/order/' + str(self.order.pk) + '/'
        response = self.client.get(path, HTTP_HOST=self.apex, secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Скачать сборник')
        response = self.client.get('/download/' + download_token(self.order) + '/', HTTP_HOST=self.apex, secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b''.join(response.streaming_content), b'%PDF-1.4 book')
        response.close()
        stranger = Client()
        response = stranger.get(path, HTTP_HOST=self.apex, secure=True, follow=True)
        self.assertEqual(response.status_code, 403)

    def test_www_does_not_disable_csrf_checks(self):
        response = Client(enforce_csrf_checks=True).post('/checkout/', {'consent': 'on'},
            HTTP_HOST=self.www, secure=True)
        self.assertEqual(response.status_code, 403)

    def test_production_settings_upgrade_existing_apex_site_url(self):
        env = {**os.environ, 'DEBUG': 'False', 'SECRET_KEY': 'test-' + 'x' * 60,
               'SITE_URL': 'https://marishkinirecepti.ru', 'DATABASE_URL': 'postgres://test:test@localhost/test',
               'ALLOWED_HOSTS': 'marishkinirecepti.ru,localhost', 'CSRF_TRUSTED_ORIGINS': 'https://marishkinirecepti.ru'}
        script = ('import json; from config import settings as s; '
                  'print(json.dumps([s.SITE_URL, s.CANONICAL_HOST, s.ALLOWED_HOSTS, s.CSRF_TRUSTED_ORIGINS]))')
        result = subprocess.run([sys.executable, '-c', script], cwd=settings.BASE_DIR,
            env=env, capture_output=True, text=True, check=True)
        site, host, allowed, csrf = json.loads(result.stdout)
        self.assertEqual(site, 'https://www.marishkinirecepti.ru')
        self.assertEqual(host, self.www)
        self.assertIn(self.www, allowed)
        self.assertIn('https://' + self.www, csrf)
