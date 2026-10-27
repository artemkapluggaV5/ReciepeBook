import uuid
from django.db import models
from django.db.models import Q

class Order(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Ожидает оплаты'
        PAID = 'paid', 'Оплачен'
        FAILED = 'failed', 'Ошибка оплаты'
        CANCELLED = 'cancelled', 'Отменён'
        REFUNDED = 'refunded', 'Возвращён'
    class Delivery(models.TextChoices):
        PENDING = 'pending', 'Ожидает'
        SENT = 'sent', 'Передано сервису отправки'
        FAILED = 'failed', 'Ошибка'
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    request_key = models.UUIDField(unique=True)
    email = models.EmailField()
    product = models.ForeignKey('products.Product', on_delete=models.PROTECT)
    product_title = models.CharField(max_length=180)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3)
    provider = models.CharField(max_length=30)
    provider_payment_id = models.CharField(max_length=120, blank=True)
    transaction_id = models.CharField(max_length=120, blank=True)
    checkout_url = models.URLField(max_length=600, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING, db_index=True)
    delivery_status = models.CharField(max_length=12, choices=Delivery.choices, default=Delivery.PENDING, db_index=True)
    delivery_attempts = models.PositiveIntegerField(default=0)
    delivery_error = models.CharField(max_length=40, blank=True)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    refunded_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    token_version = models.UUIDField(default=uuid.uuid4)
    token_issued_at = models.DateTimeField(null=True, blank=True)
    download_count = models.PositiveIntegerField(default=0)
    legal_version = models.CharField(max_length=80)
    consent_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name='positive_order_amount'),
            models.UniqueConstraint(fields=['provider', 'transaction_id'], condition=~Q(transaction_id=''), name='unique_provider_transaction'),
            models.UniqueConstraint(fields=['provider', 'provider_payment_id'], condition=~Q(provider_payment_id=''), name='unique_provider_payment'),
        ]
    def __str__(self):
        return str(self.id)

class RateBucket(models.Model):
    key = models.CharField(max_length=64, unique=True)
    start = models.DateTimeField()
    count = models.PositiveIntegerField(default=0)
