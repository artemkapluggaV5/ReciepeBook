from importlib import import_module

from django.test import TestCase
from django.utils.html import escape

from core.models import LegalPage


class SellerOfferTests(TestCase):
    def test_supplied_offer_is_available_with_all_paragraphs(self):
        source = import_module('core.migrations.0002_import_owner_offer').OFFER_BODY
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
