import re
from decimal import Decimal, InvalidOperation
from django.db import transaction
from django.utils import timezone
from orders.models import Order
from .models import PaymentEvent, RobokassaInvoice
from .providers import Robokassa

class RejectedEvent(Exception):
    pass

class InvalidSignature(RejectedEvent):
    pass

def invoice_number(value):
    if not isinstance(value, str) or not re.fullmatch(r'[1-9][0-9]{0,18}', value):
        raise RejectedEvent
    number = int(value)
    if number > 9223372036854775807:
        raise RejectedEvent
    return number

def money(value):
    # Production ResultURL uses six decimal places; do NOT round before comparing.
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{1,8}(?:\.[0-9]{1,6})?', value):
        raise RejectedEvent
    try:
        amount = Decimal(value)
        if not amount.is_finite() or amount <= 0:
            raise RejectedEvent
        return amount
    except InvalidOperation:
        raise RejectedEvent from None

def validate_event(event, success_redirect=False):
    number = invoice_number(event.get('InvId'))
    try:
        invoice = RobokassaInvoice.objects.select_related('order').get(pk=number)
    except RobokassaInvoice.DoesNotExist:
        raise RejectedEvent from None
    if not Robokassa().verify_webhook(event, invoice, success_redirect=success_redirect):
        raise InvalidSignature
    order = invoice.order
    if (order.provider != 'robokassa' or order.provider_payment_id != str(invoice.pk)
            or invoice.currency != order.currency or invoice.currency != 'RUB'
            or money(event.get('OutSum')) != order.amount):
        raise RejectedEvent
    return invoice

def process_result(event):
    invoice = validate_event(event)
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=invoice.order_id)
        if order.provider != 'robokassa' or order.amount != money(event.get('OutSum')) or order.currency != invoice.currency:
            raise RejectedEvent
        existing = PaymentEvent.objects.filter(kind='robokassa_paid', transaction_id=str(invoice.pk)).first()
        if existing:
            if existing.order_id != order.pk or existing.amount != order.amount:
                raise RejectedEvent
            return invoice.pk
        if order.transaction_id and order.transaction_id != str(invoice.pk):
            raise RejectedEvent
        # Never reactivate access after a previously recorded refund.
        if order.status == Order.Status.REFUNDED:
            raise RejectedEvent
        order.transaction_id = str(invoice.pk)
        order.status = Order.Status.PAID
        order.paid_at = order.paid_at or timezone.now()
        PaymentEvent.objects.create(order=order, kind='robokassa_paid',
                                    transaction_id=str(invoice.pk), amount=order.amount)
        order.save(update_fields=['transaction_id', 'status', 'paid_at', 'updated_at'])
    # A paid order is a durable DB delivery task. No SMTP inside ResultURL.
    return invoice.pk
