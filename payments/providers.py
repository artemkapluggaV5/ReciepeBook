"""Server-side YooKassa REST API; untrusted browser/webhook state never confirms payment."""
import base64
import json
import re
import ssl
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler, HTTPSHandler
from django.conf import settings
from django.core import signing
from django.urls import reverse

API_URL = 'https://api.yookassa.ru/v3/'
RETURN_SALT = 'yookassa-order-return-v1'

class PaymentError(Exception):
    """Only safe codes, never API bodies, secrets or authorization headers."""

def api_error_code(error):
    """Extract only documented enums/field names, never free-form API descriptions."""
    code = f'yookassa_http_{error.code}'
    try:
        body = error.read(4097)
        if len(body) > 4096:
            return code
        data = json.loads(body)
        if not isinstance(data, dict):
            return code
        if data.get('code') in {'invalid_request', 'invalid_credentials', 'forbidden',
                               'not_found', 'too_many_requests', 'internal_server_error'}:
            code += ' api_code=' + data['code']
        # Allow only known request field names; arbitrary strings could contain PII.
        fields = {'Idempotence-Key', 'amount', 'value', 'currency', 'capture', 'confirmation',
                  'type', 'return_url', 'description', 'metadata', 'order_id', 'receipt',
                  'customer', 'email', 'phone', 'full_name', 'inn', 'items', 'quantity',
                  'vat_code', 'payment_mode', 'payment_subject', 'tax_system_code',
                  'payment_method_data', 'payment_method_id', 'save_payment_method',
                  'customer_id', 'recipient', 'account_id', 'gateway_id', 'test'}
        parameter = data.get('parameter')
        if isinstance(parameter, str) and len(parameter) <= 120:
            parts = parameter.replace('[', '.').replace(']', '').split('.')
            if parts and all(part in fields or (part.isascii() and part.isdigit() and len(part) <= 3)
                             for part in parts):
                code += ' parameter=' + parameter
        if valid_payment_id(data.get('id')):
            code += ' error_id=' + data['id']
        return code
    except (ValueError, UnicodeError, OSError, TypeError):
        return code
    finally:
        error.close()

class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def configured():
    key = settings.YOOKASSA_SECRET_KEY
    return (settings.YOOKASSA_SHOP_ID.isdigit() and bool(key)
            and key.startswith('test_') == settings.YOOKASSA_TEST_MODE)

def valid_payment_id(value):
    return isinstance(value, str) and bool(re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', value))

def confirmation_url(payment):
    confirmation = payment.get('confirmation') or {}
    url = confirmation.get('confirmation_url', '')
    try:
        parsed = urlsplit(url)
        valid = (confirmation.get('type') == 'redirect' and parsed.scheme == 'https'
                 and parsed.hostname in {'yoomoney.ru', 'yookassa.ru'}
                 and not parsed.username and not parsed.password and parsed.port in (None, 443)
                 and len(url) <= 600)
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise PaymentError('invalid_confirmation_url')
    return url

class YooKassa:
    name = 'yookassa'
    def request(self, method, resource, payload=None, idempotence_key=None):
        if not configured():
            raise PaymentError('yookassa_not_configured')
        credentials = f'{settings.YOOKASSA_SHOP_ID}:{settings.YOOKASSA_SECRET_KEY}'
        headers = {'Authorization': 'Basic ' + base64.b64encode(credentials.encode()).decode(),
                   'Content-Type': 'application/json', 'Accept': 'application/json'}
        if idempotence_key:
            headers['Idempotence-Key'] = str(idempotence_key)
        request = Request(API_URL + resource, method=method, headers=headers,
                          data=json.dumps(payload).encode() if payload is not None else None)
        try:
            # Verified TLS, and auth must never follow a redirect.
            if sys.platform == 'win32':
                import truststore
                context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            else:
                context = ssl.create_default_context()
            with build_opener(NoRedirects(), HTTPSHandler(context=context)).open(request, timeout=12) as response:
                body = response.read(1024 * 1024 + 1)
                if len(body) > 1024 * 1024:
                    raise PaymentError('yookassa_response_too_large')
                result = json.loads(body)
                if not isinstance(result, dict):
                    raise PaymentError('yookassa_invalid_response')
                return result
        except HTTPError as exc:
            raise PaymentError(api_error_code(exc)) from None
        except (URLError, TimeoutError, OSError):
            raise PaymentError('yookassa_unavailable') from None
        except (ValueError, UnicodeError):
            raise PaymentError('yookassa_invalid_response') from None
    def create_payment(self, order, invoice):
        payload = {'amount': {'value': format(order.amount, '.2f'), 'currency': order.currency},
                   'capture': True, 'confirmation': {'type': 'redirect', 'return_url': invoice.return_url},
                   'description': order.product_title[:128], 'metadata': {'order_id': str(order.pk)}}
        if invoice.receipt:
            payload['receipt'] = invoice.receipt
        return self.request('POST', 'payments', payload, invoice.idempotence_key)
    def retrieve_payment(self, payment_id):
        if not valid_payment_id(payment_id):
            raise PaymentError('invalid_payment_id')
        return self.request('GET', 'payments/' + payment_id)
    def retrieve_refund(self, refund_id):
        if not valid_payment_id(refund_id):
            raise PaymentError('invalid_refund_id')
        return self.request('GET', 'refunds/' + refund_id)

def get_provider():
    return YooKassa()
