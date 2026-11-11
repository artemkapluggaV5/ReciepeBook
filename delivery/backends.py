"""Unisender Go Web API transport. Never log request bodies, credentials or recipients."""
import hashlib
import json
import logging
import uuid
from email.utils import parseaddr
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener
from urllib.parse import urlsplit

from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend

logger = logging.getLogger(__name__)
UNISENDER_BACKEND = 'delivery.backends.UnisenderEmailBackend'
API_URLS = {f'https://{host}.unisender.ru/ru/transactional/api/v1' for host in ('goapi', 'go1', 'go2')}
API_ERROR_HINTS = {
    101: 'API key missing', 102: 'API key invalid', 105: 'Enable API access in account settings',
    106: 'Account inactive; contact Unisender support', 215: 'Sending disabled; contact Unisender support',
    206: 'Verify sender domain', 1003: 'Verify sender domain', 1007: 'Verify sender domain',
    901: 'Daily sending limit reached', 902: 'Free daily sending limit reached',
    903: 'Free plan permits only own domains or confirmed recipients; confirm recipient or change plan',
    904: 'Insufficient balance; check billing', 905: 'Plan sending limit reached',
}


def safe_api_error(http_status, result):
    code = result.get('code') if isinstance(result, dict) else None
    # Provider error text can echo addresses or credentials. Expose only a bounded numeric code.
    if type(code) is not int or not 0 <= code <= 99999:
        return f'Unisender HTTP {http_status}; check sending log in cabinet'
    hint = API_ERROR_HINTS.get(code, 'Check sending log in Unisender cabinet')
    return f'Unisender HTTP {http_status}; API {code}: {hint}'


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Never forward the API key to a redirect destination.


api_open = build_opener(NoRedirect).open


def production_email_ready():
    if settings.EMAIL_BACKEND == UNISENDER_BACKEND:
        sender = parseaddr(settings.DEFAULT_FROM_EMAIL)[1]
        return bool(settings.UNISENDER_API_KEY and settings.UNISENDER_API_URL in API_URLS
                    and sender.count('@') == 1
                    and sender.rsplit('@', 1)[1].lower() == urlsplit(settings.SITE_URL).hostname)
    return (settings.EMAIL_BACKEND == 'django.core.mail.backends.smtp.EmailBackend'
            and bool(settings.EMAIL_HOST and settings.EMAIL_HOST_USER)
            and settings.EMAIL_USE_TLS != settings.EMAIL_USE_SSL)


class UnisenderEmailBackend(BaseEmailBackend):
    def send_messages(self, email_messages):
        accepted = 0
        for message in email_messages or []:
            if not message.recipients():
                continue
            try:
                self._send(message)
            except Exception:
                if not self.fail_silently:
                    raise
            else:
                accepted += 1
        return accepted

    def _send(self, message):
        if not settings.UNISENDER_API_KEY or settings.UNISENDER_API_URL not in API_URLS:
            raise RuntimeError('Unisender API configuration is missing or invalid')
        if len(message.recipients()) != 1 or message.attachments:
            raise ValueError('Unisender cookbook transport requires one recipient and no attachments')
        message.message()  # Run Django header validation before constructing the request.
        recipient = parseaddr(message.recipients()[0])[1]
        name, sender = parseaddr(message.from_email)
        body = {'html' if message.content_subtype == 'html' else 'plaintext': message.body}
        for content, mimetype in getattr(message, 'alternatives', []):
            if mimetype == 'text/html':
                body['html'] = content
        payload = {'recipients': [{'email': recipient}], 'from_email': sender,
                   'from_name': name, 'subject': message.subject, 'body': body,
                   'global_language': 'ru', 'template_engine': 'none'}
        if message.reply_to:
            reply_name, reply_email = parseaddr(message.reply_to[0])
            payload.update(reply_to=reply_email, reply_to_name=reply_name)
        # Provider deduplicates this key for one minute; database delivery state also prevents repeats.
        identity = message.extra_headers.get('Message-ID') or str(uuid.uuid4())
        payload['idempotence_key'] = hashlib.sha256(identity.encode()).hexdigest()
        request = Request(settings.UNISENDER_API_URL + '/email/send.json', method='POST',
                          data=json.dumps({'message': payload}, ensure_ascii=False).encode('utf-8'),
                          headers={'Content-Type': 'application/json', 'Accept': 'application/json',
                                   'X-API-KEY': settings.UNISENDER_API_KEY})
        try:
            with api_open(request, timeout=settings.EMAIL_TIMEOUT) as response:
                raw = response.read(65537)
                if response.status != 200 or len(raw) > 65536:
                    raise ValueError
                result = json.loads(raw)
        except HTTPError as exc:
            code = exc.code
            details = None
            try:
                raw = exc.read(65537)
                if len(raw) <= 65536:
                    details = json.loads(raw)
            except (OSError, ValueError):
                pass
            finally:
                exc.close()
            raise RuntimeError(safe_api_error(code, details)) from None
        except (URLError, OSError, ValueError):
            raise RuntimeError('Unisender connection or response error; retry later') from None
        if isinstance(result, dict) and result.get('status') == 'error':
            raise RuntimeError(safe_api_error(200, result))
        if (not isinstance(result, dict) or result.get('status') != 'success'
                or not result.get('job_id') or result.get('failed_emails')
                or ('emails' in result and recipient not in result['emails'])):
            raise RuntimeError('Unisender did not accept the recipient; check sending log in cabinet')
        logger.info('email_accepted provider=unisender')
