from decimal import Decimal
from django.db import migrations


def set_offer_price(apps, schema_editor):
    # One-time owner-requested price update. Historical order amounts stay intact.
    Product = apps.get_model('products', 'Product')
    products = Product.objects.using(schema_editor.connection.alias)
    product_id = products.filter(active=True, currency='RUB').order_by('pk').values_list('pk', flat=True).first()
    if product_id is not None:
        products.filter(pk=product_id).update(price=Decimal('1590.00'))


class Migration(migrations.Migration):
    dependencies = [('products', '0004_product_bonus_pdf_name_product_bonus_title')]
    operations = [migrations.RunPython(set_offer_price, migrations.RunPython.noop)]
