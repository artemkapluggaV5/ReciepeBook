import json
import tempfile
from decimal import Decimal
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase

from products.models import Benefit, Chapter, Product, Recipe


class HolidayPresentationTests(TestCase):
    def test_demo_update_preserves_commercial_fields_and_verified_content(self):
        product = Product.objects.create(title='Before', description='Before', price='1590.00',
            pdf_name='original.pdf', cover='covers/original.webp', recipe_count=17, page_count=41)
        Benefit.objects.create(product=product, title='Before', text='Before')
        Chapter.objects.create(product=product, title='Before', description='Before', count=7)
        verified = Recipe.objects.create(product=product, title='Verified', description='Original',
            category='Original', included_in_pdf=True, image='recipes/original.webp')
        demo = Recipe.objects.create(product=product, title='Example', description='Before', category='Before')
        with tempfile.TemporaryDirectory() as directory:
            backup = Path(directory) / 'before.json'
            call_command('apply_holiday_theme', backup=str(backup), verbosity=0)
            snapshot = json.loads(backup.read_text(encoding='utf-8'))
            self.assertEqual(snapshot[0]['fields']['title'], 'Before')
        product.refresh_from_db()
        verified.refresh_from_db()
        demo.refresh_from_db()
        self.assertEqual(product.price, Decimal('1590.00'))
        self.assertEqual(product.pdf_name, 'original.pdf')
        self.assertEqual(product.cover.name, 'covers/original.webp')
        self.assertEqual((product.recipe_count, product.page_count), (17, 41))
        self.assertEqual(product.chapters.get().count, 7)
        self.assertEqual((verified.title, verified.description, verified.image.name),
                         ('Verified', 'Original', 'recipes/original.webp'))
        self.assertEqual(demo.image_static, 'img/holiday-main.webp')
        response = self.client.get('/')
        self.assertContains(response, 'Новогодний стол,')
        self.assertContains(response, 'holiday.css')
        self.assertContains(response, 'name="csrfmiddlewaretoken"')
        self.assertContains(response, 'action="/checkout/"')
        self.assertNotContains(response, '17 рецептов')

    def test_real_product_is_never_rewritten(self):
        product = Product.objects.create(title='Real book', description='Original', price='1000.00', is_demo=False)
        with tempfile.TemporaryDirectory() as directory:
            backup = Path(directory) / 'before.json'
            call_command('apply_holiday_theme', backup=str(backup), verbosity=0)
            self.assertFalse(backup.exists())
        product.refresh_from_db()
        self.assertEqual(product.title, 'Real book')
