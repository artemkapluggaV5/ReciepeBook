from django.db import models

class LegacyInvoice(models.Model):
    # Historical accounting records only; no active provider adapter.
    order = models.OneToOneField('orders.Order', related_name='legacy_invoice', on_delete=models.PROTECT)
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

class YooKassaInvoice(models.Model):
    order = models.OneToOneField('orders.Order', related_name='yookassa_invoice', on_delete=models.PROTECT)
    shop_id = models.CharField(max_length=100)
    test_mode = models.BooleanField(default=True)
    idempotence_key = models.UUIDField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    return_url = models.CharField(max_length=600, blank=True)
    last_checked_at = models.DateTimeField(null=True, blank=True)
    receipt = models.JSONField(default=dict, blank=True)
