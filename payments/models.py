from django.db import models

class RobokassaInvoice(models.Model):
    # Separate numeric sequence: no conversion/collision with historical UUID orders.
    order = models.OneToOneField('orders.Order', related_name='robokassa_invoice', on_delete=models.PROTECT)
    merchant_login = models.CharField(max_length=100)
    test_mode = models.BooleanField(default=True)
    currency = models.CharField(max_length=3, default='RUB')
    hash_algorithm = models.CharField(max_length=10, default='SHA256')
    created_at = models.DateTimeField(auto_now_add=True)

class PaymentEvent(models.Model):
    order = models.ForeignKey('orders.Order', on_delete=models.PROTECT)
    kind = models.CharField(max_length=16)
    transaction_id = models.CharField(max_length=120)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['kind', 'transaction_id'], name='unique_payment_event')]
