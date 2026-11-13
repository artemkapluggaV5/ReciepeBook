from decimal import Decimal
from django.db import migrations


def set_check_price(apps, schema_editor):
    # Owner-requested price for new purchases; existing order amounts stay intact.
    Product = apps.get_model('products', 'Product')
    products = Product.objects.using(schema_editor.connection.alias)
    product_id = products.filter(active=True, currency='RUB').order_by('pk').values_list('pk', flat=True).first()
    if product_id is not None:
        products.filter(pk=product_id).update(price=Decimal('1.00'))


class Migration(migrations.Migration):
    dependencies = [('products', '0005_set_cookbook_price_1590')]
    operations = [migrations.RunPython(set_check_price, migrations.RunPython.noop)]
