"""Bind the approved private PDF; never activate sales or change payment states."""
import hashlib
import json
import secrets
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from products.models import Product


class Command(BaseCommand):
    help = 'Connect the approved cookbook from PRIVATE_ROOT after SHA-256 verification.'

    def add_arguments(self, parser):
        parser.add_argument('--product-id', type=int)

    @transaction.atomic
    def handle(self, *args, **options):
        release = json.loads((Path(__file__).resolve().parents[2] / 'cookbook_release.json').read_text(encoding='utf-8'))
        products = Product.objects.select_for_update().filter(active=True)
        if options['product_id'] is not None:
            products = products.filter(pk=options['product_id'])
        if products.count() != 1:
            raise CommandError('Choose exactly one active product using --product-id.')
        product = products.get()
        product.pdf_name = release['filename']
        try:
            product.clean()
            path = product.private_path()
            with path.open('rb') as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        except (OSError, ValueError) as exc:
            raise CommandError('Approved PDF missing or unreadable in PRIVATE_ROOT. Upload it first.') from exc
        if not secrets.compare_digest(digest, release['sha256']):
            raise CommandError('PDF checksum mismatch. Upload the current approved version; product unchanged.')
        product.recipe_count = release['recipe_count']
        product.page_count = release['page_count']
        product.is_demo = False
        product.save(update_fields=['pdf_name', 'recipe_count', 'page_count', 'is_demo', 'updated_at'])
        self.stdout.write(self.style.SUCCESS(
            f'PDF connected: {product.page_count} pages / {product.recipe_count} recipes. '
            'SHA-256 verified. Sales, price and payment states unchanged.'))
