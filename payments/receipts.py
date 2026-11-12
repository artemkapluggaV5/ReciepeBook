"""Receipt data for the seller's YooKassa receipt service; no outbound site email."""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from .providers import PaymentError


def receipts_enabled():
    return not settings.YOOKASSA_TEST_MODE or settings.YOOKASSA_RECEIPTS_ENABLED


def build_receipt(order, email):
    try:
        validate_email(email)
    except (ValidationError, TypeError):
        raise PaymentError('receipt_email_required') from None
    if settings.YOOKASSA_VAT_CODE not in range(1, 13):
        raise PaymentError('receipt_vat_not_configured')
    return {'customer': {'email': email}, 'items': [{
        'description': order.product_title[:128], 'quantity': '1.000',
        'amount': {'value': format(order.amount, '.2f'), 'currency': order.currency},
        'vat_code': settings.YOOKASSA_VAT_CODE,
        'payment_mode': 'full_payment',
        'payment_subject': 'intellectual_activity',
        'measure': 'piece',
    }], 'internet': True, 'timezone': 3}
