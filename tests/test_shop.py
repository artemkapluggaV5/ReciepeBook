import hashlib
from io import StringIO
import tempfile
import uuid
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import urlencode, urlsplit, parse_qs
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.management import call_command, CommandError
from django.db import IntegrityError, transaction
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from core.models import LegalPage
from delivery.services import prepare_download, renew_download, download_token
from orders.models import Order, RateBucket
from orders.services import create_checkout, can_sell
from payments.models import PaymentEvent, YooKassaInvoice
from payments.providers import YooKassa, PaymentError
from products.models import Product

@override_settings(DEBUG=True, SALES_ENABLED=True, YOOKASSA_SHOP_ID='123',
                   YOOKASSA_SECRET_KEY='test_unit_secret', YOOKASSA_TEST_MODE=True)
class ShopTests(TestCase):
    def setUp(self):
        api = patch('payments.providers.YooKassa.retrieve_payment', side_effect=PaymentError('test_pending'))
        api.start()
        self.addCleanup(api.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.override = override_settings(PRIVATE_ROOT=Path(self.temp.name))
        self.override.enable()
        self.addCleanup(self.override.disable)
        (Path(self.temp.name) / 'book.pdf').write_bytes(b'%PDF-1.4\n% unit test fixture\n%%EOF')
        self.product = Product.objects.create(title='Тестовая книга', description='Демонстрация', price='890.00', pdf_name='book.pdf')
        for slug in ['privacy', 'offer', 'consent', 'refunds', 'contacts']:
            LegalPage.objects.update_or_create(slug=slug, defaults={
                'title': slug, 'body': 'Шаблон', 'is_draft': True})


    def order(self, **kwargs):
        data = {'request_key': uuid.uuid4(), 'product': self.product,
                'product_title': self.product.title, 'amount': self.product.price, 'currency': 'RUB',
                'provider': 'yookassa', 'provider_payment_id': str(uuid.uuid4()),
                'consent_at': timezone.now(), 'legal_version': 'test'}
        data.update(kwargs)
        order = Order.objects.create(**data)
        if order.provider == 'yookassa':
            YooKassaInvoice.objects.create(order=order, shop_id='123', test_mode=True,
                                           idempotence_key=order.request_key)
        return order


    def form_data(self, **kwargs):
        self.client.get('/')
        data = {'consent': 'on', 'request_key': self.client.session['checkout_key']}
        data.update(kwargs)
        return data


    def mock_checkout(self, data):
        with patch('payments.providers.YooKassa.request') as api:
            def result(method, resource, payload=None, idempotence_key=None):
                return {'id':'00000000-0000-4000-8000-000000000001', 'status':'pending', 'paid':False,
                        'test':True, 'recipient':{'account_id':'123'}, 'amount':payload['amount'],
                        'metadata':payload['metadata'], 'confirmation':{'type':'redirect',
                        'confirmation_url':'https://yoomoney.ru/checkout/test'}}
            api.side_effect = result
            response = self.client.post('/checkout/', data)
        return response, api

    def test_landing_local_assets_and_accessibility(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'lang="ru"')
        self.assertContains(response, 'name="csrfmiddlewaretoken"')
        self.assertContains(response, 'aria-expanded="false"')
        self.assertContains(response, '/static/img/food.webp')
        self.assertNotContains(response, 'ДЕМОКОЛЛЕКЦИЯ')
        self.assertNotContains(response, 'Тестовый режим Робокассы: реальные продажи закрыты.')
        self.assertIn("frame-ancestors 'none'", response.headers['Content-Security-Policy'])


    def test_legal_health_seo_and_404(self):
        for slug in ['privacy', 'offer', 'consent', 'refunds', 'contacts']:
            self.assertEqual(self.client.get(f'/legal/{slug}/').status_code, 200)
        for path in ['/health/', '/sitemap.xml', '/robots.txt']:
            self.assertEqual(self.client.get(path).status_code, 200)
        self.assertEqual(self.client.get('/unknown/').status_code, 404)


    def test_checkout_does_not_collect_email(self):
        response, _ = self.mock_checkout(self.form_data())
        self.assertEqual(response.status_code, 302)
        self.assertNotIn('email', [f.name for f in Order._meta.fields])
        self.assertNotContains(self.client.get('/'), 'name="email"')


    def test_missing_consent(self):
        self.assertEqual(self.client.post('/checkout/', self.form_data(consent='')).status_code, 400)
        self.assertFalse(Order.objects.exists())


    def test_honeypot(self):
        self.assertEqual(self.client.post('/checkout/', self.form_data(website='spam')).status_code, 400)


    def test_session_bound_idempotency_key(self):
        self.assertEqual(self.client.post('/checkout/', self.form_data(request_key=str(uuid.uuid4()))).status_code, 400)


    def test_csrf_required_on_checkout(self):
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(client.post('/checkout/', self.form_data()).status_code, 403)


    def test_valid_csrf_form_works_with_same_origin_policy(self):
        client = Client(enforce_csrf_checks=True)
        page = client.get('/')
        self.assertEqual(page.headers['Referrer-Policy'], 'same-origin')
        self.client = client
        response, _ = self.mock_checkout({'consent':'on', 'request_key':client.session['checkout_key'],
                                         'csrfmiddlewaretoken':client.cookies['csrftoken'].value})
        self.assertEqual(response.status_code, 302)


    def test_server_side_price_and_mocked_payment_creation(self):
        response, provider = self.mock_checkout(self.form_data(amount='0.01', price='0.01', currency='USD', status='paid'))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, 'https://yoomoney.ru/checkout/test')
        order = Order.objects.get()
        self.assertEqual(order.amount, Decimal('890.00'))
        self.assertEqual(order.currency, 'RUB')
        self.assertEqual(order.status, 'pending')
        self.assertEqual(order.provider_payment_id, '00000000-0000-4000-8000-000000000001')
        self.assertEqual(provider.call_count, 1)


    def test_duplicate_checkout_creates_one_invoice(self):
        data = self.form_data()
        self.mock_checkout(data)
        response, provider = self.mock_checkout(data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Order.objects.count(), 1)
        provider.assert_not_called()


    def test_price_snapshot_survives_product_edit(self):
        data = self.form_data()
        self.mock_checkout(data)
        self.product.price = Decimal('990.00')
        self.product.save()
        self.mock_checkout(data)
        self.assertEqual(Order.objects.get().amount, Decimal('890.00'))


    def test_missing_pdf_blocks_payment_creation(self):
        (Path(self.temp.name) / 'book.pdf').unlink()
        _, provider = self.mock_checkout(self.form_data())
        provider.assert_not_called()
        self.assertFalse(Order.objects.exists())


    def test_success_redirect_never_marks_paid(self):
        order = self.order()
        self.client.get(reverse('order-status', args=[order.pk])+'?status=paid')
        order.refresh_from_db()
        self.assertEqual(order.status, 'pending')


    def test_order_status_requires_owner_session(self):
        order = self.order()
        response = self.client.get(reverse('order-status', args=[order.pk]))
        self.assertEqual(response.status_code, 403)
        self.assertNotContains(response, '/download/', status_code=403)
        self.assertIn('no-store', response.headers['Cache-Control'])


    def test_unpaid_download_denied(self):
        order = self.order(token_issued_at=timezone.now())
        self.own_order(order)
        self.assertEqual(self.client.get(reverse('download', args=[download_token(order)])).status_code, 404)


    def test_paid_pdf_download_and_headers(self):
        order = self.order(status='paid', token_issued_at=timezone.now())
        self.own_order(order)
        response = self.client.get(reverse('download', args=[download_token(order)]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['Content-Type'], 'application/pdf')
        self.assertIn('attachment', response.headers['Content-Disposition'])
        self.assertIn('no-store', response.headers['Cache-Control'])
        self.assertTrue(b''.join(response.streaming_content).startswith(b'%PDF-'))
        with patch('django.core.signals.request_finished.send'):
            response.close()
        order.refresh_from_db()
        self.assertEqual(order.download_count, 1)


    def test_head_does_not_consume_limit(self):
        order = self.order(status='paid', token_issued_at=timezone.now())
        self.own_order(order)
        response = self.client.head(reverse('download', args=[download_token(order)]))
        with patch('django.core.signals.request_finished.send'):
            response.close()
        order.refresh_from_db()
        self.assertEqual(order.download_count, 0)


    def test_invalid_and_expired_tokens(self):
        self.assertEqual(self.client.get('/download/invalid/').status_code, 404)
        order = self.order(status='paid', token_issued_at=timezone.now()-timedelta(days=31))
        self.own_order(order)
        self.assertEqual(self.client.get(reverse('download', args=[download_token(order)])).status_code, 410)


    def test_download_limit(self):
        order = self.order(status='paid', token_issued_at=timezone.now(), download_count=20)
        self.own_order(order)
        self.assertEqual(self.client.get(reverse('download', args=[download_token(order)])).status_code, 410)


    def test_missing_pdf_not_reported_as_download_ready(self):
        order = self.order(status='paid')
        (Path(self.temp.name) / 'book.pdf').unlink()
        token, issue = prepare_download(order.pk)
        self.assertIsNone(token)
        self.assertEqual(issue, 'pdf_missing')
        order.refresh_from_db()
        self.assertIsNone(order.token_issued_at)


    def test_renew_revokes_old_link(self):
        order = self.order(status='paid')
        self.own_order(order)
        old, _ = prepare_download(order.pk)
        self.assertTrue(renew_download(order.pk))
        self.assertEqual(self.client.get(reverse('download', args=[old])).status_code, 404)


    def test_admin_requires_staff(self):
        self.assertEqual(self.client.get('/admin/orders/order/').status_code, 302)
        user = get_user_model().objects.create_user('buyer', password='test-only')
        self.client.force_login(user)
        self.assertEqual(self.client.get('/admin/orders/order/').status_code, 302)


    def test_admin_cannot_forge_payment_state(self):
        admin = get_user_model().objects.create_superuser('admin', 'admin@example.test', 'test-only')
        self.client.force_login(admin)
        order = self.order()
        self.client.post(f'/admin/orders/order/{order.pk}/change/', {'status':'paid','_save':'Save'})
        order.refresh_from_db()
        self.assertEqual(order.status, 'pending')


    def test_rate_limit(self):
        for _ in range(10):
            self.client.post('/checkout/', {})
        self.assertEqual(self.client.post('/checkout/', {}).status_code, 429)


    def test_private_files_and_path_traversal(self):
        self.product.pdf_name = '../outside.pdf'
        with self.assertRaises(ValueError):
            self.product.private_path()
        self.assertEqual(self.client.get('/private/book.pdf').status_code, 404)
        self.assertEqual(self.client.get('/static/book.pdf').status_code, 404)


    def test_production_gate_identifies_missing_config(self):
        with self.assertRaises(CommandError):
            call_command('check_launch')


    def test_paid_order_shows_download_instead_of_a_new_purchase(self):
        data = self.form_data()
        self.mock_checkout(data)
        Order.objects.update(status='paid')
        response = self.client.get('/')
        self.assertEqual(self.client.session['checkout_key'], data['request_key'])
        self.assertContains(response, 'Перейти к скачиванию')
        self.assertNotContains(response, 'id="purchase-form"')


    def test_admin_login_rate_limited(self):
        for _ in range(10):
            self.client.post('/admin/login/', {'username':'unknown','password':'test-only'})
        self.assertEqual(self.client.post('/admin/login/', {}).status_code, 429)


    def test_legacy_paid_order_stays_downloadable(self):
        order = self.order(provider='cloudpayments', status='paid', token_issued_at=timezone.now())
        self.own_order(order)
        original = (Decimal(order.amount), order.status, order.token_version)
        response = self.client.get(reverse('download', args=[download_token(order)]))
        self.assertEqual(response.status_code, 200)
        with patch('django.core.signals.request_finished.send'):
            response.close()
        order.refresh_from_db()
        self.assertEqual((order.amount, order.status, order.token_version), original)
        self.assertEqual(self.client.post('/webhooks/cloudpayments/pay/', {}).status_code, 404)


    def test_inline_icons_have_accessible_geometry_and_no_font_dependency(self):
        response = self.client.get('/')
        self.assertContains(response, 'viewBox="0 0 24 24"')
        self.assertContains(response, 'focusable="false"')
        self.assertContains(response, 'viewport-fit=cover')
        self.assertContains(response, 'css/compat.css')
        self.assertIn("form-action 'self'",response.headers['Content-Security-Policy'])
        for glyph in ['✳','↗','◷','☰','⌑','✉']:
            self.assertNotContains(response, glyph)


    def own_order(self, order):
        session = self.client.session
        session['orders'] = [str(order.pk)]
        session.save()


    def test_paid_owner_sees_cover_and_download(self):
        order = self.order(status='paid')
        self.own_order(order)
        response = self.client.get(reverse('order-status', args=[order.pk]))
        self.assertContains(response, 'Скачать сборник')
        self.assertContains(response, '/download/')
        self.assertNotContains(response, 'Статус письма')
        self.assertIn('no-store', response.headers['Cache-Control'])
        self.assertEqual(response.headers['X-Robots-Tag'], 'noindex, nofollow')


    def test_unpaid_owner_never_gets_download_even_with_status_query(self):
        order = self.order()
        self.own_order(order)
        response = self.client.get(reverse('order-status', args=[order.pk]) + '?status=paid')
        self.assertContains(response, 'Проверяем оплату')
        self.assertNotContains(response, '/download/')
        self.assertContains(response, 'data-payment-pending')
        state = self.client.get(reverse('order-status', args=[order.pk]), HTTP_ACCEPT='application/json').json()
        self.assertEqual(state, {'status': 'pending', 'ready': False, 'issue': ''})


    def test_missing_file_never_offers_broken_download_button(self):
        order = self.order(status='paid')
        self.own_order(order)
        (Path(self.temp.name) / 'book.pdf').unlink()
        response = self.client.get(reverse('order-status', args=[order.pk]))
        self.assertContains(response, 'Файл временно недоступен')
        self.assertNotContains(response, '/download/')
        self.assertFalse(self.client.get(reverse('order-status', args=[order.pk]), HTTP_ACCEPT='application/json').json()['ready'])


    def test_expired_access_is_not_renewed_by_page_refresh(self):
        issued = timezone.now() - timedelta(days=31)
        order = self.order(status='paid', token_issued_at=issued)
        self.own_order(order)
        response = self.client.get(reverse('order-status', args=[order.pk]))
        self.assertNotContains(response, '/download/')
        order.refresh_from_db()
        self.assertEqual(order.token_issued_at, issued)

    def test_forwarded_download_denied_even_to_another_paying_buyer(self):
        order = self.order(status='paid', token_issued_at=timezone.now())
        self.own_order(order)
        stranger = Client()
        other = self.order(status='paid')
        session = stranger.session
        session['orders'] = [str(other.pk)]
        session.save()
        url = reverse('download', args=[download_token(order)])
        for client in [Client(), stranger]:
            for method in [client.get, client.head]:
                with patch('products.models.Product.private_path') as private_path:
                    response = method(url)
                self.assertEqual(response.status_code, 403)
                private_path.assert_not_called()
                self.assertIn('no-store', response.headers['Cache-Control'])
        order.refresh_from_db()
        self.assertEqual(order.download_count, 0)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        b''.join(response.streaming_content)
        response.close()
        order.refresh_from_db()
        self.assertEqual(order.download_count, 1)

    def test_cleared_session_cannot_use_previously_valid_download(self):
        order = self.order(status='paid', token_issued_at=timezone.now())
        self.own_order(order)
        self.client.session.flush()
        self.assertEqual(self.client.get(reverse('download', args=[download_token(order)])).status_code, 403)

    def test_checkout_return_and_download_preserve_purchaser_session(self):
        response, _ = self.mock_checkout(self.form_data())
        self.assertEqual(response.status_code, 302)
        order = Order.objects.get()
        from django.core import signing
        from payments.providers import RETURN_SALT
        token = signing.dumps(str(order.pk), salt=RETURN_SALT)
        payment = {'id': order.provider_payment_id, 'status': 'succeeded', 'paid': True,
                   'test': True, 'recipient': {'account_id': '123'},
                   'amount': {'value': '890.00', 'currency': 'RUB'},
                   'metadata': {'order_id': str(order.pk)}}
        with patch.object(YooKassa, 'retrieve_payment', return_value=payment):
            response = self.client.get(reverse('yookassa-return'), {'token': token}, follow=True)
        self.assertContains(response, '/download/')
        download, issue = prepare_download(order.pk)
        self.assertFalse(issue)
        response = self.client.get(reverse('download', args=[download]))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(b''.join(response.streaming_content).startswith(b'%PDF-'))
        response.close()
        self.assertEqual(Client().get(reverse('download', args=[download])).status_code, 403)
