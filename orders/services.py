from datetime import timedelta
from django.conf import settings
from django.core import signing
from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from payments.models import YooKassaInvoice
from payments.providers import get_provider, configured, confirmation_url, RETURN_SALT, PaymentError
from payments.services import validate_payment, apply_payment
from payments.receipts import receipts_enabled, build_receipt
from .models import Order


def can_sell(product):
    return (settings.SALES_ENABLED and configured() and product.currency == 'RUB'
            and (settings.YOOKASSA_TEST_MODE or not product.is_demo))


def create_checkout(product, key, receipt_email=''):
    if not can_sell(product):
        raise PaymentError('sales_disabled')
    try:
        product.private_path()
        if product.bonus_pdf_name:
            product.private_path(asset='bonus')
    except (ValueError, OSError) as exc:
        raise PaymentError('pdf_missing') from exc
    provider = get_provider()
    order, _ = Order.objects.get_or_create(request_key=key, defaults={
        'product': product, 'product_title': product.title,
        'amount': product.price, 'currency': product.currency, 'provider': provider.name,
        'legal_version': settings.LEGAL_VERSION, 'consent_at': timezone.now(),
    })
    # Commit the exact request identity BEFORE HTTP: timeout or process failure
    # must retry the identical payload/key, including its signed return URL.
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order.pk)
        if order.product_id != product.pk or order.provider != provider.name:
            raise PaymentError('request_conflict')
        invoice, _ = YooKassaInvoice.objects.get_or_create(order=order, defaults={
            'shop_id': settings.YOOKASSA_SHOP_ID, 'test_mode': settings.YOOKASSA_TEST_MODE,
            'idempotence_key': order.request_key,
            'return_url': settings.SITE_URL + reverse('yookassa-return') + '?token=' +
                          signing.dumps(str(order.pk), salt=RETURN_SALT),
            'receipt': build_receipt(order, receipt_email) if receipts_enabled() else {},
        })
        if invoice.test_mode != settings.YOOKASSA_TEST_MODE or invoice.shop_id != settings.YOOKASSA_SHOP_ID:
            raise PaymentError('checkout_configuration_changed')
        if receipts_enabled() and not invoice.receipt:
            # Never change an ambiguous pre-upgrade request under the same key.
            raise PaymentError('checkout_receipt_upgrade_required')
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order.pk)
        if order.status != Order.Status.PENDING:
            return order, None
        if order.provider_payment_id:
            return order, order.checkout_url or None
        # YooKassa guarantees idempotence for 24 hours. Never re-charge an
        # ambiguous older attempt after that window has elapsed.
        if timezone.now() - invoice.created_at > timedelta(hours=23):
            raise PaymentError('checkout_expired_contact_support')
        payment = provider.create_payment(order, invoice)
        validate_payment(order, invoice, payment, creating=True)
        url = confirmation_url(payment) if payment['status'] == 'pending' else ''
        order.provider_payment_id = payment['id']
        order.checkout_url = url
        order.save(update_fields=['provider_payment_id', 'checkout_url', 'updated_at'])
        apply_payment(order, payment)
    return order, url or None
