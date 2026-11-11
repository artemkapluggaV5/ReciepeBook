from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.management import call_command, CommandError
from django.test import TestCase, override_settings

from products.models import Product


class CookbookReleaseTests(TestCase):
    def test_wrong_pdf_does_not_replace_product(self):
        product = Product.objects.create(title='Книга', description='Сборник', price='1990', pdf_name='previous.pdf')
        with TemporaryDirectory() as directory, override_settings(PRIVATE_ROOT=Path(directory)):
            Path(directory, 'marina-cookbook-approved.pdf').write_bytes(b'%PDF-1.4\nwrong edition\n%%EOF')
            with self.assertRaisesMessage(CommandError, 'checksum mismatch'):
                call_command('connect_cookbook')
        product.refresh_from_db()
        self.assertEqual(product.pdf_name, 'previous.pdf')
        self.assertTrue(product.is_demo)

    def test_missing_pdf_does_not_mark_product_ready(self):
        product = Product.objects.create(title='Книга', description='Сборник', price='1990')
        with TemporaryDirectory() as directory, override_settings(PRIVATE_ROOT=Path(directory)):
            with self.assertRaisesMessage(CommandError, 'Upload it first'):
                call_command('connect_cookbook')
        product.refresh_from_db()
        self.assertEqual(product.pdf_name, '')
        self.assertTrue(product.is_demo)
