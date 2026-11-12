"""Connect the owner's private gift PDF after verifying the supplied file."""
import hashlib
import json
import secrets
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from products.models import Product


class Command(BaseCommand):
    help = 'Connect the approved bonus PDF from PRIVATE_ROOT; optionally change the product price.'

    def add_arguments(self, parser):
        parser.add_argument('--product-id', type=int)
        parser.add_argument('--price')

    @transaction.atomic
    def handle(self, *args, **options):
        release = json.loads((Path(__file__).resolve().parents[2] / 'bonus_release.json').read_text(encoding='utf-8'))
        products = Product.objects.select_for_update().filter(active=True)
        if options['product_id'] is not None:
            products = products.filter(pk=options['product_id'])
        if products.count() != 1:
            raise CommandError('Choose exactly one active product using --product-id.')
        product = products.get()
        product.bonus_pdf_name = release['filename']
        product.bonus_title = release['title']
        try:
            path = product.private_path(asset='bonus')
            with path.open('rb') as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        except (OSError, ValueError) as exc:
            raise CommandError('Upload marishkiny-retsepty.pdf to PRIVATE_ROOT first.') from exc
        if not secrets.compare_digest(digest, release['sha256']):
            raise CommandError('Bonus PDF checksum mismatch; product unchanged.')
        fields = ['bonus_pdf_name', 'bonus_title', 'updated_at']
        if options['price'] is not None:
            try:
                price = Decimal(options['price'])
                if not price.is_finite() or price < 1 or price > Decimal('99999999.99') or price != price.quantize(Decimal('.01')):
                    raise ValueError
            except (InvalidOperation, ValueError) as exc:
                raise CommandError('Price must be at least 1, with at most two decimal places.') from exc
            product.price = price
            fields.append('price')
        product.save(update_fields=fields)
        self.stdout.write(self.style.SUCCESS(f'Gift PDF connected; price: {product.price} {product.currency}. Existing orders unchanged.'))
