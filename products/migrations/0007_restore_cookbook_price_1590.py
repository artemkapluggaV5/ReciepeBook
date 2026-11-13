from decimal import Decimal
from django.db import migrations


def restore_offer_price(apps, schema_editor):
    # Restore the owner's sale price without changing existing orders/invoices.
    Product = apps.get_model('products', 'Product')
    products = Product.objects.using(schema_editor.connection.alias)
    product_id = products.filter(active=True, currency='RUB').order_by('pk').values_list('pk', flat=True).first()
    if product_id is not None:
        products.filter(pk=product_id).update(price=Decimal('1590.00'))


class Migration(migrations.Migration):
    dependencies = [('products', '0006_set_cookbook_price_1')]
    operations = [migrations.RunPython(restore_offer_price, migrations.RunPython.noop)]
