import uuid
from datetime import timedelta
from unittest.mock import patch

from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from orders.models import Order
from payments.models import YooKassaInvoice
from products.models import Product


@override_settings(DEBUG=True)
class PurchasedStorefrontTests(TestCase):
    def setUp(self):
        self.product = Product.objects.create(title='Book', price='1590.00')

    def order(self, status='paid', product=None, **extra):
        return Order.objects.create(product=product or self.product, product_title='Book',
            amount='1590.00', currency='RUB', provider='yookassa', status=status,
            request_key=uuid.uuid4(), consent_at=timezone.now(), legal_version='test',
            paid_at=timezone.now() if status == 'paid' else None, **extra)

    def own(self, order):
        session = self.client.session
        session['orders'] = [str(order.pk)]
        session.save()

    def test_paid_owner_gets_download_links_instead_of_all_purchase_buttons(self):
        order = self.order()
        self.own(order)
        response = self.client.get('/')
        self.assertContains(response, 'Перейти к скачиванию', count=3)
        self.assertContains(response, 'href="' + reverse('order-status', args=[order.pk]) + '"', count=3)
        self.assertContains(response, 'Оплата подтверждена')
        self.assertNotContains(response, 'id="purchase-form"')
        self.assertNotContains(response, 'Получить новогодний сборник')
        self.assertIn('no-store', response['Cache-Control'])
        self.assertEqual(response.context['purchased_order'], order)

    def test_unpaid_failed_cancelled_and_refunded_keep_normal_purchase_form(self):
        order = self.order('pending')
        self.own(order)
        for status in ('pending', 'failed', 'cancelled', 'refunded'):
            Order.objects.filter(pk=order.pk).update(status=status)
            response = self.client.get('/?status=paid')
            self.assertContains(response, 'id="purchase-form"')
            self.assertNotContains(response, 'Перейти к скачиванию')
            self.assertIsNone(response.context['purchased_order'])

    def test_foreign_order_or_query_parameters_do_not_grant_purchased_state(self):
        foreign = self.order()
        for client in (self.client, Client()):
            response = client.get('/?paid=1&order=' + str(foreign.pk))
            self.assertContains(response, 'id="purchase-form"')
            self.assertNotContains(response, reverse('order-status', args=[foreign.pk]))
        self.own(self.order('pending'))
        self.assertContains(self.client.get('/'), 'id="purchase-form"')

    def test_purchase_of_other_product_does_not_hide_this_products_payment(self):
        other = Product.objects.create(title='Other', price='99', active=False)
        self.own(self.order(product=other))
        self.assertContains(self.client.get('/'), 'id="purchase-form"')

    def test_stale_checkout_post_redirects_owner_without_creating_another_payment(self):
        order = self.order()
        self.own(order)
        with patch('orders.views.create_checkout') as create, patch('payments.providers.YooKassa.request') as api:
            response = self.client.post('/checkout/', {'request_key': str(uuid.uuid4()), 'price': '1'})
        self.assertRedirects(response, reverse('order-status', args=[order.pk]), fetch_redirect_response=False)
        create.assert_not_called()
        api.assert_not_called()
        self.assertEqual(Order.objects.count(), 1)
        self.assertFalse(YooKassaInvoice.objects.exists())

    def test_refund_is_reflected_on_next_request_and_legal_page_header_is_personal(self):
        order = self.order()
        self.own(order)
        response = self.client.get('/legal/contacts/')
        self.assertContains(response, 'Перейти к скачиванию')
        self.assertIn('no-store', response['Cache-Control'])
        Order.objects.filter(pk=order.pk).update(status='refunded')
        self.assertContains(self.client.get('/'), 'id="purchase-form"')

    def test_expired_paid_access_still_points_to_order_instead_of_charging_again(self):
        order = self.order(token_issued_at=timezone.now()-timedelta(days=31), download_count=20)
        self.own(order)
        self.assertContains(self.client.get('/'), 'Перейти к скачиванию', count=3)

    def test_invalid_legacy_session_values_do_not_break_storefront(self):
        session = self.client.session
        session['orders'] = ['not-a-uuid', None, {'invalid': True}]
        session.save()
        self.assertContains(self.client.get('/'), 'id="purchase-form"')
