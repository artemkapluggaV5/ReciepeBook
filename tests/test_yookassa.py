import copy
import json
import tempfile
import uuid
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch, MagicMock
from urllib.error import HTTPError, URLError
from django.conf import settings
from django.core import signing
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone
from orders.models import Order
from orders.services import create_checkout, can_sell
from payments.models import PaymentEvent, YooKassaInvoice
from payments.providers import YooKassa, PaymentError, RETURN_SALT
from payments.services import sync_payment, process_refund
from delivery.services import prepare_download, download_token
from products.models import Product

@override_settings(DEBUG=True, SALES_ENABLED=True, YOOKASSA_SHOP_ID='123',
                   YOOKASSA_SECRET_KEY='test_unit_secret', YOOKASSA_TEST_MODE=True)
class YooKassaTests(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        override = override_settings(PRIVATE_ROOT=Path(self.temp.name))
        override.enable()
        self.addCleanup(override.disable)
        (Path(self.temp.name)/'book.pdf').write_bytes(b'%PDF-1.4 test')
        self.product = Product.objects.create(title='Book', price=Decimal('1990'), pdf_name='book.pdf')
        self.order = Order.objects.create(request_key=uuid.uuid4(), product=self.product,
            product_title='Book', amount=Decimal('1990'), currency='RUB', provider='yookassa',
            provider_payment_id=str(uuid.uuid4()), consent_at=timezone.now(), legal_version='test')
        self.invoice = YooKassaInvoice.objects.create(order=self.order, shop_id='123', test_mode=True,
                                                     idempotence_key=self.order.request_key)
    def payment(self, status='succeeded'):
        return {'id':self.order.provider_payment_id, 'status':status, 'paid':status=='succeeded',
                'test':True, 'recipient':{'account_id':'123'},
                'amount':{'value':'1990.00','currency':'RUB'}, 'metadata':{'order_id':str(self.order.pk)},
                'confirmation':{'type':'redirect','confirmation_url':'https://yoomoney.ru/checkout/test'}}
    def own(self):
        session = self.client.session
        session['orders'] = [str(self.order.pk)]
        session.save()
    def callback(self, event='payment.succeeded', obj=None):
        return self.client.post(reverse('yookassa-webhook'),
            json.dumps({'type':'notification','event':event,'object':obj or self.payment()}),
            content_type='application/json')
    def sync(self):
        sync_payment(self.order.pk, force=True)
        self.order.refresh_from_db()
    def test_verified_webhook_unlocks_private_download(self):
        with patch.object(YooKassa, 'retrieve_payment', return_value=self.payment()) as api:
            self.assertEqual(self.callback().status_code, 200)
        api.assert_called_once_with(self.order.provider_payment_id)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'paid')
        self.assertEqual(PaymentEvent.objects.count(), 1)
        token, issue = prepare_download(self.order.pk)
        self.assertTrue(token)
        self.assertFalse(issue)
        response = self.client.get(reverse('download', args=[token]))
        self.assertEqual(response.status_code, 200)
        with patch('django.core.signals.request_finished.send'):
            response.close()
    def test_forged_succeeded_payload_cannot_confirm_pending_payment(self):
        with patch.object(YooKassa, 'retrieve_payment', return_value=self.payment('pending')):
            self.assertEqual(self.callback().status_code, 200)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'pending')
        self.assertFalse(PaymentEvent.objects.exists())
        self.assertFalse(prepare_download(self.order.pk)[0])
    def test_exact_api_identity_amount_currency_metadata_and_mode_required(self):
        changes = [{'id':str(uuid.uuid4())}, {'recipient':{'account_id':'another'}},
                   {'amount':{'value':'1.00','currency':'RUB'}},
                   {'amount':{'value':'1990.00','currency':'USD'}},
                   {'amount':{'value':'NaN','currency':'RUB'}},
                   {'metadata':{'order_id':str(uuid.uuid4())}}, {'test':False}, {'test':'true'},
                   {'paid':False}, {'status':'unknown'}, {'amount':None}, {'recipient':None}]
        for change in changes:
            with self.subTest(change=change):
                YooKassaInvoice.objects.update(last_checked_at=None)
                payment = self.payment()
                payment.update(change)
                with patch.object(YooKassa, 'retrieve_payment', return_value=payment):
                    self.assertEqual(self.callback().status_code, 503)
                self.order.refresh_from_db()
                self.assertEqual(self.order.status, 'pending')
        self.assertFalse(PaymentEvent.objects.exists())
    def test_waiting_for_capture_is_not_a_completed_sale(self):
        payment = self.payment('waiting_for_capture')
        payment['paid'] = True
        with patch.object(YooKassa, 'retrieve_payment', return_value=payment):
            self.sync()
        self.assertEqual(self.order.status, 'pending')
    def test_no_webhook_needed_return_verifies_api_and_shows_download(self):
        token = signing.dumps(str(self.order.pk), salt=RETURN_SALT)
        with patch.object(YooKassa, 'retrieve_payment', return_value=self.payment()):
            response = self.client.get(reverse('yookassa-return'), {'token':token}, follow=True)
        self.assertContains(response, 'Скачать сборник')
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'paid')
    def test_unsigned_or_wrong_return_cannot_grant_order_ownership(self):
        for value in ['', str(self.order.pk), signing.dumps(str(self.order.pk), salt='wrong')]:
            response = self.client.get(reverse('yookassa-return'), {'token':value, 'status':'paid'})
            self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.get(reverse('order-status', args=[self.order.pk])).status_code, 403)
    def test_signed_return_with_pending_api_does_not_unlock_download(self):
        token = signing.dumps(str(self.order.pk), salt=RETURN_SALT)
        with patch.object(YooKassa, 'retrieve_payment', return_value=self.payment('pending')):
            response = self.client.get(reverse('yookassa-return'), {'token':token}, follow=True)
        self.assertNotContains(response, '/download/')
        self.assertContains(response, 'Проверяем оплату')
    def test_cancelled_payment_redirects_to_separate_retry_page(self):
        self.own()
        with patch.object(YooKassa, 'retrieve_payment', return_value=self.payment('canceled')):
            response = self.client.get(reverse('order-status', args=[self.order.pk]), follow=True)
        self.assertEqual(response.redirect_chain[-1][0], reverse('payment-fail'))
        self.assertContains(response, '#purchase')
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'cancelled')
    def test_duplicate_webhooks_are_idempotent(self):
        with patch.object(YooKassa, 'retrieve_payment', return_value=self.payment()):
            self.assertEqual(self.callback().status_code, 200)
            YooKassaInvoice.objects.update(last_checked_at=None)
            self.assertEqual(self.callback().status_code, 200)
        self.assertEqual(PaymentEvent.objects.count(), 1)
    def test_api_failure_is_retryable_and_never_grants_download(self):
        with patch.object(YooKassa, 'retrieve_payment', side_effect=PaymentError('yookassa_unavailable')):
            self.assertEqual(self.callback().status_code, 503)
            self.own()
            response = self.client.get(reverse('order-status', args=[self.order.pk]))
        self.assertContains(response, 'Проверяем оплату')
        self.assertNotContains(response, '/download/')
    def test_unknown_and_malformed_notification_never_calls_api(self):
        with patch.object(YooKassa, 'retrieve_payment') as api:
            self.assertEqual(self.callback(obj={'id':str(uuid.uuid4())}).status_code, 200)
            self.assertEqual(self.callback(obj={'id':'../../evil'}).status_code, 400)
            for body in ['[]', '{}', 'broken']:
                self.assertEqual(self.client.post(reverse('yookassa-webhook'),body,content_type='application/json').status_code,400)
            self.assertEqual(self.client.get(reverse('yookassa-webhook')).status_code, 405)
            api.assert_not_called()
    def test_webhook_does_not_require_browser_csrf_but_always_verifies_api(self):
        self.client = Client(enforce_csrf_checks=True)
        with patch.object(YooKassa, 'retrieve_payment', return_value=self.payment('pending')) as api:
            self.assertEqual(self.callback().status_code, 200)
            api.assert_called_once()
    def test_owned_polling_claim_limits_api_queries(self):
        self.own()
        with patch.object(YooKassa, 'retrieve_payment', return_value=self.payment('pending')) as api:
            for _ in range(4):
                self.client.get(reverse('order-status', args=[self.order.pk]),HTTP_ACCEPT='application/json')
            api.assert_called_once()
    def test_sales_disabled_does_not_block_settlement(self):
        with override_settings(SALES_ENABLED=False), patch.object(YooKassa, 'retrieve_payment',return_value=self.payment()):
            self.assertEqual(self.callback().status_code, 200)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status,'paid')
    def test_refunded_order_never_reactivated(self):
        self.order.status = 'refunded'
        self.order.save()
        with patch.object(YooKassa,'retrieve_payment',return_value=self.payment()):
            self.sync()
        self.assertEqual(self.order.status,'refunded')
    def test_authenticated_refund_revokes_access_and_is_idempotent(self):
        self.order.status='paid'
        self.order.save()
        token, _ = prepare_download(self.order.pk)
        refund = {'id':str(uuid.uuid4()), 'payment_id':self.order.provider_payment_id,
                  'status':'succeeded','amount':{'value':'1990.00','currency':'RUB'}}
        with patch.object(YooKassa,'retrieve_refund',return_value=refund), patch.object(YooKassa,'retrieve_payment',return_value=self.payment()):
            for _ in range(2):
                self.assertEqual(self.callback('refund.succeeded',refund).status_code,200)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status,'refunded')
        self.assertEqual(self.order.refunded_amount,Decimal('1990'))
        self.assertEqual(self.client.get(reverse('download',args=[token])).status_code,404)
    def test_create_sends_server_price_capture_metadata_and_stable_idempotency(self):
        key=uuid.uuid4()
        with patch.object(YooKassa,'request') as api:
            def result(method,resource,payload=None,idempotence_key=None):
                data=self.payment('pending')
                data.update(amount=payload['amount'],metadata=payload['metadata'],id=str(uuid.uuid4()))
                return data
            api.side_effect=result
            order,url=create_checkout(self.product,key)
            again,url2=create_checkout(self.product,key)
        self.assertEqual(order.pk,again.pk)
        self.assertEqual(url,url2)
        api.assert_called_once()
        args=api.call_args.args
        self.assertEqual(args[0:2],('POST','payments'))
        self.assertEqual(args[2]['amount'],{'value':'1990.00','currency':'RUB'})
        self.assertTrue(args[2]['capture'])
        self.assertEqual(str(args[3]),str(key))
        token=args[2]['confirmation']['return_url'].split('?token=')[1]
        self.assertEqual(signing.loads(token,salt=RETURN_SALT),str(order.pk))
    def test_ambiguous_timeout_keeps_payload_and_key_for_retry(self):
        key=uuid.uuid4()
        payloads=[]
        def timeout(method,resource,payload=None,idempotence_key=None):
            payloads.append((payload,idempotence_key))
            raise PaymentError('yookassa_unavailable')
        with patch.object(YooKassa,'request',side_effect=timeout):
            for _ in range(2):
                with self.assertRaises(PaymentError):
                    create_checkout(self.product,key)
        self.assertEqual(payloads[0],payloads[1])
        self.assertEqual(YooKassaInvoice.objects.filter(order__request_key=key).count(),1)
    def test_ambiguous_attempt_older_than_idempotence_window_blocks_recreation(self):
        self.order.provider_payment_id=''
        self.order.save()
        YooKassaInvoice.objects.filter(pk=self.invoice.pk).update(created_at=timezone.now()-timedelta(hours=25))
        with patch.object(YooKassa,'request') as api, self.assertRaises(PaymentError):
            create_checkout(self.product,self.order.request_key)
        api.assert_not_called()
    def test_checkout_configuration_change_rotates_session_and_rejects_old_attempt(self):
        session=self.client.session
        session['checkout_key']=str(self.order.request_key)
        session.save()
        with override_settings(YOOKASSA_SHOP_ID='456'):
            self.client.get('/')
            self.assertNotEqual(self.client.session['checkout_key'],str(self.order.request_key))
            with self.assertRaises(PaymentError):
                create_checkout(self.product,self.order.request_key)
    def test_mismatch_and_unsafe_confirmation_url_do_not_create_payable_checkout(self):
        for bad in ['http://yoomoney.ru/x','https://evil.test/x','https://yoomoney.ru.evil.test/x','https://user:pass@yoomoney.ru/x']:
            with self.subTest(url=bad):
                payment=self.payment('pending')
                payment['confirmation']['confirmation_url']=bad
                with patch.object(YooKassa,'create_payment',side_effect=lambda order,invoice: dict(payment,metadata={'order_id':str(order.pk)})):
                    with self.assertRaises(PaymentError):
                        create_checkout(self.product,uuid.uuid4())
    def test_test_live_credential_mode_cannot_be_mixed(self):
        with override_settings(YOOKASSA_TEST_MODE=False):
            self.product.is_demo=False
            self.assertFalse(can_sell(self.product))
        with override_settings(YOOKASSA_SECRET_KEY=''):
            self.assertFalse(can_sell(self.product))
    def test_legacy_provider_urls_removed(self):
        for suffix in ['result','success','fail','widget-check']:
            self.assertEqual(self.client.get('/payments/robokassa/'+suffix+'/').status_code,404)
    def test_http_adapter_auth_tls_idempotency_and_safe_errors(self):
        response=MagicMock()
        response.__enter__.return_value.read.return_value=b'{"id":"test"}'
        with patch('payments.providers.build_opener') as opener:
            opener.return_value.open.return_value=response
            self.assertEqual(YooKassa().request('POST','payments',{'capture':True},'key'),{'id':'test'})
            request=opener.return_value.open.call_args.args[0]
            self.assertEqual(request.full_url,'https://api.yookassa.ru/v3/payments')
            self.assertEqual(request.get_header('Idempotence-key'),'key')
            self.assertTrue(request.get_header('Authorization').startswith('Basic '))
            for error,code in [(HTTPError(request.full_url,401,'secret',{},None),'yookassa_http_401'),(URLError('secret'),'yookassa_unavailable')]:
                opener.return_value.open.side_effect=error
                with self.assertRaisesMessage(PaymentError,code):
                    YooKassa().request('GET','payments/test')
