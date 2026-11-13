import json
import os
import subprocess
import sys
import tempfile
import uuid
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

from django.conf import settings
from django.core import signing
from django.contrib.sessions.models import Session
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from delivery.services import download_token
from orders.models import Order
from payments.models import YooKassaInvoice
from payments.providers import RETURN_SALT
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
            for path in ('/', '/legal/offer/?from=footer&x=1', '/sitemap.xml', '/health/', '/domain/missing/', '/missing/?next=//other.example/'):
                response = method(path, HTTP_HOST=self.apex, secure=True)
                self.assertEqual(response.status_code, 308)
                self.assertEqual(response['Location'], 'https://' + self.www + path)
                self.assertIn('no-store', response['Cache-Control'])
        response = self.client.get('/', HTTP_HOST=self.www, secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<link rel="canonical" href="https://www.marishkinirecepti.ru/">')
        self.assertIsNone(response.cookies.get('sessionid')['domain'] or None)

    def test_health_localhost_and_payment_callbacks_stay_available(self):
        for host in ('localhost', self.www):
            self.assertEqual(self.client.get('/health/', HTTP_HOST=host, secure=True).status_code, 200)
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

    def prepare_transfer(self, www, path):
        session = self.client.session
        session['orders'] = [str(self.order.pk)]
        session.save()
        first = self.client.get(path, HTTP_HOST=self.apex, secure=True)
        self.assertEqual(first.status_code, 302)
        self.assertEqual(urlsplit(first['Location']).hostname, self.www)
        prepare = www.get(first['Location'], HTTP_HOST=self.www, secure=True)
        self.assertEqual(prepare.status_code, 302)
        self.assertEqual(urlsplit(prepare['Location']).hostname, self.apex)
        confirm = self.client.get(prepare['Location'], HTTP_HOST=self.apex, secure=True)
        self.assertEqual(confirm.status_code, 302)
        self.assertEqual(urlsplit(confirm['Location']).hostname, self.www)
        for response in (first, prepare, confirm):
            self.assertIn('no-store', response['Cache-Control'])
            self.assertEqual(response['Referrer-Policy'], 'no-referrer')
        return confirm['Location']

    def test_old_owner_moves_to_www_with_separate_host_cookies_and_downloads(self):
        # Different clients emulate real host-only cookie jars. Django's automatic
        # redirect following otherwise sends one cookie jar to both hostnames.
        www = Client()
        path = '/order/' + str(self.order.pk) + '/'
        finish_url = self.prepare_transfer(www, path + '?from=old')
        self.assertNotIn(self.client.session.session_key, finish_url)
        finish = www.get(finish_url, HTTP_HOST=self.www, secure=True)
        self.assertEqual(finish['Location'], 'https://' + self.www + path + '?from=old')
        self.assertFalse(finish.cookies['sessionid']['domain'])
        self.assertNotEqual(www.session.session_key, self.client.session.session_key)
        response = www.get(finish['Location'], HTTP_HOST=self.www, secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Скачать сборник')
        response = www.get('/download/' + download_token(self.order) + '/', HTTP_HOST=self.www, secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b''.join(response.streaming_content), b'%PDF-1.4 book')
        response.close()
        stranger = Client()
        response = stranger.get(path, HTTP_HOST=self.apex, secure=True, follow=True)
        self.assertEqual(response.status_code, 403)

    def test_old_direct_download_also_finishes_on_www(self):
        www = Client()
        path = '/download/' + download_token(self.order) + '/'
        finish_url = self.prepare_transfer(www, path)
        response = www.get(finish_url, HTTP_HOST=self.www, secure=True)
        self.assertEqual(response['Location'], 'https://' + self.www + path)
        response = www.get(response['Location'], HTTP_HOST=self.www, secure=True)
        self.assertEqual(b''.join(response.streaming_content), b'%PDF-1.4 book')
        response.close()
        self.order.refresh_from_db()
        self.assertEqual(self.order.download_count, 1)

    def test_old_payment_return_and_existing_www_ownership_survive_transfer(self):
        www = Client()
        existing = str(uuid.uuid4())
        session = www.session
        session['orders'] = [existing]
        session.save()
        token = signing.dumps(str(self.order.pk), salt=RETURN_SALT)
        path = '/payments/yookassa/return/?token=' + token
        finish_url = self.prepare_transfer(www, path)
        response = www.get(finish_url, HTTP_HOST=self.www, secure=True)
        self.assertEqual(response['Location'], 'https://' + self.www + path)
        response = www.get(response['Location'], HTTP_HOST=self.www, secure=True)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], '/order/' + str(self.order.pk) + '/')
        self.assertIn(existing, www.session['orders'])
        self.assertIn(str(self.order.pk), www.session['orders'])

    def test_grant_requires_www_browser_and_is_single_use_not_a_login_cookie(self):
        www = Client()
        path = '/order/' + str(self.order.pk) + '/'
        finish_url = self.prepare_transfer(www, path)
        grant = parse_qs(urlsplit(finish_url).query)['grant'][0]
        stranger = Client()
        self.assertEqual(stranger.get(finish_url, HTTP_HOST=self.www, secure=True).status_code, 400)
        self.assertTrue(Session.objects.filter(session_key=grant).exists())
        stranger.cookies['sessionid'] = grant
        self.assertEqual(stranger.get(path, HTTP_HOST=self.www, secure=True).status_code, 403)
        response = www.get(finish_url, HTTP_HOST=self.www, secure=True)
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Session.objects.filter(session_key=grant).exists())
        self.assertEqual(www.get(finish_url, HTTP_HOST=self.www, secure=True).status_code, 400)

    def test_expired_grant_does_not_remove_original_access(self):
        www = Client()
        finish_url = self.prepare_transfer(www, '/order/' + str(self.order.pk) + '/')
        grant = parse_qs(urlsplit(finish_url).query)['grant'][0]
        Session.objects.filter(session_key=grant).update(expire_date=timezone.now() - timedelta(seconds=1))
        self.assertEqual(www.get(finish_url, HTTP_HOST=self.www, secure=True).status_code, 400)
        self.assertIn(str(self.order.pk), self.client.session['orders'])

    def test_transfer_does_not_allow_external_redirects(self):
        for target in ('//evil.example/', 'https://evil.example/', '/\\evil.example/', '/domain/prepare/'):
            response = self.client.get('/domain/prepare/', {'next': target}, HTTP_HOST=self.www, secure=True)
            self.assertEqual(parse_qs(urlsplit(response['Location']).query)['next'], ['/'])

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
