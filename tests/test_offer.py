from importlib import import_module
from decimal import Decimal
from types import SimpleNamespace
import uuid

from django.core import mail
from django.test import TestCase
from django.utils.html import escape

from core.models import LegalPage
from delivery.services import email_service
from products.models import Product


class SellerOfferTests(TestCase):
    def test_supplied_offer_is_available_with_all_paragraphs(self):
        source = import_module('core.migrations.0002_import_owner_offer').OFFER_BODY.replace(
            'marina.novikova-1976@mail.ru', 'marishkinirecepti@mail.ru')
        page = LegalPage.objects.get(slug='offer')
        self.assertEqual(page.body, source)
        self.assertTrue(page.is_draft)  # The supplied domain fields are still blank.
        response = self.client.get('/legal/offer/')
        self.assertEqual(response.status_code, 200)
        for paragraph in source.split('\n\n'):
            self.assertContains(response, escape(paragraph), html=False)
        self.assertContains(response, '<h2>11. Реквизиты Продавца</h2>', html=True)
        self.assertNotContains(response, '[Имя или наименование продавца]')

    def test_admin_edited_legal_text_remains_escaped(self):
        page = LegalPage.objects.get(slug='offer')
        page.body = '1. Условия\n\n<script>alert(1)</script>'
        page.save()
        response = self.client.get('/legal/offer/')
        self.assertContains(response, '&lt;script&gt;alert(1)&lt;/script&gt;')
        self.assertNotContains(response, '<script>alert(1)</script>')

    def test_contact_email_and_only_requested_footer_links(self):
        Product.objects.create(title='Книга', description='Описание', price='1990.00')
        response = self.client.get('/')
        self.assertContains(response, 'mailto:marishkinirecepti@mail.ru')
        for slug in ['privacy', 'consent', 'refunds']:
            self.assertNotContains(response, f'href="/legal/{slug}/"')
        self.assertContains(response, 'href="/legal/offer/"')
        response = self.client.get('/legal/contacts/')
        self.assertContains(response, 'mailto:marishkinirecepti@mail.ru')
        self.assertNotContains(response, 'Шаблон для заполнения владельцем')
        self.assertNotContains(response, '[Имя или наименование продавца]')
        response = self.client.get('/legal/offer/')
        self.assertNotContains(response, 'Редакция готовится к запуску продаж')

    def test_delivery_sender_and_support_reply_address(self):
        order = SimpleNamespace(pk=uuid.uuid4(), token_version=uuid.uuid4(),
                                product_title='Книга', amount=Decimal('1990'),
                                currency='RUB', email='buyer@example.test')
        email_service(order)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].from_email,
                         'Маришкины рецепты <marishkinirecepti@mail.ru>')
        self.assertEqual(mail.outbox[0].reply_to, ['marishkinirecepti@mail.ru'])
        self.assertIn('marishkinirecepti@mail.ru', mail.outbox[0].body)
