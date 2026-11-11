import hashlib
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
from payments.models import PaymentEvent, RobokassaInvoice
from payments.providers import Checkout, Robokassa, PaymentError
from products.models import Product

@override_settings(DEBUG=True, SALES_ENABLED=True, ROBOKASSA_MERCHANT_LOGIN='unit-test-shop',
                   ROBOKASSA_TEST_PASSWORD1='unit-test-only-pass1', ROBOKASSA_TEST_PASSWORD2='unit-test-only-pass2',
                   ROBOKASSA_PASSWORD1='unit-test-live-pass1', ROBOKASSA_PASSWORD2='unit-test-live-pass2',
                   ROBOKASSA_TEST_MODE=True, ROBOKASSA_HASH_ALGORITHM='SHA256',
                   EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class ShopTests(TestCase):
    def setUp(self):
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
                'provider': 'robokassa', 'provider_payment_id': 'invoice-' + uuid.uuid4().hex,
                'consent_at': timezone.now(), 'legal_version': 'test'}
        data.update(kwargs)
        order = Order.objects.create(**data)
        if order.provider == 'robokassa':
            invoice = RobokassaInvoice.objects.create(order=order, merchant_login=settings.ROBOKASSA_MERCHANT_LOGIN,
                currency=order.currency, test_mode=settings.ROBOKASSA_TEST_MODE, hash_algorithm=settings.ROBOKASSA_HASH_ALGORITHM)
            order.provider_payment_id = str(invoice.pk)
            order.save(update_fields=['provider_payment_id'])
        return order


    def form_data(self, **kwargs):
        self.client.get('/')
        data = {'consent': 'on', 'request_key': self.client.session['checkout_key']}
        data.update(kwargs)
        return data

    def mock_checkout(self, data):
        provider = Mock(name='provider')
        provider.name = 'robokassa'
        provider.create_payment.return_value = Checkout('provider-invoice', 'https://auth.robokassa.ru/Merchant/Index.aspx?test=1')
        with patch('orders.services.can_sell', return_value=True), patch('orders.services.get_provider', return_value=provider):
            response = self.client.post('/checkout/', data)
        return response, provider

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
        provider = Mock()
        provider.name = 'robokassa'
        provider.create_payment.return_value = Checkout('csrf-invoice', 'https://auth.robokassa.ru/Merchant/Index.aspx?test=1')
        with patch('orders.services.can_sell', return_value=True), patch('orders.services.get_provider', return_value=provider):
            response = client.post('/checkout/', {'consent':'on',
                'request_key':client.session['checkout_key'], 'csrfmiddlewaretoken':client.cookies['csrftoken'].value},
                HTTP_ORIGIN='http://testserver')
        self.assertEqual(response.status_code, 302)

    def test_server_side_price_and_mocked_payment_creation(self):
        response, provider = self.mock_checkout(self.form_data(amount='0.01', price='0.01', currency='USD', status='paid'))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, 'https://auth.robokassa.ru/Merchant/Index.aspx?test=1')
        order = Order.objects.get()
        self.assertEqual(order.amount, Decimal('890.00'))
        self.assertEqual(order.currency, 'RUB')
        self.assertEqual(order.status, 'pending')
        self.assertEqual(order.provider_payment_id, 'provider-invoice')
        self.assertEqual(provider.create_payment.call_count, 1)

    def test_duplicate_checkout_creates_one_invoice(self):
        data = self.form_data()
        self.mock_checkout(data)
        response, provider = self.mock_checkout(data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Order.objects.count(), 1)
        provider.create_payment.assert_not_called()

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
        provider.create_payment.assert_not_called()
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
        self.assertEqual(self.client.get(reverse('download', args=[download_token(order)])).status_code, 404)

    def test_paid_pdf_download_and_headers(self):
        order = self.order(status='paid', token_issued_at=timezone.now())
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
        response = self.client.head(reverse('download', args=[download_token(order)]))
        with patch('django.core.signals.request_finished.send'):
            response.close()
        order.refresh_from_db()
        self.assertEqual(order.download_count, 0)

    def test_invalid_and_expired_tokens(self):
        self.assertEqual(self.client.get('/download/invalid/').status_code, 404)
        order = self.order(status='paid', token_issued_at=timezone.now()-timedelta(days=31))
        self.assertEqual(self.client.get(reverse('download', args=[download_token(order)])).status_code, 410)

    def test_download_limit(self):
        order = self.order(status='paid', token_issued_at=timezone.now(), download_count=20)
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


    def test_finished_order_allows_a_new_purchase_nonce(self):
        data = self.form_data()
        self.mock_checkout(data)
        Order.objects.update(status='paid')
        self.client.get('/')
        self.assertNotEqual(self.client.session['checkout_key'], data['request_key'])


    def test_admin_login_rate_limited(self):
        for _ in range(10):
            self.client.post('/admin/login/', {'username':'unknown','password':'test-only'})
        self.assertEqual(self.client.post('/admin/login/', {}).status_code, 429)

    def signed(self, order, password_number=2, **changes):
        invoice = order.robokassa_invoice
        event = {'InvId': str(invoice.pk), 'OutSum': '890.000000', 'Shp_currency': order.currency,
                 'Shp_order': str(order.pk), 'Shp_mode': 'test' if invoice.test_mode else 'live'}
        event.update(changes)
        secret = getattr(settings, f'ROBOKASSA_{"TEST_" if invoice.test_mode else ""}PASSWORD{password_number}')
        parts = [event['OutSum'], event['InvId'], secret]
        parts.extend(f'{key}={event[key]}' for key in sorted(event) if key.startswith('Shp_'))
        event['SignatureValue'] = hashlib.new(invoice.hash_algorithm.lower(), ':'.join(parts).encode()).hexdigest()
        return event

    def callback(self, data):
        return self.client.post(reverse('robokassa-result'), urlencode(data), content_type='application/x-www-form-urlencoded')

    def test_robokassa_url_signature_and_test_parameters(self):
        response = self.client.post('/checkout/', self.form_data())
        self.assertEqual(response.status_code, 302)
        order = Order.objects.get()
        invoice = order.robokassa_invoice
        parsed = urlsplit(response.url)
        self.assertEqual(parsed.scheme, 'https')
        self.assertEqual(parsed.hostname, 'auth.robokassa.ru')
        self.assertEqual(parsed.path, '/Merchant/Index.aspx')
        params = {key: values[0] for key, values in parse_qs(parsed.query).items()}
        self.assertEqual(params['IsTest'], '1')
        self.assertEqual(params['OutSum'], '890.00')
        self.assertEqual(params['InvId'], str(invoice.pk))
        self.assertNotIn('Email', params)
        base = f'unit-test-shop:890.00:{invoice.pk}:unit-test-only-pass1:Shp_currency=RUB:Shp_mode=test:Shp_order={order.pk}'
        self.assertEqual(params['SignatureValue'], hashlib.sha256(base.encode()).hexdigest())
        self.assertNotIn('unit-test-only-pass1', response.url)

    def test_real_adapter_duplicate_checkout_reuses_numeric_invoice(self):
        data = self.form_data()
        first = self.client.post('/checkout/', data)
        second = self.client.post('/checkout/', data)
        self.assertEqual(first.status_code, 302)
        self.assertEqual(first.url, second.url)
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(RobokassaInvoice.objects.count(), 1)

    @override_settings(ROBOKASSA_TEST_MODE=False)
    def test_live_request_does_not_include_is_test_and_uses_live_password(self):
        order = self.order()
        result = Robokassa().create_payment(order)
        params = {key: values[0] for key, values in parse_qs(urlsplit(result.url).query).items()}
        self.assertNotIn('IsTest', params)
        self.assertEqual(params['Shp_mode'], 'live')
        base = f'unit-test-shop:890.00:{order.robokassa_invoice.pk}:unit-test-live-pass1:Shp_currency=RUB:Shp_mode=live:Shp_order={order.pk}'
        self.assertEqual(params['SignatureValue'], hashlib.sha256(base.encode()).hexdigest())

    @override_settings(ROBOKASSA_HASH_ALGORITHM='MD5')
    def test_documented_alternative_algorithm_matches_merchant_setting(self):
        order = self.order()
        response = self.callback(self.signed(order))
        self.assertEqual(response.content, f'OK{order.robokassa_invoice.pk}'.encode())

    def test_verified_result_marks_paid_and_enables_download(self):
        order = self.order()
        self.assertEqual(self.callback(self.signed(order)).content, f'OK{order.robokassa_invoice.pk}'.encode())
        order.refresh_from_db()
        self.assertEqual(order.status, 'paid')
        self.assertIsNotNone(order.paid_at)
        token, issue = prepare_download(order.pk)
        self.assertTrue(token)
        self.assertEqual(issue, '')

    def test_result_invalid_signature_and_password1_are_rejected(self):
        order = self.order()
        event = self.signed(order)
        event['SignatureValue'] = '0' * 64
        self.assertEqual(self.callback(event).status_code, 403)
        self.assertEqual(self.callback(self.signed(order, password_number=1)).status_code, 403)
        order.refresh_from_db()
        self.assertEqual(order.status, 'pending')
        self.assertFalse(PaymentEvent.objects.exists())

    def test_result_rejects_signed_wrong_amount(self):
        order = self.order()
        for amount in ['1.00', '890.000001', 'NaN', '-890.00', '8.9e2', '890,00']:
            self.assertEqual(self.callback(self.signed(order, OutSum=amount)).status_code, 400)
        order.refresh_from_db()
        self.assertEqual(order.status, 'pending')

    def test_result_requires_exact_signed_order_currency_and_mode(self):
        order = self.order()
        for changes in [{'Shp_currency':'USD'}, {'Shp_order':str(uuid.uuid4())}, {'Shp_mode':'live'}, {'Shp_extra':'unexpected'}]:
            self.assertEqual(self.callback(self.signed(order, **changes)).status_code, 403)
        order.refresh_from_db()
        self.assertEqual(order.status, 'pending')

    def test_result_rejects_unknown_and_noncanonical_invoice_identifiers(self):
        order = self.order()
        for number in ['0', '-1', '01', '999999999999999999999999', 'not-an-invoice', '999999']:
            self.assertEqual(self.callback(self.signed(order, InvId=number)).status_code, 400)

    def test_duplicate_result_does_not_repeat_payment_or_delivery(self):
        order = self.order()
        event = self.signed(order)
        self.callback(event)
        token = prepare_download(order.pk)[0]
        order.refresh_from_db()
        issued_at = order.token_issued_at
        self.assertTrue(token)
        self.assertEqual(self.callback(event).content, f'OK{order.robokassa_invoice.pk}'.encode())
        self.assertTrue(prepare_download(order.pk)[0])
        order.refresh_from_db()
        self.assertEqual(order.token_issued_at, issued_at)
        self.assertEqual(PaymentEvent.objects.filter(kind='robokassa_paid').count(), 1)
        self.assertEqual(len(mail.outbox), 0)

    def test_case_insensitive_signature_and_six_decimal_sum(self):
        order = self.order()
        event = self.signed(order)
        event['SignatureValue'] = event['SignatureValue'].upper()
        self.assertEqual(self.callback(event).status_code, 200)

    def test_parameter_pollution_is_rejected(self):
        order = self.order()
        data = urlencode(list(self.signed(order).items()) + [('InvId', '123')])
        response = self.client.post(reverse('robokassa-result'), data, content_type='application/x-www-form-urlencoded')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.post(reverse('robokassa-result')+'?InvId=1', self.signed(order)).status_code, 400)

    def test_callback_keeps_working_during_sales_shutdown(self):
        order = self.order()
        with override_settings(SALES_ENABLED=False):
            self.assertEqual(self.callback(self.signed(order)).status_code, 200)

    def test_invoice_snapshot_selects_correct_test_secret_after_mode_switch(self):
        order = self.order()
        event = self.signed(order)
        with override_settings(ROBOKASSA_TEST_MODE=False):
            self.assertEqual(self.callback(event).status_code, 200)

    def test_browser_success_is_read_only_even_with_valid_password1_signature(self):
        order = self.order()
        event = self.signed(order, password_number=1)
        self.assertEqual(self.client.get(reverse('robokassa-success'), event).status_code, 302)
        self.assertEqual(self.client.post(reverse('robokassa-success'), urlencode(event), content_type='application/x-www-form-urlencoded').status_code, 302)
        order.refresh_from_db()
        self.assertEqual(order.status, 'pending')
        self.assertFalse(PaymentEvent.objects.exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_invalid_success_signature_does_not_disclose_order(self):
        order = self.order()
        event = self.signed(order, password_number=1)
        event['SignatureValue'] = '0' * 64
        self.assertEqual(self.client.get(reverse('robokassa-success'), event).status_code, 400)

    def test_failure_redirect_and_late_failure_cannot_change_payment(self):
        order = self.order()
        self.assertRedirects(self.client.get(reverse('robokassa-fail'), {'InvId':order.robokassa_invoice.pk}), '/#purchase', fetch_redirect_response=False)
        order.refresh_from_db()
        self.assertEqual(order.status, 'pending')
        self.callback(self.signed(order))
        self.client.post(reverse('robokassa-fail'), {'InvId':order.robokassa_invoice.pk})
        order.refresh_from_db()
        self.assertEqual(order.status, 'paid')

    def test_missing_result_signature_is_not_a_csrf_shortcut(self):
        client = Client(enforce_csrf_checks=True)
        order = self.order()
        event = self.signed(order)
        del event['SignatureValue']
        self.assertEqual(client.post(reverse('robokassa-result'), urlencode(event), content_type='application/x-www-form-urlencoded').status_code, 403)

    def test_legacy_paid_order_stays_downloadable(self):
        order = self.order(provider='cloudpayments', status='paid', token_issued_at=timezone.now())
        original = (Decimal(order.amount), order.status, order.token_version)
        response = self.client.get(reverse('download', args=[download_token(order)]))
        self.assertEqual(response.status_code, 200)
        with patch('django.core.signals.request_finished.send'):
            response.close()
        order.refresh_from_db()
        self.assertEqual((order.amount, order.status, order.token_version), original)
        self.assertEqual(self.client.post('/webhooks/cloudpayments/pay/', {}).status_code, 404)

    def test_refunded_order_is_not_reactivated(self):
        order = self.order(status='refunded', refunded_amount=Decimal('890'))
        self.assertEqual(self.callback(self.signed(order)).status_code, 400)
        self.assertFalse(prepare_download(order.pk)[0])

    @override_settings(ROBOKASSA_TEST_PASSWORD1='')
    def test_missing_credentials_block_sales(self):
        self.assertFalse(can_sell(self.product))
        self.assertEqual(self.client.post('/checkout/', self.form_data()).status_code, 503)
        self.assertFalse(Order.objects.exists())

    @override_settings(DEBUG=False, ROBOKASSA_TEST_MODE=False, LEGAL_READY=True, FISCALIZATION_READY=True,
                       MERCHANT_COUNTRY='RU', MERCHANT_NAME='Test merchant', MERCHANT_DETAILS='Test details',
                       CONTACT_EMAIL='support@example.test')
    def test_live_sales_require_real_product_and_legal_pages(self):
        self.assertFalse(can_sell(self.product))
        self.product.is_demo = False
        self.product.save()
        LegalPage.objects.update(is_draft=False)
        self.assertTrue(can_sell(self.product))
    def test_inline_icons_have_accessible_geometry_and_no_font_dependency(self):
        response = self.client.get('/')
        self.assertContains(response, 'viewBox="0 0 24 24"')
        self.assertContains(response, 'focusable="false"')
        self.assertContains(response, 'viewport-fit=cover')
        self.assertContains(response, 'css/compat.css')
        self.assertIn("form-action 'self' https://auth.robokassa.ru",response.headers['Content-Security-Policy'])
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

    def test_delayed_webhook_unlocks_existing_page(self):
        order = self.order()
        self.own_order(order)
        url = reverse('order-status', args=[order.pk])
        self.assertFalse(self.client.get(url, HTTP_ACCEPT='application/json').json()['ready'])
        self.callback(self.signed(order))
        self.assertTrue(self.client.get(url, HTTP_ACCEPT='application/json').json()['ready'])
        self.assertContains(self.client.get(url), 'Скачать сборник')

    def test_success_return_restores_only_signed_order_session_for_cross_site_post(self):
        order = self.order(status='paid')
        event = self.signed(order, password_number=1)
        client = Client(enforce_csrf_checks=True)
        response = client.post(reverse('robokassa-success'), urlencode(event), content_type='application/x-www-form-urlencoded')
        self.assertRedirects(response, reverse('order-status', args=[order.pk]))
        self.assertEqual(client.session['orders'], [str(order.pk)])
        self.assertContains(client.get(response.url), 'Скачать сборник')
        other = self.order(status='paid')
        self.assertEqual(client.get(reverse('order-status', args=[other.pk]), HTTP_ACCEPT='application/json').status_code, 403)

    def test_success_return_before_result_waits_and_never_confirms_payment(self):
        order = self.order()
        response = self.client.get(reverse('robokassa-success'), self.signed(order, password_number=1), follow=True)
        self.assertContains(response, 'Проверяем оплату')
        self.assertNotContains(response, '/download/')
        order.refresh_from_db()
        self.assertEqual(order.status, 'pending')
        self.assertFalse(PaymentEvent.objects.exists())

    def test_unsigned_success_cannot_grant_access_to_paid_order(self):
        order = self.order(status='paid')
        self.assertEqual(self.client.get(reverse('robokassa-success'), {'InvId': order.robokassa_invoice.pk, 'status': 'paid'}).status_code, 400)
        self.assertEqual(self.client.get(reverse('order-status', args=[order.pk])).status_code, 403)

    def test_failed_payment_returns_to_purchase_with_notice(self):
        response = self.client.get(reverse('robokassa-fail'), follow=True)
        self.assertContains(response, 'Оплата не завершена')
        response, _ = self.mock_checkout(self.form_data())
        self.assertEqual(response.status_code, 302)

    def test_late_fail_for_owned_paid_order_returns_to_download(self):
        order = self.order(status='paid')
        self.own_order(order)
        self.assertRedirects(self.client.get(reverse('robokassa-fail'), {'InvId': order.robokassa_invoice.pk}), reverse('order-status', args=[order.pk]))

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

    def test_outbound_mail_is_disabled_by_default(self):
        with patch('django.core.mail.send_mail') as send:
            order = self.order()
            self.callback(self.signed(order))
            self.own_order(order)
            self.client.get(reverse('order-status', args=[order.pk]))
            send.assert_not_called()

    @override_settings(DEBUG=False, ROBOKASSA_TEST_MODE=True, LEGAL_READY=False, FISCALIZATION_READY=False)
    def test_owner_can_enable_provider_test_checkout_on_https_server(self):
        self.assertTrue(can_sell(self.product))

    @override_settings(DEBUG=False, ROBOKASSA_TEST_MODE=False, LEGAL_READY=False, FISCALIZATION_READY=False)
    def test_live_checkout_uses_owner_switch_without_faking_review_flags(self):
        self.product.is_demo = False
        self.product.save()
        self.assertTrue(can_sell(self.product))
        self.assertFalse(settings.LEGAL_READY)
        self.assertFalse(settings.FISCALIZATION_READY)
        with override_settings(SALES_ENABLED=False):
            self.assertFalse(can_sell(self.product))
        with override_settings(ROBOKASSA_PASSWORD2=''):
            self.assertFalse(can_sell(self.product))

    def test_mode_change_rotates_browser_checkout_key(self):
        data = self.form_data()
        self.client.post('/checkout/', data)
        with override_settings(ROBOKASSA_TEST_MODE=False):
            self.client.get('/')
            self.assertNotEqual(self.client.session['checkout_key'], data['request_key'])

    def test_stale_test_checkout_never_reused_for_live_payment(self):
        data = self.form_data()
        self.client.post('/checkout/', data)
        self.product.is_demo = False
        self.product.save()
        with override_settings(ROBOKASSA_TEST_MODE=False):
            with self.assertRaisesMessage(PaymentError, 'checkout_mode_changed'):
                create_checkout(self.product, data['request_key'])
