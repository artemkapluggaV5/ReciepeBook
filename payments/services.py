import re
from decimal import Decimal, InvalidOperation
from django.db import transaction
from django.utils import timezone
from orders.models import Order
from .models import PaymentEvent, RobokassaInvoice
from .providers import Robokassa, user_fields

class RejectedEvent(Exception):
    CODES = {'parameters', 'invoice_missing', 'invoice_invalid', 'invoice_unknown',
             'amount_invalid', 'amount_mismatch', 'order_mismatch', 'currency_mismatch',
             'custom_fields_mismatch', 'signature', 'content_type', 'mixed_sources',
             'duplicate_parameters', 'event_conflict', 'transaction_conflict', 'refunded'}

    def __init__(self, code='parameters'):
        self.code = code if code in self.CODES else 'parameters'
        super().__init__(self.code)

class InvalidSignature(RejectedEvent):
    def __init__(self, code='signature'):
        super().__init__(code)

def invoice_number(value):
    if not isinstance(value, str) or not re.fullmatch(r'[1-9][0-9]{0,18}', value):
        raise RejectedEvent('invoice_missing' if value is None else 'invoice_invalid')
    number = int(value)
    if number > 9223372036854775807:
        raise RejectedEvent('invoice_invalid')
    return number

def money(value):
    # Production ResultURL uses six decimal places; do NOT round before comparing.
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{1,8}(?:\.[0-9]{1,6})?', value):
        raise RejectedEvent('amount_invalid')
    try:
        amount = Decimal(value)
        if not amount.is_finite() or amount <= 0:
            raise RejectedEvent('amount_invalid')
        return amount
    except InvalidOperation:
        raise RejectedEvent('amount_invalid') from None

def validate_event(event, success_redirect=False):
    number = invoice_number(event.get('InvId'))
    try:
        invoice = RobokassaInvoice.objects.select_related('order').get(pk=number)
    except RobokassaInvoice.DoesNotExist:
        raise RejectedEvent('invoice_unknown') from None
    if {key: event[key] for key in event if key.startswith('Shp_')} != user_fields(invoice):
        raise InvalidSignature('custom_fields_mismatch')
    if not Robokassa().verify_webhook(event, invoice, success_redirect=success_redirect):
        raise InvalidSignature
    order = invoice.order
    if order.provider != 'robokassa' or order.provider_payment_id != str(invoice.pk):
        raise RejectedEvent('order_mismatch')
    if invoice.currency != order.currency or invoice.currency != 'RUB':
        raise RejectedEvent('currency_mismatch')
    if money(event.get('OutSum')) != order.amount:
        raise RejectedEvent('amount_mismatch')
    return invoice

def process_result(event):
    invoice = validate_event(event)
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=invoice.order_id)
        if order.provider != 'robokassa' or order.amount != money(event.get('OutSum')) or order.currency != invoice.currency:
            raise RejectedEvent('order_mismatch')
        existing = PaymentEvent.objects.filter(kind='robokassa_paid', transaction_id=str(invoice.pk)).first()
        if existing:
            if existing.order_id != order.pk or existing.amount != order.amount:
                raise RejectedEvent('event_conflict')
            return invoice.pk
        if order.transaction_id and order.transaction_id != str(invoice.pk):
            raise RejectedEvent('transaction_conflict')
        # Never reactivate access after a previously recorded refund.
        if order.status == Order.Status.REFUNDED:
            raise RejectedEvent('refunded')
        order.transaction_id = str(invoice.pk)
        order.status = Order.Status.PAID
        order.paid_at = order.paid_at or timezone.now()
        PaymentEvent.objects.create(order=order, kind='robokassa_paid',
                                    transaction_id=str(invoice.pk), amount=order.amount)
        order.save(update_fields=['transaction_id', 'status', 'paid_at', 'updated_at'])
    # Only this authenticated callback confirms payment. Browser returns never do.
    return invoice.pk
