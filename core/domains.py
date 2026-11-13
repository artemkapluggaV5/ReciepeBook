"""Move legacy purchase ownership to www without domain-wide auth cookies."""
import re
import secrets
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session
from django.db import transaction
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_safe

from orders.rate_limit import limited


def _host(request):
    return request.get_host().split(':', 1)[0].lower().rstrip('.')


def _target(value):
    if not isinstance(value, str) or not value.startswith('/') or value.startswith('//') or '\\' in value:
        return '/'
    if value.startswith('/domain/') or any(ord(char) < 32 for char in value):
        return '/'
    return value


def _redirect(url):
    response = HttpResponseRedirect(url)
    response['Cache-Control'] = 'private, no-store'
    response['Referrer-Policy'] = 'no-referrer'
    response['X-Robots-Tag'] = 'noindex, nofollow'
    return response


@require_safe
def prepare(request):
    target = _target(request.GET.get('next', '/'))
    if not settings.CANONICAL_HOST or _host(request) != settings.CANONICAL_HOST:
        return _redirect(settings.SITE_URL + target)
    challenge = secrets.token_urlsafe(32)
    request.session['_canonical_challenge'] = challenge
    apex = settings.CANONICAL_REDIRECT_HOSTS[0]
    return _redirect('https://' + apex + '/domain/confirm/?' + urlencode({'challenge': challenge, 'next': target}))


@require_safe
def confirm(request):
    target = _target(request.GET.get('next', '/'))
    if not settings.CANONICAL_HOST or _host(request) not in settings.CANONICAL_REDIRECT_HOSTS:
        return _redirect(settings.SITE_URL + target)
    challenge = request.GET.get('challenge', '')
    owned = request.session.get('orders', [])
    if not re.fullmatch(r'[A-Za-z0-9_-]{43}', challenge) or not owned:
        return _redirect(settings.SITE_URL + target)
    if limited(request, 'canonical-transfer', limit=20, seconds=120):
        return _redirect(settings.SITE_URL + target)
    # A dedicated, expiring grant record is NOT a usable authenticated session:
    # purchase IDs stay nested, and only the bound www browser can redeem it.
    grant = SessionStore()
    grant['_canonical_grant'] = {'challenge': challenge, 'orders': owned[-20:], 'next': target}
    grant.set_expiry(120)
    grant.create()
    return _redirect(settings.SITE_URL + '/domain/finish/?' + urlencode({'grant': grant.session_key}))


@require_safe
def finish(request):
    if not settings.CANONICAL_HOST or _host(request) != settings.CANONICAL_HOST:
        return _redirect(settings.SITE_URL + '/')
    key = request.GET.get('grant', '')
    challenge = request.session.get('_canonical_challenge', '')
    grant_data = None
    if re.fullmatch(r'[a-z0-9]{32}', key) and isinstance(challenge, str) and challenge:
        with transaction.atomic():
            grant = Session.objects.select_for_update().filter(session_key=key, expire_date__gt=timezone.now()).first()
            data = grant.get_decoded().get('_canonical_grant', {}) if grant else {}
            expected = data.get('challenge', '')
            if isinstance(expected, str) and expected and secrets.compare_digest(challenge, expected):
                grant_data = data
                grant.delete()
    if grant_data is None:
        response = render(request, 'message.html', {'title': 'Повторите переход на сайт',
            'text': 'Откройте исходную ссылку ещё раз в браузере покупки. Доступ к сборнику сохранён.'}, status=400)
        response['Cache-Control'] = 'private, no-store'
        response['Referrer-Policy'] = 'no-referrer'
        response['X-Robots-Tag'] = 'noindex, nofollow'
        return response
    owned = request.session.get('orders', []) + grant_data['orders']
    request.session.cycle_key()
    request.session['orders'] = list(dict.fromkeys(owned))[-40:]
    request.session.pop('_canonical_challenge', None)
    return _redirect(settings.SITE_URL + _target(grant_data['next']))
