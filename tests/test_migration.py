import uuid
from decimal import Decimal
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone

class HistoricalMigrationTests(TransactionTestCase):
    def test_upgrade_preserves_legacy_paid_order_customer_and_token(self):
        executor = MigrationExecutor(connection)
        executor.migrate([('payments', '0001_initial'), ('orders', '0002_alter_order_delivery_status'),
                          ('products', '0001_initial')])
        try:
            old = executor.loader.project_state([('payments','0001_initial'),('orders','0002_alter_order_delivery_status')]).apps
            Product = old.get_model('products', 'Product')
            Order = old.get_model('orders', 'Order')
            product = Product.objects.create(title='Historical book',description='History',price=Decimal('890'))
            order = Order.objects.create(request_key=uuid.uuid4(),product=product,product_title='Historical book',
                email='historical@example.test',amount=Decimal('890'),currency='RUB',provider='cloudpayments',
                provider_payment_id='historical-invoice',transaction_id='historical-transaction',status='paid',
                delivery_status='sent',delivery_attempts=1,paid_at=timezone.now(),token_issued_at=timezone.now(),
                consent_at=timezone.now(),legal_version='old')
            snapshot = {field:getattr(order,field) for field in ['amount','provider','provider_payment_id',
                'transaction_id','status','token_version','token_issued_at','paid_at']}
        finally:
            executor = MigrationExecutor(connection)
            executor.migrate(executor.loader.graph.leaf_nodes())
        from orders.models import Order as CurrentOrder
        from payments.models import LegacyInvoice
        saved = CurrentOrder.objects.get(pk=order.pk)
        self.assertEqual({field:getattr(saved,field) for field in snapshot},snapshot)
        self.assertNotIn('email', [f.name for f in CurrentOrder._meta.fields])
        self.assertFalse(LegacyInvoice.objects.filter(order=saved).exists())
