from datetime import timedelta
from decimal import Decimal, InvalidOperation
import re
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from orders.models import Order
from .models import PaymentEvent, YooKassaInvoice
from .providers import YooKassa, PaymentError, valid_payment_id


def money(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{1,8}\.[0-9]{2}', value):
        raise PaymentError('amount_invalid')
    try:
        amount = Decimal(value)
        if amount <= 0:
            raise PaymentError('amount_invalid')
        return amount
    except InvalidOperation:
        raise PaymentError('amount_invalid') from None


def validate_payment(order, invoice, payment, creating=False):
    try:
        if not valid_payment_id(payment.get('id')):
            raise PaymentError('payment_id_invalid')
        if not creating and payment['id'] != order.provider_payment_id:
            raise PaymentError('payment_id_mismatch')
        if (order.provider != 'yookassa' or invoice.shop_id != settings.YOOKASSA_SHOP_ID
                or payment.get('recipient', {}).get('account_id') != invoice.shop_id):
            raise PaymentError('shop_mismatch')
        if type(payment.get('test')) is not bool or payment['test'] != invoice.test_mode:
            raise PaymentError('payment_mode_mismatch')
        if payment.get('metadata', {}).get('order_id') != str(order.pk):
            raise PaymentError('order_mismatch')
        if payment['amount']['currency'] != order.currency or order.currency != 'RUB':
            raise PaymentError('currency_mismatch')
        if money(payment['amount']['value']) != order.amount:
            raise PaymentError('amount_mismatch')
        if payment.get('status') not in {'pending', 'waiting_for_capture', 'succeeded', 'canceled'}:
            raise PaymentError('status_invalid')
        if payment['status'] == 'succeeded' and payment.get('paid') is not True:
            raise PaymentError('not_paid')
    except (KeyError, TypeError, AttributeError):
        raise PaymentError('payment_invalid') from None


def apply_payment(order, payment):
    """Caller holds order lock; only authenticated API results may enter here."""
    if order.status == Order.Status.REFUNDED:
        return
    if payment['status'] == 'succeeded':
        if order.transaction_id and order.transaction_id != payment['id']:
            raise PaymentError('transaction_conflict')
        PaymentEvent.objects.get_or_create(kind='yookassa_paid', transaction_id=payment['id'],
                                           defaults={'order': order, 'amount': order.amount})
        order.status = Order.Status.PAID
        order.transaction_id = payment['id']
        order.paid_at = order.paid_at or timezone.now()
        order.save(update_fields=['status', 'transaction_id', 'paid_at', 'updated_at'])
    elif payment['status'] == 'canceled' and order.status == Order.Status.PENDING:
        order.status = Order.Status.CANCELLED
        order.save(update_fields=['status', 'updated_at'])


def sync_payment(order_id, force=False):
    order = Order.objects.select_related('yookassa_invoice').get(pk=order_id)
    invoice = getattr(order, 'yookassa_invoice', None)
    if not invoice or not order.provider_payment_id or order.provider != 'yookassa':
        return
    if not force and order.status != Order.Status.PENDING:
        return
    # Atomic DB claim bounds polling, concurrent tabs and notification floods.
    now = timezone.now()
    claimed = YooKassaInvoice.objects.filter(pk=invoice.pk).filter(
        Q(last_checked_at__isnull=True) | Q(last_checked_at__lt=now-timedelta(seconds=5))
    ).update(last_checked_at=now)
    if not claimed:
        if force:
            raise PaymentError('verification_busy')  # non-200 lets the provider retry
        return
    payment = YooKassa().retrieve_payment(order.provider_payment_id)
    validate_payment(order, invoice, payment)
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order_id)
        validate_payment(order, invoice, payment)
        apply_payment(order, payment)


def process_refund(refund_id, order_id):
    order = Order.objects.select_related('yookassa_invoice').get(pk=order_id)
    refund = YooKassa().retrieve_refund(refund_id)
    if refund.get('id') != refund_id or refund.get('payment_id') != order.provider_payment_id:
        raise PaymentError('refund_mismatch')
    if refund.get('status') != 'succeeded':
        return
    payment = YooKassa().retrieve_payment(order.provider_payment_id)
    validate_payment(order, order.yookassa_invoice, payment)
    try:
        amount = money(refund['amount']['value'])
        if refund['amount']['currency'] != order.currency or amount > order.amount:
            raise PaymentError('refund_amount_mismatch')
    except (KeyError, TypeError):
        raise PaymentError('refund_invalid') from None
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order_id)
        _, created = PaymentEvent.objects.get_or_create(kind='yookassa_refund', transaction_id=refund_id,
                                                       defaults={'order':order, 'amount':amount})
        if created:
            order.refunded_amount += amount
            order.status = Order.Status.REFUNDED
            order.save(update_fields=['refunded_amount', 'status', 'updated_at'])
