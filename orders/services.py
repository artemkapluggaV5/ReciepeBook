from django.conf import settings
from django.db import transaction
from django.utils import timezone
from core.models import LegalPage
from delivery.backends import production_email_ready
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
    sandbox = settings.DEBUG and settings.ROBOKASSA_TEST_MODE
    if sandbox and settings.ROBOKASSA_MERCHANT_LOGIN:
        return True
    email_ready = production_email_ready()
    identity_ready = ('[' not in settings.MERCHANT_NAME and '[' not in settings.MERCHANT_DETAILS
                      and not settings.CONTACT_EMAIL.endswith('.invalid'))
    return (settings.SALES_ENABLED and settings.LEGAL_READY and settings.FISCALIZATION_READY
            and settings.MERCHANT_COUNTRY == 'RU' and bool(settings.ROBOKASSA_MERCHANT_LOGIN)
            and settings.ROBOKASSA_CURRENCY == product.currency == 'RUB' and not product.is_demo
            and identity_ready and email_ready
            and not LegalPage.objects.filter(is_draft=True).exists()
            and LegalPage.objects.filter(slug__in=['privacy','offer','consent','refunds','contacts']).count() == 5)

def create_checkout(product, email, key):
    if not can_sell(product):
        raise PaymentError('sales_disabled')
    try:
        product.private_path()
    except (ValueError, OSError) as exc:
        raise PaymentError('pdf_missing') from exc
    provider = get_provider()
    order, _ = Order.objects.get_or_create(request_key=key, defaults={
        'email': email, 'product': product, 'product_title': product.title,
        'amount': product.price, 'currency': product.currency, 'provider': provider.name,
        'legal_version': settings.LEGAL_VERSION, 'consent_at': timezone.now(),
    })
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order.pk)
        if order.email != email or order.product_id != product.pk or order.provider != provider.name:
            raise PaymentError('request_conflict')
        if order.status in [Order.Status.PAID, Order.Status.REFUNDED]:
            return order, None
        if order.checkout_url:
            return order, order.checkout_url
        # Stable local InvId: no remote creation request or external cache window.
        result = provider.create_payment(order)
        order.provider_payment_id = result.payment_id
        order.checkout_url = result.url
        order.save(update_fields=['provider_payment_id', 'checkout_url', 'updated_at'])
    return order, order.checkout_url
