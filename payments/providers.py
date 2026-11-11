"""Robokassa payment interface: https://docs.robokassa.ru/ru/pay-interface."""
import hashlib
import hmac
import re
from dataclasses import dataclass
from decimal import Decimal
from urllib.parse import urlencode
from django.conf import settings
from .models import RobokassaInvoice

PAYMENT_URL = 'https://auth.robokassa.ru/Merchant/Index.aspx'
HASHES = {'SHA256': 'sha256', 'SHA384': 'sha384', 'SHA512': 'sha512', 'MD5': 'md5'}

class PaymentError(Exception):
    pass

@dataclass(frozen=True)
class Checkout:
    payment_id: str
    url: str

def password(number, test_mode):
    suffix = f'TEST_PASSWORD{number}' if test_mode else f'PASSWORD{number}'
    value = getattr(settings, 'ROBOKASSA_' + suffix)
    if not value:
        raise PaymentError('robokassa_not_configured')
    return value

def digest(parts, algorithm):
    try:
        name = HASHES[algorithm]
    except KeyError:
        raise PaymentError('unsupported_hash') from None
    # This is Robokassa's documented colon-separated digest, NOT HMAC.
    return hashlib.new(name, ':'.join(parts).encode('utf-8')).hexdigest()

def user_fields(invoice):
    return {'Shp_currency': invoice.currency, 'Shp_mode': 'test' if invoice.test_mode else 'live',
            'Shp_order': str(invoice.order_id)}

def signed_fields(fields):
    return [f'{key}={fields[key]}' for key in sorted(fields)]

class Robokassa:
    name = 'robokassa'

    def create_payment(self, order):
        if not settings.ROBOKASSA_MERCHANT_LOGIN:
            raise PaymentError('robokassa_not_configured')
        if order.currency != settings.ROBOKASSA_CURRENCY or order.currency != 'RUB':
            raise PaymentError('unsupported_currency')
        # Caller holds the order row lock; OneToOne also prevents duplicate invoices.
        invoice, _ = RobokassaInvoice.objects.get_or_create(order=order, defaults={
            'merchant_login': settings.ROBOKASSA_MERCHANT_LOGIN,
            'test_mode': settings.ROBOKASSA_TEST_MODE, 'currency': order.currency,
            'hash_algorithm': settings.ROBOKASSA_HASH_ALGORITHM,
        })
        if not 1 <= invoice.pk <= 9223372036854775807:
            raise PaymentError('invalid_invoice')
        amount = format(Decimal(str(order.amount)), '.2f')
        fields = user_fields(invoice)
        parts = [invoice.merchant_login, amount, str(invoice.pk),
                 password(1, invoice.test_mode), *signed_fields(fields)]
        # Required callback password is checked before offering a payable URL.
        password(2, invoice.test_mode)
        description = re.sub(r'[^\w\s.,-]', '', order.product_title, flags=re.UNICODE)[:100]
        params = {'MerchantLogin': invoice.merchant_login, 'OutSum': amount, 'InvId': str(invoice.pk),
                  'Description': description, 'Culture': 'ru', 'Encoding': 'utf-8',
                  'SignatureValue': digest(parts, invoice.hash_algorithm), **fields}
        if invoice.test_mode:
            params['IsTest'] = '1'
        if settings.ROBOKASSA_PAYMENT_METHOD:
            params['IncCurrLabel'] = settings.ROBOKASSA_PAYMENT_METHOD
        return Checkout(str(invoice.pk), PAYMENT_URL + '?' + urlencode(params))

    def verify_webhook(self, event, invoice, success_redirect=False):
        fields = {key: event[key] for key in event if key.startswith('Shp_')}
        # Reject missing, extra or changed custom parameters, all of which must be signed.
        if fields != user_fields(invoice):
            return False
        supplied = event.get('SignatureValue', '')
        if not re.fullmatch(r'[0-9a-fA-F]{32,128}', supplied):
            return False
        try:
            parts = [event['OutSum'], event['InvId'],
                     password(1 if success_redirect else 2, invoice.test_mode), *signed_fields(fields)]
            expected = digest(parts, invoice.hash_algorithm)
        except (KeyError, PaymentError):
            return False
        return hmac.compare_digest(expected.encode('ascii'), supplied.lower().encode('ascii'))

def get_provider():
    # Historical provider values stay in Order; every NEW checkout uses Robokassa.
    return Robokassa()
