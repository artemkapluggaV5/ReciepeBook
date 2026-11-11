from django.conf import settings
from django.db import transaction
from django.utils import timezone
from payments.providers import get_provider, password, PaymentError
from .models import Order

def can_sell(product):
    if not settings.SALES_ENABLED:
        return False
    try:
        password(1, settings.ROBOKASSA_TEST_MODE)
        password(2, settings.ROBOKASSA_TEST_MODE)
    except PaymentError:
        return False
    # SALES_ENABLED is the owner's explicit operational switch. Legal/fiscal
    # review flags belong to check_launch, not a second hidden checkout switch.
    if not settings.ROBOKASSA_MERCHANT_LOGIN or settings.ROBOKASSA_CURRENCY != product.currency:
        return False
    if not settings.ROBOKASSA_TEST_MODE and product.is_demo:
        return False
    return product.currency == 'RUB'

def create_checkout(product, key):
    if not can_sell(product):
        raise PaymentError('sales_disabled')
    try:
        product.private_path()
    except (ValueError, OSError) as exc:
        raise PaymentError('pdf_missing') from exc
    provider = get_provider()
    order, _ = Order.objects.get_or_create(request_key=key, defaults={
        'product': product, 'product_title': product.title,
        'amount': product.price, 'currency': product.currency, 'provider': provider.name,
        'legal_version': settings.LEGAL_VERSION, 'consent_at': timezone.now(),
    })
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order.pk)
        if order.product_id != product.pk or order.provider != provider.name:
            raise PaymentError('request_conflict')
        if order.status in [Order.Status.PAID, Order.Status.REFUNDED]:
            return order, None
        invoice = getattr(order, 'robokassa_invoice', None)
        if invoice and invoice.test_mode != settings.ROBOKASSA_TEST_MODE:
            raise PaymentError('checkout_mode_changed')
        if order.checkout_url:
            return order, order.checkout_url
        # Stable local InvId: no remote creation request or external cache window.
        result = provider.create_payment(order)
        order.provider_payment_id = result.payment_id
        order.checkout_url = result.url
        order.save(update_fields=['provider_payment_id', 'checkout_url', 'updated_at'])
    return order, order.checkout_url
